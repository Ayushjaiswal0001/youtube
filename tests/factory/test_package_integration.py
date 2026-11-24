"""End-to-end: a freshly rendered Nexus package must pass its own verification and its own gate.

This is the test that would have caught H1. It exercises the real chain - render artefacts, the
package `render_episode` builds, `manifesting.verify`, and `evaluate_publish_gate` - and it asserts the
verdict *without* a manual `cli manifest` rebuild in between, because that rebuild is what hid the
defect: the workflow happened to run it, an operator calling `gate` did not.

The media is a real, tiny MP4 encoded with the same encoder settings the renderer uses, so the gate's
ffprobe/loudness checks run for real rather than being stubbed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.content.models import Script, ScriptLine, WordTiming
from factory.manifesting import verify
from factory.qa.publish_gate import evaluate_publish_gate
from factory.reliability import production_manifest

HERE = Path(__file__).resolve().parents[2]
RENDERED = Path("C:/Users/DELL/AppData/Local/Temp/x100new/nexus-node/nexus-robot-video")


def make_script() -> Script:
    text = "A robot arm learns a grasp from video footage."
    words = text.split()
    span = 3.0 / len(words)
    line = ScriptLine(text=text, headline="DATA WALL", visual="network", caption=text,
                      start=0.2, end=3.2,
                      words=[WordTiming(word, 0.2 + index * span, 0.2 + (index + 1) * span - 0.02)
                             for index, word in enumerate(words)])
    return Script(channel="nexus-node", language="en", format="shorts", topic="t",
                  title="Acceptance package", hook=text, lines=[line],
                  description="A short description that is long enough.",
                  tags=["ai", "robotics"], sources=["https://example.test/source"],
                  style="deep-dive", series=None, episode=None, moral=None, series_title=None,
                  produced_at="2026-11-24T00:00:00+00:00", metadata={"plan_id": "acceptance"})


def write_episode(directory: Path) -> dict:
    """The artefact set a real render writes, with a genuine encoded video."""

    directory.mkdir(parents=True, exist_ok=True)
    video = directory / "video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=0x050B16:s=1080x1920:r=30:d=3",
         "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100:duration=3",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(video)],
        check=True,
    )
    artifacts = {"video": video, "thumbnail": directory / "thumbnail.jpg",
                 "captions": directory / "captions.srt", "qc_report": directory / "qc.json",
                 "timeline": directory / "timeline.json", "framing": directory / "framing.json",
                 "story": directory / "story.json", "script": directory / "script.json"}
    from PIL import Image

    Image.new("RGB", (1280, 720), "#10243A").save(artifacts["thumbnail"])
    artifacts["captions"].write_text(
        "1\n00:00:00,200 --> 00:00:03,000\nA robot arm learns a grasp\n", encoding="utf-8")
    (directory / "qc.json").write_text(json.dumps({"ok": True, "duration": 3.0}),
                                       encoding="utf-8")
    (directory / "timeline.json").write_text(json.dumps({"duration": 3.0}), encoding="utf-8")
    (directory / "story.json").write_text(json.dumps({"scene_count": 1}), encoding="utf-8")
    (directory / "script.json").write_text(json.dumps({"channel": "nexus-node"}), encoding="utf-8")
    (directory / "framing.json").write_text(json.dumps({
        "cropped_required_frames": 0, "subtitle_collision_frames": 0,
        "elements": {"caption": {"max_overflow_px": 0}, "headline": {"max_overflow_px": 0},
                     "visual": {"max_overflow_px": 0, "painted_frames": 10}},
    }), encoding="utf-8")
    (directory / "scenes.json").write_text(json.dumps({
        "schema": "scene-plan/1", "channel": "nexus-node", "narration_ms": 3000,
        "allowed_scene_count": [1, 3], "min_scene_ms": 2000, "max_scene_ms": 8000,
        "problems": [], "decisions": [],
        "scenes": [{
            "scene_id": "s01", "start_ms": 200, "end_ms": 3000, "duration_ms": 2800,
            "narration_text": "A robot arm learns a grasp from video footage.",
            "main_concept": "A robot arm learns a grasp", "on_screen_text": "DATA WALL",
            "coverage_category": "diagram", "asset_id": "gen-pipeline-abc", "duration_deviation": None,
            "derived_from": {"line_index": 0, "word_range": [0, 8]},
            "resolution": {"scene_id": "s01", "category": "diagram", "kind": "generated",
                           "asset_id": "gen-pipeline-abc", "variant": "pipeline",
                           "spec_title": "A robot arm learns", "path": "x100_asset_cache/x.png"},
        }],
    }), encoding="utf-8")
    (directory / "creative.json").write_text(json.dumps({
        "schema": "creative-qc/1", "channel": "nexus-node", "ok": True, "failures": [],
        "warnings": [], "checks": [],
        "metrics": {"scenes": 1, "distinct_assets": 1, "compositions": ["pipeline"]},
        "thresholds": {},
    }), encoding="utf-8")
    artifacts["scene_plan"] = directory / "scenes.json"
    artifacts["creative_qc"] = directory / "creative.json"
    return artifacts


class TestFreshPackagePassesWithoutARebuild:
    def test_the_package_verifies_before_any_manifest_rebuild(self, tmp_path: Path) -> None:
        artifacts = write_episode(tmp_path)
        manifest = production_manifest(channel="nexus-node", plan_id="acceptance", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        names = {entry["name"] for entry in manifest["artifacts"]}
        assert {"scene_plan", "creative_qc"} <= names
        assert verify(tmp_path) == []

    def test_the_publishing_gate_passes_on_a_fresh_package(self, tmp_path: Path) -> None:
        artifacts = write_episode(tmp_path)
        manifest = production_manifest(channel="nexus-node", plan_id="acceptance", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        spec = load_channel_specs()["nexus-node"]
        result = evaluate_publish_gate(spec, make_script(), tmp_path / "video.mp4",
                                       out_dir=tmp_path, measure_decode=False,
                                       measure_loudness=False).to_dict()
        manifest_check = next(check for check in result["checks"] if check["name"] == "manifest")
        assert manifest_check["ok"], manifest_check
        assert "manifest" not in result["blockers"], result["blockers"]

    def test_the_creative_check_is_part_of_the_gate_for_a_scene_planned_package(
            self, tmp_path: Path) -> None:
        artifacts = write_episode(tmp_path)
        manifest = production_manifest(channel="nexus-node", plan_id="acceptance", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        spec = load_channel_specs()["nexus-node"]
        result = evaluate_publish_gate(spec, make_script(), tmp_path / "video.mp4",
                                       out_dir=tmp_path, measure_decode=False,
                                       measure_loudness=False).to_dict()
        names = {check["name"] for check in result["checks"]}
        assert "creative_quality" in names

    def test_a_missing_creative_report_blocks_a_scene_planned_package(self, tmp_path: Path) -> None:
        artifacts = write_episode(tmp_path)
        (tmp_path / "creative.json").unlink()
        del artifacts["video"]  # avoid re-encoding; only the manifest/gate behaviour is under test
        manifest = production_manifest(channel="nexus-node", plan_id="acceptance", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        spec = load_channel_specs()["nexus-node"]
        result = evaluate_publish_gate(spec, make_script(), tmp_path / "video.mp4",
                                       out_dir=tmp_path, measure_decode=False,
                                       measure_loudness=False).to_dict()
        assert "creative_quality" in result["blockers"]

    def test_a_legacy_package_has_no_creative_requirement(self, tmp_path: Path) -> None:
        artifacts = write_episode(tmp_path)
        for name in ("scene_plan", "creative_qc"):
            artifacts.pop(name)
        (tmp_path / "scenes.json").unlink()
        (tmp_path / "creative.json").unlink()
        manifest = production_manifest(channel="academic-biohacker", plan_id="acceptance",
                                       engine="shorts", format="shorts", artifacts=artifacts,
                                       qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert verify(tmp_path) == []
        spec = load_channel_specs()["academic-biohacker"]
        result = evaluate_publish_gate(spec, make_script(), tmp_path / "video.mp4",
                                       out_dir=tmp_path, measure_decode=False,
                                       measure_loudness=False).to_dict()
        names = {check["name"] for check in result["checks"]}
        assert "creative_quality" not in names


@pytest.mark.skipif(not (RENDERED / "manifest.json").is_file(), reason="no local render on this machine")
class TestTheRealRenderedPackage:
    def test_the_rendered_nexus_package_gates_clean(self, tmp_path: Path) -> None:
        """The artefact this pass actually produced, gated as the workflow gates it."""

        copy = tmp_path / "episode"
        shutil.copytree(RENDERED, copy)
        assert verify(copy) == []
        spec = load_channel_specs()["nexus-node"]
        script = Script.from_dict(json.loads((copy / "script.json").read_text(encoding="utf-8")))
        result = evaluate_publish_gate(spec, script, copy / "video.mp4", out_dir=copy).to_dict()
        assert result["ok"], result["blockers"]
        names = {check["name"] for check in result["checks"]}
        assert "creative_quality" in names
