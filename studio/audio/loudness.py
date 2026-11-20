"""EBU R128 loudness measurement and normalisation for the episode audio path.

The long-form renderer normalised its mix, but the animated Shorts path went out at whatever
level the voice/sfx/music mix produced — measured at **-24.3 LUFS**, ten LU below YouTube's
reference. Two-pass *linear* normalisation is used because a linear gain cannot change the
duration, so A/V sync (and therefore lip-sync) is unaffected.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Mapping

LOUDNESS_TARGET = {"I": -14.0, "TP": -1.5, "LRA": 11.0}

# What a finished episode is allowed to measure. The window is deliberately wider than the
# target so a different but sane mix is not rejected, and narrow enough that the old -24 LUFS
# output would fail.
ACCEPTED_RANGE = (-16.5, -11.5)
MAX_TRUE_PEAK = -1.0


def measure(path: Path | str) -> dict[str, float]:
    """Integrated loudness, true peak and loudness range from an EBU R128 pass."""

    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
            "-af", (f"loudnorm=I={LOUDNESS_TARGET['I']}:TP={LOUDNESS_TARGET['TP']}"
                    f":LRA={LOUDNESS_TARGET['LRA']}:print_format=json"),
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    text = result.stderr or ""
    block = text[text.rfind("{"): text.rfind("}") + 1] if "{" in text else ""
    data: dict[str, float] = {}
    if not block:
        return data
    try:
        raw = json.loads(block)
    except ValueError:
        return data
    for key, name in (("integrated_lufs", "input_i"), ("true_peak_dbtp", "input_tp"),
                      ("lra_lu", "input_lra"), ("threshold_lufs", "input_thresh")):
        try:
            data[key] = float(raw[name])
        except (KeyError, TypeError, ValueError):
            continue
    return data


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def normalize_file(path: Path | str, *, target: Mapping[str, float] | None = None,
                   output: Path | str | None = None,
                   keep_duration: float | None = None) -> dict[str, object]:
    """Normalise a mixed audio file in place (or to ``output``) with a linear gain.

    Returns the measurement before and after, plus whether the pass was applied. A file that
    cannot be measured is left untouched and reported, rather than being replaced by silence.
    """

    source = Path(path)
    destination = Path(output) if output is not None else source
    peaks = target or LOUDNESS_TARGET
    before = measure(source)
    report: dict[str, object] = {"before": before, "applied": False}
    if not before or "integrated_lufs" not in before:
        report["error"] = "loudness could not be measured"
        return report

    chain = ""
    if keep_duration is not None:
        chain += f"atrim=0:{keep_duration:.3f},apad,atrim=0:{keep_duration:.3f},"
    chain += (
        f"loudnorm=I={peaks['I']}:TP={peaks['TP']}:LRA={peaks['LRA']}"
        f":measured_I={before['integrated_lufs']}:measured_TP={before['true_peak_dbtp']}"
        f":measured_LRA={before['lra_lu']}:measured_thresh={before.get('threshold_lufs', -70.0)}"
        ":linear=true:print_format=summary"
    )
    temporary = destination.with_name(f"{destination.stem}_norm{destination.suffix}")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-af", chain, "-ac", "2", "-ar", "44100",
         "-c:a", "pcm_s16le", str(temporary)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        temporary.unlink(missing_ok=True)
        report["error"] = (result.stderr or "")[-500:]
        return report

    before_duration = _duration(source)
    after_duration = _duration(temporary)
    temporary.replace(destination)
    report["applied"] = True
    report["after"] = measure(destination)
    report["duration_before"] = before_duration
    report["duration_after"] = after_duration
    report["duration_delta"] = round(after_duration - before_duration, 4)
    return report


def within_tolerance(measured: Mapping[str, float],
                     accepted: tuple[float, float] = ACCEPTED_RANGE,
                     max_true_peak: float = MAX_TRUE_PEAK) -> tuple[bool, str]:
    """Whether a measurement is acceptable for publishing."""

    if not measured or "integrated_lufs" not in measured:
        return False, "loudness could not be measured"
    integrated = measured["integrated_lufs"]
    true_peak = measured.get("true_peak_dbtp")
    low, high = accepted
    if not low <= integrated <= high:
        return False, f"{integrated:.1f} LUFS outside {low}..{high}"
    if true_peak is not None and true_peak > max_true_peak:
        return False, f"true peak {true_peak:.1f} dBTP above {max_true_peak}"
    return True, f"{integrated:.1f} LUFS, {true_peak if true_peak is not None else float('nan'):.1f} dBTP"
