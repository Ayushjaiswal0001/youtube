"""Tiny procedural music/SFX bed generator (no external assets or licenses)."""

from __future__ import annotations

import logging
import math
import wave
from pathlib import Path
from typing import Iterable

import numpy as np

LOGGER = logging.getLogger(__name__)

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


LOUDNESS_TARGET = {"I": -14.0, "TP": -1.5, "LRA": 11.0}


def measure_loudness(path: Path | str) -> dict[str, float]:
    """EBU R128 integrated loudness, true peak and loudness range of a file."""

    from ..util import run

    result = run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
            "-af", f"loudnorm=I={LOUDNESS_TARGET['I']}:TP={LOUDNESS_TARGET['TP']}:LRA={LOUDNESS_TARGET['LRA']}:print_format=json",
            "-f", "null", "-",
        ],
        timeout=300,
        check=False,
    )
    text = result.stderr
    block = text[text.rfind("{") : text.rfind("}") + 1] if "{" in text else ""
    data: dict[str, float] = {}
    if block:
        import json as _json

        try:
            raw = _json.loads(block)
            data = {
                "integrated_lufs": float(raw.get("input_i", "nan")),
                "true_peak_dbtp": float(raw.get("input_tp", "nan")),
                "lra_lu": float(raw.get("input_lra", "nan")),
                "threshold_lufs": float(raw.get("input_thresh", "nan")),
            }
        except (ValueError, TypeError):
            data = {}
    return data


def mix_narration(
    narration_path: Path | str,
    bed_path: Path | str,
    output_path: Path | str,
    duration: float,
    *,
    normalize: bool = True,
    bed_gain: float = 0.22,
) -> Path:
    """Mix narration over the bed with ducking, then normalise to -14 LUFS.

    The music bed is side-chain compressed by the narration instead of sitting at a
    fixed low volume, so words stay clear without the bed disappearing. Loudness is
    applied as a *linear* gain from a measured pass, which preserves the exact duration
    and therefore A/V sync; the result is trimmed/padded to ``duration`` as a guard.
    """

    from ..util import run

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_path.with_name(f"{output_path.stem}_raw.wav")

    filter_complex = (
        "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[nar][key];"
        f"[1:a]volume={bed_gain},afade=t=in:st=0:d=0.9,"
        f"afade=t=out:st={max(0.0, duration - 1.2):.2f}:d=1.0[bed];"
        "[bed][key]sidechaincompress=threshold=0.045:ratio=9:attack=6:release=280:makeup=1[duck];"
        "[nar][duck]amix=inputs=2:duration=first:dropout_transition=2,"
        "alimiter=limit=0.97:level=disabled[a]"
    )
    run(
        [
            "ffmpeg", "-y", "-i", str(narration_path), "-i", str(bed_path),
            "-filter_complex", filter_complex,
            "-map", "[a]", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le",
            str(raw_path),
        ],
        timeout=300,
    )

    chain = f"atrim=0:{duration:.3f},apad,atrim=0:{duration:.3f}"
    if normalize:
        measured = measure_loudness(raw_path)
        if measured and measured.get("integrated_lufs") not in (None, float("nan")):
            chain += (
                f",loudnorm=I={LOUDNESS_TARGET['I']}:TP={LOUDNESS_TARGET['TP']}:LRA={LOUDNESS_TARGET['LRA']}"
                f":measured_I={measured['integrated_lufs']}:measured_TP={measured['true_peak_dbtp']}"
                f":measured_LRA={measured['lra_lu']}:measured_thresh={measured['threshold_lufs']}"
                ":linear=true:print_format=summary"
            )
    # A final brick-wall limiter after normalisation. `loudnorm` in linear mode targets -1.0 dBTP and overshoots
    # it: academic measured -0.7 dBTP, then -1.41 with the limiter at 0.82. The long-form academic episode later
    # came out at -0.96 dBTP with the same settings, because `alimiter` limits *sample* peak and the AAC encoder
    # adds inter-sample overshoot on the way out - so a 0.82 limit is about -1.7 dBFS of sample peak and roughly
    # -1.0 dBTP after encoding, which straddles the gate. 0.74 gives about 2.6 dB of sample headroom and keeps
    # the encoded true peak below -1.0 dBTP. The gate is unchanged: this makes the audio quieter at the peak,
    # not the check weaker, and the integrated loudness target (-14 LUFS) is untouched.
    # The limiter constant is a starting point, not a guarantee. `alimiter` caps *sample* peak and the
    # AAC encoder adds inter-sample overshoot on the way out, so the encoded true peak depends on the
    # material: `nexus-small-models` encoded to -2.33 dBTP at 0.74 while `nexus-robot-video` encoded to
    # -0.46 dBTP, which is above the -1.0 dBTP gate and blocked the episode. Measuring the file that was
    # actually written and tightening only when the gate would fail closes that gap; the gate itself is
    # unchanged, and the -14 LUFS integrated target is applied before the limiter so it is untouched.
    limit = 0.74
    for attempt in range(3):
        run(
            [
                "ffmpeg", "-y", "-i", str(raw_path),
                "-af", f"{chain},alimiter=limit={limit:.4f}:attack=5:release=50:level=disabled",
                "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(output_path),
            ],
            timeout=300,
        )
        # A failed measurement returns None; treat it as "nothing to compare against" rather than
        # crashing the mix, which would fail an episode for a reason the episode does not have.
        encoded = measure_loudness(output_path) or {}
        peak = encoded.get("true_peak_dbtp")
        if peak is None or peak <= -1.0:
            break
        # Tighten by the overshoot plus 0.3 dB of margin, and never below -6 dBFS.
        limit = max(0.50, limit * 10 ** (-(peak + 1.0 + 0.3) / 20))
        LOGGER.warning("mix_narration: encoded true peak %.2f dBTP is above -1.0; re-encoding at "
                       "limiter %.3f (attempt %d)", peak, limit, attempt + 1)
    raw_path.unlink(missing_ok=True)
    return output_path
