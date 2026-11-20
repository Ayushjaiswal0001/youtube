"""Tiny procedural music/SFX bed generator (no external assets or licenses)."""

from __future__ import annotations

import math
import wave
from pathlib import Path
from typing import Iterable

import numpy as np

SAMPLE_RATE = 44100


def _envelope(length: int, attack: float = 0.02, release: float = 0.25) -> np.ndarray:
    attack_samples = max(1, int(attack * SAMPLE_RATE))
    release_samples = max(1, int(release * SAMPLE_RATE))
    env = np.ones(length, dtype=np.float64)
    if attack_samples < length:
        env[:attack_samples] = np.linspace(0.0, 1.0, attack_samples)
    if release_samples < length:
        env[-release_samples:] *= np.linspace(1.0, 0.0, release_samples)
    return env


def _tone(freq: float, duration: float, amplitude: float, detune: float = 0.0) -> np.ndarray:
    length = max(1, int(duration * SAMPLE_RATE))
    t = np.arange(length, dtype=np.float64) / SAMPLE_RATE
    signal = np.sin(2 * math.pi * freq * t)
    if detune:
        signal += 0.35 * np.sin(2 * math.pi * (freq * (1.0 + detune)) * t)
    return amplitude * signal * _envelope(length, 0.01, min(0.2, duration))


def _add_at(buffer: np.ndarray, signal: np.ndarray, start: float, gain: float = 1.0) -> None:
    index = int(start * SAMPLE_RATE)
    if index >= len(buffer):
        return
    end = min(len(buffer), index + len(signal))
    buffer[index:end] += signal[: end - index] * gain


def make_bed(
    duration: float,
    palette: str,
    cue_times: Iterable[float],
    output_path: Path | str,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    length = max(1, int((duration + 0.6) * SAMPLE_RATE))
    t = np.arange(length, dtype=np.float64) / SAMPLE_RATE
    bed = np.zeros(length, dtype=np.float64)

    if palette == "academic":
        root = 196.0
        pad = (
            0.028 * np.sin(2 * math.pi * root * t)
            + 0.018 * np.sin(2 * math.pi * root * 1.25 * t)
            + 0.012 * np.sin(2 * math.pi * root * 1.5 * t)
        )
        bed += pad * (0.75 + 0.25 * np.sin(2 * math.pi * 0.05 * t))
        notes = [root * 2, root * 2.25, root * 2.5, root * 3.0, root * 2.5, root * 2.25]
        step = max(0.36, duration / max(1, len(notes)))
        for index, freq in enumerate(notes):
            _add_at(bed, _tone(freq, 1.1, 0.035), index * step * 0.9)
    else:
        root = 55.0
        pulse = 0.5 + 0.5 * np.sin(2 * math.pi * 1.8 * t)
        bed += 0.024 * np.sin(2 * math.pi * root * t) * (0.4 + 0.6 * pulse)
        bed += 0.012 * np.sin(2 * math.pi * root * 2 * t) * pulse
        bed += 0.008 * np.sin(2 * math.pi * root * 4 * t) * (0.5 + 0.5 * np.sin(2 * math.pi * 0.9 * t))
        notes = [220.0, 261.63, 329.63, 392.0, 329.63, 261.63]
        step = max(0.28, duration / max(1, len(notes)))
        for index, freq in enumerate(notes):
            _add_at(bed, _tone(freq, 0.55, 0.025, detune=0.003), index * step)

    for cue in cue_times:
        whoosh_len = int(0.32 * SAMPLE_RATE)
        wt = np.arange(whoosh_len, dtype=np.float64) / SAMPLE_RATE
        sweep = np.sin(2 * math.pi * (450 + 1300 * wt / 0.32) * wt)
        noise = np.random.default_rng(7).normal(0, 0.25, whoosh_len)
        whoosh = (sweep * 0.5 + noise) * np.linspace(0.0, 1.0, whoosh_len) ** 2
        _add_at(bed, whoosh, max(0.0, cue - 0.12), 0.22)

    peak = float(np.max(np.abs(bed))) or 1.0
    bed = bed / peak * 0.55
    stereo = np.column_stack([bed, np.roll(bed, 220)]).astype(np.float32)
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return output_path


def mix_narration(
    narration_path: Path | str,
    bed_path: Path | str,
    output_path: Path | str,
    duration: float,
) -> Path:
    from ..util import run

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fade_out = max(0.0, duration - 1.2)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(narration_path),
            "-i",
            str(bed_path),
            "-filter_complex",
            (
                f"[1:a]volume=0.14,afade=t=in:st=0:d=0.8,"
                f"afade=t=out:st={fade_out:.2f}:d=1.0[bg];"
                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]"
            ),
            "-map",
            "[a]",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ],
        timeout=120,
    )
    return output_path
