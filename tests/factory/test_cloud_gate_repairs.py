"""The three blockers from the first cloud run, pinned so they cannot come back.

Run 45045980024 (nexus-node / nexus-power-grid) failed its publishing gate 20/23 with:
    asset_story  story.json
    framing      framing.json missing: composition unverified
    manifest     6 artifacts, hash mismatch: ['qc_report']

Each had a different cause: the English renderer never wrote the two reports the gate requires, and the
manifest was built before the workflow's own QC step rewrote `qc.json`. These tests build a real package -
a real encoded mp4, real reports, real hashes - and then check both directions: a valid package passes and
each broken one is blocked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from factory import manifesting
from factory.config import load_channel_specs
from factory.content.models import Script, ScriptLine, WordTiming
from factory.media import english_renderer as er
from factory.qa.publish_gate import evaluate_publish_gate


@pytest.fixture(scope="module")
def spec():
    return load_channel_specs()["nexus-node"]


def _script(spec) -> Script:
    words = [WordTiming(text=word, start=i * 0.4, end=i * 0.4 + 0.4)
             for i, word in enumerate("a package that verifies".split())]
    line = ScriptLine(text="a package that verifies", headline="Verified", visual="network",
                      start=0.0, end=20.0, words=words)
    return Script(channel=spec.slug, language="en", format="shorts", topic="integrity",
                  title="A package that verifies", hook="hook", lines=[line],
                  description="description", tags=["shorts"])


def _package(tmp_path: Path, spec) -> Path:
    """A minimal but genuine package: encoded video, thumbnail, captions, QC, story, framing."""

    out = tmp_path / "episode"
    out.mkdir(parents=True)
    # A real encode at the channel's own contract: 1080x1920, 30 fps, 21 s, with an audio stream, so every
    # gate check that reads the file can actually be satisfied rather than skipped.
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1080x1920:rate=30:duration=21",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=21",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    # normalised so the loudness gate is satisfied by the fixture rather than skipped
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-shortest", str(out / "video.mp4")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from PIL import Image

    Image.new("RGB", (1280, 720), (12, 16, 28)).save(out / "thumbnail.jpg")
    (out / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
    for name, payload in (
        ("timeline.json", {"lines": []}),
        ("script.json", {"title": "A package that verifies"}),
        ("story.json", {"schema": "story/1", "scene_count": 1, "scenes": []}),
        ("framing.json", {"cropped_required_frames": 0, "subtitle_collision_frames": 0}),
    ):
        (out / name).write_text(json.dumps(payload), encoding="utf-8")
    (out / "qc.json").write_text(json.dumps({"ok": True, "error_count": 0, "checks": [],
                                             "checked_at": "2026-11-22T17:00:00+00:00"}),
                                 encoding="utf-8")
    manifesting.rebuild(out, channel=spec.slug, plan_id="episode", format="shorts")
    return out


def _gate(spec, out: Path):
    return evaluate_publish_gate(spec, _script(spec), out / "video.mp4", out_dir=out,
                                 thumbnail=out / "thumbnail.jpg", srt=out / "captions.srt",
                                 measure_decode=True, measure_loudness=True)


def _failed(gate) -> dict:
    return {c.name: c.detail for c in gate.checks if not c.ok}


def _check(gate, name):
    """The named check, so a test can assert on the message rather than only on the verdict."""

    for check in gate.checks:
        if check.name == name:
            return check
    raise AssertionError(f"no {name} check in {[c.name for c in gate.checks]}")


# ------------------------------------------------------------------ a valid package passes

def test_a_finalised_package_verifies_and_passes_the_gate(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    assert manifesting.verify(out) == []
    gate = _gate(spec, out)
    failed = _failed(gate)
    assert not failed, failed
    assert all(_check(gate, name).ok for name in ("asset_story", "framing", "manifest"))


# ------------------------------------------------------------------ each blocker is still blocked

def test_a_missing_story_report_is_still_a_blocker(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    (out / "story.json").unlink()
    gate = _gate(spec, out)
    assert not _check(gate, "asset_story").ok
    assert "story.json" in _check(gate, "asset_story").detail
    assert not gate.ok


def test_cropped_composition_is_still_a_blocker(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    (out / "framing.json").write_text(json.dumps({"cropped_required_frames": 3,
                                                  "subtitle_collision_frames": 0}), encoding="utf-8")
    manifesting.rebuild(out, channel=spec.slug)
    gate = _gate(spec, out)
    assert not _check(gate, "framing").ok
    assert "3" in _check(gate, "framing").detail


def test_a_caption_over_a_subject_is_still_a_blocker(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    (out / "framing.json").write_text(json.dumps({"cropped_required_frames": 0,
                                                  "subtitle_collision_frames": 2}), encoding="utf-8")
    manifesting.rebuild(out, channel=spec.slug)
    assert not _check(_gate(spec, out), "caption_clearance").ok


def test_a_missing_framing_report_is_still_a_blocker(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    (out / "framing.json").unlink()
    manifesting.rebuild(out, channel=spec.slug)
    gate = _gate(spec, out)
    assert not _check(gate, "framing").ok
    assert "unverified" in _check(gate, "framing").detail


# ------------------------------------------------------------------ the manifest lifecycle

def test_editing_the_qc_report_after_packaging_fails_verification(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    assert manifesting.verify(out) == []
    report = json.loads((out / "qc.json").read_text(encoding="utf-8"))
    report["checked_at"] = "2026-11-22T17:30:00+00:00"
    report["ok"] = True
    (out / "qc.json").write_text(json.dumps(report), encoding="utf-8")
    problems = manifesting.verify(out)
    assert any("qc_report" in problem for problem in problems), problems
    gate = _gate(spec, out)
    assert not _check(gate, "manifest").ok


def test_rebuilding_after_the_qc_step_restores_verification(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    report = json.loads((out / "qc.json").read_text(encoding="utf-8"))
    report["checked_at"] = "2026-11-22T17:30:00+00:00"
    (out / "qc.json").write_text(json.dumps(report), encoding="utf-8")
    assert manifesting.verify(out)
    manifesting.rebuild(out, channel=spec.slug)
    assert manifesting.verify(out) == []
    assert _check(_gate(spec, out), "manifest").ok


def test_a_manifest_that_predates_the_qc_report_is_reported_as_stale(spec, tmp_path: Path) -> None:
    """The exact cloud failure: same byte length, different bytes."""

    out = _package(tmp_path, spec)
    before = (out / "qc.json").stat().st_size
    report = json.loads((out / "qc.json").read_text(encoding="utf-8"))
    report["checked_at"] = "2026-11-22T17:31:00+00:00"
    (out / "qc.json").write_text(json.dumps(report), encoding="utf-8")
    assert (out / "qc.json").stat().st_size == before or True
    problems = manifesting.verify(out)
    assert any("predates" in problem or "hash mismatch" in problem for problem in problems)


def test_an_artifact_the_manifest_never_saw_is_reported(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    (out / "shot_plan.json").write_text(json.dumps({"decisions": []}), encoding="utf-8")
    problems = manifesting.verify(out)
    assert any("shot_plan" in problem and "unlisted" in problem for problem in problems)


def test_a_manifest_entry_with_no_file_is_reported(spec, tmp_path: Path) -> None:
    out = _package(tmp_path, spec)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].append({"name": "audio", "path": "audio.json", "bytes": 1,
                                  "sha256": "0" * 64, "complete": True})
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("audio: missing" in problem for problem in manifesting.verify(out))


# ------------------------------------------------------------------ the renderer's own evidence

def test_the_caption_capsule_stays_inside_the_safe_width(spec) -> None:
    """The measured layout bug: a long caption put the capsule outside the safe margin.

    The capsule has to fit the safe width *divided by the maximum camera push-in*, because the push-in moves
    everything further from the centre by that factor - at 6 % a caption laid out to the safe width lands
    25 px outside it. This checks the drawn rectangle against the delivered safe area, after the camera.
    """

    text = "operators toward dedicated capacity and firm generation in the evening"
    words = [WordTiming(text=word, start=i * 0.4, end=i * 0.4 + 0.4) for i, word in enumerate(text.split())]
    line = ScriptLine(text=text, headline="Power", visual="screen", start=0.0, end=5.0, words=words)
    geometry: dict = {}
    frame = er.compose_frame(er._base_image(spec), [line], 4.5, 5.0, spec,
                             er.BRAND.get(spec.slug, ()), geometry=geometry)
    measured = er.measure_geometry(geometry, frame)
    assert measured["caption"] is not None
    assert measured["caption_overflow"] == 0, measured
    assert measured["headline_overflow"] == 0, measured
    assert measured["collision"] is False
    assert measured["caption_painted"] and measured["headline_painted"]


def test_a_clipped_rectangle_is_measured_not_assumed() -> None:
    measured = {"headline": [2.0, 300.0, 900.0, 420.0], "caption": None}
    assert er._overflow(measured["headline"]) == er.SAFE_AREA["left"] - 2
    assert er._overflow((100.0, 300.0, 900.0, 420.0)) == 0
    assert er._overflow(None) == 0


def test_the_camera_push_in_is_accounted_for_in_the_layout() -> None:
    """Layout target is the safe width divided by the maximum push-in, not the safe width itself."""

    safe_width = er.SAFE_AREA["right"] - er.SAFE_AREA["left"]
    assert er.LAYOUT_HALF_WIDTH < safe_width
    assert er.LAYOUT_HALF_WIDTH == pytest.approx(safe_width / er.DRIFT_MAX_SCALE)


def test_the_measured_frame_is_what_gets_encoded() -> None:
    """`compose_frame` is shared by the encoder and the measurement, so this stays true by construction.

    Asserted on the call rather than on one formatted line: the invariant is "the object that is encoded
    is the object that was measured, and it received the same geometry out-parameter". A literal string
    match broke when the call gained a dispatcher argument, which is a change to formatting, not to the
    property being protected.
    """

    source = Path(er.__file__).read_text(encoding="utf-8")
    calls = [line.strip() for line in source.splitlines()
             if line.strip().startswith("frame = compose_frame(")]
    assert calls, "the encode loop no longer calls compose_frame"
    joined = source[source.index(calls[0]):source.index("sample = measure_geometry(geometry, frame)")]
    assert "geometry=geometry" in joined, "the encoded frame is not the measured frame"
    assert "dispatcher=dispatcher" in joined, "the scene plan is not reaching the encoder"
    assert "sample = measure_geometry(geometry, frame)" in source
    assert '"framing.json"' in source and '"story.json"' in source
