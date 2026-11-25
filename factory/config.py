"""Static configuration and channel specs for the autonomous factory."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from .publishing import PublishingPolicy, parse_publishing_policy

LOGGER = logging.getLogger(__name__)

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


VISUAL_CATEGORIES = ("diagram", "dataviz", "motion_graphics", "kinetic_type", "photo",
                     "illustration", "software_demo")
# Every field ``parse_visual_policy`` understands. Anything else is reported, not dropped silently.
_POLICY_FIELDS = frozenset({"scene_planning", "categories", "min_scene_ms", "max_scene_ms",
                            "palette", "chart_values", "warnings"})
VISUAL_PALETTES = ("default", "paper")
DEFAULT_VISUAL_MIN_MS = 2000
DEFAULT_VISUAL_MAX_MS = 8000


@dataclass(frozen=True)
class VisualPolicy(Mapping[str, Any]):
    """How a channel is allowed to be visualised, parsed once and validated.

    A raw dict allowed ``{"categories": "diagram"}`` to survive, which ``set()`` then turned into
    ``{'d','i','a','g','r','m'}``; the planner compared categories against single characters and
    silently picked a different visual language. This type refuses to be parsed that way, keeps the
    warnings it produced, and still behaves like the dict every existing caller expects.
    """

    scene_planning: bool = False
    categories: tuple[str, ...] = ()
    min_scene_ms: int = DEFAULT_VISUAL_MIN_MS
    max_scene_ms: int = DEFAULT_VISUAL_MAX_MS
    palette: str = "default"
    chart_values: bool = True
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """The mapping view, for callers that pass a policy around as plain data."""

        return {
            "scene_planning": self.scene_planning,
            "categories": list(self.categories),
            "min_scene_ms": self.min_scene_ms,
            "max_scene_ms": self.max_scene_ms,
            "palette": self.palette,
            "chart_values": self.chart_values,
        }

    # Mapping protocol: `policy.get("scene_planning")`, `dict(policy)` and `policy or {}` all keep
    # working exactly as they did with a plain dict.
    def __getitem__(self, key: str) -> Any:
        try:
            return self.as_dict()[key]
        except KeyError as error:
            raise KeyError(key) from error

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self.as_dict().get(key, default)


def parse_visual_policy(raw: Any, *, slug: str = "") -> VisualPolicy:
    """Parse and validate ``visual_policy``. Bad values fall back and record why.

    A typo in one channel's config must not stop the other two from rendering, so this warns and
    defaults rather than raising - but the warning is kept on the object so a test (and a reviewer)
    can see exactly what was rejected.
    """

    if isinstance(raw, VisualPolicy):
        return raw
    if raw is None:
        return VisualPolicy()
    if not isinstance(raw, Mapping):
        message = f"visual_policy is {type(raw).__name__}, expected an object: ignored"
        LOGGER.warning("%s: %s", slug or "channel", message)
        return VisualPolicy(warnings=(message,))

    warnings: list[str] = []
    data = dict(raw)
    unknown_keys = sorted(str(key) for key in data if key not in _POLICY_FIELDS)
    if unknown_keys:
        # A typo ("chart_value", "min_scenes_ms") used to be dropped in silence, so a channel could
        # believe it had changed a setting that never changed. A warning is the whole point of D4.
        warnings.append(f"unknown visual_policy keys ignored: {unknown_keys}")

    scene_planning = data.get("scene_planning", False)
    if not isinstance(scene_planning, bool):
        warnings.append(f"scene_planning={scene_planning!r} is not a boolean: using False")
        scene_planning = False

    raw_categories = data.get("categories")
    if raw_categories is None:
        categories: tuple[str, ...] = ()
    elif isinstance(raw_categories, str):
        # One string is one category. Treating it as a sequence produced single characters.
        categories = (raw_categories.strip(),) if raw_categories.strip() else ()
    elif isinstance(raw_categories, (list, tuple, set, frozenset)):
        categories = tuple(str(item).strip() for item in raw_categories if str(item).strip())
    else:
        warnings.append(f"categories={type(raw_categories).__name__} is not a list: ignored")
        categories = ()
    unknown = [category for category in categories if category not in VISUAL_CATEGORIES]
    if unknown:
        warnings.append(f"unknown visual categories dropped: {unknown}")
        categories = tuple(category for category in categories if category in VISUAL_CATEGORIES)

    def positive_int(key: str, default: int) -> int:
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            warnings.append(f"{key}={value!r} is not a number: using {default}")
            return default
        number = int(value)
        if number <= 0:
            warnings.append(f"{key}={value!r} must be positive: using {default}")
            return default
        return number

    min_scene_ms = positive_int("min_scene_ms", DEFAULT_VISUAL_MIN_MS)
    max_scene_ms = positive_int("max_scene_ms", DEFAULT_VISUAL_MAX_MS)
    if min_scene_ms >= max_scene_ms:
        warnings.append(f"min_scene_ms ({min_scene_ms}) >= max_scene_ms ({max_scene_ms}): using defaults")
        min_scene_ms, max_scene_ms = DEFAULT_VISUAL_MIN_MS, DEFAULT_VISUAL_MAX_MS

    palette = data.get("palette", "default")
    if not isinstance(palette, str) or palette not in VISUAL_PALETTES:
        warnings.append(f"palette={palette!r} is not one of {list(VISUAL_PALETTES)}: using 'default'")
        palette = "default"

    chart_values = data.get("chart_values", True)
    if not isinstance(chart_values, bool):
        warnings.append(f"chart_values={chart_values!r} is not a boolean: using True")
        chart_values = True

    policy = VisualPolicy(scene_planning=scene_planning, categories=categories,
                          min_scene_ms=min_scene_ms, max_scene_ms=max_scene_ms, palette=palette,
                          chart_values=chart_values, warnings=tuple(warnings))
    if warnings:
        LOGGER.warning("%s: visual_policy: %s", slug or "channel", "; ".join(warnings))
    return policy


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
    # How this channel is allowed to be visualised. Empty means the legacy renderer: one visual per
    # narration line. ``scene_planning`` opts a channel into the scene planner, and ``categories``
    # bounds the visual jobs it may plan (a channel with no imagery supplied can never claim a photo).
    # Parsed into :class:`VisualPolicy`, which is also a Mapping, so ``.get()`` callers keep working.
    visual_policy: VisualPolicy = field(default_factory=VisualPolicy)
    # May this channel upload and set a release time without an operator? Parsed into PublishingPolicy,
    # which fails closed: an unknown mode means manual, an unknown late-run policy means skip.
    publishing: PublishingPolicy = field(default_factory=PublishingPolicy)

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
            visual_policy=parse_visual_policy(factory.get("visual_policy"), slug=slug),
            publishing=parse_publishing_policy(
                raw.get("publishing"),
                slug=slug,
                release_time_ist=str(factory.get("publish_time_ist", "")),
            ),
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
