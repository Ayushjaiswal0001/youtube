"""Audio-driven lip-sync for the 2D rigs.

The rigs used to open the mouth with ``abs(sin(t * 14))`` — a periodic wave that has no
relationship to what is being said, so mouths flapped through pauses and stayed closed
mid-word. This module derives openness from the narration itself: decode the voice track,
measure a per-frame RMS envelope, smooth it with attack/release, and map the result onto
the existing ``Viseme`` states.

Everything here is deterministic and dependency-free apart from ffmpeg, so it can be
tested without any synthesis service.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from .rig_base import Viseme

SAMPLE_RATE = 16000
SILENCE_FLOOR = 0.06  # normalised openness below this is a closed mouth


def viseme_for(openness: float) -> str:
    """Map normalised mouth openness onto a viseme state."""

    if openness <= SILENCE_FLOOR:
        return Viseme.CLOSED
    if openness < 0.25:
        return Viseme.SMILE
    if openness < 0.55:
        return Viseme.OPEN_SMALL
    if openness < 0.80:
        return Viseme.OPEN_WIDE
    return Viseme.SURPRISED


@dataclass
class VisemeTrack:
    """Per-frame mouth openness sampled at a fixed frame rate."""

    fps: float
    openness: List[float]
    source: str = "audio"

    def __len__(self) -> int:
        return len(self.openness)

    @property
    def duration(self) -> float:
        return len(self.openness) / self.fps if self.fps else 0.0

    def at(self, t: float) -> float:
        """Interpolated openness at time ``t`` seconds (0.0 outside the track)."""

        if not self.openness or t < 0:
            return 0.0
        position = t * self.fps
        index = int(position)
        if index >= len(self.openness) - 1:
            return self.openness[-1] if index < len(self.openness) else 0.0
        frac = position - index
        return self.openness[index] * (1.0 - frac) + self.openness[index + 1] * frac

    def viseme_at(self, t: float) -> str:
        return viseme_for(self.at(t))

    def speaking_at(self, t: float) -> bool:
        return self.at(t) > SILENCE_FLOOR

    # -- construction -------------------------------------------------------

    @classmethod
    def from_samples(
        cls,
        samples: Sequence[float],
        fps: float,
        sample_rate: int = SAMPLE_RATE,
        *,
        attack: float = 0.65,
        release: float = 0.55,
        percentile: float = 0.95,
    ) -> "VisemeTrack":
        """Build a track from mono PCM floats in [-1, 1]."""

        if fps <= 0:
            raise ValueError("fps must be positive")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        window = max(1, int(sample_rate / fps))
        frames: List[float] = []
        for start in range(0, len(samples), window):
            chunk = samples[start : start + window]
            if not chunk:
                break
            energy = math.sqrt(sum(value * value for value in chunk) / len(chunk))
            frames.append(energy)
        if not frames:
            return cls(fps=fps, openness=[], source="samples")

        ordered = sorted(frames)
        ceiling = ordered[min(len(ordered) - 1, int(percentile * (len(ordered) - 1)))]
        ceiling = ceiling or (max(frames) or 1.0)
        normalised = [min(1.0, value / ceiling) for value in frames]

        smoothed: List[float] = []
        current = 0.0
        for value in normalised:
            coefficient = attack if value > current else release
            current += (value - current) * coefficient
            smoothed.append(0.0 if current < SILENCE_FLOOR else current)
        return cls(fps=fps, openness=smoothed, source="samples")

    @classmethod
    def from_audio(
        cls,
        path: Path | str,
        fps: float = 30.0,
        *,
        start: float = 0.0,
        end: Optional[float] = None,
    ) -> "VisemeTrack":
        """Decode ``path`` with ffmpeg and build a track for the requested window."""

        path = Path(path)
        if not path.is_file() or path.stat().st_size < 500:
            return cls(fps=fps, openness=[], source=f"missing:{path.name}")
        if shutil.which("ffmpeg") is None:
            return cls(fps=fps, openness=[], source="ffmpeg-missing")

        with tempfile.TemporaryDirectory(prefix="lipsync-") as tmp:
            pcm_path = Path(tmp) / "pcm.wav"
            command = ["ffmpeg", "-v", "error", "-y"]
            if start > 0:
                command += ["-ss", f"{start:.3f}"]
            if end is not None and end > start:
                command += ["-t", f"{end - start:.3f}"]
            command += [
                "-i", str(path), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                "-c:a", "pcm_s16le", str(pcm_path),
            ]
            subprocess.run(command, check=True, capture_output=True, timeout=180)
            with wave.open(str(pcm_path), "rb") as handle:
                raw = handle.readframes(handle.getnframes())
                width = handle.getsampwidth()
        if width != 2:
            return cls(fps=fps, openness=[], source="unsupported-sample-width")
        count = len(raw) // 2
        samples = [value / 32768.0 for value in struct.unpack(f"<{count}h", raw)]
        return cls.from_samples(samples, fps, SAMPLE_RATE)
