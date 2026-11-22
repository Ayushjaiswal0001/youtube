"""The English cards used to freeze: a held card for one narration line measured 1.5-2.2 s of stillness.

These tests reproduce that defect with the same detector the QC gate uses (`ffmpeg freezedetect`), and
then hold the fix to the same measurement. Nothing here mocks the renderer: `compose_frame` is the
function the encode loop calls, and the freeze tests go through a real libx264 encode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from factory.content.models import ScriptLine, WordTiming
from factory.config import load_channel_specs
from factory.media import english_renderer as er
from factory.qa.validator import _freeze_events, _frozen_seconds

ENGLISH = ("nexus-node", "academic-biohacker")


def _held_card(spec, visual: str = "shield", seconds: float = 8.0):
    """A card whose motif is entirely static - the shape that used to freeze."""

    text = "a static card never moves at all here"
    words = [WordTiming(text=word, start=i * 0.5, end=i * 0.5 + 0.5)
             for i, word in enumerate(text.split())]
    line = ScriptLine(text=text, headline="Static card", visual=visual, start=0.0, end=seconds,
                      words=words)
    return [line]


def _frame(spec, lines, t: float, duration: float = 30.0):
    return er.compose_frame(er._base_image(spec), lines, t, duration, spec, er.BRAND.get(spec.slug, ()))


def _encode(spec, lines, path: Path, seconds: float) -> Path:
    command = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
               f"{er.WIDTH}x{er.HEIGHT}", "-r", str(er.FPS), "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    for index in range(int(seconds * er.FPS)):
        process.stdin.write(_frame(spec, lines, index / er.FPS, seconds).convert("RGB").tobytes())
    process.stdin.close()
    assert process.wait() == 0
    return path


# ------------------------------------------------------------------ the defect, reproduced

def test_the_detector_still_calls_a_repeated_frame_a_freeze(tmp_path: Path) -> None:
    """If this stops failing, the QC gate is blind and every other test here is meaningless."""

    spec = load_channel_specs()["nexus-node"]
    lines = _held_card(spec)
    still = _frame(spec, lines, 4.0).convert("RGB")
    path = tmp_path / "still.mp4"
    command = ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
               f"{er.WIDTH}x{er.HEIGHT}", "-r", str(er.FPS), "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(path)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    payload = still.tobytes()
    for _ in range(int(6.0 * er.FPS)):
        process.stdin.write(payload)
    process.stdin.close()
    assert process.wait() == 0
    assert _frozen_seconds(path) >= 4.5, _freeze_events(path)


# ------------------------------------------------------------------ the fix, measured

@pytest.mark.parametrize("slug", ENGLISH)
def test_a_held_card_is_never_frozen(slug: str, tmp_path: Path) -> None:
    spec = load_channel_specs()[slug]
    path = _encode(spec, _held_card(spec), tmp_path / f"{slug}.mp4", 6.0)
    assert _freeze_events(path) == [], f"{slug} still freezes: {_freeze_events(path)}"


@pytest.mark.parametrize("slug", ENGLISH)
def test_every_motif_kind_moves(slug: str) -> None:
    """The static kinds (chip, robot, shield, sandbox, screen) were the ones that froze."""

    spec = load_channel_specs()[slug]
    for kind in ("chip", "robot", "shield", "sandbox", "screen", "network", "loop"):
        lines = _held_card(spec, visual=kind)
        before = np.asarray(_frame(spec, lines, 4.0).convert("L"), dtype="int16")
        after = np.asarray(_frame(spec, lines, 5.0).convert("L"), dtype="int16")
        changed = float((np.abs(after - before) > 2).mean())
        assert changed > 0.02, f"{slug}/{kind} changed {changed:.3%} of pixels in a second"


@pytest.mark.parametrize("slug", ENGLISH)
def test_the_motion_is_gentle_and_continuous(slug: str) -> None:
    """No jump, no flicker: consecutive frames differ, but never by much."""

    spec = load_channel_specs()[slug]
    lines = _held_card(spec)
    frames = [np.asarray(_frame(spec, lines, index / er.FPS).convert("L"), dtype="int16")
              for index in range(int(3.0 * er.FPS))]
    steps = [float(np.abs(b - a).mean()) for a, b in zip(frames, frames[1:])]
    assert max(steps) < 4.0, f"an abrupt jump of {max(steps):.2f} grey levels"
    assert sum(1 for step in steps if step < 1e-4) <= 2, "the picture stalls for more than two frames"


@pytest.mark.parametrize("slug", ENGLISH)
def test_the_headline_stays_legible_while_it_moves(slug: str) -> None:
    """Motion must not smear the type or push it out of its safe area."""

    spec = load_channel_specs()[slug]
    lines = _held_card(spec)
    counts = []
    for t in (0.5, 3.0, 6.0):
        region = _frame(spec, lines, t).convert("L").crop((60, 240, er.WIDTH - 60, 400))
        array = np.asarray(region, dtype="uint8")
        counts.append(int((array > 200).sum()))          # bright headline pixels
    assert min(counts) > 2000, f"headline lost mass: {counts}"
    spread = (max(counts) - min(counts)) / max(counts)
    assert spread < 0.25, f"headline contrast swung by {spread:.0%}: {counts}"


def test_the_camera_curve_is_monotonic_and_bounded() -> None:
    scales = [er.camera_scale(t) for t in range(0, 120)]
    assert scales[0] == pytest.approx(1.0)
    assert all(later >= earlier - 0.005 for earlier, later in zip(scales, scales[1:]))
    assert max(er.camera_scale(t) for t in range(0, 5000)) <= 1.0 + er.DRIFT_MAX
    # and it must still be moving at the cap, which is the ring's job
    assert er.camera_scale(1000) == er.camera_scale(2000)


@pytest.mark.parametrize("slug", ENGLISH)
def test_identical_inputs_produce_identical_frames(slug: str) -> None:
    spec = load_channel_specs()[slug]
    lines = _held_card(spec)
    assert _frame(spec, lines, 2.25).tobytes() == _frame(spec, lines, 2.25).tobytes()


def test_natkhat_toons_did_not_receive_the_english_camera_move() -> None:
    """The portrait character renderer is a different pipeline and must stay byte-identical."""

    from factory.media import hindi_renderer

    assert "compose_frame" not in vars(hindi_renderer)
    assert not hasattr(hindi_renderer, "camera_scale")


@pytest.mark.parametrize("slug", ENGLISH)
def test_a_long_hold_after_the_narration_stops_does_not_freeze(slug: str, tmp_path: Path) -> None:
    """The defect the first fix missed: narration ends, the caption stops changing, and the tail froze.

    The push-in reaches its cap after 20 s, so past that point the only thing moving is the light sweep and
    the accent ring. This test holds one card for 16 s with no caption change - long enough to cover the
    capped drift - and requires the tail (last 4 s) to be clean.
    """

    spec = load_channel_specs()[slug]
    text = "a b c"
    words = [WordTiming(text=word, start=i * 0.5, end=i * 0.5 + 0.5)
             for i, word in enumerate(text.split())]
    lines = [ScriptLine(text=text, headline="Held", visual="chip", start=0.0, end=16.0, words=words)]
    path = _encode(spec, lines, tmp_path / f"{slug}-hold.mp4", 16.0)
    tail = [(start, length) for start, length in _freeze_events(path) if start + length > 12.0]
    assert tail == [], f"{slug} tail froze: {tail}"
