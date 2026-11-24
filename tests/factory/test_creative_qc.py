"""Creative QC: a check that can only be failed by the video it measures.

Every test here builds the artefacts a render produces and asks the report a question that has a
wrong answer - so a green report cannot be produced by an empty scene list or a missing file.
"""

from __future__ import annotations

import json
from pathlib import Path

from factory.qa.creative import DEFAULTS, evaluate, evaluate_scenes_file, load_thresholds


def scene(scene_id: str, start: int, end: int, *, variant: str = "pipeline",
          asset: str | None = None, category: str = "diagram", deviation=None,
          title: str = "PRETRAIN ON VIDEO", on_screen: str = "Pretrain on video") -> dict:
    asset_id = asset if asset is not None else f"gen-{variant}-{scene_id}"
    return {
        "scene_id": scene_id, "start_ms": start, "end_ms": end,
        "duration_ms": end - start, "narration_text": "text", "main_concept": title,
        "on_screen_text": on_screen, "visual_category": category,
        "coverage_category": category, "asset_id": asset_id, "asset_source": "generated",
        # v1.1: every scene carries provenance and the fingerprint of the plate actually drawn.
        "license": "generated-local", "attribution_text": None,
        "duration_deviation": deviation,
        "resolution": {"scene_id": scene_id, "category": category, "kind": "generated",
                       "asset_id": asset_id, "variant": variant, "spec_title": title,
                       "entities": ["video"], "license": "generated-local", "attribution": None,
                       # the renderer records what the plate shows; the figure check reads this
                       "visible_text": [title],
                       "plate_fingerprint": f"{abs(hash(scene_id + variant)) % (16 ** 16):016x}"},
    }


def plan(scenes: list[dict], narration_ms: int = 36_000, allowed=(5, 18)) -> dict:
    return {"schema": "scene-plan/1", "channel": "nexus-node", "narration_ms": narration_ms,
            "allowed_scene_count": list(allowed), "scenes": scenes}


def healthy() -> dict:
    scenes = [
        scene("s01", 300, 4300, variant="pipeline"),
        scene("s02", 4300, 7900, variant="gap"),
        scene("s03", 7900, 12400, variant="comparison"),
        scene("s04", 12400, 16800, variant="topology"),
        scene("s05", 16800, 21300, variant="timeline"),
        scene("s06", 21300, 25500, variant="pipeline"),
        scene("s07", 25500, 29900, variant="gap"),
        scene("s08", 29900, 32800, variant="comparison"),
        scene("s09", 32800, 36300, variant="cta"),
    ]
    return plan(scenes, narration_ms=36_000, allowed=(5, 18))


class TestHealthyPlan:
    def test_a_planned_video_passes(self) -> None:
        report = evaluate(channel="nexus-node", scene_plan=healthy())
        assert report.ok, report.failures
        assert report.metrics["scenes"] == 9
        assert report.metrics["distinct_assets"] == 9

    def test_the_report_records_the_band_it_judged_against(self) -> None:
        report = evaluate(channel="nexus-node", scene_plan=healthy())
        assert report.thresholds["min_scene_ms"] == DEFAULTS["min_scene_ms"]
        assert report.to_dict()["schema"] == "creative-qc/1"


class TestFailuresHaveTeeth:
    def test_a_gap_in_the_tiling_is_a_failure(self) -> None:
        broken = healthy()
        broken["scenes"][3]["start_ms"] += 500
        report = evaluate(channel="nexus-node", scene_plan=broken)
        assert "scenes_tile_narration" in report.failures

    def test_a_scene_count_outside_the_derived_window_is_a_failure(self) -> None:
        thin = plan([scene("s01", 300, 20_300, variant="pipeline")], narration_ms=36_000,
                    allowed=(5, 18))
        report = evaluate(channel="nexus-node", scene_plan=thin)
        assert "scene_count_in_derived_window" in report.failures

    def test_an_unexplained_short_scene_is_a_failure(self) -> None:
        scenes = healthy()["scenes"]
        scenes[0]["end_ms"] = scenes[0]["start_ms"] + 900
        scenes[0]["duration_ms"] = 900
        scenes[1]["start_ms"] = scenes[0]["end_ms"]
        scenes[0]["duration_deviation"] = None
        report = evaluate(channel="nexus-node", scene_plan=plan(scenes))
        assert "pacing_inside_band" in report.failures

    def test_a_short_scene_with_a_reason_is_accepted(self) -> None:
        scenes = healthy()["scenes"]
        scenes[0]["end_ms"] = scenes[0]["start_ms"] + 1800
        scenes[0]["duration_ms"] = 1800
        scenes[1]["start_ms"] = scenes[0]["end_ms"]
        scenes[0]["duration_deviation"] = {"ms": 1800, "reason": "one-clause punch-in"}
        report = evaluate(channel="nexus-node", scene_plan=plan(scenes))
        assert "pacing_inside_band" not in report.failures

    def test_one_composition_repeated_is_a_failure(self) -> None:
        scenes = [scene(f"s0{index}", 300 + index * 4000, 4300 + index * 4000,
                        variant="pipeline", asset=f"gen-pipeline-{index}")
                  for index in range(1, 6)]
        report = evaluate(channel="nexus-node", scene_plan=plan(scenes, narration_ms=20_000,
                                                                allowed=(3, 10)))
        assert "no_repeated_composition_runs" in report.failures

    def test_one_visual_reused_everywhere_is_a_failure(self) -> None:
        scenes = [scene(f"s0{index}", 300 + index * 4000, 4300 + index * 4000,
                        variant="pipeline" if index % 2 else "gap", asset="gen-pipeline-same")
                  for index in range(1, 6)]
        report = evaluate(channel="nexus-node", scene_plan=plan(scenes, narration_ms=20_000,
                                                                allowed=(3, 10)))
        assert "distinct_visuals" in report.failures

    def test_a_scene_without_a_visual_is_a_failure(self) -> None:
        broken = healthy()
        broken["scenes"][2]["resolution"] = None
        broken["scenes"][2]["asset_id"] = None
        report = evaluate(channel="nexus-node", scene_plan=broken)
        assert "every_scene_has_a_visual" in report.failures

    def test_a_scene_without_a_rendered_category_is_a_failure(self) -> None:
        broken = healthy()
        broken["scenes"][0]["coverage_category"] = None
        report = evaluate(channel="nexus-node", scene_plan=broken)
        assert "rendered_category_recorded" in report.failures

    def test_an_empty_plan_fails_rather_than_passing_vacuously(self) -> None:
        report = evaluate(channel="nexus-node", scene_plan=plan([], narration_ms=30_000))
        assert not report.ok
        assert "scene_count_in_derived_window" in report.failures


class TestFramingEvidence:
    def test_caption_collisions_fail_the_report(self) -> None:
        framing = {"subtitle_collision_frames": 3,
                   "elements": {"caption": {"max_overflow_px": 0},
                                "headline": {"max_overflow_px": 0},
                                "visual": {"max_overflow_px": 0, "painted_frames": 20}}}
        report = evaluate(channel="nexus-node", scene_plan=healthy(), framing=framing)
        assert "no_caption_collisions" in report.failures

    def test_a_plate_leaving_the_safe_area_fails(self) -> None:
        framing = {"subtitle_collision_frames": 0,
                   "elements": {"caption": {"max_overflow_px": 0},
                                "headline": {"max_overflow_px": 0},
                                "visual": {"max_overflow_px": 12, "painted_frames": 20}}}
        report = evaluate(channel="nexus-node", scene_plan=healthy(), framing=framing)
        assert "visual_inside_safe_area" in report.failures

    def test_clean_framing_adds_passing_checks(self) -> None:
        framing = {"subtitle_collision_frames": 0,
                   "elements": {"caption": {"max_overflow_px": 0},
                                "headline": {"max_overflow_px": 0},
                                "visual": {"max_overflow_px": 0, "painted_frames": 20}}}
        report = evaluate(channel="nexus-node", scene_plan=healthy(), framing=framing)
        assert report.ok
        assert "visual_inside_safe_area" in [check.name for check in report.checks]


class TestThresholds:
    def test_missing_config_uses_the_defaults(self, tmp_path: Path) -> None:
        assert load_thresholds(tmp_path / "absent.json") == DEFAULTS

    def test_a_config_cannot_invent_a_key(self, tmp_path: Path) -> None:
        path = tmp_path / "creative_qc.json"
        path.write_text(json.dumps({"min_scene_ms": 1200, "disable": True}), encoding="utf-8")
        thresholds = load_thresholds(path)
        assert thresholds["min_scene_ms"] == 1200
        assert "disable" not in thresholds

    def test_a_malformed_config_falls_back_to_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "creative_qc.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_thresholds(path) == DEFAULTS


class TestFilesOnDisk:
    def test_the_report_reads_the_artefacts_it_is_pointed_at(self, tmp_path: Path) -> None:
        scenes_path = tmp_path / "scenes.json"
        framing_path = tmp_path / "framing.json"
        scenes_path.write_text(json.dumps(healthy()), encoding="utf-8")
        framing_path.write_text(json.dumps({"subtitle_collision_frames": 0, "elements": {}}),
                                encoding="utf-8")
        report = evaluate_scenes_file(scenes_path, framing_path=framing_path)
        assert report.ok
        written = report.write(tmp_path / "creative.json")
        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload["ok"] is True and payload["metrics"]["scenes"] == 9
