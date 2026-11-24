"""P0-6 and the P1-1 QC checks: diversity is measured in pixels, charts only show stated numbers."""

from __future__ import annotations

import pytest

from factory.media.english_renderer import (
    compared_fingerprint,
    fingerprint_distance,
    plate_fingerprint,
)
from factory.qa.creative import _hamming, evaluate


def scene(scene_id: str, start: int, end: int, *, fingerprint: str | None,
          text: str = "Robots learn from video footage.",
          title: str = "ROBOT VIDEO", visible: list[str] | None = None,
          category: str = "diagram", coverage: str = "diagram",
          variant: str = "pipeline") -> dict:
    return {
        "scene_id": scene_id, "start_ms": start, "end_ms": end, "duration_ms": end - start,
        "narration_text": text, "main_concept": title, "on_screen_text": title,
        "visual_category": category, "coverage_category": coverage,
        "asset_id": f"gen-{scene_id}", "asset_source": "generated", "license": "generated-local",
        "attribution_text": None,
        "variant": variant,
        "resolution": {"scene_id": scene_id, "category": category, "variant": variant,
                       "asset_id": f"gen-{scene_id}",
                       "entities": ["robot"], "license": "generated-local", "attribution": None,
                       "visible_text": visible if visible is not None else [title],
                       "spec_title": title, "plate_fingerprint": fingerprint},
    }


def plan(scenes: list[dict]) -> dict:
    return {"channel": "nexus-node", "narration_ms": scenes[-1]["end_ms"],
            "allowed_scene_count": [1, 20], "scenes": scenes}


def report_for(scenes: list[dict]):
    return evaluate(channel="nexus-node", scene_plan=plan(scenes))


def varied(scenes: list[dict]) -> list[dict]:
    """Two compositions, so a fixture that asserts "the video passes" is not failing on variety."""

    for index, item in enumerate(scenes):
        variant = "pipeline" if index % 2 == 0 else "panels"
        item["variant"] = variant
        item["resolution"]["variant"] = variant
    return scenes


class TestFingerprint:
    def test_identical_pictures_produce_the_same_fingerprint(self) -> None:
        from PIL import Image

        image = Image.new("RGB", (232, 232), "#10243A")
        assert plate_fingerprint(image) == plate_fingerprint(image.copy())
        assert fingerprint_distance(plate_fingerprint(image), plate_fingerprint(image.copy())) == 0

    def test_different_pictures_produce_a_distance(self) -> None:
        from PIL import Image

        dark = Image.new("RGB", (232, 232), "#050B16")
        light = Image.new("RGB", (232, 232), "#F4F1EA")
        assert fingerprint_distance(plate_fingerprint(dark), plate_fingerprint(light)) > 6

    def test_the_fingerprint_is_a_stable_hex_string(self) -> None:
        from PIL import Image

        value = plate_fingerprint(Image.new("RGB", (32, 32), "#4FD1E8"))
        assert len(value) == 16 and int(value, 16) == int(value, 16)

    def test_missing_inputs_are_reported_not_crashed(self) -> None:
        assert compared_fingerprint(None) is None
        assert _hamming("", "ff") == 64


class TestDiversity:
    def test_nine_identical_plates_fail(self) -> None:
        scenes = [scene(f"s{index:02d}", (index - 1) * 4000, index * 4000,
                        fingerprint="0" * 16) for index in range(1, 10)]
        check = next(item for item in report_for(scenes).checks
                     if item.name == "visual_diversity_pixels")
        assert not check.ok
        assert "1 distinct pictures over 9 plates" in check.detail

    def test_nine_distinct_plates_pass(self) -> None:
        scenes = [scene(f"s{index:02d}", (index - 1) * 4000, index * 4000,
                        fingerprint=f"{index * 0x1111111111111:016x}"[:16])
                  for index in range(1, 10)]
        check = next(item for item in report_for(scenes).checks
                     if item.name == "visual_diversity_pixels")
        assert check.ok, check.detail

    def test_five_of_nine_distinct_plates_pass_the_half_rule(self) -> None:
        fingerprints = ["0" * 16] * 5 + [f"{value:016x}" for value in (0xF0F0, 0x0F0F, 0xAAAA,
                                                                       0x5555)]
        scenes = varied([scene(f"s{index:02d}", (index - 1) * 4000, index * 4000,
                               fingerprint=fingerprint)
                         for index, fingerprint in enumerate(fingerprints, start=1)])
        check = next(item for item in report_for(scenes).checks
                     if item.name == "visual_diversity_pixels")
        assert check.ok, check.detail

    def test_missing_fingerprints_warn_instead_of_failing(self) -> None:
        scenes = varied([scene("s01", 0, 6000, fingerprint=None),
                         scene("s02", 6000, 12000, fingerprint=None)])
        report = report_for(scenes)
        check = next(item for item in report.checks if item.name == "visual_diversity_pixels")
        assert not check.ok and check.severity == "warn"
        assert report.ok, "an unmeasured render must not fail the video"


class TestStatedFigures:
    def test_a_number_the_plate_shows_but_the_narration_does_not_fails(self) -> None:
        scenes = [scene("s01", 0, 5000, fingerprint="a" * 16, text="Video is much cheaper.",
                        title="40% CHEAPER", visible=["40 percent cheaper"])]
        report = report_for(scenes)
        check = next(item for item in report.checks if item.name == "figure_is_stated")
        assert not check.ok and check.severity == "error"
        assert "s01:40" in check.detail

    def test_a_number_the_narration_states_passes(self) -> None:
        scenes = varied([scene("s01", 0, 5000, fingerprint="a" * 16,
                              text="Video pretraining is 40 percent cheaper.",
                              title="CHEAPER", visible=["video", "40 percent"])])
        assert next(item for item in report_for(scenes).checks
                    if item.name == "figure_is_stated").ok

    def test_a_padded_number_still_matches(self) -> None:
        scenes = varied([scene("s01", 0, 5000, fingerprint="a" * 16,
                              text="It needs 1,200 examples.", title="EXAMPLES",
                              visible=["1,200 examples"])])
        assert next(item for item in report_for(scenes).checks
                    if item.name == "figure_is_stated").ok

    def test_a_spec_title_with_a_digit_is_checked_too(self) -> None:
        scenes = [scene("s01", 0, 5000, fingerprint="a" * 16, text="Two years later.",
                        title="STEP 2", visible=["step"])]
        assert next(item for item in report_for(scenes).checks
                    if item.name == "figure_is_stated").ok


class TestDatavizDelivery:
    def test_a_dataviz_scene_rendered_as_a_diagram_warns(self) -> None:
        scenes = [scene("s01", 0, 5000, fingerprint="a" * 16, category="dataviz",
                        coverage="diagram")]
        check = next(item for item in report_for(scenes).checks
                     if item.name == "dataviz_delivered")
        assert not check.ok and check.severity == "warn"
        assert "s01" in check.detail

    def test_a_dataviz_scene_rendered_as_a_chart_passes(self) -> None:
        scenes = [scene("s01", 0, 5000, fingerprint="a" * 16, category="dataviz",
                        coverage="dataviz")]
        assert next(item for item in report_for(scenes).checks
                    if item.name == "dataviz_delivered").ok
