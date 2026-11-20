from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
HANDLE_RE = re.compile(r"^@[0-9A-Za-z._-]{3,30}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CATEGORY_RE = re.compile(r"^\d{1,2}$")
PRIVACY_VALUES = {"private", "unlisted", "public"}


@dataclass(frozen=True)
class ChannelDefaults:
    tags: tuple[str, ...] = ()
    category_id: str = "27"
    privacy_status: str = "private"
    made_for_kids: bool | None = False
    notify_subscribers: bool = False
    description_footer: str = ""
    playlist_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelDefaults":
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ConfigError("channel defaults.tags must be a list of strings")
        category_id = str(data.get("category_id", "27"))
        if not CATEGORY_RE.match(category_id):
            raise ConfigError("channel defaults.category_id must be numeric")
        privacy_status = str(data.get("privacy_status", "private"))
        if privacy_status not in PRIVACY_VALUES:
            raise ConfigError("channel defaults.privacy_status is invalid")
        made_for_kids = data.get("made_for_kids", False)
        if made_for_kids is not None and not isinstance(made_for_kids, bool):
            raise ConfigError("channel defaults.made_for_kids must be bool or null")
        notify_subscribers = data.get("notify_subscribers", False)
        if not isinstance(notify_subscribers, bool):
            raise ConfigError("channel defaults.notify_subscribers must be bool")
        description_footer = data.get("description_footer", "")
        if not isinstance(description_footer, str):
            raise ConfigError("channel defaults.description_footer must be a string")
        playlist_id = data.get("playlist_id")
        if playlist_id is not None and not isinstance(playlist_id, str):
            raise ConfigError("channel defaults.playlist_id must be a string or null")
        return cls(
            tags=tuple(tags),
            category_id=category_id,
            privacy_status=privacy_status,
            made_for_kids=made_for_kids,
            notify_subscribers=notify_subscribers,
            description_footer=description_footer,
            playlist_id=playlist_id,
        )


@dataclass(frozen=True)
class ChannelConfig:
    slug: str
    display_name: str
    handle: str
    expected_channel_id: str
    defaults: ChannelDefaults = field(default_factory=ChannelDefaults)
    requires_made_for_kids_confirmation: bool = False
    force_made_for_kids: bool = False
    allow_public_upload: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelConfig":
        required = (
            "slug",
            "display_name",
            "handle",
            "expected_channel_id",
        )
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ConfigError(f"channel config missing required fields: {', '.join(missing)}")
        slug = str(data["slug"])
        if not SLUG_RE.match(slug):
            raise ConfigError("channel slug must be lowercase kebab-case")
        display_name = str(data["display_name"]).strip()
        handle = str(data["handle"]).strip()
        expected_channel_id = str(data["expected_channel_id"]).strip()
        if not HANDLE_RE.match(handle):
            raise ConfigError(f"invalid handle for channel {slug}")
        if not CHANNEL_ID_RE.match(expected_channel_id):
            raise ConfigError(f"invalid expected_channel_id for channel {slug}")
        defaults = ChannelDefaults.from_dict(data.get("defaults", {}))
        requires_made_for_kids_confirmation = data.get(
            "requires_made_for_kids_confirmation", False
        )
        force_made_for_kids = data.get("force_made_for_kids", False)
        allow_public_upload = data.get("allow_public_upload", False)
        if not isinstance(requires_made_for_kids_confirmation, bool):
            raise ConfigError("requires_made_for_kids_confirmation must be bool")
        if not isinstance(force_made_for_kids, bool):
            raise ConfigError("force_made_for_kids must be bool")
        if not isinstance(allow_public_upload, bool):
            raise ConfigError("allow_public_upload must be bool")
        return cls(
            slug=slug,
            display_name=display_name,
            handle=handle,
            expected_channel_id=expected_channel_id,
            defaults=defaults,
            requires_made_for_kids_confirmation=requires_made_for_kids_confirmation,
            force_made_for_kids=force_made_for_kids,
            allow_public_upload=allow_public_upload,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "handle": self.handle,
            "expected_channel_id": self.expected_channel_id,
            "requires_made_for_kids_confirmation": self.requires_made_for_kids_confirmation,
            "force_made_for_kids": self.force_made_for_kids,
            "allow_public_upload": self.allow_public_upload,
            "defaults": {
                "tags": list(self.defaults.tags),
                "category_id": self.defaults.category_id,
                "privacy_status": self.defaults.privacy_status,
                "made_for_kids": self.defaults.made_for_kids,
                "notify_subscribers": self.defaults.notify_subscribers,
                "description_footer": self.defaults.description_footer,
                "playlist_id": self.defaults.playlist_id,
            },
        }


def load_channel_configs(directory: Path | str) -> dict[str, ChannelConfig]:
    path = Path(directory)
    if not path.is_dir():
        raise ConfigError(f"channels directory not found: {path}")
    configs: dict[str, ChannelConfig] = {}
    ids: dict[str, str] = {}
    for file_path in sorted(path.glob("*.json")):
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read channel config {file_path.name}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"channel config must be an object: {file_path.name}")
        config = ChannelConfig.from_dict(data)
        if config.slug in configs:
            raise ConfigError(f"duplicate channel slug: {config.slug}")
        if config.expected_channel_id in ids:
            raise ConfigError(
                f"duplicate expected_channel_id for {config.slug} and {ids[config.expected_channel_id]}"
            )
        configs[config.slug] = config
        ids[config.expected_channel_id] = config.slug
    if not configs:
        raise ConfigError(f"no channel configs found in {path}")
    return configs
