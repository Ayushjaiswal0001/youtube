"""Plan generation: turn topic banks and series bibles into renderable plans.

The factory was plan-driven: `content/batch_<date>.json` had to be authored by hand.
This module makes plan creation autonomous while keeping it deterministic and
reviewable:

* English channels draw from ``content/topics/<slug>.json``. A topic is claimed when
  it produces a plan, and a topic that already appears in the channel history is
  rejected, so nothing repeats.
* Natkhat Toons draws from ``content/series/<slug>.json`` and keeps series memory in
  ``pipeline_state/<slug>/series.json``. An episode is only planned when the previous
  episode was actually published (override with ``allow_unpublished`` for dry runs),
  and a finished series rolls over to the next series automatically.

Nothing here invents facts at runtime: the plans are authored content that the
selector orders. When a bank or bible is exhausted the generator fails loudly instead
of emitting filler.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import CONTENT_DIR, ChannelSpec
from ..util import IST, atomic_write_json, iso_now, read_json, slugify
from ..state import ChannelState

TOPICS_DIR = CONTENT_DIR / "topics"
SERIES_DIR = CONTENT_DIR / "series"


class PlanGenerationError(RuntimeError):
    """Raised when no new plan can be produced without human input."""


# --------------------------------------------------------------------------- banks


def topic_bank_path(spec: ChannelSpec) -> Path:
    return TOPICS_DIR / f"{spec.slug}.json"


def series_bible_path(spec: ChannelSpec) -> Path:
    return SERIES_DIR / f"{spec.slug}.json"


def load_topic_bank(spec: ChannelSpec) -> list[dict[str, Any]]:
    path = topic_bank_path(spec)
    if not path.is_file():
        raise PlanGenerationError(f"no topic bank for {spec.slug}: {path}")
    data = read_json(path, {})
    topics = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics, list) or not topics:
        raise PlanGenerationError(f"topic bank {path} has no topics")
    for topic in topics:
        missing = [key for key in ("id", "title", "hook", "beats") if not topic.get(key)]
        if missing:
            raise PlanGenerationError(f"topic {topic.get('id', '?')} is missing {missing}")
    return topics


def load_series_bible(spec: ChannelSpec) -> dict[str, Any]:
    path = series_bible_path(spec)
    if not path.is_file():
        raise PlanGenerationError(f"no series bible for {spec.slug}: {path}")
    data = read_json(path, {})
    series = data.get("series") if isinstance(data, dict) else None
    if not isinstance(series, list) or not series:
        raise PlanGenerationError(f"series bible {path} has no series")
    for entry in series:
        if not entry.get("series") or not entry.get("episodes"):
            raise PlanGenerationError("series entry needs 'series' and 'episodes'")
    return data


# ----------------------------------------------------------------- batch helpers


def batch_files() -> list[Path]:
    return sorted(CONTENT_DIR.glob("batch_*.json"))


def batch_path_for(date: datetime | None = None) -> Path:
    moment = date or (datetime.now(timezone.utc) + IST)
    return CONTENT_DIR / f"batch_{moment.date().isoformat()}.json"


def plan_id_of(plan: dict[str, Any]) -> str:
    return slugify(str(plan.get("id") or plan.get("title") or "episode"))


def all_plans(spec: ChannelSpec) -> list[dict[str, Any]]:
    """Every plan written for a channel, across all batch files."""

    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in batch_files():
        data = read_json(path, {})
        channels = data.get("channels") if isinstance(data, dict) else None
        if not isinstance(channels, dict):
            continue
        for plan in channels.get(spec.slug, []) or []:
            if not isinstance(plan, dict):
                continue
            pid = plan_id_of(plan)
            if pid in seen:
                continue
            seen.add(pid)
            plans.append(plan)
    return plans


def existing_plan(spec: ChannelSpec, plan_id: str) -> dict[str, Any] | None:
    wanted = slugify(plan_id)
    for plan in all_plans(spec):
        if plan_id_of(plan) == wanted:
            return plan
    return None


def write_plan(spec: ChannelSpec, plan: dict[str, Any], path: Path | None = None) -> Path:
    target = Path(path or batch_path_for())
    data = read_json(target, {})
    if not isinstance(data, dict) or not data:
        data = {
            "batch_id": target.stem.replace("batch_", "batch-"),
            "created_at": iso_now(),
            "auto_generated": True,
            "channels": {},
        }
    channels = data.setdefault("channels", {})
    bucket = channels.setdefault(spec.slug, [])
    if any(plan_id_of(item) == plan_id_of(plan) for item in bucket if isinstance(item, dict)):
        raise PlanGenerationError(f"plan {plan_id_of(plan)} already exists in {target.name}")
    bucket.append(plan)
    atomic_write_json(target, data)
    return target


# --------------------------------------------------------------- English plans


def _claimable_topics(spec: ChannelSpec, state: ChannelState) -> list[dict[str, Any]]:
    claimed = {plan_id_of(plan) for plan in all_plans(spec)}
    fresh: list[dict[str, Any]] = []
    for topic in load_topic_bank(spec):
        if plan_id_of(topic) in claimed:
            continue
        if state.is_duplicate(str(topic.get("topic") or topic.get("title") or "")):
            continue
        fresh.append(topic)
    return fresh


def plan_from_topic(topic: dict[str, Any]) -> dict[str, Any]:
    """Normalise a bank entry into the plan shape build_english_script expects."""

    plan = {
        "id": plan_id_of(topic),
        "title": topic["title"],
        "topic": topic.get("topic", topic["title"]),
        "hook": topic["hook"],
        "hook_headline": topic.get("hook_headline", "The big idea"),
        "hook_visual": topic.get("hook_visual", "network"),
        "beats": topic["beats"],
        "payoff": topic.get("payoff", ""),
        "payoff_headline": topic.get("payoff_headline", "The takeaway"),
        "cta": topic.get("cta", "Follow for more."),
        "cta_headline": topic.get("cta_headline", "Follow"),
        "tags": topic.get("tags", []),
        "sources": topic.get("sources", []),
        "slot": topic.get("slot", "pm"),
        "angle": topic.get("angle", ""),
    }
    return plan


def next_english_plan(spec: ChannelSpec, state: ChannelState) -> dict[str, Any]:
    fresh = _claimable_topics(spec, state)
    if not fresh:
        raise PlanGenerationError(
            f"{spec.slug}: topic bank exhausted; add entries to {topic_bank_path(spec)}"
        )
    return plan_from_topic(fresh[0])


# ---------------------------------------------------------------- Natkhat series


def series_state(state: ChannelState) -> dict[str, Any]:
    data = state.series()
    return {
        "active_series": data.get("active_series") or "",
        "next_episode": int(data.get("next_episode") or 0),
        "completed": list(data.get("completed") or []),
        "updated_at": data.get("updated_at", ""),
    }


def _episode_plan_id(series: str, episode: int) -> str:
    return f"{series}-e{episode}"


def _find_series(bible: dict[str, Any], series_key: str) -> dict[str, Any] | None:
    for entry in bible["series"]:
        if entry["series"] == series_key:
            return entry
    return None


def _resolve_slot(
    bible: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    """Pick the series and episode the continuity state points at."""

    completed = set(payload["completed"])
    key = payload["active_series"]
    episode = payload["next_episode"]

    # Walk forward until a series still has an unplayed episode.
    for _ in range(len(bible["series"]) + 1):
        entry = _find_series(bible, key) if key else None
        if entry is None:
            candidate = next(
                (item for item in bible["series"] if item["series"] not in completed),
                None,
            )
            if candidate is None:
                raise PlanGenerationError(
                    "every series in the bible is finished; write the next series"
                )
            entry = candidate
            key = entry["series"]
            episode = int(entry.get("start_episode", 1))

        start = int(entry.get("start_episode", 1))
        last = start + len(entry["episodes"]) - 1
        if episode < start:
            episode = start
        if episode <= last:
            return entry, episode, {**payload, "active_series": key, "next_episode": episode}

        completed.add(key)
        key = ""
        episode = 0
        payload = {**payload, "completed": sorted(completed)}

    raise PlanGenerationError("could not resolve a playable series episode")


def _history_status(state: ChannelState, plan_id: str) -> str | None:
    for item in state.history():
        if item.get("plan_id") == plan_id:
            return str(item.get("status") or "")
    return None


def next_natkhat_plan(
    spec: ChannelSpec,
    state: ChannelState,
    *,
    allow_unpublished: bool = False,
) -> dict[str, Any]:
    bible = load_series_bible(spec)
    entry, episode, _ = _resolve_slot(bible, series_state(state))
    start = int(entry.get("start_episode", 1))

    if episode > 1 and not allow_unpublished:
        previous = _episode_plan_id(entry["series"], episode - 1)
        status = _history_status(state, previous)
        if status != "uploaded":
            raise PlanGenerationError(
                f"episode {previous} is {status or 'not in history'}, not uploaded; "
                "publishing out of order is blocked (use --allow-unpublished for a dry run)"
            )

    raw = entry["episodes"][episode - start]
    plan = {
        "id": _episode_plan_id(entry["series"], episode),
        "title": raw["title"],
        "topic": raw.get("topic", raw["title"]),
        "hook": raw.get("hook", ""),
        "series": entry["series"],
        "series_title": entry.get("series_title", ""),
        "episode": episode,
        "moral": entry.get("moral", ""),
        "tags": raw.get("tags", []),
        "scenes": raw["scenes"],
        "slot": "pm",
        "category": entry.get("category", ""),
        "auto_generated": True,
    }
    return plan


# ------------------------------------------------------------------- entry points


def generate_plan(
    spec: ChannelSpec,
    *,
    allow_unpublished: bool = False,
    batch_date: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Return the next plan for a channel, writing it to today's batch by default."""

    state = ChannelState(spec.slug)
    plan = (
        next_natkhat_plan(spec, state, allow_unpublished=allow_unpublished)
        if spec.is_hindi
        else next_english_plan(spec, state)
    )
    delegate = existing_plan(spec, plan_id_of(plan))
    if delegate is not None:
        return {
            "plan": delegate,
            "plan_id": plan_id_of(delegate),
            "channel": spec.slug,
            "created": False,
            "reason": "plan already exists (already rendered or awaiting render)",
        }
    path = None
    if write:
        path = write_plan(spec, plan, batch_path_for(batch_date))
    return {
        "plan": plan,
        "plan_id": plan_id_of(plan),
        "channel": spec.slug,
        "created": True,
        "batch": str(path) if path else "",
    }


def advance_after_publish(spec: ChannelSpec, plan: dict[str, Any]) -> dict[str, Any] | None:
    """Move series memory forward once an episode is actually uploaded."""

    if not spec.is_hindi:
        return None
    series = plan.get("series")
    episode = plan.get("episode")
    if not series or episode is None:
        return None
    bible = load_series_bible(spec)
    entry = _find_series(bible, str(series))
    if entry is None:
        return None
    start = int(entry.get("start_episode", 1))
    last = start + len(entry["episodes"]) - 1
    current = int(episode)
    payload = {
        "active_series": str(series) if current < last else "",
        "next_episode": current + 1 if current < last else 0,
        "completed": series_state(ChannelState(spec.slug))["completed"],
        "updated_at": iso_now(),
        "last_series": str(series),
        "last_episode": current,
    }
    if current >= last:
        payload["completed"] = sorted({*payload["completed"], str(series)})
    ChannelState(spec.slug).save_series(payload)
    return payload


def bank_status(spec: ChannelSpec) -> dict[str, Any]:
    state = ChannelState(spec.slug)
    if spec.is_hindi:
        bible = load_series_bible(spec)
        payload = series_state(state)
        entry, episode, _ = _resolve_slot(bible, payload)
        start = int(entry.get("start_episode", 1))
        return {
            "channel": spec.slug,
            "mode": "series",
            "active_series": entry["series"],
            "next_episode": episode,
            "episodes_left_in_series": len(entry["episodes"]) - (episode - start),
            "completed": payload["completed"],
            "series_available": [item["series"] for item in bible["series"]],
        }
    fresh = _claimable_topics(spec, state)
    return {
        "channel": spec.slug,
        "mode": "topics",
        "unused_topics": [plan_id_of(topic) for topic in fresh],
        "remaining": len(fresh),
        "plans_written": len(all_plans(spec)),
    }
