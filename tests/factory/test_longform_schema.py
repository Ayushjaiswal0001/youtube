"""A landscape plan is not a portrait plan with different key names.

Cloud run 45045980024 exposed the shorts path; the landscape path had the mirror-image defect on the read
side. `production`, `validate`, `manifest` and `gate` all called `build_hindi_script`, which requires
`scenes[].dialogue`, so the landscape plan (`scenes[].line`) was rejected as "invalid scene" even though the
renderer had produced it and its own QC passed 27/27. The render path always dispatched by engine; the read
path now does too, through `orchestrator.build_script`.

None of this loosens anything: a scene with no text is still an error, and the portrait Hindi schema is still
strict about its own keys.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from factory import manifesting
from factory.config import load_channel_specs
from factory.content.script import build_hindi_script
from factory.media import landscape_stage
from factory.media.landscape_stage import build_script as build_stage_script
from factory.media.landscape_stage import plan_scenes
from factory.orchestrator import build_script, plan_specs
from factory.qa.publish_gate import evaluate_publish_gate


@pytest.fixture(scope="module")
def specs():
    return load_channel_specs()


@pytest.fixture(scope="module")
def spec_long(specs):
    from dataclasses import replace

    return replace(specs["natkhat-toons"], format="long")


def _portrait_plan() -> dict:
    return {
        "id": "portrait-1",
        "title": "चीकू की चाबी",
        "topic": "a brass key",
        "hook": "हवेली में एक चाबी मिली",
        "episode": 3,
        "scenes": [
            {"n": 1, "speaker": "narrator", "dialogue": "पहला दृश्य यहाँ है।", "sfx": "whoosh"},
            {"n": 2, "speaker": "chiku", "dialogue": "दूसरा दृश्य यहाँ है।"},
            {"n": 3, "speaker": "gappu", "dialogue": "तीसरा दृश्य यहाँ है।"},
        ],
    }


def _landscape_plan(**extra) -> dict:
    plan = {
        "id": "landscape-1",
        "format": "long",
        "engine": "stage",
        "title": "हवेली का रहस्य",
        "topic": "haveli mystery",
        "hook": "आधी रात को दरवाज़ा खुला",
        "episode": 1,
        "series": "natkhat-haveli",
        "series_title": "नटखट हवेली",
        "moral": "साथ मिलकर हर मुश्किल हल होती है",
        "chapters": [{"title": "रात", "start_scene": 1}, {"title": "सुबह", "start_scene": 7}],
        "scenes": [
            {"n": 1, "speaker": "narrator", "line": "दरवाज़े पर दोनों खड़े थे।",
             "chiku_pose": "idle", "gappu_pose": "idle", "camera": "two_shot",
             "bg": "haunted_haveli", "sfx": "whoosh"},
            {"n": 2, "speaker": "chiku", "line": "यह चाबी किसकी है?",
             "chiku_pose": "point", "camera": "close", "bg": "haunted_haveli",
             "lighting": {"mood": "moon"}},
            {"n": 3, "speaker": "gappu", "line": "चलो अंदर चलते हैं।",
             "camera": "wide", "bg": "haunted_haveli", "pickup": {"prop": "key"}},
        ],
    }
    plan.update(extra)
    return plan


# ------------------------------------------------------------------ both schemas build

def test_a_landscape_plan_using_line_builds_a_script(spec_long) -> None:
    script = build_script(spec_long, _landscape_plan())
    assert script.format == "long"
    assert len(script.lines) == 3
    assert script.lines[1].text == "यह चाबी किसकी है?"
    assert script.metadata["engine"] == "stage"


def test_a_portrait_plan_using_dialogue_still_builds(specs) -> None:
    script = build_hindi_script(specs["natkhat-toons"], _portrait_plan())
    assert len(script.lines) == 3
    assert script.episode == 3


def test_the_dispatcher_does_not_send_a_portrait_plan_to_the_landscape_builder(specs) -> None:
    """The channel is Hindi either way; the engine, not the language, decides the schema."""

    portrait = build_script(specs["natkhat-toons"], _portrait_plan())
    landscape = build_script(specs["natkhat-toons"], _landscape_plan())
    assert portrait.metadata.get("engine") in (None, "hindi")
    assert landscape.metadata["engine"] == "stage"


# ------------------------------------------------------------------ malformed plans are still rejected

def test_a_landscape_scene_without_text_is_rejected() -> None:
    plan = _landscape_plan()
    plan["scenes"][1].pop("line")
    with pytest.raises(ValueError) as caught:
        plan_scenes(plan)
    assert "scene 2" in str(caught.value)


def test_a_landscape_scene_with_blank_text_is_rejected() -> None:
    plan = _landscape_plan()
    plan["scenes"][0]["line"] = "   "
    with pytest.raises(ValueError) as caught:
        plan_scenes(plan)
    assert "no line" in str(caught.value)


def test_a_landscape_plan_with_no_scenes_is_rejected() -> None:
    with pytest.raises(ValueError):
        plan_scenes({"id": "empty", "scenes": []})


def test_a_portrait_scene_without_dialogue_is_rejected(specs) -> None:
    plan = _portrait_plan()
    plan["scenes"][1].pop("dialogue")
    with pytest.raises(ValueError) as caught:
        build_hindi_script(specs["natkhat-toons"], plan)
    assert "invalid scene" in str(caught.value)


def test_a_scene_text_that_is_not_a_string_is_rejected(specs) -> None:
    plan = _portrait_plan()
    plan["scenes"][0]["dialogue"] = {"text": "not a string"}
    with pytest.raises(ValueError):
        build_hindi_script(specs["natkhat-toons"], plan)


# ------------------------------------------------------------------ structure is preserved

def test_chapters_and_beats_survive_normalisation(spec_long) -> None:
    script = build_script(spec_long, _landscape_plan())
    assert script.metadata["chapters"] == [{"title": "रात", "start_scene": 1},
                                          {"title": "सुबह", "start_scene": 7}]
    scenes = script.metadata["scenes"]
    assert [scene["scene_num"] for scene in scenes] == [1, 2, 3]
    assert scenes[1]["camera"] == "close"
    assert scenes[1]["lighting"] == {"mood": "moon"}
    assert scenes[2]["pickup"] == {"prop": "key"}
    assert script.series == "natkhat-haveli" and script.episode == 1


def test_source_attribution_and_captions_are_kept(spec_long) -> None:
    script = build_script(spec_long, _landscape_plan())
    assert script.lines[0].caption == script.lines[0].text
    assert script.moral


def test_the_stage_story_record_names_its_scenes(spec_long) -> None:
    plan = _landscape_plan()
    script = build_stage_script(spec_long, plan)
    story = landscape_stage.build_story(spec_long, plan, script)
    assert story["story_id"] == landscape_stage.stage_story_id(spec_long, plan)
    assert len(story["scenes"]) == 3


# ------------------------------------------------------------------ the gate can see both profiles

def test_plan_specs_covers_both_composition_profiles(specs) -> None:
    formats = {spec.format for spec in plan_specs(specs["natkhat-toons"])}
    assert formats == {"shorts", "long"}


# ------------------------------------------------------------------ a long-form package

def _long_package(tmp_path: Path, spec) -> Path:
    out = tmp_path / "episode"
    out.mkdir()
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=61",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=61",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-shortest", str(out / "video.mp4")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from PIL import Image

    Image.new("RGB", (1280, 720), (10, 14, 26)).save(out / "thumbnail.jpg")
    (out / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:20,000\nदृश्य\n", encoding="utf-8")
    for name, payload in (
        ("timeline.json", {"lines": []}),
        ("script.json", {"title": "हवेली का रहस्य"}),
        ("story.json", {"schema": "story/1", "scene_count": 3, "scenes": []}),
        ("framing.json", {"cropped_required_frames": 0, "subtitle_collision_frames": 0, "scenes": []}),
        ("continuity.json", {"ok": True, "issues": []}),
        ("shot_plan.json", {"decisions": [], "warnings": []}),
    ):
        (out / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (out / "qc.json").write_text(json.dumps({"ok": True, "error_count": 0, "checks": [],
                                             "checked_at": "2026-11-23T09:00:00+00:00"}),
                                 encoding="utf-8")
    manifesting.rebuild(out, channel=spec.slug, plan_id="landscape-1", format="long")
    return out


def _long_gate(spec, out: Path):
    from factory.content.models import Script, ScriptLine

    script = Script(channel=spec.slug, language="hi", format="long", topic="t",
                    title="हवेली का रहस्य", hook="h",
                    lines=[ScriptLine(text="दरवाज़े पर दोनों खड़े थे।", start=0.0, end=20.0)],
                    description="d", tags=["long"])
    return evaluate_publish_gate(spec, script, out / "video.mp4", out_dir=out,
                                 thumbnail=out / "thumbnail.jpg", srt=out / "captions.srt",
                                 measure_decode=True, measure_loudness=True)


def test_a_long_form_package_verifies_and_passes_the_gate(spec_long, tmp_path: Path) -> None:
    out = _long_package(tmp_path, spec_long)
    assert manifesting.verify(out) == []
    gate = _long_gate(spec_long, out)
    failed = {c.name: c.detail for c in gate.checks if not c.ok}
    assert not failed, failed
    assert len(manifesting.collect_artifacts(out)) == 10  # incl. continuity + shot_plan


def test_a_long_form_package_with_a_missing_artifact_is_reported(spec_long, tmp_path: Path) -> None:
    out = _long_package(tmp_path, spec_long)
    (out / "continuity.json").unlink()
    problems = manifesting.verify(out)
    assert any("continuity: missing" in problem for problem in problems), problems


def test_a_long_form_package_with_a_stale_manifest_fails(spec_long, tmp_path: Path) -> None:
    out = _long_package(tmp_path, spec_long)
    report = json.loads((out / "qc.json").read_text(encoding="utf-8"))
    report["checked_at"] = "2026-11-23T10:00:00+00:00"
    (out / "qc.json").write_text(json.dumps(report), encoding="utf-8")
    assert manifesting.verify(out)
    manifesting.rebuild(out, channel=spec_long.slug, format="long")
    assert manifesting.verify(out) == []


def test_a_long_form_package_with_cropped_composition_is_blocked(spec_long, tmp_path: Path) -> None:
    out = _long_package(tmp_path, spec_long)
    (out / "framing.json").write_text(json.dumps({"cropped_required_frames": 4,
                                                  "subtitle_collision_frames": 0, "scenes": []}),
                                      encoding="utf-8")
    manifesting.rebuild(out, channel=spec_long.slug, format="long")
    check = next(c for c in _long_gate(spec_long, out).checks if c.name == "framing")
    assert not check.ok and "4" in check.detail
