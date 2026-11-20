"""Thin factory layer over the hardened uploader.

Dry-run is the default. Real uploads require both an explicit CLI flag and an
environment gate so an accidental workflow invocation cannot publish anything.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from uploader.config import load_channel_configs
from uploader.credentials import CredentialManager
from uploader.router import ChannelRouter

from .config import CHANNELS_DIR, SECRETS_ROOT, UPLOAD_STATE_ROOT, ChannelSpec
from .content.models import Script
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
) -> dict[str, Any]:
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
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

    if execute and result.get("status") == "uploaded":
        state = ChannelState(spec.slug)
        state.record(
            topic=script.topic,
            title=script.title,
            status="uploaded",
            video_id=result.get("video_id"),
            publish_at=publish_at,
        )
    return result


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
