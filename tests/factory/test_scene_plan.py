"""Scene planning: semantic boundaries, derived counts, honest deviations.

The Shorts renderer used to render exactly one visual per script line, which is why a 38-second
video was seven cards. These tests pin the properties that replace it: scenes tile the narration,
the count lands inside a window derived from the narration itself, punctuation is read from the line
text (TTS word timings are bare tokens), and any scene outside the pacing band carries a reason.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from factory.content.models import Script, ScriptLine, WordTiming
from factory.content.scene_plan import (
    MAX_SCENE_MS,
    MIN_SCENE_MS,
    allowed_scene_count,
    plan_scenes,
    plans_per_line,
    scene_plan_problems,
)


def make_line(text: str, start: float, end: float, *, headline: str = "") -> ScriptLine:
    """A line whose word timings are evenly spread and, like real TTS, carry no punctuation."""

    tokens = [token.strip(".,;:!?") for token in text.split()]
    span = (end - start) / max(1, len(tokens))
    words = [WordTiming(text=token, start=start + i * span, end=start + (i + 1) * span - 0.02)
             for i, token in enumerate(tokens)]
    return ScriptLine(text=text, headline=headline, start=start, end=end, words=words)


def make_script(line_specs: list[tuple[str, float, float]]) -> Script:
    lines = [make_line(text, start, end) for text, start, end in line_specs]
    return Script(channel="nexus-node", language="en", format="shorts", topic="t",
                  title="T", hook=lines[0].text, lines=lines, description="")


def make_spec(categories: tuple[str, ...] = ("diagram", "dataviz", "motion_graphics", "kinetic_type")):
    return SimpleNamespace(slug="nexus-node", visual_policy={"categories": list(categories)})


class TestDerivedSceneCount:
    def test_window_comes_from_the_narration_length(self) -> None:
        # 36.8 s of narration: at most one scene per 8 s, at least one per 2 s
        assert allowed_scene_count(36_800) == (5, 18)
        assert allowed_scene_count(9_000) == (2, 4)
        assert allowed_scene_count(5_000) == (1, 2)

    def test_a_scene_cannot_be_shorter_than_the_floor_without_a_reason(self) -> None:
        with pytest.raises(ValueError):
            allowed_scene_count(0)
        with pytest.raises(ValueError):
            allowed_scene_count(4_000, min_scene_ms=8_000, max_scene_ms=2_000)

    def test_the_plan_lands_inside_the_derived_window(self) -> None:
        script = make_script([
            ("Robots used to need demonstrations. Now they learn from video.", 0.3, 5.3),
            ("A robot arm needs thousands of examples to learn one grasp.", 5.6, 11.9),
            ("Video pretraining lets a model watch ordinary footage first.", 12.1, 18.3),
            ("The gap is action: a video shows what happened, not the forces.", 18.5, 24.5),
            ("The fix is a little real data to anchor the model.", 24.7, 29.8),
            ("Follow for more on AI in the physical world.", 30.0, 32.6),
        ])
        plan = plan_scenes(make_spec(), script)
        low, high = plan.allowed_scene_count
        assert low <= len(plan.scenes) <= high
        assert scene_plan_problems(plan) == []


class TestSemanticBoundaries:
    def test_scenes_tile_the_narration_exactly(self) -> None:
        script = make_script([
            ("One idea ends here. Another begins right after it.", 0.3, 6.0),
            ("A second line continues the explanation for a while.", 6.2, 12.2),
        ])
        plan = plan_scenes(make_spec(), script)
        span = sum(scene.duration_ms for scene in plan.scenes)
        assert span == plan.narration_ms
        for previous, following in zip(plan.scenes, plan.scenes[1:]):
            assert following.start_ms == previous.end_ms

    def test_a_line_with_two_sentences_becomes_two_scenes(self) -> None:
        script = make_script([
            ("Robots used to need demonstrations. Now they learn from video.", 0.3, 8.0),
            ("Second line for padding so the count stays legal.", 8.2, 14.0),
        ])
        plan = plan_scenes(make_spec(), script)
        assert plan.scenes[0].end_ms < plan.narration_ms
        assert len(plan.scenes) > 2

    def test_punctuation_is_read_from_the_line_text_not_the_word_timings(self) -> None:
        # TTS returns bare tokens: "demonstrations." arrives as "demonstrations"
        assert all("." not in word.text for word in make_line("A. B. C.", 0, 3).words)
        script = make_script([("One ends here. Another starts now.", 0.3, 8.0),
                              ("Padding line to keep the window legal.", 8.2, 14.0)])
        plan = plan_scenes(make_spec(), script)
        first = plan.scenes[0].derived_from["word_range"]
        assert first[1] < len(make_line("One ends here. Another starts now.", 0.3, 8.0).words)

    def test_not_every_line_produces_exactly_one_scene(self) -> None:
        script = make_script([
            ("Video pretraining lets a model watch ordinary footage. Then it infers motion.", 0.3, 7.0),
            ("The gap is action: a video shows what happened, not the forces applied.", 7.2, 13.8),
            ("A short closing line that finishes the episode cleanly.", 14.0, 18.0),
        ])
        plan = plan_scenes(make_spec(), script)
        assert max(plans_per_line(plan).values()) >= 2 or len(plan.scenes) >= 4

    def test_mid_line_scenes_keep_the_line_headline_as_their_concept(self) -> None:
        line = make_line("The gap is action: a video shows what happened, not the forces.",
                         0.3, 7.0, headline="Seeing is not doing")
        script = Script(channel="nexus-node", language="en", format="shorts", topic="t", title="T",
                        hook=line.text, lines=[line], description="")
        plan = plan_scenes(make_spec(), script, min_scene_ms=500, max_scene_ms=3_000)
        mid_line = [scene for scene in plan.scenes if scene.derived_from["word_range"][0] > 0]
        assert mid_line, "expected at least one scene that starts mid-line"
        assert all(scene.main_concept == "Seeing is not doing" for scene in mid_line)


class TestPacingBand:
    def test_a_long_single_idea_is_split_at_its_largest_pause(self) -> None:
        script = make_script([("A very long continuous sentence that keeps going well past the "
                               "ceiling of eight seconds without any punctuation at all inside it",
                               0.3, 12.0)])
        plan = plan_scenes(make_spec(), script)
        assert all(scene.duration_ms <= MAX_SCENE_MS for scene in plan.scenes)
        assert any(decision["action"] == "split" for decision in plan.decisions)

    def test_a_short_line_is_merged_and_the_merge_is_recorded(self) -> None:
        script = make_script([
            ("A first line that runs long enough to stand alone as a scene.", 0.3, 6.0),
            ("Tiny.", 6.2, 6.9),
            ("A closing line long enough to stay on its own as well.", 7.1, 12.0),
        ])
        plan = plan_scenes(make_spec(), script)
        assert all(scene.duration_ms >= MIN_SCENE_MS for scene in plan.scenes)
        assert any(decision["action"] == "merge" for decision in plan.decisions)

    def test_an_unavoidable_deviation_carries_a_reason(self) -> None:
        script = make_script([("One unbroken sentence with no punctuation that runs past the "
                               "ceiling for a long time", 0.3, 12.0)])
        plan = plan_scenes(make_spec(), script, min_scene_ms=500, max_scene_ms=3_000)
        for scene in plan.scenes:
            if scene.duration_ms > 3_000 or scene.duration_ms < 500:
                assert scene.duration_deviation, f"{scene.scene_id} left the band silently"
                assert scene.duration_deviation["reason"]

    def test_short_narration_records_an_exception_instead_of_faking_scenes(self) -> None:
        script = make_script([("Too short.", 0.3, 1.2)])
        plan = plan_scenes(make_spec(), script)
        assert len(plan.scenes) == 1
        assert plan.scenes[0].duration_deviation is not None


class TestLookupAndProblems:
    def test_lookup_returns_the_scene_covering_the_time(self) -> None:
        script = make_script([("First idea here. Second idea follows.", 0.3, 8.0),
                              ("Padding to keep the window legal.", 8.2, 14.0)])
        plan = plan_scenes(make_spec(), script)
        assert plan.at(plan.scenes[0].start_ms / 1000) is plan.scenes[0]
        assert plan.at(999.0) is plan.scenes[-1]

    def test_overlap_and_unexplained_deviations_are_reported(self) -> None:
        script = make_script([("First line of the episode.", 0.3, 6.0),
                              ("Second line of the episode.", 6.2, 12.0)])
        plan = plan_scenes(make_spec(), script)
        plan.scenes[1].start_ms = plan.scenes[0].start_ms + 100  # deliberate damage
        problems = scene_plan_problems(plan)
        assert any("overlap" in problem or "span" in problem for problem in problems)

    def test_planning_is_deterministic(self) -> None:
        def build():
            return plan_scenes(make_spec(), make_script([
                ("One. Two. Three lines of narration that keep going.", 0.3, 9.0),
                ("Another line to keep the window legal.", 9.2, 14.0)]))

        first, second = build(), build()
        assert [scene.to_dict() for scene in first.scenes] == [scene.to_dict() for scene in second.scenes]
        assert first.decisions == second.decisions


class TestChannelPolicy:
    def test_a_channel_without_imagery_never_plans_a_photo(self) -> None:
        script = make_script([("A robot arm and a factory floor full of machines.", 0.3, 6.0),
                              ("Padding line so the window stays legal.", 6.2, 12.0)])
        plan = plan_scenes(make_spec(("diagram", "kinetic_type")), script)
        assert all(scene.visual_category in {"diagram", "kinetic_type"} for scene in plan.scenes)

    def test_a_channel_that_allows_photos_can_plan_one(self) -> None:
        script = make_script([("A robot arm on a factory floor picks up a part.", 0.3, 6.0),
                              ("Padding line so the window stays legal.", 6.2, 12.0)])
        plan = plan_scenes(make_spec(("photo", "diagram")), script)
        assert any(scene.visual_category == "photo" for scene in plan.scenes)
