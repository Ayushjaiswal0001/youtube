"""Content data structures shared by research, scripting, TTS, and rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WordTiming:
    text: str
    start: float
    end: float

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WordTiming":
        return cls(str(data["text"]), float(data["start"]), float(data["end"]))


@dataclass
class ScriptLine:
    text: str
    headline: str = ""
    visual: str = "network"
    sfx: str = ""
    caption: str = ""
    highlight: str = ""
    start: float = 0.0
    end: float = 0.0
    words: list[WordTiming] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "headline": self.headline,
            "visual": self.visual,
            "sfx": self.sfx,
            "caption": self.caption,
            "highlight": self.highlight,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "words": [word.to_dict() for word in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptLine":
        return cls(
            text=str(data["text"]),
            headline=str(data.get("headline", "")),
            visual=str(data.get("visual", "network")),
            sfx=str(data.get("sfx", "")),
            caption=str(data.get("caption", "")),
            highlight=str(data.get("highlight", "")),
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            words=[WordTiming.from_dict(item) for item in data.get("words", [])],
        )


@dataclass
class Script:
    channel: str
    language: str
    format: str
    topic: str
    title: str
    hook: str
    lines: list[ScriptLine]
    description: str
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    style: str = ""
    series: str | None = None
    episode: int | None = None
    moral: str = ""
    series_title: str = ""
    produced_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "language": self.language,
            "format": self.format,
            "topic": self.topic,
            "title": self.title,
            "hook": self.hook,
            "lines": [line.to_dict() for line in self.lines],
            "description": self.description,
            "tags": self.tags,
            "sources": self.sources,
            "style": self.style,
            "series": self.series,
            "episode": self.episode,
            "moral": self.moral,
            "series_title": self.series_title,
            "produced_at": self.produced_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Script":
        return cls(
            channel=str(data["channel"]),
            language=str(data.get("language", "en")),
            format=str(data.get("format", "shorts")),
            topic=str(data.get("topic", "")),
            title=str(data["title"]),
            hook=str(data.get("hook", "")),
            lines=[ScriptLine.from_dict(item) for item in data["lines"]],
            description=str(data.get("description", "")),
            tags=[str(item) for item in data.get("tags", [])],
            sources=[str(item) for item in data.get("sources", [])],
            style=str(data.get("style", "")),
            series=data.get("series"),
            episode=data.get("episode"),
            moral=str(data.get("moral", "")),
            series_title=str(data.get("series_title", "")),
            produced_at=str(data.get("produced_at", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class Narration:
    audio_path: str
    duration: float
    words: list[WordTiming] = field(default_factory=list)
    lines: list[ScriptLine] = field(default_factory=list)
    voice: str = ""
    provider: str = "edge"

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_path": self.audio_path,
            "duration": round(self.duration, 3),
            "words": [word.to_dict() for word in self.words],
            "lines": [line.to_dict() for line in self.lines],
            "voice": self.voice,
            "provider": self.provider,
        }
