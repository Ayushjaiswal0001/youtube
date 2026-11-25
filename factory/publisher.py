"""Thin factory layer over the hardened uploader.

Dry-run is the default. Real uploads require both an explicit CLI flag and an
environment gate so an accidental workflow invocation cannot publish anything.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uploader.config import load_channel_configs
from uploader.credentials import CredentialManager
from uploader.errors import UploaderError
from uploader.router import ChannelRouter

from .config import CHANNELS_DIR, SECRETS_ROOT, UPLOAD_STATE_ROOT, ChannelSpec
from .content.models import Script
from .content.plans import advance_after_publish, existing_plan
from .state import ChannelState


def bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def make_router() -> ChannelRouter:
    configs = load_channel_configs(CHANNELS_DIR)
    credentials = CredentialManager(SECRETS_ROOT)
    return ChannelRouter(configs, credentials, UPLOAD_STATE_ROOT)


def build_upload_data(
    spec: ChannelSpec,
    script: Script,
    *,
    privacy: str = "private",
    publish_at: str | None = None,
    thumbnail: Path | str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "channel_slug": spec.slug,
        "title": script.title,
        "description": script.description,
        "tags": script.tags,
        "categoryId": spec.category_id,
        "madeForKids": bool(spec.made_for_kids),
        "privacyStatus": privacy,
        "notifySubscribers": False,
        "defaultLanguage": spec.language,
        "defaultAudioLanguage": spec.language,
    }
    if publish_at:
        data["publishAt"] = publish_at
    if thumbnail:
        data["thumbnail"] = str(thumbnail)
    return data


def publish_episode(
    spec: ChannelSpec,
    script: Script,
    video_path: Path | str,
    *,
    execute: bool = False,
    confirm_channel: str | None = None,
    publish_at: str | None = None,
    thumbnail: Path | str | None = None,
    allow_public: bool = False,
    router: ChannelRouter | None = None,
    skip_gate: bool = False,
) -> dict[str, Any]:
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")

    # The publishing gate runs for dry runs too, so an operator sees the same verdict the workflow
    # would see. It is enforced - not advisory - for a real upload: an artifact that fails the gate
    # is not published, whatever the CLI flags say.
    from .qa.publish_gate import evaluate_publish_gate

    gate = evaluate_publish_gate(
        spec, script, video_path, out_dir=video_path.parent, thumbnail=thumbnail,
        measure_decode=execute, measure_loudness=True,
    )
    if not gate.ok and not skip_gate:
        if execute:
            raise PermissionError(
                "publishing gate failed: " + ", ".join(gate.blockers))
    if not gate.ok and skip_gate:
        gate_note = "gate bypassed by --skip-gate (dry run only)"
    else:
        gate_note = ""
    if execute and not bool_env("FACTORY_ALLOW_UPLOAD"):
        raise PermissionError(
            "real uploads are disabled; set FACTORY_ALLOW_UPLOAD=1 only after approval"
        )
    if execute and publish_at and not bool_env("FACTORY_ALLOW_SCHEDULE"):
        raise PermissionError(
            "scheduled releases are disabled; set FACTORY_ALLOW_SCHEDULE=1 only after approval"
        )
    if execute and confirm_channel != spec.slug:
        raise ValueError("--confirm-channel must exactly match the selected channel")

    privacy = "private"
    if allow_public and not publish_at:
        privacy = "public"
    data = build_upload_data(
        spec,
        script,
        privacy=privacy,
        publish_at=publish_at,
        thumbnail=thumbnail,
    )
    client = router or make_router()
    result = client.upload(
        spec.slug,
        video_path,
        data,
        execute=execute,
        confirm_channel=confirm_channel,
        allow_public=allow_public,
    )
    result["requested_privacy"] = privacy
    result["scheduled"] = bool(publish_at)
    result["gate"] = gate.to_dict()
    if gate_note:
        result["gate_note"] = gate_note

    if execute and publish_at and result.get("status") == "uploaded":
        verify_schedule(client, spec, result, publish_at)

    if execute and result.get("status") == "uploaded":
        state = ChannelState(spec.slug)
        state.record(
            topic=script.topic,
            title=script.title,
            status="uploaded",
            video_id=result.get("video_id"),
            publish_at=publish_at,
            plan_id=script.metadata.get("plan_id"),
        )
        # Natkhat continuity: only an actual upload advances the series pointer.
        target = existing_plan(spec, str(script.metadata.get("plan_id") or ""))
        if target is not None:
            result["series_state"] = advance_after_publish(spec, target)
    return result


#: How many times to re-read `videos.list` before calling a schedule unverified. The insert response and the
#: list API are not always consistent within the same second; a few seconds of retry removes that race without
#: ever turning a missing `publishAt` into a success.
SCHEDULE_READ_BACK_ATTEMPTS = 5
SCHEDULE_READ_BACK_SECONDS = 3.0


def _same_instant(left: Any, right: Any) -> bool:
    if not left or not right:
        return False
    try:
        a = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
    except ValueError:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=timezone.utc)
    if b.tzinfo is None:
        b = b.replace(tzinfo=timezone.utc)
    return abs((a - b).total_seconds()) < 1.0


def verify_schedule(client: Any, spec: ChannelSpec, result: dict[str, Any], publish_at: str) -> None:
    """Read the video back and require YouTube to hold the release time we asked for.

    `result["scheduled"]` records what the factory *asked* for. This turns it into evidence. It raises rather
    than returning a flag, because a run that uploaded a video and did not schedule it must not end green: the
    video is private in that case, so failing is safe and visible.

    Deliberately no retry on an API *error*: a permission failure is not transient, and retrying it is how a
    token gets throttled. The retry loop only covers a missing `publishAt` while the API catches up.
    """

    api_factory = getattr(client, "refresh_api", None)
    if api_factory is None:  # a test double that cannot read back
        result["schedule_verified"] = None
        return

    observed: Any = None
    detail = ""
    for attempt in range(SCHEDULE_READ_BACK_ATTEMPTS):
        try:
            api = api_factory(spec.slug)
            status = api.get_video(str(result.get("video_id")), parts="status").get("status", {})
        except Exception as exc:  # noqa: BLE001 - a failed read must never look like a successful schedule
            result["schedule_verified"] = False
            result["schedule_error"] = f"{type(exc).__name__}: {exc}"
            raise UploaderError(
                f"uploaded {result.get('video_id')} but could not read its release time back: {exc}"
            ) from exc
        observed = status.get("publishAt")
        if _same_instant(observed, publish_at):
            result["schedule_verified"] = True
            result["observed_publish_at"] = observed
            result["privacy_status"] = status.get("privacyStatus")
            return
        detail = (
            f"YouTube holds publishAt={observed!r} privacyStatus={status.get('privacyStatus')!r} "
            f"for video {result.get('video_id')}"
        )
        if attempt + 1 < SCHEDULE_READ_BACK_ATTEMPTS:
            time.sleep(SCHEDULE_READ_BACK_SECONDS)

    result["schedule_verified"] = False
    result["observed_publish_at"] = observed
    raise UploaderError(
        f"uploaded {result.get('video_id')} but the release was not applied: {detail}. "
        f"requested publishAt={publish_at}. The video is private; set the release time in Studio."
    )


def analytics_for(
    spec: ChannelSpec,
    *,
    router: ChannelRouter | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    client = router or make_router()
    state = ChannelState(spec.slug)
    uploaded = [
        item
        for item in state.history()
        if item.get("status") == "uploaded" and item.get("video_id")
    ][-limit:]
    if not uploaded:
        return {
            "channel": spec.slug,
            "videos": [],
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
        }
    api = client.refresh_api(spec.slug)
    ids = [str(item["video_id"]) for item in uploaded]
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(ids), 50):
        payload = api.videos_stats(ids[offset : offset + 50])
        for item in payload:
            stats = item.get("statistics", {})
            rows.append(
                {
                    "video_id": item.get("id"),
                    "title": item.get("snippet", {}).get("title", ""),
                    "published_at": item.get("snippet", {}).get("publishedAt"),
                    "privacy_status": item.get("status", {}).get("privacyStatus"),
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                }
            )
    rows.sort(key=lambda row: row["views"], reverse=True)
    return {
        "channel": spec.slug,
        "videos": rows,
        "total_views": sum(row["views"] for row in rows),
        "total_likes": sum(row["likes"] for row in rows),
        "total_comments": sum(row["comments"] for row in rows),
    }
