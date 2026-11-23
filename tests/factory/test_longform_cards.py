"""The 16:9 card engine: reports the gate needs, and motion that never stops.

Two defects, both found by running it rather than by reading it.

`render_landscape` wrote `timeline.json` and `script.json` but not `story.json` or `framing.json`, and the
publishing gate treats a missing report as a blocker - so an English long-form episode was ungateable by
construction, exactly as an English Short was before cloud run 45045980024.

Then both long-form cloud runs failed QC on `frozen_frames`: 9.6 s at 131 s in the cloud, 5.4 s at 164.5 s
locally. Several motif kinds finish their intro and hold, the caption only changes when a chunk changes, and the
rail moves a few pixels a second. The plate now carries two counter-rotating rings and six orbiting dots.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from factory.config import load_channel_specs
from factory.content.models import Narration, Script, ScriptLine, WordTiming
from factory.media import landscape_renderer as R


@pytest.fixture(scope="module")
def spec_long():
    from dataclasses import replace

    return replace(load_channel_specs()["nexus-node"], format="long")


def _line(text: str, headline: str, start: float, end: float, visual: str = "shield") -> ScriptLine:
    words = text.split()
    step = (end - start) / max(1, len(words))
    timings = [WordTiming(text=word, start=start + index * step, end=start + (index + 1) * step)
               for index, word in enumerate(words)]
    return ScriptLine(text=text, headline=headline, start=start, end=end, visual=visual,
                      caption=text, sfx="pop", words=timings)


def _script(lines: list[ScriptLine]) -> Script:
    return Script(channel="nexus-node", language="en", format="long", topic="t",
                  title="A long form episode", hook="hook",
                  lines=lines, description="d", tags=["long"], sources=["a", "b"],
                  metadata={"plan_id": "long-test", "chapters": []})


def _frame(spec, script, lines, t: float) -> tuple[Image.Image, dict]:
    profile = R.get_profile(spec)
    base = R._base(profile, spec)
    mapping, marks, starts = R._chapter_map(script, lines)
    line, index = R._active_line(lines, t)
    geometry: dict = {}
    frame = R._draw_frame(base, line, t, lines[-1].end, index, len(lines), spec,
                          R.BRAND["nexus-node"], marks, mapping, starts, geometry=geometry)
    return frame, geometry


# ---------------------------------------------------------------- motion

def test_a_static_motif_still_moves(spec_long) -> None:
    """The freeze was reproducible without encoding: same line, five seconds apart, almost identical frames."""

    line = _line("A held card with a shield motif that finishes its intro and then stops moving.",
                 "The local bill", 0.0, 12.0, visual="shield")
    lines = [line]
    script = _script(lines)
    first, _ = _frame(spec_long, script, lines, 1.0)
    later, _ = _frame(spec_long, script, lines, 6.0)
    diff = np.abs(np.asarray(first, dtype=np.int16) - np.asarray(later, dtype=np.int16))
    changed = int((diff.sum(axis=2) > 6).sum())
    # the old code moved a few hundred pixels here (the rail); the ring churns tens of thousands
    assert changed > 20_000, changed
    assert diff.mean() > 1.0


def test_motion_continues_late_in_a_long_episode(spec_long) -> None:
    """Drift caps at 6 % and then the picture is still; the ring has to keep moving at minute five."""

    lines = [_line("Late in the episode the plate must still be animating.", "Late card", 0.0, 400.0,
                   visual="scale")]
    script = _script(lines)
    a, _ = _frame(spec_long, script, lines, 300.0)
    b, _ = _frame(spec_long, script, lines, 301.0)
    changed = int((np.abs(np.asarray(a, dtype=np.int16) - np.asarray(b, dtype=np.int16)).sum(axis=2) > 6).sum())
    assert changed > 3_000, changed


# ---------------------------------------------------------------- measurement

def test_the_frame_reports_what_it_drew(spec_long) -> None:
    line = _line("Support copy that sits between the rule and the caption band.", "Headline here", 0.0, 6.0)
    _, geometry = _frame(spec_long, _script([line]), [line], 1.0)
    assert geometry["headline"] and geometry["body"] and geometry["caption"]
    assert geometry["chapter_card"] is False
    assert geometry["headline"][0] >= R.SAFE_AREA_16X9["left"] - 1
    assert geometry["headline"][2] <= R.SAFE_AREA_16X9["right"] + 1


def test_a_chapter_card_is_recorded_as_a_chapter_card(spec_long) -> None:
    """A chapter card covers the layout on purpose; the report says so instead of counting it as cropped."""

    line = _line("Chapter opening line.", "Chapter one", 0.0, 8.0)
    script = Script(**{**_script([line]).to_dict(), "chapters": []}) if False else _script([line])
    script.metadata["chapters"] = [{"line": 0, "title": "Chapter one"}]
    mapping, marks, starts = R._chapter_map(script, [line])
    geometry: dict = {}
    R._draw_frame(R._base(R.get_profile(spec_long), spec_long), line, 0.2, 8.0, 0, 1, spec_long,
                  R.BRAND["nexus-node"], marks, mapping, starts, geometry=geometry)
    assert geometry["chapter_card"] is True
    sample = R.measure_geometry(geometry, Image.new("RGB", (R.WIDTH, R.HEIGHT)))
    assert sample["chapter_card"] is True and sample["headline_overflow"] == 0


def test_measure_geometry_catches_a_caption_over_the_body(spec_long) -> None:
    geometry = {"headline": (104, 200, 900, 300), "body": (104, 400, 900, 700),
                "caption": (300, 680, 1200, 760), "chapter_card": False}
    sample = R.measure_geometry(geometry, Image.new("RGB", (R.WIDTH, R.HEIGHT)))
    assert sample["collision"] is True
    assert sample["caption_overflow"] == 0


def test_measure_geometry_catches_overflow() -> None:
    geometry = {"headline": (40, 200, 900, 300), "body": None, "caption": None, "chapter_card": False}
    assert R.measure_geometry(geometry, Image.new("RGB", (R.WIDTH, R.HEIGHT)))["headline_overflow"] == 64


# ---------------------------------------------------------------- the package the gate needs

def _narration(audio: Path, duration: float, lines: list[ScriptLine]) -> Narration:
    return Narration(audio_path=str(audio), duration=duration, lines=lines)


def test_a_real_render_writes_story_and_framing(spec_long, tmp_path: Path) -> None:
    """3 s of real video, real encode: the gate's two required reports have to exist afterwards."""

    silence = tmp_path / "silence.m4a"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", "3.4", "-c:a", "aac", str(silence)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lines = [_line("A one line card that still has to produce a full package.", "One line", 0.0, 3.0)]
    script = _script(lines)
    out = tmp_path / "episode"
    out.mkdir()
    R.render_landscape(script, _narration(silence, 3.2, lines), spec_long, out / "video.mp4")

    assert (out / "video.mp4").is_file() and (out / "video.mp4").stat().st_size > 2000
    framing = json.loads((out / "framing.json").read_text(encoding="utf-8"))
    story = json.loads((out / "story.json").read_text(encoding="utf-8"))
    assert framing["schema"] == "framing/1" and framing["measured"] is True
    assert framing["cropped_required_frames"] == 0
    assert framing["subtitle_collision_frames"] == 0
    assert framing["layout_frames_sampled"] > 0
    assert story["schema"] == "story/1" and story["engine"] == "cards"
    assert story["scene_count"] == 1 and story["sources"] == ["a", "b"]
    # every file the manifest will hash is now produced by the renderer
    for name in ("timeline.json", "script.json", "story.json", "framing.json"):
        assert (out / name).is_file(), name


def _freeze_events(path: Path) -> list[str]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
                          "freezedetect=n=-50dB:d=2", "-map", "0:v", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return [line for line in log.splitlines() if "freeze_start" in line]


def test_a_held_line_does_not_freeze_once_encoded(spec_long, tmp_path: Path) -> None:
    """The real test, on encoded pixels: this is what the QC gate measures.

    Before the animated grain, a single held line encoded to a 2.13 s freeze window. Content motion alone (rings
    at 300 px/s, a sweeping band) is a 10 px column per frame at 30 fps - 0.5 % of the frame, below the -50 dB
    floor. The grain makes every frame genuinely different, which is why this test asserts the encoded result
    rather than a proxy statistic.
    """

    silence = tmp_path / "silence.m4a"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", "8.5", "-c:a", "aac", str(silence)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    line = _line("A held card whose motif finishes its intro and then stops entirely.", "Held card",
                 0.0, 8.0, visual="shield")
    script = _script([line])
    out = tmp_path / "held.mp4"
    R.render_landscape(script, _narration(silence, 8.2, [line]), spec_long, out)
    assert not _freeze_events(out), _freeze_events(out)


def test_the_pan_stays_inside_the_layout_margins() -> None:
    offsets = [R.pan_offset(t / 10.0) for t in range(0, 3000)]
    assert max(abs(dx) for dx, _ in offsets) <= R.PAN_X[0]
    assert max(abs(dy) for _, dy in offsets) <= R.PAN_Y[0]
    # the excursion has to stay well inside the 104 px margin or the pan would clip the composition
    assert R.PAN_X[0] + R.PAN_Y[0] < R.MARGIN - 20
    # and it has to actually move: a pan that rounds to zero changes nothing
    assert len({px for px, _ in offsets}) > 20


def test_the_framing_report_measures_the_panned_frame(spec_long) -> None:
    """The report must describe the picture that was encoded, not the composition before the pan."""

    line = _line("Support copy that sits between the rule and the caption band.", "Headline here", 0.0, 6.0)
    geometry = {"headline": (200.0, 260.0, 900.0, 340.0), "body": None, "caption": None,
                "chapter_card": False, "pan": (30, -12)}
    sample = R.measure_geometry(geometry, Image.new("RGB", (R.WIDTH, R.HEIGHT)))
    assert sample["headline"][:2] == [230.0, 248.0]
