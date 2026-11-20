from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config import CATEGORY_RE, PRIVACY_VALUES, ChannelConfig
from .errors import SafetyError, ValidationError

_SENTINEL = object()


@dataclass(frozen=True)
class UploadRequest:
    channel_slug: str
    video_path: Path
    title: str
    description: str
    tags: tuple[str, ...]
    category_id: str
    privacy_status: str
    made_for_kids: bool | None
    notify_subscribers: bool
    force_made_for_kids: bool = False
    playlist_id: str | None = None

    @classmethod
    def from_data(
        cls,
        channel: ChannelConfig,
        video_path: Path | str,
        data: Mapping[str, Any],
    ) -> "UploadRequest":
        if not isinstance(data, Mapping):
            raise ValidationError("video metadata must be an object")
        requested_slug = data.get("channel_slug", data.get("channel"))
        if requested_slug is not None and str(requested_slug) != channel.slug:
            raise ValidationError(
                f"metadata channel {requested_slug!r} does not match {channel.slug!r}"
            )
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", ""))
        footer = channel.defaults.description_footer
        if footer and footer not in description:
            description = f"{description.rstrip()}\n\n{footer}".strip()

        requested_tags = data.get("tags", [])
        if not isinstance(requested_tags, list) or not all(
            isinstance(tag, str) for tag in requested_tags
        ):
            raise ValidationError("tags must be a list of strings")
        merged_tags: list[str] = []
        for tag in (*channel.defaults.tags, *requested_tags):
            cleaned = tag.strip()
            if cleaned and cleaned not in merged_tags:
                merged_tags.append(cleaned)

        category_id = str(
            data.get("categoryId", data.get("category_id", channel.defaults.category_id))
        )
        privacy_status = str(
            data.get(
                "privacyStatus",
                data.get("privacy_status", channel.defaults.privacy_status),
            )
        ).lower()
        made_value = data.get("madeForKids", data.get("made_for_kids", _SENTINEL))
        if made_value is _SENTINEL:
            made_for_kids = channel.defaults.made_for_kids
        elif made_value is None or isinstance(made_value, bool):
            made_for_kids = made_value
        else:
            raise ValidationError("madeForKids must be true or false")
        notify_value = data.get(
            "notifySubscribers",
            data.get("notify_subscribers", _SENTINEL),
        )
        if notify_value is _SENTINEL:
            notify_subscribers = channel.defaults.notify_subscribers
        elif isinstance(notify_value, bool):
            notify_subscribers = notify_value
        else:
            raise ValidationError("notifySubscribers must be true or false")
        playlist_id = data.get(
            "playlistId",
            data.get("playlist_id", channel.defaults.playlist_id),
        )
        return cls(
            channel_slug=channel.slug,
            video_path=Path(video_path),
            title=title,
            description=description,
            tags=tuple(merged_tags),
            category_id=category_id,
            privacy_status=privacy_status,
            made_for_kids=made_for_kids if isinstance(made_for_kids, bool) else None,
            notify_subscribers=notify_subscribers,
            force_made_for_kids=channel.force_made_for_kids,
            playlist_id=str(playlist_id) if playlist_id else None,
        )

    def validate(self, *, allow_public: bool = False) -> None:
        if not self.title:
            raise ValidationError("title is required")
        if len(self.title) > 100:
            raise ValidationError("title exceeds 100 characters")
        if len(self.description) > 5000:
            raise ValidationError("description exceeds 5000 characters")
        if not isinstance(self.tags, tuple) or not all(
            isinstance(tag, str) for tag in self.tags
        ):
            raise ValidationError("tags must be strings")
        if len(",".join(self.tags)) > 500:
            raise ValidationError("tags exceed the 500-character total limit")
        if not CATEGORY_RE.match(self.category_id):
            raise ValidationError("categoryId must be numeric")
        if not 1 <= int(self.category_id) <= 44:
            raise ValidationError("categoryId is outside the supported range")
        if self.privacy_status not in PRIVACY_VALUES:
            raise ValidationError("privacyStatus must be private, unlisted, or public")
        if self.privacy_status == "public" and not allow_public:
            raise SafetyError(
                "public upload is disabled; pass --allow-public and use explicit approval"
            )
        if not isinstance(self.made_for_kids, bool):
            raise ValidationError(
                "madeForKids is required for this channel and must be true or false"
            )
        if self.force_made_for_kids and self.made_for_kids is not True:
            raise ValidationError("madeForKids must be true for this channel")
        if not isinstance(self.notify_subscribers, bool):
            raise ValidationError("notifySubscribers must be true or false")
        if self.playlist_id is not None and not self.playlist_id.strip():
            raise ValidationError("playlistId cannot be empty")
        if not self.video_path.is_file():
            raise ValidationError(f"video file not found: {self.video_path}")
        if self.video_path.suffix.lower() != ".mp4":
            raise ValidationError("video file must be an .mp4")
        if self.video_path.stat().st_size <= 0:
            raise ValidationError("video file is empty")

    def to_api_body(self) -> dict[str, Any]:
        snippet: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "categoryId": self.category_id,
        }
        if self.tags:
            snippet["tags"] = list(self.tags)
        return {
            "snippet": snippet,
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": bool(self.made_for_kids),
            },
        }

    def video_sha256(self) -> str:
        digest = hashlib.sha256()
        with self.video_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def metadata_sha256(self) -> str:
        canonical = {
            "channel_slug": self.channel_slug,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "category_id": self.category_id,
            "privacy_status": self.privacy_status,
            "made_for_kids": self.made_for_kids,
            "notify_subscribers": self.notify_subscribers,
            "playlist_id": self.playlist_id,
        }
        encoded = json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def probe_media(self) -> dict[str, Any]:
        ffprobe = _find_ffprobe()
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(self.video_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise ValidationError(f"ffprobe failed for {self.video_path.name}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValidationError("ffprobe returned invalid JSON") from exc
        streams = payload.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        if len(video_streams) != 1:
            raise ValidationError("video must have exactly one video stream")
        if not audio_streams:
            raise ValidationError("video must have an audio stream")
        video = video_streams[0]
        width = video.get("width")
        height = video.get("height")
        if width != 1080 or height != 1920:
            raise ValidationError(
                f"video must be 1080x1920, got {width}x{height}"
            )
        return {
            "width": width,
            "height": height,
            "duration": payload.get("format", {}).get("duration"),
            "audio_streams": len(audio_streams),
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "channel_slug": self.channel_slug,
            "video_file": self.video_path.name,
            "video_size": self.video_path.stat().st_size,
            "title": self.title,
            "description": self.description,
            "tags": list(self.tags),
            "category_id": self.category_id,
            "privacy_status": self.privacy_status,
            "made_for_kids": self.made_for_kids,
            "notify_subscribers": self.notify_subscribers,
            "playlist_id": self.playlist_id,
            "video_sha256": self.video_sha256(),
            "metadata_sha256": self.metadata_sha256(),
        }


def _find_ffprobe() -> str:
    import shutil

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValidationError("ffprobe is not available on PATH")
    return ffprobe


def load_metadata_file(path: Path | str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.is_file():
        raise ValidationError(f"metadata file not found: {file_path}")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read metadata file: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError("metadata file must contain a JSON object")
    return data
