"""Deterministic pre-publish checks for a rendered episode."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import ChannelSpec
from ..content.models import Script
from ..util import atomic_write_json, ffprobe_duration, ffprobe_streams, iso_now, run
from studio.audio.loudness import measure as measure_loudness, within_tolerance

TITLE_BANNED = re.compile(r"[<>]")

# A shot may push or drift, but it must not snap. Ceiling for how fast the frame may re-zoom, in
# zoom units per second, taken from the framing report (T39).
FRAMING_MAX_ZOOM_RATE = 1.6
PLACEHOLDER = re.compile(r"\?{3,}")


def _check(
    name: str,
    ok: bool,
    detail: str,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "severity": severity,
        "detail": detail,
    }


def _volume_stats(video_path: Path) -> dict[str, float | None]:
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        timeout=120,
        check=False,
    )
    output = result.stderr
    mean = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    peak = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB", output)
    return {
        "mean_db": float(mean.group(1)) if mean else None,
        "max_db": float(peak.group(1)) if peak else None,
    }


def validate_episode(
    spec: ChannelSpec,
    script: Script,
    video_path: Path | str,
    *,
    thumbnail: Path | str | None = None,
    srt: Path | str | None = None,
    report_path: Path | str | None = None,
) -> dict[str, Any]:
    video_path = Path(video_path)
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    expected_width, expected_height = spec.size

    checks.append(_check("video_exists", video_path.is_file(), str(video_path)))
    duration = 0.0
    streams: list[dict[str, Any]] = []
    if video_path.is_file():
        streams = ffprobe_streams(video_path).get("streams", [])
        duration = ffprobe_duration(video_path)
        video_stream = next(
            (item for item in streams if item.get("codec_type") == "video"), None
        )
        audio_stream = next(
            (item for item in streams if item.get("codec_type") == "audio"), None
        )
        checks.append(_check("video_stream", video_stream is not None, "H.264 video stream"))
        checks.append(_check("audio_stream", audio_stream is not None, "AAC audio stream"))
        if video_stream:
            width = int(video_stream.get("width") or 0)
            height = int(video_stream.get("height") or 0)
            checks.append(
                _check(
                    "geometry",
                    (width, height) == (expected_width, expected_height),
                    f"{width}x{height}, expected {expected_width}x{expected_height}",
                )
            )
            checks.append(
                _check(
                    "video_codec",
                    str(video_stream.get("codec_name")) == "h264",
                    str(video_stream.get("codec_name")),
                )
            )
            rate_text = str(video_stream.get("avg_frame_rate") or "0/0")
            try:
                numerator, denominator = rate_text.split("/")
                fps = float(numerator) / float(denominator or 1)
            except (ValueError, ZeroDivisionError):
                fps = 0.0
            checks.append(
                _check(
                    "frame_rate",
                    abs(fps - 30.0) <= 0.01,
                    f"{fps:.2f} fps, expected 30",
                )
            )
        if audio_stream:
            checks.append(
                _check(
                    "audio_codec",
                    str(audio_stream.get("codec_name")) == "aac",
                    str(audio_stream.get("codec_name")),
                )
            )
        minimum, maximum = (20.0, 65.0) if spec.format == "shorts" else (60.0, 900.0)
        checks.append(
            _check(
                "duration",
                minimum <= duration <= maximum,
                f"{duration:.2f}s, expected {minimum:.0f}-{maximum:.0f}s",
            )
        )
        size = video_path.stat().st_size
        checks.append(_check("file_size", size >= 100_000, f"{size} bytes"))
        volume = _volume_stats(video_path)
        mean_db = volume["mean_db"]
        max_db = volume["max_db"]
        checks.append(
            _check(
                "audio_levels",
                mean_db is not None and mean_db > -40.0 and max_db is not None and max_db > -18.0,
                f"mean={mean_db} dB, peak={max_db} dB",
            )
        )
        loudness = measure_loudness(video_path)
        ok, detail = within_tolerance(loudness)
        checks.append(_check("audio_loudness", ok, f"EBU R128: {detail}"))
        if mean_db is not None and mean_db < -32.0:
            warnings.append(
                _check(
                    "quiet_mix",
                    False,
                    f"mean level {mean_db} dB is quiet",
                    severity="warning",
                )
            )
    else:
        checks.append(_check("video_probe", False, "video missing; probe skipped"))

    # Framing (T39): the camera is told which characters must be on screen, and this is the
    # check that it got them there. The report is produced by the renderer from the same
    # projection the frames were drawn with, so a cropped subject here means a cropped subject
    # on screen. Episodes without character framing (the 16:9 renderer draws none yet) simply
    # have no report, which is recorded as information rather than passed off as a check.
    framing_path = video_path.with_name("framing.json")
    if framing_path.is_file():
        try:
            framing = json.loads(framing_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append(_check("framing", False, f"unreadable framing report: {exc}"))
            framing = None
        if framing is not None:
            cropped = {name: int(stats.get("cropped_frames", 0))
                       for name, stats in (framing.get("subjects") or {}).items()
                       if stats.get("required") and int(stats.get("cropped_frames", 0)) > 0}
            excluded = {name: int(stats.get("cropped_frames", 0))
                        for name, stats in (framing.get("subjects") or {}).items()
                        if not stats.get("required") and int(stats.get("cropped_frames", 0))}
            checks.append(_check("framing_subjects", not cropped,
                                 "every required subject stayed inside the frame"
                                 if not cropped else f"cropped: {cropped}"))
            if excluded:
                warnings.append(_check(
                    "framing_off_shot_characters", False,
                    f"characters outside the chosen shot (by design): {excluded}",
                    severity="warning"))
            zoom_rate = float(framing.get("max_zoom_rate", 0.0))
            checks.append(_check("framing_continuity", zoom_rate <= FRAMING_MAX_ZOOM_RATE,
                                 f"peak zoom change {zoom_rate:.2f}/s "
                                 f"(limit {FRAMING_MAX_ZOOM_RATE:.2f})"))
    else:
        checks.append(_check("framing_subjects", True, "no framing report for this episode",
                             severity="info"))

    title = script.title.strip()
    checks.append(_check("title_length", 0 < len(title) <= 100, f"{len(title)} chars"))
    checks.append(
        _check(
            "title_chars",
            not TITLE_BANNED.search(title) and not PLACEHOLDER.search(title),
            "no angle brackets or mojibake placeholders",
        )
    )
    description = script.description.strip()
    checks.append(
        _check(
            "description_length",
            0 < len(description) <= 5000,
            f"{len(description)} chars",
        )
    )
    tag_blob = ",".join(script.tags)
    checks.append(
        _check(
            "tags_length",
            len(tag_blob) <= 500 and all("<" not in tag and ">" not in tag for tag in script.tags),
            f"{len(tag_blob)} chars across {len(script.tags)} tags",
        )
    )
    scene_text = "\n".join(line.text for line in script.lines)
    checks.append(
        _check(
            "script_text",
            bool(scene_text.strip()) and not PLACEHOLDER.search(scene_text),
            "script text is present and free of replacement characters",
        )
    )
    checks.append(
        _check(
            "made_for_kids",
            script.channel != "natkhat-toons" or bool(spec.made_for_kids),
            f"made_for_kids={spec.made_for_kids}",
        )
    )

    if thumbnail is not None:
        thumb_path = Path(thumbnail)
        thumb_ok = thumb_path.is_file()
        dimensions = ""
        if thumb_ok:
            try:
                with Image.open(thumb_path) as image:
                    dimensions = f"{image.width}x{image.height}"
                    thumb_ok = image.width >= 640 and image.height >= 360 and abs(
                        image.width / image.height - 16 / 9
                    ) < 0.02
            except Exception as exc:  # noqa: BLE001 - corrupt image is a QC failure
                dimensions = f"unreadable: {exc}"
                thumb_ok = False
            thumb_ok = thumb_ok and thumb_path.stat().st_size <= 2 * 1024 * 1024
        checks.append(
            _check(
                "thumbnail",
                thumb_ok,
                f"{thumb_path} ({dimensions}, {thumb_path.stat().st_size if thumb_path.is_file() else 0} bytes)",
            )
        )

    if srt is not None:
        srt_path = Path(srt)
        text = srt_path.read_text(encoding="utf-8") if srt_path.is_file() else ""
        checks.append(
            _check(
                "captions",
                "-->" in text and len(text.strip()) > 20,
                f"{srt_path} ({len(text)} chars)",
            )
        )

    errors = [item for item in checks if not item["ok"] and item["severity"] == "error"]
    report = {
        "ok": not errors,
        "checked_at": iso_now(),
        "channel": spec.slug,
        "title": script.title,
        "video_path": str(video_path),
        "duration": round(duration, 3),
        "checks": checks,
        "warnings": warnings,
        "error_count": len(errors),
    }
    if report_path is not None:
        atomic_write_json(report_path, report)
    return report
