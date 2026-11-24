"""P0-1: `visual_policy` is a validated type, not a dict that silently mis-parses."""

from __future__ import annotations

import warnings

import pytest

from factory.config import (
    DEFAULT_VISUAL_MAX_MS,
    DEFAULT_VISUAL_MIN_MS,
    ChannelSpec,
    VisualPolicy,
    load_channel_specs,
    parse_visual_policy,
)


class TestParsing:
    def test_the_nexus_policy_parses_without_warnings(self) -> None:
        policy = load_channel_specs()["nexus-node"].visual_policy
        assert policy.scene_planning is True
        assert policy.categories == ("diagram", "dataviz", "motion_graphics")
        assert (policy.min_scene_ms, policy.max_scene_ms) == (2000, 8000)
        assert policy.warnings == ()

    def test_a_channel_without_a_policy_gets_an_inert_one(self) -> None:
        for slug in ("academic-biohacker", "natkhat-toons"):
            policy = load_channel_specs()[slug].visual_policy
            assert policy.scene_planning is False
            assert policy.categories == ()

    def test_a_single_string_category_is_one_category_not_characters(self) -> None:
        """v1.0: set("diagram") == {'d','i','a','g','r','m'} and the planner picked kinetic_type."""

        policy = parse_visual_policy({"categories": "diagram"})
        assert policy.categories == ("diagram",)
        assert "d" not in policy.categories

    def test_unknown_categories_are_dropped_with_a_warning(self) -> None:
        policy = parse_visual_policy({"categories": ["diagram", "hologram"]})
        assert policy.categories == ("diagram",)
        assert any("hologram" in message for message in policy.warnings)

    def test_a_non_numeric_duration_falls_back(self) -> None:
        policy = parse_visual_policy({"min_scene_ms": "two thousand"})
        assert policy.min_scene_ms == DEFAULT_VISUAL_MIN_MS
        assert any("min_scene_ms" in message for message in policy.warnings)

    def test_an_inverted_band_falls_back_to_the_defaults(self) -> None:
        policy = parse_visual_policy({"min_scene_ms": 9000, "max_scene_ms": 3000})
        assert (policy.min_scene_ms, policy.max_scene_ms) == (DEFAULT_VISUAL_MIN_MS,
                                                             DEFAULT_VISUAL_MAX_MS)
        assert any("defaults" in message for message in policy.warnings)

    def test_a_non_positive_duration_falls_back(self) -> None:
        assert parse_visual_policy({"max_scene_ms": 0}).max_scene_ms == DEFAULT_VISUAL_MAX_MS
        assert parse_visual_policy({"max_scene_ms": -5}).max_scene_ms == DEFAULT_VISUAL_MAX_MS

    def test_an_unknown_palette_falls_back(self) -> None:
        policy = parse_visual_policy({"palette": "neon"})
        assert policy.palette == "default"
        assert any("palette" in message for message in policy.warnings)

    def test_a_non_boolean_flag_falls_back(self) -> None:
        policy = parse_visual_policy({"scene_planning": "yes", "chart_values": "no"})
        assert policy.scene_planning is False and policy.chart_values is True
        assert len(policy.warnings) == 2

    def test_a_policy_that_is_not_an_object_is_ignored_with_a_warning(self) -> None:
        policy = parse_visual_policy(["diagram"])
        assert policy.scene_planning is False
        assert policy.warnings and "expected an object" in policy.warnings[0]

    def test_parsing_is_idempotent(self) -> None:
        once = parse_visual_policy({"scene_planning": True, "categories": ["diagram"]})
        assert parse_visual_policy(once) is once


class TestCompatibility:
    def test_the_mapping_view_round_trips(self) -> None:
        policy = parse_visual_policy({"scene_planning": True, "categories": ["diagram"],
                                      "min_scene_ms": 2500})
        data = policy.as_dict()
        assert data["categories"] == ["diagram"]
        assert data["min_scene_ms"] == 2500
        assert parse_visual_policy(data).as_dict() == data

    def test_get_still_works_for_every_v1_0_caller(self) -> None:
        policy = parse_visual_policy({"scene_planning": True, "min_scene_ms": 2500})
        assert policy.get("scene_planning") is True
        assert policy.get("min_scene_ms") == 2500
        assert policy.get("cache_root") is None
        assert policy.get("missing", "fallback") == "fallback"

    def test_mapping_protocol(self) -> None:
        policy = parse_visual_policy({"scene_planning": True})
        assert dict(policy)["scene_planning"] is True
        assert "categories" in policy
        assert len(policy) == len(policy.as_dict())

    def test_a_plain_dict_still_works_where_a_policy_is_expected(self) -> None:
        """Existing tests and callers pass dicts; only the loader produces the typed object."""

        policy = {"categories": ["diagram"]}
        assert set(policy.get("categories")) == {"diagram"}

    def test_a_channel_spec_defaults_to_an_inert_policy(self) -> None:
        spec = ChannelSpec(slug="x", display_name="X", handle="@x", channel_id="c", language="en",
                           format="shorts", style="s", voice="v", rate="+0%", pitch="+0Hz",
                           palette="nexus", niche="n")
        assert isinstance(spec.visual_policy, VisualPolicy)
        assert spec.visual_policy.scene_planning is False
