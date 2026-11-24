"""Regression tests for the independent v1.1 PR audit (defects A1-A9).

Each test is named after the defect it pins, and each one failed before the correction. They live in
their own file so the audit trail is legible: a reviewer can see exactly what was wrong, what the
contract now is, and where the evidence is.
"""

from __future__ import annotations

import inspect

import pytest

from factory.config import load_channel_specs, parse_visual_policy
from factory.content.figures import extract
from factory.media.assets import generated
from factory.media.assets.generated import chart_kind, share_framed, spec_for
from factory.qa.creative import evaluate

COLORS = load_channel_specs()["nexus-node"].colors


def figures(text: str) -> tuple[tuple[str, float | None, str], ...]:
    return tuple((figure.phrase, figure.value, figure.unit) for figure in extract(text))


def planned(text: str, *, category: str = "dataviz", concept: str = "COST", **kwargs):
    return spec_for(concept=concept, narration=text, objective="", colors=COLORS,
                    figures=figures(text), category=category, **kwargs)


def scene(scene_id: str, start: int, end: int, *, resolution: dict, **overrides) -> dict:
    base = {
        "scene_id": scene_id, "start_ms": start, "end_ms": end, "duration_ms": end - start,
        "narration_text": "Robots learn from video footage.", "main_concept": "T",
        "on_screen_text": "T", "visual_category": "diagram", "coverage_category": "diagram",
        "asset_id": f"gen-{scene_id}", "asset_source": "generated", "license": "generated-local",
        "attribution_text": None, "resolution": resolution,
    }
    base.update(overrides)
    return base


def report_for(scenes: list[dict], **kwargs):
    plan = {"channel": "nexus-node", "narration_ms": scenes[-1]["end_ms"],
            "allowed_scene_count": [1, 20], "scenes": scenes}
    return evaluate(channel="nexus-node", scene_plan=plan, **kwargs)


def check(report, name: str):
    return next(item for item in report.checks if item.name == name)


# ---------------------------------------------------------------- A1: a change is not a share
class TestA1RelativeChangeIsNotAShare:
    """"40 percent cheaper" drawn as a filled track asserted a whole the sentence never states."""

    @pytest.mark.parametrize("text", [
        "Video is 40 percent cheaper.",
        "Video is 40 percent faster than demonstrations.",
        "The cost drops 40 percent.",
        "Yield rose 40 percent.",
        "It is 40 percent slower.",
        "Training is 40 percent more efficient.",
    ])
    def test_it_is_not_charted(self, text: str) -> None:
        plate = planned(text)
        assert plate.variant not in {"bars", "ratio"}
        assert plate.note

    def test_the_reason_is_recorded_rather_than_silent(self) -> None:
        plate = planned("Video is 40 percent cheaper.")
        assert "share of a change" in plate.note
        assert "40 percent" in plate.note

    @pytest.mark.parametrize("text", [
        "Video is 40 percent of the training cost.",
        "Demos account for 40 percent of the budget.",
        "Video makes up 60 percent of the library.",
        "40 percent of the data is video.",
    ])
    def test_a_real_share_is_still_drawn(self, text: str) -> None:
        assert share_framed(text) is True
        assert planned(text).variant == "ratio"

    def test_the_decision_function_says_no(self) -> None:
        text = "Video is 40 percent cheaper."
        assert chart_kind(figures(text), narration=text, category="dataviz") is None

    def test_a_forced_ratio_on_a_change_is_downgraded(self) -> None:
        """A caller that asks for a ratio still cannot draw one the sentence does not support."""

        text = "Video is 40 percent cheaper."
        plate = spec_for(concept="COST", narration=text, objective="", colors=COLORS,
                         figures=figures(text), variant="ratio")
        assert plate.variant == "statement"
        assert "share of a change" in plate.note

    def test_the_footer_still_describes_a_share_for_a_share(self) -> None:
        body = inspect.getsource(generated._draw_ratio)
        assert "THE SHARE THE SENTENCE STATES" in body
        # ... and it is only reachable when the sentence frames one.
        assert planned("Video is 40 percent of the cost.").variant == "ratio"


# ---------------------------------------------------------------- A7: a truthful note
class TestA7DisabledChartPolicyIsSaidOutLoud:
    def test_the_note_names_the_policy_not_a_unit_problem(self) -> None:
        text = "Demos are 80 percent of the cost."
        plate = planned(text, chart_values=False)
        assert plate.variant not in {"bars", "ratio"}
        assert "chart_values is disabled" in plate.note
        assert "cannot share one scale" not in plate.note


# ---------------------------------------------------------------- A3: the plan is the contract
class TestA3ChartsNeverOverrideAPlannedCategory:
    @pytest.mark.parametrize("category", ["diagram", "motion_graphics", "kinetic_type", "photo",
                                          "illustration", "software_demo"])
    def test_the_planned_category_wins(self, category: str) -> None:
        plate = planned("Demos are 80 percent of the cost.", category=category)
        assert plate.variant not in {"bars", "ratio"}
        assert category in plate.note

    def test_a_dataviz_plan_still_gets_its_chart(self) -> None:
        assert planned("Video is 40 percent of the cost.").variant == "ratio"
        assert planned("Demos are 80 percent of the cost and video is 20 percent.").variant == "bars"

    def test_an_unplanned_scene_may_still_chart(self) -> None:
        plate = spec_for(concept="COST", narration="Video is 40 percent of the cost.", objective="",
                         colors=COLORS, figures=figures("Video is 40 percent of the cost."))
        assert plate.variant == "ratio"


# ---------------------------------------------------------------- A2: the sentence is the authority
class TestA2TheClaimComesFromTheSentence:
    """A headline that says "video versus model" must not make a plate claim a contest."""

    def test_a_concept_only_comparator_does_not_create_a_comparison(self) -> None:
        plate = spec_for(concept="Video versus model", narration="Video is the new manual.",
                         objective="", colors=COLORS)
        assert plate.variant != "comparison", plate.variant

    def test_a_sentence_comparator_still_does(self) -> None:
        plate = spec_for(concept="", narration="Demonstrations cost more than video footage.",
                         objective="", colors=COLORS)
        assert plate.variant == "comparison"
        assert plate.entities == ("demonstration", "video")

    def test_the_pair_is_never_derived_from_the_headline(self) -> None:
        plate = spec_for(concept="Demos versus video", narration="Video is the new manual.",
                         objective="", colors=COLORS)
        assert plate.variant != "comparison"


# ---------------------------------------------------------------- A4: no silent config change
class TestA4UnknownPolicyKeysAreReported:
    @pytest.mark.parametrize("typo", ["chart_value", "min_scenes_ms", "max_scene_ms_", "pallete"])
    def test_a_typo_is_a_recorded_warning(self, typo: str) -> None:
        policy = parse_visual_policy({"scene_planning": True, typo: 1})
        assert any(typo in warning for warning in policy.warnings), policy.warnings

    def test_a_clean_policy_has_no_warnings(self) -> None:
        policy = parse_visual_policy({"scene_planning": True, "categories": ["diagram"],
                                      "min_scene_ms": 2500, "max_scene_ms": 8000,
                                      "palette": "default", "chart_values": True})
        assert policy.warnings == ()

    def test_the_nexus_policy_is_still_clean(self) -> None:
        from factory.config import load_channel_specs as load

        assert load()["nexus-node"].visual_policy.warnings == ()


# ---------------------------------------------------------------- A5: unmeasured is not a pass
class TestA5FigureCheckCannotPassUnmeasured:
    def test_a_plate_without_recorded_text_is_reported_as_unverified(self) -> None:
        resolution = {"scene_id": "s01", "category": "diagram", "kind": "generated",
                      "asset_id": "gen-1", "variant": "statement", "spec_title": "T",
                      "entities": ["video"], "license": "generated-local", "attribution": None,
                      "plate_fingerprint": "0123456789abcdef"}
        result = check(report_for([scene("s01", 0, 6000, resolution=resolution)]),
                       "figure_is_stated")
        assert not result.ok
        assert "did not run" in result.detail
        assert "s01" in result.detail

    def test_an_empty_visible_text_list_is_a_measured_plate(self) -> None:
        """A photo plate legitimately shows no text; only a missing record is unmeasured."""

        resolution = {"scene_id": "s01", "category": "photo", "kind": "library",
                      "asset_id": "local-1", "variant": None, "spec_title": None,
                      "entities": [], "license": "owner-supplied", "attribution": None,
                      "visible_text": [], "plate_fingerprint": "0123456789abcdef"}
        result = check(report_for([scene("s01", 0, 6000, resolution=resolution,
                                         license="owner-supplied", asset_source="local",
                                         visual_category="photo", coverage_category="photo")],
                                  ),
                       "figure_is_stated")
        assert result.ok, result.detail

    def test_a_recorded_number_the_narration_lacks_still_fails(self) -> None:
        resolution = {"scene_id": "s01", "category": "dataviz", "kind": "generated",
                      "asset_id": "gen-1", "variant": "ratio", "spec_title": "T",
                      "entities": ["video"], "license": "generated-local", "attribution": None,
                      "visible_text": ["40 percent"], "plate_fingerprint": "0123456789abcdef"}
        result = check(report_for([scene("s01", 0, 6000, resolution=resolution,
                                         visual_category="dataviz", coverage_category="dataviz")]),
                       "figure_is_stated")
        assert not result.ok
        assert "s01:40" in result.detail


# ---------------------------------------------------------------- A6: malformed is unmeasured
class TestA6MalformedFingerprintsAreUnmeasured:
    @pytest.mark.parametrize("fingerprint", ["zz", "not-a-hash", "0123", "0123456789ABCDEF", ""])
    def test_it_is_not_counted_as_a_distinct_picture(self, fingerprint: str) -> None:
        scenes = []
        for index in range(3):
            resolution = {"scene_id": f"s{index:02d}", "category": "diagram", "kind": "generated",
                          "asset_id": f"gen-{index}", "variant": "panels", "spec_title": "T",
                          "entities": ["video"], "license": "generated-local", "attribution": None,
                          "visible_text": ["T"], "plate_fingerprint": fingerprint}
            scenes.append(scene(f"s{index:02d}", index * 5000, (index + 1) * 5000,
                                resolution=resolution, variant="panels"))
        result = check(report_for(scenes), "visual_diversity_pixels")
        assert not result.ok
        assert result.severity == "warn"
        assert "unmeasured" in result.detail

    def test_a_well_formed_fingerprint_is_measured(self) -> None:
        scenes = []
        for index, value in enumerate(["0123456789abcdef", "fedcba9876543210"]):
            resolution = {"scene_id": f"s{index:02d}", "category": "diagram", "kind": "generated",
                          "asset_id": f"gen-{index}", "variant": "panels", "spec_title": "T",
                          "entities": ["video"], "license": "generated-local", "attribution": None,
                          "visible_text": ["T"], "plate_fingerprint": value}
            scenes.append(scene(f"s{index:02d}", index * 5000, (index + 1) * 5000,
                                resolution=resolution, variant="panels"))
        result = check(report_for(scenes), "visual_diversity_pixels")
        assert result.ok, result.detail
        assert "2 distinct pictures over 2 plates" in result.detail


# ---------------------------------------------------------------- A8: one authority
class TestA8ThereIsOneChartDecision:
    def test_figures_no_longer_carries_a_second_chart_decision(self) -> None:
        from factory.content import figures as module

        assert not hasattr(module, "chart_kind")
        assert not hasattr(module, "chartable")
        assert hasattr(module, "numeric_figures")

    def test_the_asset_layer_owns_it(self) -> None:
        assert callable(generated.chart_kind)
        assert "This is the only place that decides whether a chart is drawn" in \
            inspect.getsource(generated.chart_kind)

    def test_a_mixed_unit_sentence_is_refused_by_the_single_decision(self) -> None:
        text = "Costs drop 40 percent of the budget after 3 hours."
        assert chart_kind(figures(text), narration=text, category="dataviz") is None
