"""Regression tests for the four MEDIUM-severity issues from the independent audit.

M1  a cross-line merge kept a stale word-index space and stamped a hardcoded reason
M2  creative QC judged the plan against global defaults instead of the band the plan declared
M3  nothing checked that a plate title belongs to its own sentence, or that the headline line agrees
M4  a legacy render reported a zero-valued "visual" element as though a plate had been measured
"""

from __future__ import annotations

import json
from pathlib import Path

from factory.config import load_channel_specs
from factory.content.models import Script, ScriptLine, WordTiming
from factory.content.scene_plan import plan_scenes
from factory.qa.creative import DEFAULTS, evaluate, load_thresholds

SPEC = load_channel_specs()["nexus-node"]


def line(text: str, start: float, end: float, headline: str = "") -> ScriptLine:
    tokens = [token.strip(".,;:!?") for token in text.split()]
    span = (end - start) / max(1, len(tokens))
    words = [WordTiming(token, start + i * span, start + (i + 1) * span - 0.02)
             for i, token in enumerate(tokens)]
    return ScriptLine(text=text, headline=headline, start=start, end=end, words=words)


def plan_for(line_specs):
    lines = [line(text, start, end, headline) for text, start, end, headline in line_specs]
    script = Script(channel="nexus-node", language="en", format="shorts", topic="t", title="T",
                    hook=lines[0].text, lines=lines, description="")
    return plan_scenes(SPEC, script)


# ------------------------------------------------------------------ M1
class TestM1CrossLineMerges:
    def test_a_merge_that_would_break_the_ceiling_is_refused(self) -> None:
        plan = plan_for([
            ("This is a long first sentence that runs on and on without any punctuation to break it "
             "for quite a while and keeps going", 0.3, 7.9, "LONG"),
            ("Tiny tail sentence", 8.1, 9.2, "SHORT"),
            ("A closing line long enough to stand alone as a scene on its own", 9.4, 14.0, "CLOSE"),
        ])
        assert all(scene.duration_ms <= plan.max_scene_ms for scene in plan.scenes)
        assert any(decision["action"] == "keep_separate" for decision in plan.decisions)

    def test_no_scene_crosses_the_ceiling_without_a_true_reason(self) -> None:
        plan = plan_for([
            ("This is a long first sentence that runs on and on without any punctuation to break it "
             "for quite a while and keeps going", 0.3, 7.9, "LONG"),
            ("Tiny tail sentence", 8.1, 9.2, "SHORT"),
            ("A closing line long enough to stand alone as a scene on its own", 9.4, 14.0, "CLOSE"),
        ])
        for scene in plan.scenes:
            if scene.duration_ms > plan.max_scene_ms:
                reason = (scene.duration_deviation or {}).get("reason", "")
                assert reason
                # the old text claimed a "single continuous idea" for a two-sentence scene
                assert "continuous idea" not in reason

    def test_a_short_scene_says_why_it_is_short(self) -> None:
        plan = plan_for([
            ("A first line that runs long enough to stand alone as a scene.", 0.3, 6.5, "A"),
            ("Tiny.", 6.7, 7.4, "B"),
            ("A closing line long enough to stand alone as well here.", 7.6, 12.5, "C"),
        ])
        short = [scene for scene in plan.scenes if scene.duration_ms < plan.min_scene_ms]
        for scene in short:
            assert scene.duration_deviation
            assert "min_scene_ms" in scene.duration_deviation["reason"]

    def test_a_merged_scene_reports_the_lines_it_spans(self) -> None:
        plan = plan_for([
            ("Short one here", 0.3, 2.2, "A"),
            ("Short two here", 2.4, 4.4, "B"),
            ("A third line that is comfortably long enough to stand alone", 4.6, 9.0, "C"),
        ])
        merged = [scene for scene in plan.scenes if (scene.derived_from or {}).get("lines")]
        assert merged, "expected one cross-line merge"
        for scene in merged:
            assert scene.derived_from["word_range"] is None
            assert len(scene.derived_from["lines"]) >= 2
            for index in scene.derived_from["lines"]:
                assert 0 <= index < 3

    def test_a_merged_scene_is_never_split_on_wrong_indices(self) -> None:
        plan = plan_for([
            ("Short one here", 0.3, 2.2, "A"),
            ("Short two here", 2.4, 4.4, "B"),
            ("A third line that is comfortably long enough to stand alone", 4.6, 9.0, "C"),
        ])
        for scene in plan.scenes:
            for word in scene.narration_text.split():
                assert word.strip(".,;:!?") in (
                    "Short one here Short two here A third line that is comfortably long enough to "
                    "stand alone"), word

    def test_tiling_still_holds_with_merges(self) -> None:
        plan = plan_for([
            ("Short one here", 0.3, 2.2, "A"),
            ("Short two here", 2.4, 4.4, "B"),
            ("A third line that is comfortably long enough to stand alone", 4.6, 9.0, "C"),
        ])
        for previous, following in zip(plan.scenes, plan.scenes[1:]):
            assert following.start_ms == previous.end_ms
        assert sum(scene.duration_ms for scene in plan.scenes) == plan.narration_ms


# ------------------------------------------------------------------ M2
def scene(scene_id: str, start: int, end: int, variant: str = "pipeline") -> dict:
    return {
        "scene_id": scene_id, "start_ms": start, "end_ms": end, "duration_ms": end - start,
        "narration_text": "A robot arm learns a grasp from video footage.",
        "main_concept": "Robot arm learns", "on_screen_text": "Robot arm learns",
        "coverage_category": "diagram", "duration_deviation": None,
        # the real scenes.json carries the asset at both levels; the QC reads the top-level one
        "asset_id": f"a-{scene_id}",
        "resolution": {"scene_id": scene_id, "variant": variant, "asset_id": f"a-{scene_id}",
                       "spec_title": "Robot arm learns"},
    }


class TestM2PlanBand:
    def test_the_plan_band_overrides_the_global_defaults(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 20000, "allowed_scene_count": [2, 10],
                "min_scene_ms": 3000, "max_scene_ms": 6000,
                "scenes": [scene("s01", 0, 2500), scene("s02", 2500, 5000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        pacing = next(check for check in report.checks if check.name == "pacing_inside_band")
        assert report.thresholds["min_scene_ms"] == 3000
        assert report.thresholds["max_scene_ms"] == 6000
        assert not pacing.ok, "a 2.5 s scene violates a 3000 ms floor"

    def test_without_a_plan_band_the_configured_defaults_apply(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 20000, "allowed_scene_count": [2, 10],
                "scenes": [scene("s01", 0, 2500), scene("s02", 2500, 5000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        assert report.thresholds["min_scene_ms"] == DEFAULTS["min_scene_ms"]
        pacing = next(check for check in report.checks if check.name == "pacing_inside_band")
        assert pacing.ok

    def test_a_tightened_config_file_is_enforced_when_the_plan_is_silent(self, tmp_path: Path) -> None:
        config = tmp_path / "creative_qc.json"
        config.write_text(json.dumps({"max_scene_ms": 4000}), encoding="utf-8")
        thresholds = load_thresholds(config)
        plan = {"channel": "nexus-node", "narration_ms": 20000, "allowed_scene_count": [2, 10],
                "scenes": [scene("s01", 0, 5000), scene("s02", 5000, 9000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan, thresholds=thresholds)
        pacing = next(check for check in report.checks if check.name == "pacing_inside_band")
        assert not pacing.ok, "a 5 s scene must fail a 4000 ms ceiling"


# ------------------------------------------------------------------ M3
class TestM3SemanticChecks:
    def test_a_plate_title_with_no_shared_word_is_a_warning(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 12000, "allowed_scene_count": [2, 10],
                "scenes": [dict(scene("s01", 0, 6000),
                                narration_text="Robots learn from video footage.",
                                resolution={"scene_id": "s01", "variant": "pipeline",
                                            "asset_id": "a", "spec_title": "STUDY"}),
                           scene("s02", 6000, 12000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        check = next(item for item in report.checks if item.name == "title_matches_narration")
        assert not check.ok
        assert check.severity == "warn"
        assert "s01" in check.detail
        assert report.ok, "a paraphrase warning must not fail the video"

    def test_a_paraphrase_is_not_flagged(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 12000, "allowed_scene_count": [2, 10],
                "scenes": [scene("s01", 0, 6000), scene("s02", 6000, 12000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        check = next(item for item in report.checks if item.name == "title_matches_narration")
        assert check.ok

    def test_an_abstract_title_grounded_elsewhere_in_the_episode_is_not_flagged(self) -> None:
        """The real render: "THE DATA PROBLEM" over a sentence that never says data."""

        plan = {"channel": "nexus-node", "narration_ms": 12000, "allowed_scene_count": [2, 10],
                "scenes": [dict(scene("s01", 0, 6000),
                                narration_text="A robot arm needs thousands of examples.",
                                resolution={"scene_id": "s01", "variant": "comparison",
                                            "asset_id": "a", "spec_title": "THE DATA PROBLEM"}),
                           dict(scene("s02", 6000, 12000, "gap"),
                                narration_text="The fix is a small amount of real robot data.")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        check = next(item for item in report.checks if item.name == "title_matches_narration")
        assert check.ok, check.detail

    def test_headline_agreement_is_reported_when_the_render_supplies_it(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 12000, "allowed_scene_count": [2, 10],
                "line_agreement": {"checked": 2, "mismatches": ["s02"]},
                "scenes": [scene("s01", 0, 6000), scene("s02", 6000, 12000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        check = next(item for item in report.checks if item.name == "headline_matches_active_line")
        assert not check.ok and check.severity == "warn"
        assert report.ok

    def test_headline_agreement_is_absent_without_evidence(self) -> None:
        plan = {"channel": "nexus-node", "narration_ms": 12000, "allowed_scene_count": [2, 10],
                "scenes": [scene("s01", 0, 6000), scene("s02", 6000, 12000, "gap")]}
        report = evaluate(channel="nexus-node", scene_plan=plan)
        names = {check.name for check in report.checks}
        assert "headline_matches_active_line" not in names


# ------------------------------------------------------------------ M4
class TestM4LegacyFramingMetadata:
    def test_the_visual_element_is_only_written_when_the_dispatcher_runs(self) -> None:
        import inspect

        from factory.media import english_renderer as renderer

        source = inspect.getsource(renderer.render_english)
        marker = 'framing["elements"]["visual"] = {'
        assert marker in source
        preceding = [row.strip() for row in source[:source.index(marker)].splitlines()
                     if row.strip() and not row.strip().startswith("#")]
        assert preceding[-1].startswith("if dispatcher is not None"), preceding[-1]

    def test_legacy_frames_report_no_visual_geometry(self) -> None:
        from factory.media.english_renderer import measure_geometry
        from PIL import Image

        frame = Image.new("RGB", (1080, 1920), "#000000")
        sample = measure_geometry({"headline": (100, 200, 900, 300)}, frame)
        assert sample["visual"] is None
        assert sample["visual_overflow"] == 0
        assert sample["visual_painted"] is False
