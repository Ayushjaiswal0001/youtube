"""Static configuration and channel specs for the autonomous factory."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANNELS_DIR = REPO_ROOT / "channels"
ASSETS_DIR = REPO_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
SKILL_ROOT = REPO_ROOT / "skills" / "faceless-shorts"
CONTENT_DIR = REPO_ROOT / "content"
BUILD_ROOT = Path(os.environ.get("FACTORY_BUILD_DIR", REPO_ROOT / "build"))
STATE_ROOT = Path(os.environ.get("FACTORY_STATE_DIR", REPO_ROOT / "pipeline_state"))
SECRETS_ROOT = Path(
    os.environ.get(
        "YT_SECRETS_ROOT",
        Path.home() / ".faceless-shorts" / "secrets" / "youtube",
    )
)
UPLOAD_STATE_ROOT = Path(
    os.environ.get(
        "YT_STATE_ROOT",
        Path.home() / ".faceless-shorts" / "state" / "youtube",
    )
)
LOG_ROOT = Path(
    os.environ.get(
        "FACTORY_LOG_DIR",
        Path.home() / ".faceless-shorts" / "logs" / "youtube",
    )
)

SUPPORTED_LANGUAGES = {"en", "hi"}
SUPPORTED_FORMATS = {"shorts", "long"}

VIDEO_SIZES = {
    "shorts": (1080, 1920),
    "long": (1920, 1080),
}

FPS = 30
SAMPLE_RATE = 44100

PALETTES: dict[str, dict[str, str]] = {
    "nexus": {
        "bg": "#050B16",
        "bg2": "#0B1B2E",
        "panel": "#10243A",
        "text": "#F5F9FF",
        "muted": "#8FA6BF",
        "accent": "#4FD1E8",
        "accent2": "#FFB84D",
        "danger": "#FF5C7A",
        "grid": "#17324D",
    },
    "academic": {
        "bg": "#F4F1EA",
        "bg2": "#E9E2D4",
        "panel": "#FFFDF7",
        "text": "#1A1A1E",
        "muted": "#6B6257",
        "accent": "#D62839",
        "accent2": "#2A9D8F",
        "danger": "#B8283A",
        "grid": "#D8CFC0",
    },
    "natkhat": {
        "bg": "#120F24",
        "bg2": "#241A3A",
        "panel": "#2E2147",
        "text": "#FFF6E4",
        "muted": "#C8B6E2",
        "accent": "#FFD43B",
        "accent2": "#FF7A59",
        "danger": "#FF5C7A",
        "grid": "#3A2A5A",
    },
}


def bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ChannelSpec:
    slug: str
    display_name: str
    handle: str
    channel_id: str
    language: str
    format: str
    style: str
    voice: str
    rate: str
    pitch: str
    palette: str
    niche: str
    queries: tuple[str, ...] = field(default_factory=tuple)
    # Terms that must appear in a discovered item before it may be produced for this channel. A generic
    # relevance score let a Nature astronomy story top the learning-science channel at 0.62, because
    # freshness and title quality carried it; a channel now states what it is actually about.
    focus_terms: tuple[str, ...] = field(default_factory=tuple)
    publish_time_ist: str = ""
    series_key: str | None = None
    category_id: str = "27"
    tags: tuple[str, ...] = field(default_factory=tuple)
    description_footer: str = ""
    made_for_kids: bool | None = False

    @property
    def is_hindi(self) -> bool:
        return self.language == "hi"

    @property
    def size(self) -> tuple[int, int]:
        return VIDEO_SIZES[self.format]

    @property
    def colors(self) -> dict[str, str]:
        return PALETTES[self.palette]

    def safe_tags(self) -> list[str]:
        merged: list[str] = []
        for tag in (*self.tags, "shorts" if self.format == "shorts" else "video"):
            cleaned = tag.strip()
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
        return merged

    def as_upload_dict(self) -> dict[str, Any]:
        return {
            "channel_slug": self.slug,
            "title": "",
            "description": "",
            "tags": self.safe_tags(),
            "categoryId": self.category_id,
            "madeForKids": self.made_for_kids,
            "privacyStatus": "private",
            "notifySubscribers": False,
        }


def _require(data: Mapping[str, Any], key: str, slug: str) -> Any:
    value = data.get(key)
    if value in (None, ""):
        raise ValueError(f"channel {slug!r} is missing required key {key!r}")
    return value


def load_channel_specs(channels_dir: Path | str | None = None) -> dict[str, ChannelSpec]:
    directory = Path(channels_dir or CHANNELS_DIR)
    if not directory.is_dir():
        raise FileNotFoundError(f"channels directory not found: {directory}")
    specs: dict[str, ChannelSpec] = {}
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"channel config must be an object: {path.name}")
        slug = str(_require(raw, "slug", path.stem))
        factory = raw.get("factory") or {}
        if not isinstance(factory, dict):
            raise ValueError(f"channel factory block must be an object: {path.name}")
        defaults = raw.get("defaults") or {}
        language = str(factory.get("language", "en")).lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language for {slug}: {language}")
        fmt = str(factory.get("format", "shorts")).lower()
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported format for {slug}: {fmt}")
        palette = str(factory.get("palette", "nexus"))
        if palette not in PALETTES:
            raise ValueError(f"unknown palette for {slug}: {palette}")
        queries = factory.get("queries", [])
        if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
            raise ValueError(f"factory.queries for {slug} must be a list of strings")
        tags = defaults.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError(f"defaults.tags for {slug} must be a list of strings")
        spec = ChannelSpec(
            slug=slug,
            display_name=str(_require(raw, "display_name", slug)),
            handle=str(_require(raw, "handle", slug)),
            channel_id=str(_require(raw, "expected_channel_id", slug)),
            language=language,
            format=fmt,
            style=str(factory.get("style", "deep-dive")),
            voice=str(factory.get("voice", "en-US-AndrewNeural")),
            rate=str(factory.get("rate", "+8%")),
            pitch=str(factory.get("pitch", "+0Hz")),
            palette=palette,
            niche=str(factory.get("niche", "")),
            queries=tuple(queries),
            focus_terms=tuple(str(term).lower() for term in (factory.get("focus_terms") or [])),
            publish_time_ist=str(factory.get("publish_time_ist", "")),
            series_key=factory.get("series_key"),
            category_id=str(defaults.get("category_id", "27")),
            tags=tuple(tags),
            description_footer=str(defaults.get("description_footer", "")),
            made_for_kids=defaults.get("made_for_kids", False),
        )
        specs[slug] = spec
    if not specs:
        raise ValueError(f"no channel configs found in {directory}")
    return specs


def selected_channels(value: str | None, specs: Mapping[str, ChannelSpec]) -> list[ChannelSpec]:
    if not value or value == "all":
        return list(specs.values())
    wanted = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [slug for slug in wanted if slug not in specs]
    if unknown:
        raise ValueError(f"unknown channel: {', '.join(unknown)}")
    return [specs[slug] for slug in wanted]


def ensure_runtime_dirs() -> None:
    for path in (BUILD_ROOT, STATE_ROOT, LOG_ROOT, ASSETS_DIR / "sfx", ASSETS_DIR / "music"):
        path.mkdir(parents=True, exist_ok=True)
