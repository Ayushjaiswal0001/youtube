"""P0-2 and P0-3: no invented subject, and a composition must have the cue it claims."""

from __future__ import annotations

import pytest

from factory.config import load_channel_specs
from factory.content.figures import extract
from factory.media.assets.generated import (
    _DRAWERS,
    LEXICON,
    choose_variant,
    comparison_pair,
    entities_in,
    has_sequence_cue,
    render_diagram,
    spec_for,
)

COLORS = load_channel_specs()["nexus-node"].colors


def spec(narration: str, *, concept: str = "", category: str = "diagram",
         on_screen: str | None = None, variant: str | None = None):
    figures = tuple((figure.phrase, figure.value, figure.unit) for figure in extract(narration))
    return spec_for(concept=concept or narration, narration=narration, objective="", colors=COLORS,
                    on_screen=on_screen, figures=figures, category=category, variant=variant)


class TestNoInventedSubject:
    @pytest.mark.parametrize("narration", ["That is the whole point.", "It just works."])
    def test_an_entity_less_sentence_invents_nothing(self, narration: str) -> None:
        planned = spec(narration)
        assert planned.entities == (), "an entity was invented for a sentence that names nothing"
        assert planned.variant == "statement"
        assert planned.figures == ()
        assert planned.note and "no subject" in planned.note
        render_diagram(planned)

    def test_no_lexicon_label_appears_on_an_entity_less_plate(self) -> None:
        planned = spec("That is the whole point.", on_screen="THE WHOLE POINT")
        visible = {planned.title, *[LEXICON[entity][0] for entity in planned.entities]}
        assert not any(label in visible for label in ("data", "study", "model"))
        assert planned.title == "THE WHOLE POINT"

    def test_the_title_is_the_scene_text_not_an_invented_noun(self) -> None:
        planned = spec("It just works.", on_screen="JUST WORKS")
        assert planned.title == "JUST WORKS"


class TestCueBasedComposition:
    @pytest.mark.parametrize("text", [
        "Video pretraining lets a model watch ordinary footage first",
        "Anchor the model, then scale with cheap footage",
        "Step one: collect video, step two: train the model",
        "Finally the model learns the action",
        "After the demonstrations, the model adapts",
    ])
    def test_a_stated_order_is_drawn_as_a_pipeline(self, text: str) -> None:
        assert has_sequence_cue(text) is True
        assert spec(text).variant in {"pipeline", "timeline", "components", "layers", "gap"}

    def test_the_audited_future_sentence_is_not_a_timeline(self) -> None:
        """"The future of robot training..." mentions time and states no chronology."""

        text = ("The future of robot training looks less like programming and more like a very large "
                "video library")
        planned = spec(text, on_screen="VIDEO IS THE NEW MANUAL")
        assert has_sequence_cue(text) is False
        assert planned.variant != "timeline", planned.variant
        # It does compare ("less like ... more like"), so the comparison rule applies instead.
        assert planned.variant == "comparison"

    def test_two_entities_without_a_cue_become_panels(self) -> None:
        planned = spec("Robots used to need demonstrations Now they are learning from videos anyone "
                       "can record", on_screen="WATCH AND LEARN")
        assert planned.variant == "panels"
        assert len(planned.entities) >= 2

    def test_one_entity_without_a_cue_becomes_a_statement(self) -> None:
        planned = spec("Video is useful.")
        assert planned.variant in {"statement", "panels"}

    def test_a_timeline_needs_both_a_time_word_and_a_cue(self) -> None:
        assert choose_variant(["time", "video"], "In the next year the model changes") == "panels"
        assert choose_variant(["time", "video"],
                              "First the model trains, then a year later it ships") == "timeline"

    def test_a_comparison_needs_comparative_language(self) -> None:
        assert choose_variant(["video", "model"], "video and model") == "panels"
        assert choose_variant(["video", "model"], "video is cheaper than model") == "comparison"

    def test_a_comparison_draws_the_pair_it_contrasts(self) -> None:
        """"less like programming and more like a video library" is ROBOT vs VIDEO, not TIME vs ROBOT."""

        text = ("The future of robot training looks less like programming and more like a very large "
                "video library")
        planned = spec(text, on_screen="VIDEO IS THE NEW MANUAL")
        assert planned.variant == "comparison"
        assert planned.entities == ("robot", "video"), planned.entities

    def test_a_property_only_side_still_finds_the_subject(self) -> None:
        assert comparison_pair(["demonstration", "cost", "video"],
                               "Demonstrations cost more than video footage.") == ("demonstration",
                                                                                    "video")

    def test_a_comparative_word_with_no_two_sides_is_not_a_comparison(self) -> None:
        assert comparison_pair(["model"], "The model learns more slowly.") is None
        assert spec("The model learns more slowly.").variant in {"statement", "panels"}

    def test_the_robot_arm_sentence_is_not_a_parts_cutaway(self) -> None:
        """The components drawer is a labelled cutaway; "arm" alone must not earn it."""

        planned = spec("A robot arm needs thousands of examples to learn one grasp")
        assert planned.variant == "panels"
        assert choose_variant(["robot"], "the gripper has a joint") == "components"

    def test_every_recipe_is_drawn_somewhere(self) -> None:
        """No rule may strand a sentence on a composition that cannot draw it."""

        assert set(_DRAWERS) >= {"bars", "ratio", "statement", "panels", "pipeline", "timeline"}


class TestEveryCompositionSurvivesThinSubjects:
    @pytest.mark.parametrize("variant", sorted(_DRAWERS))
    @pytest.mark.parametrize("count", [0, 1, 2, 3])
    def test_it_renders(self, variant: str, count: int) -> None:
        base = spec_for(concept="T", narration="x", objective="", colors=COLORS, variant=variant)
        entities = tuple("data video model robot".split()[:count])
        image = render_diagram(type(base)(variant=variant, title=base.title, entities=entities,
                                         emphasis="idea", palette=base.palette))
        assert image.size == (912, 600)

    def test_a_forced_pipeline_with_no_entities_draws_a_statement(self) -> None:
        planned = spec("That is the whole point.", variant="pipeline")
        assert render_diagram(planned).size == (912, 600)
