"""Per-channel publishing policy and the release-time resolver.

Three authorizations are deliberately separate, because each one failing on its own must stop a
publication:

* **rendering** - may this machine produce an episode at all (``factory.controls``);
* **uploading** - may this run send a file to YouTube (the workflow's ``upload`` input, plus
  ``FACTORY_ALLOW_UPLOAD`` inside the CLI);
* **scheduled publication** - may this channel put a *release time* on the upload, which is what makes a
  video public without anyone watching (this module).

The third one used to be implicit: a scheduled GitHub Actions run cannot pass ``upload=true``, so the daily
workflows produced episodes and skipped the upload for ever, and even a manual upload carried no
``publishAt``. A channel now states its policy, and a scheduled run consults it.

The release time is resolved from the *production run's* IST date, not from the moment the upload happens. A
cron that starts at 20:00 IST and uploads at 20:06 is still producing today's episode; the previous
``_next_ist_date`` rolled it to tomorrow, which is the failure this module exists to remove.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping

from .util import IST, publish_at_utc

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module importable from config
    from .config import ChannelSpec

LOGGER = logging.getLogger(__name__)

#: ``manual`` keeps the historical behaviour: nothing is scheduled unless an operator asks for it.
#: ``scheduled`` lets a cron-triggered run upload and set the channel's release time.
MODES = ("manual", "scheduled")
#: What to do when a run finishes after its channel's release time.
#: ``shift`` keeps the episode and moves the release to the next valid instant (today, a few minutes out).
#: ``skip`` refuses to schedule it at all, so a late episode is never published quietly.
LATE_RUN_POLICIES = ("shift", "skip")


@dataclass(frozen=True)
class PublishingPolicy:
    """What a channel is allowed to do automatically."""

    mode: str = "manual"
    scheduled_upload: bool = False
    late_run_policy: str = "shift"
    late_grace_minutes: int = 90
    minimum_lead_minutes: int = 15
    warnings: tuple[str, ...] = ()

    @property
    def may_schedule(self) -> bool:
        """True only when this channel has opted into automatic scheduled publication."""

        return self.mode == "scheduled" and self.scheduled_upload

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "scheduled_upload": self.scheduled_upload,
            "late_run_policy": self.late_run_policy,
            "late_grace_minutes": self.late_grace_minutes,
            "minimum_lead_minutes": self.minimum_lead_minutes,
            "may_schedule": self.may_schedule,
            "warnings": list(self.warnings),
        }


def parse_publishing_policy(
    raw: Any,
    *,
    slug: str = "",
    release_time_ist: str = "",
) -> PublishingPolicy:
    """Read a channel's ``publishing`` block, failing closed on anything unexpected.

    A typo must not silently enable publishing, so an unknown mode means ``manual`` and an unknown late-run
    policy means ``skip``; both are recorded as warnings the CLI prints and the docs explain.
    """

    warnings: list[str] = []
    if raw is None:
        return PublishingPolicy(warnings=())
    if not isinstance(raw, Mapping):
        LOGGER.warning("%s: publishing block is not an object; publishing stays manual", slug)
        return PublishingPolicy(warnings=(f"{slug}: publishing block is not an object",))

    mode = str(raw.get("mode", "manual")).strip().lower() or "manual"
    if mode not in MODES:
        warnings.append(f"unknown publishing mode {mode!r}; using manual")
        mode = "manual"

    late = str(raw.get("late_run_policy", "shift")).strip().lower() or "shift"
    if late not in LATE_RUN_POLICIES:
        warnings.append(f"unknown late_run_policy {late!r}; using skip")
        late = "skip"

    def number(key: str, default: int, low: int, high: int) -> int:
        value = raw.get(key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            warnings.append(f"ignoring non-numeric {key}={value!r}; using {default}")
            return default
        return max(low, min(high, parsed))

    scheduled_upload = bool(raw.get("scheduled_upload", mode == "scheduled"))
    if scheduled_upload and mode != "scheduled":
        warnings.append("scheduled_upload is set on a manual channel; publishing stays manual")
        scheduled_upload = False
    if mode == "scheduled" and not release_time_ist:
        warnings.append("scheduled publishing needs publish_time_ist; publishing stays manual")
        mode = "manual"
        scheduled_upload = False

    return PublishingPolicy(
        mode=mode,
        scheduled_upload=scheduled_upload,
        late_run_policy=late,
        late_grace_minutes=number("late_grace_minutes", 90, 0, 24 * 60),
        minimum_lead_minutes=number("minimum_lead_minutes", 15, 5, 24 * 60),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class Release:
    """The release decision for one production run, with the reason it was made."""

    publish_at: datetime | None
    reason: str
    intended: datetime | None = None
    policy: str = ""

    @property
    def scheduled(self) -> bool:
        return self.publish_at is not None

    def iso(self) -> str | None:
        if self.publish_at is None:
            return None
        return self.publish_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def describe(self) -> dict[str, Any]:
        return {
            "publish_at": self.iso(),
            "publish_at_ist": self.publish_at.astimezone(timezone(IST)).isoformat()
            if self.publish_at
            else None,
            "reason": self.reason,
            "intended": self.intended.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if self.intended
            else None,
            "late_run_policy": self.policy,
        }


def release_time_for(spec: "ChannelSpec") -> str:
    return spec.publish_time_ist or "12:00"


def intended_release(spec: "ChannelSpec", anchor: datetime) -> datetime:
    """The channel's release instant on the IST date of ``anchor``."""

    at_ist = anchor.astimezone(timezone(IST))
    iso = publish_at_utc(at_ist.date().isoformat(), release_time_for(spec))
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def resolve_release(
    spec: "ChannelSpec",
    *,
    now: datetime | None = None,
    run_started: datetime | None = None,
    existing_scheduled: datetime | None = None,
) -> Release:
    """Decide the release time this run should schedule, or refuse to schedule at all.

    Order of decisions:

    1. the intended instant is the channel's release time on the run's IST date;
    2. if it is far enough in the future, use it;
    3. if it is in the future but too close (a publish time only seconds away is a race with the API), push
       it out by ``minimum_lead_minutes``;
    4. if it has already passed, apply ``late_run_policy``: ``shift`` publishes today, a few minutes from
       now, within the grace window; ``skip`` refuses, so nothing is published quietly;
    5. never return a ``publishAt`` in the past, and never overwrite a newer release that is already
       scheduled.
    """

    policy = spec.publishing
    moment = now or datetime.now(timezone.utc)
    anchor = run_started or moment
    intended = intended_release(spec, anchor)
    lead = timedelta(minutes=policy.minimum_lead_minutes)

    if intended - moment >= lead:
        candidate = Release(intended, "on_time", intended, policy.late_run_policy)
    elif intended > moment:
        candidate = Release(moment + lead, "too_close_to_release", intended, policy.late_run_policy)
    else:
        lateness = moment - intended
        grace = timedelta(minutes=policy.late_grace_minutes)
        if policy.late_run_policy == "shift" and lateness <= grace:
            candidate = Release(
                moment + lead,
                f"late_run_shifted (late by {int(lateness.total_seconds())}s, grace "
                f"{policy.late_grace_minutes}min)",
                intended,
                policy.late_run_policy,
            )
        else:
            return Release(
                None,
                f"release_window_missed (late by {int(lateness.total_seconds())}s, policy "
                f"{policy.late_run_policy}, grace {policy.late_grace_minutes}min)",
                intended,
                policy.late_run_policy,
            )

    if existing_scheduled is not None and existing_scheduled >= candidate.publish_at:
        return Release(
            None,
            f"release_already_scheduled (this channel already has a release at "
            f"{existing_scheduled.isoformat()}, which is at or after {candidate.iso()} )",
            intended,
            policy.late_run_policy,
        )
    if candidate.publish_at <= moment:
        # Belt and braces: nothing above should produce this, and a past publishAt is invalid at the API.
        return Release(None, "refused_past_release", intended, policy.late_run_policy)
    return candidate


def scheduled_plan_at(
    spec: "ChannelSpec", plan_id: str, when: datetime) -> datetime | None:
    """The release already recorded for *this plan* on the same IST day, if there is one.

    A channel publishes a Short and a long-form episode every day, so "one release per day" is wrong. "One
    release per plan per day" is right: a retried job must not upload the same episode twice, while the two
    formats of the same day remain free to schedule independently.
    """

    from .state import ChannelState

    if not plan_id:
        return None
    target = when.astimezone(timezone(IST)).date()
    for item in ChannelState(spec.slug).history():
        if str(item.get("status") or "") not in {"uploaded", "scheduled"}:
            continue
        if str(item.get("plan_id") or "") != plan_id:
            continue
        value = item.get("publish_at")
        if not value:
            continue
        try:
            recorded = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        if recorded.astimezone(timezone(IST)).date() == target:
            return recorded
    return None


def latest_scheduled_release(spec: "ChannelSpec") -> datetime | None:
    """The newest future release already recorded for this channel, if any."""

    from .state import ChannelState

    newest: datetime | None = None
    for item in ChannelState(spec.slug).history():
        if str(item.get("status") or "") not in {"uploaded", "scheduled"}:
            continue
        value = item.get("publish_at")
        if not value:
            continue
        try:
            when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when > datetime.now(timezone.utc) and (newest is None or when > newest):
            newest = when
    return newest
