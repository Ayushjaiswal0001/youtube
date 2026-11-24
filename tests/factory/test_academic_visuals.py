"""Academic Biohacker visual vocabulary, and the composition rules the integration needed.

Three things are pinned here because each of them was a defect found by rendering real episodes:

* C1 - the diagram lexicon had no physiology words, so an evidence-first health channel drew nothing
  but statement plates. Nine entities and pictograms were added; the count alone would not prove
  anything, so the tests render the plates and measure drawn geometry.
* C2 - a headline could pick a composition that draws hardware. "A light sensor" over a sentence about
  retinal cells drew a labelled robot-arm cutaway. Object-specific drawings now need their cue in the
  narration.
* C3 - consecutive statements tripped the no-repeat check because the ladder's only escapes
  (`pipeline`, `timeline`) are refused without a stated order. `focus` is the second honest
  single-subject composition, and the ladder now filters candidates through the same honesty rules.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from factory.config import load_channel_specs
from factory.content.figures import extract, numeric_figures
from factory.media.assets.generated import (
    _DRAWERS,
    _LADDER,
    _narration_cued,
    ATTRIBUTE_ENTITIES,
    ICONS,
    LEXICON,
    _draw_focus,
    choose_variant,
    entities_in,
    has_sequence_cue,
    render_diagram,
    spec_for,
)
from factory.media.english_renderer import fingerprint_distance, plate_fingerprint

ACADEMIC_COLORS = {
    "bg": "#F4F1EA", "panel": "#FFFDF7", "accent": "#D62839", "accent2": "#2A9D8F",
    "text": "#1B1B1B",
}
NEXUS_COLORS = {
    "bg": "#050B16", "panel": "#10243A", "accent": "#4FD1E8", "accent2": "#FFB84D",
    "text": "#F5F9FF",
}


def _spec(narration: str, *, concept: str = "T", colors: dict[str, str] | None = None,
          **kwargs: object):
    return spec_for(concept=concept, narration=narration, objective="",
                    colors=colors or ACADEMIC_COLORS, **kwargs)


def _ink(image: Image.Image) -> int:
    """Pixels that differ from the plate background: a crude but honest 'was anything drawn'."""

    array = np.asarray(image.convert("RGB"), dtype=np.int16)
    background = np.array([255, 253, 247], dtype=np.int16)
    return int((np.abs(array - background).sum(axis=2) > 24).sum())


class TestAcademicVocabulary:
    """C1: the channel needs words for the body, or it cannot draw the body."""

    @pytest.mark.parametrize("entity", ["breath", "heart", "brain", "sleep", "light", "glucose",
                                        "movement", "temperature", "meal"])
    def test_each_academic_entity_has_a_pictogram(self, entity: str) -> None:
        assert entity in LEXICON
        assert entity in ICONS

    def test_every_lexicon_entity_has_an_icon(self) -> None:
        # `_icon_for` silently falls back to the data pictogram, so a missing entry would draw the
        # wrong object rather than fail. The sets must match exactly.
        assert set(LEXICON) == set(ICONS)

    def test_academic_entities_are_not_attributes(self) -> None:
        # An attribute is drawn as a property pill, never as a stage or a panel subject.
        for entity in ("breath", "heart", "brain", "sleep", "light", "glucose", "movement",
                       "temperature", "meal"):
            assert entity not in ATTRIBUTE_ENTITIES

    @pytest.mark.parametrize("sentence,expected", [
        ("Heart rate naturally rises on the in-breath and falls on the out-breath.", "heart"),
        ("Breathing at roughly six breaths per minute amplifies that reflex.", "breath"),
        ("That fall is one of the signals the brain uses to time sleep.", "brain"),
        ("Morning light advances the clock and anchors it.", "light"),
        ("After you eat, glucose rises in the blood.", "glucose"),
        ("Standing or walking for a couple of minutes every half hour.", "movement"),
        ("In the evening your body shifts heat from the core to the skin.", "temperature"),
        ("Protein triggers satiety signals and takes more energy to digest.", "meal"),
    ])
    def test_a_physiology_sentence_names_a_drawable_subject(self, sentence: str,
                                                           expected: str) -> None:
        assert expected in entities_in(sentence)

    @pytest.mark.parametrize("entity", ["breath", "heart", "brain", "sleep", "light", "glucose",
                                        "movement", "temperature", "meal"])
    def test_each_academic_pictogram_draws_something(self, entity: str) -> None:
        spec = _spec(f"The role of the {entity} in this process.", variant="statement")
        spec = type(spec)(**{**spec.__dict__, "entities": (entity,)})
        image = render_diagram(spec)
        assert _ink(image) > 2_000, f"{entity} pictogram drew almost nothing"

    def test_the_academic_palette_is_used_not_the_nexus_one(self) -> None:
        spec = _spec("Heart rate rises on the in-breath.", variant="statement")
        image = np.asarray(render_diagram(spec).convert("RGB"))
        # The paper background must dominate a paper plate.
        assert (image[..., 0] > 200).mean() > 0.5

    def test_sleep_is_a_subject_not_a_study_synonym(self) -> None:
        """`sleep` was a synonym of `study`, so "time sleep" drew a book instead of a night sky."""

        assert "sleep" not in LEXICON["study"][1]
        assert "sleep" in entities_in("That fall is one of the signals the brain uses to time sleep.")

    def test_slow_is_not_a_cost(self) -> None:
        """"Longer slow exhales" earned a COST pill because "slow" was a cost synonym."""

        assert "slow" not in LEXICON["cost"][1]
        assert "cost" not in entities_in("Longer slow exhales are the practical part.")
        # The word the Nexus sentence actually used still resolves.
        assert "cost" in entities_in("human demonstrations are slow and costly")


class TestNarrationCuedCompositions:
    """C2: a headline may pick a style, never an object the sentence does not mention."""

    def test_a_headline_saying_sensor_does_not_draw_a_robot_arm(self) -> None:
        spec = _spec("A special set of retinal cells reports light levels to the brain's master "
                     "clock, separate from image vision.", concept="A light sensor",
                     category="diagram")
        assert spec.variant != "components"

    def test_the_same_headline_still_draws_a_cutaway_when_the_sentence_says_joint(self) -> None:
        # The sentence needs a drawable subject as well as the hardware cue: a cutaway with no named
        # subject would be a drawing of something the sentence never mentioned.
        spec = _spec("The robot joint carries a motor and a sensor in the wrist.",
                     concept="Inside", category="diagram")
        assert spec.variant == "components"

    @pytest.mark.parametrize("variant,cue,sentence", [
        ("components", "joint", "The joint at the wrist holds the gripper."),
        ("layers", "layer", "The stack has a perception layer and a control layer."),
        ("topology", "grid", "The grid balances load between substations."),
    ])
    def test_object_specific_drawers_need_their_cue_in_the_sentence(
            self, variant: str, cue: str, sentence: str) -> None:
        assert _narration_cued(variant, sentence) is True
        assert _narration_cued(variant, "Nothing here mentions that word.") is False

    def test_a_headline_may_not_supply_a_sequence_cue(self) -> None:
        """An arrow asserts an order, and the order has to be spoken."""

        spec = _spec("The video library keeps growing.", concept="First, then, finally",
                     category="diagram")
        assert spec.variant not in {"pipeline", "timeline"}

    def test_the_nexus_ordered_sentence_still_draws_a_pipeline(self) -> None:
        spec = _spec("The fix is a small amount of real robot data to anchor the model then scale "
                     "with cheap footage", colors=NEXUS_COLORS, category="diagram")
        assert spec.variant == "pipeline"

    def test_a_stated_property_does_not_collapse_an_ordered_sentence(self) -> None:
        """The attribute rule used to turn this pipeline into a statement, losing the order.

        `_draw_pipeline` already drops the property from its stages, so the order survives and the
        cost is not drawn as a step.
        """

        spec = _spec("The fix is a small amount of real robot data to anchor the model then scale "
                     "with cheap footage", colors=NEXUS_COLORS, category="diagram")
        assert spec.variant == "pipeline"
        assert "cost" in spec.entities
        image = np.asarray(render_diagram(spec).convert("RGB"))
        assert image.shape[0] > 0  # renders without raising on the attribute


class TestFocusComposition:
    """C3: two compositions that make the same claim, so a run can alternate honestly."""

    def test_focus_is_registered(self) -> None:
        assert "focus" in _DRAWERS
        assert _LADDER["statement"][0] == "focus"
        assert _LADDER["focus"][0] == "statement"

    def test_a_repeat_of_statement_steps_to_focus(self) -> None:
        spec = _spec("The effect is modest and short-lived, so it complements movement.", avoid=(
            "statement",))
        assert spec.variant == "focus"

    def test_focus_never_claims_more_than_the_sentence(self) -> None:
        spec = _spec("Protein triggers satiety signals and takes more energy to digest.")
        focus = _spec("Protein triggers satiety signals and takes more energy to digest.",
                      variant="focus")
        assert set(focus.entities) == set(spec.entities)
        assert focus.figures == ()          # no number invented
        assert "FIGURES THE SENTENCE STATES" not in focus.note.upper()

    def test_focus_and_statement_are_visually_distinct(self) -> None:
        text = "The effect is modest and short-lived, so it complements movement across the day."
        a = plate_fingerprint(render_diagram(_spec(text, variant="statement")))
        b = plate_fingerprint(render_diagram(_spec(text, variant="focus")))
        # The engine's own clustering threshold is 6 bits; two compositions must clear it by a margin.
        assert fingerprint_distance(a, b) > 20

    def test_focus_without_a_property_still_draws_the_subject(self) -> None:
        spec = _spec("The effect is modest and short-lived.", variant="focus")
        assert _ink(render_diagram(spec)) > 2_000

    def test_focus_with_no_entity_falls_back_to_statement(self) -> None:
        spec = _spec("It just works.", variant="focus")
        plate = render_diagram(spec)
        assert plate.size == (912, 600)
        # A statement with no entity draws the neutral marker, not an invented subject.
        assert _ink(plate) > 500


class TestLadderHonesty:
    """The ladder may not pick a composition the honesty rules then reject."""

    def test_the_ladder_never_returns_an_avoided_variant_when_a_legal_one_exists(self) -> None:
        text = "and human demonstrations are slow and costly"
        spec = _spec(text, avoid=("panels",))
        assert spec.variant != "panels"

    def test_a_ladder_candidate_needs_the_narration_cue(self) -> None:
        # `panels` is avoided and the sentence states no order, so `pipeline` and `timeline` are both
        # refused. Repeating the neighbouring composition is the honest outcome; inventing an order
        # to avoid the repeat would not be.
        spec = _spec("A robot arm needs thousands of examples to learn one grasp.",
                     avoid=("panels",))
        assert spec.variant not in {"pipeline", "timeline"}

    def test_the_longest_run_is_at_most_two_on_the_academic_reference(self) -> None:
        sentences = [
            "Your breathing rate is one of the few levers you can pull directly.",
            "Heart rate naturally rises on the in-breath and falls on the out-breath.",
            "Breathing at roughly six breaths per minute amplifies that reflex.",
            "Small trials report short-term drops in perceived stress.",
            "Longer slow exhales are the practical part.",
            "Try a longer exhale than inhale for two minutes.",
        ]
        variants: list[str] = []
        avoid: tuple[str, ...] = ()
        for sentence in sentences:
            spec = _spec(sentence, category="diagram", avoid=avoid)
            variants.append(spec.variant)
            avoid = () if spec.variant == "cta" else (spec.variant,)
        longest = 1
        run = 1
        for previous, current in zip(variants, variants[1:]):
            run = run + 1 if current == previous else 1
            longest = max(longest, run)
        assert longest <= 2, variants


class TestAcademicChartsStayHonest:
    def test_a_spoken_quantity_is_not_a_chart(self) -> None:
        """"Roughly six breaths per minute" is a quantity in words; a bar would need a baseline."""

        text = "Breathing at roughly six breaths per minute amplifies that reflex."
        figures = tuple((figure.phrase, figure.value, figure.unit) for figure in extract(text))
        spec = _spec(text, category="dataviz", figures=figures)
        assert spec.variant not in {"bars", "ratio"}
        assert spec.note, "a refused chart must say why"

    def test_a_stated_percentage_of_a_whole_is_a_ratio(self) -> None:
        text = "Roughly 40 percent of the effect comes from the exhale."
        figures = tuple((figure.phrase, figure.value, figure.unit) for figure in extract(text))
        spec = _spec(text, category="dataviz", figures=figures)
        assert spec.variant == "ratio"

    def test_numeric_figures_ignores_number_words(self) -> None:
        # Word numbers are deliberately not extracted: "six breaths" is a rate the chart drawers cannot
        # place on a bar, and a bar labelled "6" would be a number the sentence never wrote down.
        assert numeric_figures(extract("Roughly six breaths per minute.")) == []
        assert numeric_figures(extract("The trial ran 12 tests."))


class TestChannelsLoad:
    def test_all_three_channels_load_with_a_policy(self) -> None:
        specs = load_channel_specs()
        assert set(specs) >= {"nexus-node", "academic-biohacker", "natkhat-toons"}
        for slug in ("nexus-node", "academic-biohacker", "natkhat-toons"):
            assert specs[slug].visual_policy is not None

    def test_natkhat_keeps_its_character_path(self) -> None:
        policy = load_channel_specs()["natkhat-toons"].visual_policy
        assert policy.scene_planning is False
        assert policy.categories == ()
