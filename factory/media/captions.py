"""SRT caption generation from renderer timelines."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from ..config import ChannelSpec
from ..content.models import Script
from ..util import atomic_write_text, distribute_times, hhmmss


def _split_caption(text: str, max_chars: int) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _cues_from_line(
    text: str,
    start: float,
    end: float,
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text or end <= start:
        return []
    chunks = _split_caption(text, max_chars)
    if not chunks:
        return []
    weights = [max(4, len(chunk)) for chunk in chunks]
    times = distribute_times(end - start, weights)
    return [
        {
            "start": start + offset_start,
            "end": start + offset_end,
            "text": chunk,
        }
        for chunk, (offset_start, offset_end) in zip(chunks, times)
    ]


def _english_cues(timeline: dict[str, Any], max_chars: int) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for line in timeline.get("lines", []):
        if not isinstance(line, dict):
            continue
        cues.extend(
            _cues_from_line(
                str(line.get("text", "")),
                float(line.get("start", 0.0)),
                float(line.get("end", 0.0)),
                max_chars=max_chars,
            )
        )
    return cues


def _hindi_cues(
    timeline: dict[str, Any],
    story: dict[str, Any] | None,
    max_chars: int,
) -> list[dict[str, Any]]:
    scenes = timeline.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        scenes = (story or {}).get("scenes", [])
    cues: list[dict[str, Any]] = []
    cursor = 0.0
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        duration = float(scene.get("duration") or 0.0)
        if duration <= 0:
            continue
        cues.extend(
            _cues_from_line(
                str(scene.get("dialogue", "")),
                cursor,
                cursor + duration,
                max_chars=max_chars,
            )
        )
        cursor += duration
    return cues


def _srt_text(cues: Iterable[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(cues, 1):
        start = float(cue["start"])
        end = max(start + 0.12, float(cue["end"]))
        blocks.append(
            f"{index}\n{hhmmss(start)} --> {hhmmss(end)}\n{cue['text']}\n"
        )
    return "\n".join(blocks)


def build_srt(
    spec: ChannelSpec,
    script: Script,
    timeline: dict[str, Any],
    output_path: Path | str,
    *,
    story: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    output_path = Path(output_path)
    limit = max_chars or (38 if spec.is_hindi else 46)
    if spec.is_hindi:
        cues = _hindi_cues(timeline, story, limit)
    else:
        cues = _english_cues(timeline, limit)
    if not cues:
        raise ValueError(f"no caption cues could be built for {script.title!r}")
    atomic_write_text(output_path, _srt_text(cues))
    return {
        "srt_path": str(output_path),
        "cue_count": len(cues),
        "first_cue": cues[0],
        "last_cue": cues[-1],
    }
