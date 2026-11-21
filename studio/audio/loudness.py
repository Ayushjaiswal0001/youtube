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


# ffmpeg prints the loudnorm summary as one flat JSON object inside its stderr. Slicing from
# the last "{" to the last "}" assumed that object was the final thing in the output; any
# trailing brace in a warning made the slice unparseable and the measurement vanished without
# a word. Match candidate objects and take the last one that actually decodes.
_JSON_OBJECT = re.compile(r"\{[^{}]*\}")


def _decode_summary(stderr_text: str) -> dict[str, object] | None:
    for candidate in reversed(_JSON_OBJECT.findall(stderr_text or "")):
        try:
            raw = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(raw, dict) and "input_i" in raw:
            return raw
    return None


def measure_with_diagnostics(path: Path | str) -> tuple[dict[str, float], str]:
    """Measure a file, and say *why* when the measurement could not be read.

    The second value is an empty string on success. It exists because a silent empty result
    once made a CI failure look like a broken audio path when the real cause was the input
    path being unusable.
    """

    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
            "-af", (f"loudnorm=I={LOUDNESS_TARGET['I']}:TP={LOUDNESS_TARGET['TP']}"
                    f":LRA={LOUDNESS_TARGET['LRA']}:print_format=json"),
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    raw = _decode_summary(result.stderr or "")
    if raw is None:
        lines = [line for line in (result.stderr or "").splitlines() if line.strip()]
        detail = lines[-1].strip() if lines else "ffmpeg produced no output"
        return {}, detail[:300]
    data: dict[str, float] = {}
    for key, name in (("integrated_lufs", "input_i"), ("true_peak_dbtp", "input_tp"),
                      ("lra_lu", "input_lra"), ("threshold_lufs", "input_thresh")):
        try:
            data[key] = float(raw[name])
        except (KeyError, TypeError, ValueError):
            continue
    return data, ""


def measure(path: Path | str) -> dict[str, float]:
    """Integrated loudness, true peak and loudness range from an EBU R128 pass."""

    return measure_with_diagnostics(path)[0]


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
    before, before_error = measure_with_diagnostics(source)
    if not before:
        return {"before": {}, "after": {}, "applied": False,
                "error": f"loudness could not be measured: {before_error}"}
    report: dict[str, object] = {"before": before, "applied": False}

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
