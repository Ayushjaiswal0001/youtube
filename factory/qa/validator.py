"""Deterministic pre-publish checks for a rendered episode."""

from __future__ import annotations

import json
import re
import subprocess
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


def _duration_seconds(path: Path) -> float:
    """Container duration, so a freeze that outlives the last frame can be sized."""

    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
               "default=nw=1:nk=1", str(path)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _freeze_events(path: Path) -> list[tuple[float, float]]:
    """Freeze segments detected in the video, as ``(start, duration)``.

    A frozen frame is what a broken animation loop looks like: the renderer keeps writing frames but
    the picture stops. `freezedetect` is the cheap honest measurement - it decodes, which catches
    streams that ffprobe alone would call healthy.

    A freeze that runs to the end of the file emits ``freeze_start`` and never emits ``freeze_end``.
    Ignoring that case - which is what this function did until it was found by its own regression test -
    hid the most likely stall of all: a renderer that stops animating on the last line and keeps writing
    the same frame until the video ends.
    """

    command = ["ffmpeg", "-v", "info", "-i", str(path), "-vf",
               "freezedetect=n=-50dB:d=1.5", "-map", "0:v", "-f", "null", "-"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            check=False)
    events: list[tuple[float, float]] = []
    start = None
    for line in result.stderr.splitlines():
        if "freeze_start:" in line:
            try:
                start = float(line.split("freeze_start:")[1].strip())
            except ValueError:
                start = None
        elif "freeze_end:" in line and start is not None:
            try:
                end = float(line.split("freeze_end:")[1].strip())
            except ValueError:
                continue
            events.append((start, end - start))
            start = None
    if start is not None:
        end = _duration_seconds(path)
        if end > start:
            events.append((start, end - start))
    return events


def _frozen_seconds(path: Path) -> float:
    events = _freeze_events(path)
    return max((length for _, length in events), default=0.0)


def _frozen_at(path: Path) -> str:
    events = _freeze_events(path)
    if not events:
        return "unknown"
    start, length = max(events, key=lambda item: item[1])
    return f"{start:.1f}s ({length:.1f}s)"


def _check_continuity(video_path: Path) -> dict[str, Any] | None:
    """Fail the episode when the story contradicts itself between scenes.

    The report is produced by the renderer from the same normalised plan it animated, so an error
    here is a real discontinuity in what was drawn - an object that changed hands with no hand-off,
    a prop that vanished from a hand, a character who flipped sides without turning.
    """

    path = video_path.with_name("continuity.json")
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    counts = report.get("counts") or {}
    errors = [issue for issue in (report.get("issues") or []) if issue.get("severity") == "error"]
    detail = (f"{counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), "
              f"{counts.get('info', 0)} info across {len(report.get('states') or [])} scenes")
    if errors:
        first = errors[0]
        return _check("continuity", False,
                      f"{detail}; first: scene {first.get('scene')} {first.get('code')}: "
                      f"{first.get('message')}", severity="error")
    return _check("continuity", True, detail)


def _check_pickup(video_path: Path) -> dict[str, Any] | None:
    """Gate a world-space pickup on measured contact, not on the schedule.

    The pickup report is written by the renderer from the wrist it actually drew. A run of frames
    where the state machine says CONTACT while the hand is outside the object's box is the exact
    failure the interaction system exists to prevent, so it is an error rather than a warning.
    """

    path = video_path.with_name("framing.json")
    if not path.is_file():
        return None
    try:
        framing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    pickups = [scene.get("pickup") for scene in (framing.get("scenes") or [])
               if isinstance(scene, dict) and scene.get("pickup")]
    if not pickups:
        return None
    lying = sum(int(item.get("report", {}).get("claimed_contact_without_touch") or 0)
                for item in pickups)
    errors = [item.get("report", {}).get("min_contact_error") for item in pickups]
    measured = [value for value in errors if isinstance(value, (int, float))]
    unreachable = [item for item in pickups if not item.get("report", {}).get("reachable", True)]
    # A hand-off that was authored but never happened is the same class of defect as a pickup whose
    # hand never arrived: the object must appear in the next shot in someone's hand, and if it was left
    # in the giver's, the story is now wrong.
    broken_handoffs = [item for item in pickups
                       if item.get("report", {}).get("handoff_to")
                       and (item.get("report", {}).get("transferred") is not True
                            or item.get("report", {}).get("handoff_reachable") is False)]
    detail = (f"{len(pickups)} pickup(s), closest hand-to-object "
              f"{min(measured):.1f} px" if measured else f"{len(pickups)} pickup(s)")
    if lying:
        return _check("pickup_contact", False,
                      f"{detail}; contact claimed without touch on {lying} frames",
                      severity="error")
    if unreachable:
        return _check("pickup_contact", False,
                      f"{detail}; {len(unreachable)} declared out of reach", severity="error")
    if broken_handoffs:
        worst = broken_handoffs[0].get("report", {})
        return _check("pickup_contact", False,
                      f"{detail}; {len(broken_handoffs)} hand-off(s) did not complete "
                      f"(to {worst.get('handoff_to')}, transferred={worst.get('transferred')})",
                      severity="error")
    if any(item.get("report", {}).get("handoff_to") for item in pickups):
        detail += f"; hand-off(s) transferred: {sum(1 for i in pickups if i.get('report', {}).get('transferred'))}"
    return _check("pickup_contact", True, detail)


def _check_shot_continuity(video_path: Path) -> dict[str, Any]:
    """Read the directed shot plan, if the renderer wrote one, and gate its violations.

    An episode whose shot plan frames the listener while the speaker is talking has a mouth that
    does not move with the audio; that is a real defect, not a matter of taste, so it is an error.
    """

    plan_path = video_path.parent / "shot_plan.json"
    if not plan_path.is_file():
        return _check("shot_continuity", True, "no directed shot plan (authored cameras)")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _check("shot_continuity", False, f"unreadable shot_plan.json: {exc}")
    violations = list(plan.get("warnings") or [])
    decided = len(plan.get("decisions") or [])
    return _check("shot_continuity", not violations,
                  f"{decided} directed shots, {len(violations)} violations"
                  + (f": {violations[0]}" if violations else ""))


def validate_episode(
    spec: ChannelSpec,
    script: Script,
    video_path: Path | str,
    *,
    thumbnail: Path | str | None = None,
    srt: Path | str | None = None,
    report_path: Path | str | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    video_path = Path(video_path)
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    expected_width, expected_height = spec.size

    checks.append(_check("video_exists", video_path.is_file(), str(video_path)))
    checks.append(_check_shot_continuity(video_path))
    pickup_check = _check_pickup(video_path)
    if pickup_check is not None:
        checks.append(pickup_check)
    continuity_check = _check_continuity(video_path)
    if continuity_check is not None:
        checks.append(continuity_check)
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
        # A demo render (a deliberate fragment of an episode) relaxes the duration bound and says
        # so, rather than passing quietly and implying a complete episode was validated.
        checks.append(
            _check(
                "duration",
                duration <= maximum if demo else minimum <= duration <= maximum,
                f"{duration:.2f}s, expected {minimum:.0f}-{maximum:.0f}s"
                + (" (demo: lower bound waived)" if demo and duration <= maximum else ""),
                severity="warning" if demo and duration < minimum else "error",
            )
        )
        # Audio/video sync (T41): the streams have to start together and end together. A scene
        # whose audio outlives its video shifts every following scene, which is how the concat
        # step first delivered 29.93 fps.
        video_start = float(video_stream.get("start_time") or 0.0) if video_stream else 0.0
        audio_start = float(audio_stream.get("start_time") or 0.0) if audio_stream else 0.0
        video_duration = float(video_stream.get("duration") or duration) if video_stream else 0.0
        audio_duration = float(audio_stream.get("duration") or duration) if audio_stream else 0.0
        start_delta = abs(video_start - audio_start)
        length_delta = abs(video_duration - audio_duration)
        checks.append(_check(
            "av_sync",
            start_delta <= 0.10 and length_delta <= 0.60,
            f"start delta {start_delta:.3f}s, length delta {length_delta:.3f}s",
        ))

        frozen = _frozen_seconds(video_path)
        checks.append(_check(
            "frozen_frames",
            not frozen,
            "no freeze longer than 1.5s" if not frozen
            else f"frozen for {frozen:.1f}s at {_frozen_at(video_path)}",
        ))

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
            measured = framing.get("subtitle_collision_frames")
            collisions = int(measured or 0)
            checks.append(_check(
                "subtitle_collision",
                measured is not None and collisions == 0,
                "not measured: caption clearance unverified" if measured is None
                else ("no character behind the caption band" if collisions == 0
                      else f"a character overlaps the caption band on {collisions} frames"),
                severity="error",
            ))

            occlusion = (framing.get("occlusion") or {}).get("prop") or {}
            hidden = int(occlusion.get("frames", 0))
            if occlusion:
                checks.append(_check(
                    "prop_visibility", hidden == 0,
                    "the prop cleared the caption band on every frame"
                    if hidden == 0 else
                    f"prop hidden behind the caption band on {hidden} frames "
                    f"(frame lifted on {int(occlusion.get('lifted_frames', 0))})",
                    severity="error" if hidden else "error"))
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
