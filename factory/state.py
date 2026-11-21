"""Durable factory state: topic history, episode progress, and run records."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import STATE_ROOT
from .util import (
    append_jsonl,
    atomic_write_json,
    fingerprint,
    iso_now,
    read_json,
    read_jsonl,
    utc_now,
)


@dataclass
class HistoryEntry:
    topic: str
    fingerprint: str
    produced_at: str
    video_id: str | None = None
    status: str = "planned"
    publish_at: str | None = None
    title: str = ""
    plan_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "fingerprint": self.fingerprint,
            "produced_at": self.produced_at,
            "video_id": self.video_id,
            "status": self.status,
            "publish_at": self.publish_at,
            "title": self.title,
            "plan_id": self.plan_id,
        }


class ChannelState:
    def __init__(self, channel: str, root: Path | None = None):
        self.channel = channel
        self.root = Path(root or STATE_ROOT) / channel
        self.history_path = self.root / "history.json"
        self.series_path = self.root / "series.json"
        self.runs_path = self.root / "runs.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def history(self) -> list[dict[str, Any]]:
        data = read_json(self.history_path, [])
        return data if isinstance(data, list) else []

    def recent_topics(self, days: int = 180) -> list[str]:
        cutoff = utc_now() - timedelta(days=days)
        topics: list[str] = []
        for item in self.history():
            produced = item.get("produced_at", "")
            try:
                when = datetime.fromisoformat(produced)
            except (TypeError, ValueError):
                when = cutoff
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when >= cutoff:
                topics.append(str(item.get("topic", "")))
        return [topic for topic in topics if topic]

    def is_duplicate(self, topic: str, days: int = 180) -> bool:
        candidate = fingerprint(topic)
        for item in self.history():
            if item.get("fingerprint") == candidate:
                return True
        for old in self.recent_topics(days):
            if fingerprint(old) == candidate:
                return True
        return False

    def record(
        self,
        *,
        topic: str,
        title: str,
        status: str = "rendered",
        video_id: str | None = None,
        publish_at: str | None = None,
        plan_id: str | None = None,
    ) -> None:
        entry = HistoryEntry(
            topic=topic,
            fingerprint=fingerprint(topic),
            produced_at=iso_now(),
            video_id=video_id,
            status=status,
            publish_at=publish_at,
            title=title,
            plan_id=plan_id,
        )
        items = self.history()
        items = [item for item in items if item.get("fingerprint") != entry.fingerprint]
        items.append(entry.to_dict())
        atomic_write_json(self.history_path, items)

    def log_run(self, entry: dict[str, Any]) -> None:
        append_jsonl(self.runs_path, {"timestamp": iso_now(), **_scrub(entry)})

    def plan_status(self, plan_id: str) -> str | None:
        """Status recorded for a plan id, or None when the plan never ran."""

        for item in self.history():
            if item.get("plan_id") == plan_id:
                return str(item.get("status") or "")
        return None

    def series(self) -> dict[str, Any]:
        data = read_json(self.series_path, {})
        return data if isinstance(data, dict) else {}

    def save_series(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.series_path, data)

    def next_episode(self, series_key: str, max_episode: int) -> int:
        data = self.series()
        if data.get("active_series") != series_key:
            return 1
        value = int(data.get("next_episode", 1))
        return 1 if value > max_episode else max(1, value)

    def advance_series(self, series_key: str, episode: int, max_episode: int) -> None:
        next_episode = episode + 1
        active = series_key
        if next_episode > max_episode:
            active = ""
            next_episode = 1
        self.save_series(
            {
                "active_series": active,
                "next_episode": next_episode,
                "last_episode": episode,
                "last_series": series_key,
                "updated_at": iso_now(),
            }
        )



#: Prefix markers that identify a path as belonging to this project rather than to a machine.
_PROJECT_MARKERS = ("/build/", "\\build\\", "/pipeline_state/", "\\pipeline_state\\")


def portable_path(value: str) -> str:
    """A path with the machine left out.

    The run journal is uploaded as a CI artifact on a public repository, so an absolute
    ``C:\\Users\\<name>\\...`` path publishes the owner's account name and directory layout for no
    operational benefit. Anything inside this project is kept relative to it; a path outside it is
    reduced to its file name, which is all the journal needs in order to be useful.
    """

    text = str(value)
    for marker in _PROJECT_MARKERS:
        index = text.find(marker)
        if index > 0:
            return text[index + 1:].replace("\\", "/")
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith(("/c/", "/home/", "/Users/")):
        return Path(text).name
    return text


def _scrub(value, key: str = ""):
    if isinstance(value, dict):
        return {k: _scrub(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(item, key) for item in value]
    if isinstance(value, str) and (key.endswith("_path") or key in {
            "manifest", "video", "thumbnail", "thumbnail_file"}):
        return portable_path(value)
    return value

@dataclass
class RunResult:
    channel: str
    topic: str
    title: str
    video_path: str
    duration: float
    status: str
    video_id: str | None = None
    publish_at: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "topic": self.topic,
            "title": self.title,
            "video_path": self.video_path,
            "duration": self.duration,
            "status": self.status,
            "video_id": self.video_id,
            "publish_at": self.publish_at,
            "artifacts": self.artifacts,
        }
