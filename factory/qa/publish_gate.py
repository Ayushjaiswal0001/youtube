"""The gate a video must pass before it may leave the building (T49 / Part 7).

`validate_episode` answers "did this render work". This module answers a different question: "may
this artifact be published". The difference matters because the two audiences are different - a
render QC report is read by an engineer, a publishing decision is made unattended at 02:00 by a
workflow.

Two rules shape it:

* **do not trust a stale report.** The media checks (container, streams, resolution, frame rate,
  duration, decode, loudness, silence) are re-measured from the file itself. A `qc.json` from an
  earlier render of the same path proves nothing about the bytes on disk now.
* **the pixel checks come from the render**, because re-running blackdetect and freezedetect costs
  minutes. Those are read from `qc.json` and `framing.json`, and a missing report is a blocker
  rather than a pass.

The result is machine-readable so a workflow can gate on it without parsing prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import ChannelSpec
from ..content.models import Script
from .validator import ffprobe_duration, ffprobe_streams

# YouTube's own limits, which a gate has to know about because the API rejects, not truncates.
MAX_TITLE = 100
MAX_DESCRIPTION = 5000
MAX_TAGS_TOTAL_CHARS = 500

TARGET_FPS = 30.0
FPS_TOLERANCE = 0.01  # pinned deliberately: 30.01 is not 30 and YouTube re-encodes anyway


@dataclass
class GateCheck:
    name: str
    ok: bool
    detail: str
    severity: str = "error"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail,
                "severity": self.severity}


@dataclass
class GateResult:
    checks: List[GateCheck] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", *, severity: str = "error") -> None:
        self.checks.append(GateCheck(name, bool(ok), str(detail), severity))

    @property
    def ok(self) -> bool:
        return all(check.ok or check.severity != "error" for check in self.checks)

    @property
    def blockers(self) -> List[str]:
        return [check.name for check in self.checks
                if not check.ok and check.severity == "error"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "blockers": self.blockers,
            "passed": sum(1 for check in self.checks if check.ok),
            "total": len(self.checks),
        }


def _rate(value: Any) -> float:
    text = str(value or "0/1")
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        try:
            return float(numerator) / float(denominator or 1)
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _srt_is_valid(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return False, "empty"
    blocks = re.split(r"\n\s*\n", text)
    previous_end = -1.0
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            return False, "malformed block"
        timing = next((line for line in lines if "-->" in line), None)
        if timing is None:
            return False, "block without timing"
        start, _, end = timing.partition("-->")
        try:
            start_s = _srt_seconds(start)
            end_s = _srt_seconds(end)
        except ValueError:
            return False, f"unparsable timing {timing!r}"
        if end_s <= start_s:
            return False, f"non-positive cue at {timing.strip()!r}"
        if start_s < previous_end - 0.01:
            return False, f"overlapping cue at {timing.strip()!r}"
        previous_end = end_s
    return True, f"{len(blocks)} cues"


def _srt_seconds(stamp: str) -> float:
    match = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)", stamp)
    if not match:
        raise ValueError(stamp)
    hours, minutes, seconds, fraction = match.groups()
    return (int(hours) * 3600 + int(minutes) * 60 + int(seconds)
            + int(fraction) / (10 ** len(fraction)))


def _measure_loudness(path: Path) -> Optional[Dict[str, float]]:
    try:
        from studio.audio.loudness import measure

        return measure(str(path))
    except Exception:  # noqa: BLE001
        return None


def _silence_seconds(path: Path, duration: float) -> float:
    """Total silence reported by ffmpeg's silencedetect."""

    import subprocess

    if duration <= 0:
        return 0.0
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-v", "info", "-nostats", "-i", str(path),
             "-af", "silencedetect=n=-45dB:d=0.6", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
    except Exception:  # noqa: BLE001
        return duration  # cannot measure: treat as fully silent, i.e. do not publish
    total = 0.0
    for match in re.finditer(r"silence_duration: ([0-9.]+)", result.stderr or ""):
        total += float(match.group(1))
    return total


def _decode_errors(path: Path) -> Optional[str]:
    import subprocess

    result = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                            capture_output=True, text=True, timeout=900)
    text = (result.stderr or "").strip()
    return text or None


def evaluate_publish_gate(
    spec: ChannelSpec,
    script: Script,
    video_path: Path | str,
    *,
    out_dir: Optional[Path | str] = None,
    thumbnail: Optional[Path | str] = None,
    srt: Optional[Path | str] = None,
    measure_decode: bool = True,
    measure_loudness: bool = True,
) -> GateResult:
    """Decide whether this artifact may be published. Never raises on a failed check."""

    video = Path(video_path)
    out = Path(out_dir) if out_dir else video.parent
    result = GateResult()

    # 1-3. container and streams
    result.add("mp4_container", video.is_file() and video.suffix.lower() == ".mp4", str(video))
    # A file that is not an MP4 makes ffprobe exit non-zero, and `ffprobe_streams` raises. The gate
    # must return a verdict, not an exception: the caller is deciding whether to publish, and a
    # traceback is not a decision.
    try:
        streams = ffprobe_streams(video).get("streams", []) if video.is_file() else []
    except Exception:  # noqa: BLE001
        streams = []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    result.add("video_stream", bool(video_streams),
               ", ".join(str(s.get("codec_name")) for s in video_streams) or "none")
    result.add("audio_stream", bool(audio_streams),
               ", ".join(str(s.get("codec_name")) for s in audio_streams) or "none")

    # 4-6. geometry, frame rate, duration. A file with no video stream reaches this point (the
    # checks above recorded it), so the geometry reads from an empty mapping rather than indexing.
    expected_w, expected_h = spec.size
    primary = video_streams[0] if video_streams else {}
    width = int(primary.get("width") or 0)
    height = int(primary.get("height") or 0)
    result.add("resolution", (width, height) == (expected_w, expected_h),
               f"{width}x{height} (expected {expected_w}x{expected_h})")

    rate = _rate(primary.get("avg_frame_rate"))
    result.add("frame_rate", abs(rate - TARGET_FPS) <= FPS_TOLERANCE,
               f"{rate:.3f} fps (expected {TARGET_FPS:.0f})")

    try:
        duration = ffprobe_duration(video) if video.is_file() else 0.0
    except Exception:  # noqa: BLE001
        duration = 0.0
    # The same bounds `validate_episode` uses; a vlog-length Short and a five-minute landscape
    # episode are both legitimate, so the bounds follow the channel's profile.
    low, high = (20.0, 65.0) if spec.format == "shorts" else (60.0, 900.0)
    result.add("duration", low <= duration <= high,
               f"{duration:.2f}s within [{low:.0f}, {high:.0f}]")

    # 7. full decode
    if measure_decode:
        errors = _decode_errors(video) if video.is_file() else "missing file"
        result.add("decode_clean", errors is None, (errors or "no errors")[:300])

    # 8. A/V synchronisation
    if video_streams and audio_streams:
        try:
            v_start = float(video_streams[0].get("start_time") or 0.0)
            a_start = float(audio_streams[0].get("start_time") or 0.0)
            v_len = float(video_streams[0].get("duration") or duration)
            a_len = float(audio_streams[0].get("duration") or duration)
            result.add("av_sync", abs(v_start - a_start) <= 0.10 and abs(v_len - a_len) <= 0.60,
                       f"start delta {abs(v_start - a_start) * 1000:.0f} ms, "
                       f"length delta {abs(v_len - a_len) * 1000:.0f} ms")
        except (TypeError, ValueError):
            result.add("av_sync", False, "unreadable stream timing")
    else:
        result.add("av_sync", False, "missing stream")

    # 9-10. loudness and silence
    loudness = _measure_loudness(video) if (measure_loudness and video.is_file()) else None
    if loudness:
        integrated = float(loudness.get("integrated_lufs") or 0.0)
        peak = float(loudness.get("true_peak_dbtp") or 0.0)
        result.add("loudness", -16.5 <= integrated <= -11.5 and peak <= -1.0,
                   f"{integrated:.2f} LUFS, {peak:.2f} dBTP")
    else:
        result.add("loudness", False, "could not be measured")

    # Silence is measured here rather than read from a report: a video whose audio track failed to
    # mux is silent everywhere, and that is exactly the failure a stale report would hide. Pauses
    # are legitimate (they are performance), so the bar is a fraction of the runtime, not zero.
    if video.is_file():
        silent = _silence_seconds(video, duration)
        budget = max(3.0, duration * 0.25)
        result.add("silence_policy", silent <= budget,
                   f"{silent:.1f}s of silence in {duration:.1f}s (budget {budget:.1f}s)")
    else:
        result.add("silence_policy", False, "missing file")

    qc = _read_json(out / "qc.json")
    if not qc:
        result.add("qc_report", False, "qc.json missing: pixel checks cannot be trusted")

    # 11. subtitles
    cue_path = Path(srt) if srt else out / "captions.srt"
    srt_ok, srt_detail = _srt_is_valid(cue_path)
    result.add("subtitles", srt_ok, srt_detail)

    # 12. production assets
    for name, path in (("timeline", out / "timeline.json"),
                       ("script", out / "script.json"),
                       ("story", out / "story.json")):
        result.add(f"asset_{name}", Path(path).is_file(), str(Path(path).name))

    # 13-14. picture defects, from the render's own analysis
    if qc:
        # Check names as `validate_episode` actually emits them; guessing "black_frames" made a
        # report that never had that key read as a blocker, which is a false alarm rather than a
        # pass - but a false alarm in a gate is still a defect.
        names = {c.get("name") for c in qc.get("checks", [])}
        for check_name in ("frozen_frames", "black_frames", "black_scene", "fade_frames"):
            if check_name not in names:
                continue
            check = next(c for c in qc.get("checks", []) if c.get("name") == check_name)
            result.add(check_name, bool(check.get("ok")), str(check.get("detail")))

    # 15-16. character framing and captions over faces
    framing = _read_json(out / "framing.json")
    if framing:
        result.add("framing", int(framing.get("cropped_required_frames") or 0) == 0,
                   f"{framing.get('cropped_required_frames')} required subjects cropped")
        collisions = framing.get("subtitle_collision_frames")
        if collisions is None:
            # The portrait Hindi report omitted this key, and `int(None or 0) == 0` turned "not measured" into a
            # pass. A missing measurement is a blocker, not a zero.
            result.add("caption_clearance", False,
                       "subtitle_collision_frames missing: caption clearance unverified")
        else:
            result.add("caption_clearance", int(collisions) == 0,
                       f"{collisions} face/band collisions")
    else:
        result.add("framing", False, "framing.json missing: composition unverified")

    # 17. scene continuity
    shot_plan = _read_json(out / "shot_plan.json")
    if shot_plan:
        violations = list(shot_plan.get("warnings") or [])
        result.add("shot_continuity", not violations,
                   f"{len(shot_plan.get('decisions') or [])} shots, {len(violations)} violations")

    # 18. thumbnail
    thumb = Path(thumbnail) if thumbnail else out / "thumbnail.jpg"
    thumb_ok = False
    thumb_detail = "missing"
    if thumb.is_file():
        try:
            from PIL import Image

            with Image.open(thumb) as image:
                thumb_ok = image.width >= 640 and image.height >= 360
                thumb_detail = f"{image.width}x{image.height} {image.format}"
        except Exception as exc:  # noqa: BLE001
            thumb_detail = f"unreadable: {exc}"
    result.add("thumbnail", thumb_ok, thumb_detail)

    # 19. channel metadata, against YouTube's own limits
    result.add("metadata_title", 1 <= len(script.title) <= MAX_TITLE,
               f"{len(script.title)} chars")
    result.add("metadata_description", len(script.description) <= MAX_DESCRIPTION,
               f"{len(script.description)} chars")
    result.add("metadata_tags", sum(len(str(tag)) + 1 for tag in script.tags)
               <= MAX_TAGS_TOTAL_CHARS, f"{len(script.tags)} tags")
    result.add("metadata_language", bool(spec.language), spec.language)
    result.add("metadata_family_safe", (not spec.made_for_kids)
               or str(script.title).strip() != "", "madeForKids channels need a clean title")

    # 20. creative quality - only for a video rendered with a scene plan
    #
    # A channel that has not adopted the visual engine has no scenes.json and is unaffected: this is an
    # additional requirement, not a changed one. But when the render *does* claim a scene plan, the
    # absence of a creative verdict is a blocker, because that is exactly the state in which a video
    # ships as a wall of type with nothing in the pipeline complaining.
    scenes = _read_json(out / "scenes.json")
    if scenes is not None:
        creative = _read_json(out / "creative.json")
        if creative is None:
            result.add("creative_quality", False,
                       "scenes.json present but creative.json missing: creative quality unverified")
        else:
            metrics = creative.get("metrics") or {}
            detail = (f"{metrics.get('scenes')} scenes, "
                      f"{metrics.get('distinct_assets')} distinct visuals, "
                      f"compositions={','.join(metrics.get('compositions') or []) or 'none'}")
            failures = creative.get("failures") or []
            result.add("creative_quality", bool(creative.get("ok")) and not failures,
                       detail + (f"; failed: {failures}" if failures else ""))

    # 21. manifest
    from ..manifesting import verify as verify_manifest

    problems = verify_manifest(out)
    manifest = _read_json(out / "manifest.json") or {}
    result.add("manifest", not problems,
               f"{len(manifest.get('artifacts') or [])} artifacts"
               + (f", {len(problems)} problem(s): {problems}" if problems else ""))

    return result


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
