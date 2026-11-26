"""Deterministic, source-grounded script construction and batch planning."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..config import CONTENT_DIR, ChannelSpec
from ..util import iso_now, slugify
from .models import Script, ScriptLine


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "by",
    "can",
    "do",
    "for",
    "from",
    "has",
    "have",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "more",
    "not",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "up",
    "was",
    "what",
    "when",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def caption_for(text: str) -> str:
    words = re.findall(r"\S+", text)
    significant = [word for word in words if word.lower().strip(".,!?;:") not in STOPWORDS]
    chosen = significant[:3] or words[:3]
    return " ".join(chosen).strip(".,!?;: ")


def highlight_for(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9']{4,}", text)
    if not words:
        return ""
    return max(words, key=len).strip(".,!?;: ")


def _line(text: str, headline: str, visual: str, sfx: str = "whoosh") -> ScriptLine:
    return ScriptLine(
        text=_clean(text),
        headline=_clean(headline).upper(),
        visual=visual,
        sfx=sfx,
        caption=caption_for(text),
        highlight=highlight_for(text),
    )


def _description(title: str, hook: str, sources: Iterable[str], tags: Iterable[str], footer: str = "") -> str:
    parts = [title, "", hook]
    source_list = [source for source in sources if source]
    if source_list:
        parts.extend(["", "Sources:"] + [f"- {source}" for source in source_list])
    hashtags = " ".join(f"#{re.sub(r'[^A-Za-z0-9]', '', tag)}" for tag in tags if tag)
    if hashtags:
        parts.extend(["", hashtags])
    if footer:
        parts.extend(["", footer])
    text = "\n".join(parts).strip()
    return text[:4900]


@dataclass
class BatchPlan:
    batch_id: str
    created_at: str
    plans: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str) -> "BatchPlan":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("batch plan must be a JSON object")
        channels = data.get("channels")
        if not isinstance(channels, dict):
            raise ValueError("batch plan must contain a channels object")
        return cls(
            batch_id=str(data.get("batch_id", Path(path).stem)),
            created_at=str(data.get("created_at", "")),
            plans={str(key): list(value) for key, value in channels.items()},
        )

    def for_channel(self, channel: str) -> list[dict[str, Any]]:
        return self.plans.get(channel, [])


def default_batch_path() -> Path:
    """Newest authored batch; kept for callers that still expect a single file."""

    candidates = sorted(CONTENT_DIR.glob("batch_*.json"))
    if candidates:
        return candidates[-1]
    return CONTENT_DIR / "batch_2026-11-20.json"


def build_english_script(spec: ChannelSpec, plan: dict[str, Any]) -> Script:
    title = _clean(str(plan["title"]))
    topic = _clean(str(plan.get("topic", title)))
    hook = _clean(str(plan["hook"]))
    lines = [_line(hook, str(plan.get("hook_headline", "The big idea")), str(plan.get("hook_visual", "network")), "whoosh")]

    beats = plan.get("beats") or []
    minimum_beats = 6 if spec.format == "long" else 4
    if not isinstance(beats, list) or len(beats) < minimum_beats:
        raise ValueError(f"plan {topic!r} needs at least {minimum_beats} beats")
    for beat in beats:
        if not isinstance(beat, dict) or not beat.get("text"):
            raise ValueError(f"plan {topic!r} has an invalid beat")
        lines.append(
            _line(
                str(beat["text"]),
                str(beat.get("headline", caption_for(str(beat["text"])))),
                str(beat.get("visual", "network")),
                str(beat.get("sfx", "pop")),
            )
        )
    lines.append(_line(str(plan.get("payoff", "")), str(plan.get("payoff_headline", "The takeaway")), "spark", "ding"))
    lines.append(_line(str(plan.get("cta", "Follow for more.")), str(plan.get("cta_headline", "Follow")), "logo", "pop"))

    total_words = sum(word_count(line.text) for line in lines)
    minimum_words, maximum_words = (300, 1800) if spec.format == "long" else (60, 140)
    if total_words < minimum_words:
        raise ValueError(f"plan {topic!r} is too short ({total_words} words, {spec.format} needs {minimum_words}+)")
    if total_words > maximum_words:
        raise ValueError(f"plan {topic!r} is too long ({total_words} words, {spec.format} allows {maximum_words})")

    tags = list(dict.fromkeys([*spec.safe_tags(), *[str(tag) for tag in plan.get("tags", [])]]))
    sources = [str(source) for source in plan.get("sources", []) if str(source).strip()]
    if len(sources) < 2:
        raise ValueError(f"plan {topic!r} needs at least two sources")
    description = _description(title, hook, sources, tags, spec.description_footer)
    return Script(
        channel=spec.slug,
        language=spec.language,
        format=spec.format,
        topic=topic,
        title=title,
        hook=hook,
        lines=lines,
        description=description,
        tags=tags,
        sources=sources,
        style=spec.style,
        produced_at=iso_now(),
        metadata={
            "plan_id": str(plan.get("id", slugify(title))),
            "slot": plan.get("slot"),
            "angle": plan.get("angle", ""),
            "word_count": total_words,
            "chapters": plan.get("chapters", []),
        },
    )


def build_hindi_script(spec: ChannelSpec, plan: dict[str, Any]) -> Script:
    title = _clean(str(plan["title"]))
    topic = _clean(str(plan.get("topic", title)))
    hook = _clean(str(plan.get("hook", "")))
    scenes = plan.get("scenes") or []
    if not isinstance(scenes, list) or len(scenes) < 3:
        raise ValueError(f"Hindi plan {topic!r} needs at least three scenes")
    lines: list[ScriptLine] = []
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise ValueError(f"Hindi plan {topic!r} scene {index} is not an object")
        dialogue = scene.get("dialogue")
        if dialogue is not None and not isinstance(dialogue, str):
            # `str()` of a dict is a string, so the old check silently accepted nonsense text
            raise ValueError(f"Hindi plan {topic!r} scene {index} has a non-string dialogue")
        if not dialogue or not dialogue.strip():
            raise ValueError(f"Hindi plan {topic!r} has an invalid scene")
        lines.append(
            ScriptLine(
                text=_clean(str(scene["dialogue"])),
                headline=title.upper(),
                visual="studio",
                sfx=str(scene.get("sfx", "whoosh")),
                caption=caption_for(str(scene["dialogue"])),
                highlight="",
            )
        )
    tags = list(dict.fromkeys([*spec.safe_tags(), *[str(tag) for tag in plan.get("tags", [])]]))
    description = _description(
        title,
        hook,
        ["Original Natkhat Toons story"],
        tags,
        spec.description_footer,
    )
    return Script(
        channel=spec.slug,
        language=spec.language,
        format=spec.format,
        topic=topic,
        title=title,
        hook=hook,
        lines=lines,
        description=description,
        tags=tags,
        sources=["Original Natkhat Toons story"],
        style=spec.style,
        series=plan.get("series"),
        episode=int(plan["episode"]) if plan.get("episode") is not None else None,
        moral=_clean(str(plan.get("moral", ""))),
        series_title=_clean(str(plan.get("series_title", ""))),
        produced_at=iso_now(),
        metadata={
            "plan_id": str(plan.get("id", slugify(title))),
            "slot": plan.get("slot"),
            "scenes": scenes,
        },
    )


def story_packet(script: Script, spec: ChannelSpec) -> dict[str, Any]:
    if not script.series or not script.episode:
        raise ValueError("story_packet requires a series and episode")
    scenes: list[dict[str, Any]] = []
    for index, (line, raw) in enumerate(zip(script.lines, script.metadata.get("scenes", [])), 1):
        scenes.append(
            {
                "scene_num": index,
                "speaker": str(raw.get("speaker", "narrator")),
                "dialogue": line.text,
                "chiku_pose": str(raw.get("chiku_pose", "idle")),
                "gappu_pose": str(raw.get("gappu_pose", "idle")),
                "camera": str(raw.get("camera", "medium_pan")),
                "bg": str(raw.get("bg", "haunted_haveli")),
                "visual_style": spec.visual_style,
                "sfx": str(raw.get("sfx", "whoosh")),
                "subtitle_png": str(raw.get("subtitle_png", "")),
                "title_png": str(raw.get("title_png", "")),
            }
        )
    plan_id = str(script.metadata.get("plan_id") or f"{script.series}_e{script.episode:02d}")
    story_id = f"{spec.slug}_{slugify(plan_id)}"
    return {
        "story_id": story_id,
        "hash": f"factory:{script.topic}",
        "created_at": script.produced_at,
        "category": "haunted_haveli",
        "title": script.title,
        "hook": script.hook,
        "characters": {
            "chiku": {"name": "चीकू", "role": "curious hero"},
            "gappu": {"name": "गप्पू", "role": "clever friend"},
        },
        "scenes": scenes,
        "total_scenes": len(scenes),
        "moral": script.moral,
        "series": script.series,
        "series_title": script.series_title,
        "episode": script.episode,
    }


def load_plans_for(spec: ChannelSpec, batch_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Every plan for a channel, oldest batch first, first occurrence wins.

    Batch files are additive: a daily run appends its generated plan to
    ``batch_<date>.json`` and older batches keep working, so pending plans are never
    lost when a new batch appears.
    """

    if batch_path:
        paths = [Path(batch_path)]
    else:
        longform = CONTENT_DIR / "longform"
        paths = sorted(CONTENT_DIR.glob("batch_*.json"))
        if longform.is_dir():
            paths.extend(sorted(longform.glob("*.json")))
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        batch = BatchPlan.load(path)
        for plan in batch.for_channel(spec.slug):
            if not isinstance(plan, dict):
                continue
            key = slugify(str(plan.get("id") or plan.get("title") or ""))
            if key in seen:
                continue
            seen.add(key)
            plans.append(plan)
    wanted = str(spec.format).lower()
    plans = [
        plan
        for plan in plans
        if str(plan.get("format") or "shorts").lower() == wanted
    ]
    if not plans:
        raise ValueError(f"no {wanted} plans for channel {spec.slug!r}")
    return plans
