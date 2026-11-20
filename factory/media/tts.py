"""Per-line narration with Edge-TTS word timings and a gTTS fallback."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import ChannelSpec
from ..content.models import Narration, Script, ScriptLine, WordTiming
from ..util import distribute_times, ffprobe_duration, run, utc_now


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _fallback_words(text: str, duration: float) -> list[WordTiming]:
    tokens = _word_tokens(text)
    if not tokens:
        return []
    weights = [max(2.0, len(token.strip(".,!?;:"))) for token in tokens]
    times = distribute_times(duration, weights)
    return [
        WordTiming(token, start, end)
        for token, (start, end) in zip(tokens, times)
    ]


async def _edge_line(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    output_path: Path,
) -> list[WordTiming]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        boundary="WordBoundary",
    )
    boundaries: list[WordTiming] = []
    with output_path.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = float(chunk["offset"]) / 10_000_000.0
                duration = float(chunk["duration"]) / 10_000_000.0
                word = str(chunk.get("text", "")).strip()
                if word:
                    boundaries.append(WordTiming(word, start, start + max(0.05, duration)))
    if not output_path.is_file() or output_path.stat().st_size < 1000:
        raise RuntimeError(f"Edge-TTS produced an empty file for: {text[:60]}")
    return boundaries


def _gtts_line(text: str, language: str, output_path: Path) -> None:
    from gtts import gTTS

    tld = "co.in" if language == "hi" else "com"
    gTTS(text=text, lang=language, tld=tld, slow=False).save(str(output_path))
    if not output_path.is_file() or output_path.stat().st_size < 1000:
        raise RuntimeError(f"gTTS produced an empty file for: {text[:60]}")


def _normalize_boundaries(
    boundaries: list[WordTiming],
    text: str,
    duration: float,
) -> list[WordTiming]:
    tokens = _word_tokens(text)
    if not boundaries or len(boundaries) < max(1, len(tokens) // 3):
        return _fallback_words(text, duration)
    cleaned: list[WordTiming] = []
    for item in boundaries:
        start = max(0.0, min(duration, item.start))
        end = max(start + 0.05, min(duration, item.end))
        cleaned.append(WordTiming(item.text, start, end))
    cleaned.sort(key=lambda item: item.start)
    return cleaned


def _make_silence(path: Path, duration: float) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo",
            "-t",
            f"{duration:.3f}",
            "-q:a",
            "4",
            str(path),
        ],
        timeout=30,
    )


def _concat_mp3(parts: list[Path], output_path: Path, work_dir: Path) -> None:
    list_file = work_dir / "audio_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{part.resolve().as_posix()}'" for part in parts) + "\n",
        encoding="utf-8",
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "3",
            str(output_path),
        ],
        timeout=120,
    )


def synthesize_script(script: Script, spec: ChannelSpec, output_dir: Path | str) -> Narration:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    voice = spec.voice
    rate = spec.rate
    pitch = spec.pitch
    language = spec.language
    gap = 0.18
    lead = 0.22
    tail = 0.45

    work_dir = output_dir / "tts_parts"
    work_dir.mkdir(parents=True, exist_ok=True)
    silence_gap = work_dir / "silence_gap.mp3"
    silence_lead = work_dir / "silence_lead.mp3"
    silence_tail = work_dir / "silence_tail.mp3"
    _make_silence(silence_gap, gap)
    _make_silence(silence_lead, lead)
    _make_silence(silence_tail, tail)

    parts: list[Path] = [silence_lead]
    timeline: list[ScriptLine] = []
    cursor = lead
    provider = "edge"

    for index, line in enumerate(script.lines, 1):
        raw_path = work_dir / f"line_{index:03d}.mp3"
        boundaries: list[WordTiming] = []
        error: Exception | None = None
        for attempt in range(3):
            try:
                boundaries = asyncio.run(
                    _edge_line(line.text, voice, rate, pitch, raw_path)
                )
                error = None
                break
            except Exception as exc:  # noqa: BLE001 - network/provider errors are expected
                error = exc
                try:
                    raw_path.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < 2:
                    import time

                    time.sleep(1.5 * (attempt + 1))
        if error is not None or not raw_path.is_file():
            provider = "gtts"
            _gtts_line(line.text, language, raw_path)
            boundaries = []

        line_duration = ffprobe_duration(raw_path)
        words = _normalize_boundaries(boundaries, line.text, line_duration)
        padded_path = work_dir / f"line_{index:03d}_padded.mp3"
        run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_path),
                "-af",
                f"apad=pad_dur={gap:.3f}",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "3",
                str(padded_path),
            ],
            timeout=60,
        )
        parts.append(padded_path)
        start = cursor
        end = start + line_duration
        timeline.append(
            ScriptLine(
                text=line.text,
                headline=line.headline,
                visual=line.visual,
                sfx=line.sfx,
                caption=line.caption,
                highlight=line.highlight,
                start=start,
                end=end,
                words=[WordTiming(word.text, start + word.start, start + word.end) for word in words],
            )
        )
        cursor = end + gap
        print(f"  [TTS] {index:02d}/{len(script.lines)} {line_duration:.2f}s {line.text[:60]!r}")

    if len(parts) == 1:
        raise ValueError("script has no lines to synthesize")
    parts.append(silence_tail)
    narration_path = output_dir / "narration.mp3"
    _concat_mp3(parts, narration_path, work_dir)
    duration = ffprobe_duration(narration_path)
    return Narration(
        audio_path=str(narration_path),
        duration=duration,
        words=[word for line in timeline for word in line.words],
        lines=timeline,
        voice=voice,
        provider=provider,
    )
