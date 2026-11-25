"""The composition ladder must never step onto a composition the honesty rules reject.

Found by the gate on a real repo plan (`nexus-small-models`), not by a unit test: the ladder ran on the
raw choice, a later rule demoted the chosen composition, and the demotion landed on the composition the
ladder was trying to avoid. The result was a run of four `statement` plates and a `creative_quality`
blocker, which blocked publishing for an episode that was otherwise fine.

These tests pin the ordering, so the same defect cannot come back through a rule that is added later.
"""

from __future__ import annotations

import pytest

from factory.config import load_channel_specs
from factory.content.figures import extract
from factory.media.assets.generated import spec_for

NEXUS = load_channel_specs()["nexus-node"].colors
ACADEMIC = load_channel_specs()["academic-biohacker"].colors


def _variant(narration: str, *, concept: str = "", category: str = "dataviz",
             colors: dict[str, str] | None = None,
             avoid: tuple[str, ...] = (), **kwargs: object) -> str:
    figures = tuple((figure.phrase, figure.value, figure.unit) for figure in extract(narration))
    return spec_for(concept=concept, narration=narration, objective="", colors=colors or NEXUS,
                    category=category, figures=figures, avoid=avoid, **kwargs).variant


def _longest_run(variants: list[str]) -> int:
    longest = run = 1
    for previous, current in zip(variants, variants[1:]):
        run = run + 1 if current == previous else 1
        longest = max(longest, run)
    return longest if variants else 0


def _plan_variants(lines: list[tuple[str, str]],
                   colors: dict[str, str] | None = None) -> list[str]:
    variants: list[str] = []
    avoid: tuple[str, ...] = ()
    for narration, category in lines:
        variant = _variant(narration, category=category, colors=colors, avoid=avoid)
        variants.append(variant)
        avoid = () if variant == "cta" else (variant,)
    return variants


SMALL_MODELS = [
    ("The most useful AI model this year might be the one that runs on your phone.", "dataviz"),
    ("Small models are trained to imitate larger models, a process called distillation.", "diagram"),
    ("and run faster. On narrow tasks like summarizing or routing, a small model can match a big one.",
     "dataviz"),
    ("Running locally cuts latency, cloud cost, and the risk of sending private data away.", "dataviz"),
    ("The catch is range, because small models forget more and fail on open-ended reasoning.",
     "dataviz"),
    ("Subscribe for practical AI breakdowns.", "cta"),
]


class TestLadderOrdering:
    def test_a_property_demotion_does_not_land_on_the_avoided_composition(self) -> None:
        """`panels` plus a stated cost is demoted to `statement`; that must not defeat the ladder."""

        variant = _variant("Running locally cuts latency, cloud cost, and the risk of sending "
                           "private data away.", avoid=("statement",))
        assert variant != "statement"

    def test_a_sequence_demotion_does_not_land_on_the_avoided_composition(self) -> None:
        variant = _variant("A robot arm needs thousands of examples to learn one grasp.",
                           category="diagram", avoid=("statement",))
        assert variant != "statement"

    def test_the_ladder_prefers_a_composition_that_survives_the_rules(self) -> None:
        # `statement` needs an escape that is not `pipeline`/`timeline` (no stated order here), and
        # `focus` is the alternative that survives - it draws the same subject and properties.
        assert _variant("Longer slow exhales are the practical part.", category="diagram",
                        colors=ACADEMIC, avoid=("statement",)) == "focus"

    def test_a_sentence_with_no_subject_has_nothing_to_alternate_to(self) -> None:
        # `focus` needs a subject to draw; with none, the honest answer is the same neutral statement
        # even though it repeats. The threshold tolerates that because nothing else is true.
        assert _variant("The effect is modest and short-lived.", category="diagram",
                        avoid=("statement",)) == "statement"

    def test_a_cta_is_never_demoted_for_having_no_subject(self) -> None:
        """The no-subject guard used to rewrite the closing card into a statement."""

        variant = _variant("Subscribe for practical AI breakdowns.", category="cta")
        assert variant == "cta"

    def test_a_statement_with_no_subject_is_still_a_statement(self) -> None:
        assert _variant("It just works.", category="diagram") == "statement"

    @pytest.mark.parametrize("lines,colors", [
        (SMALL_MODELS, NEXUS),
        ([("Your breathing rate is one of the few levers you can pull directly.", "diagram"),
          ("Heart rate naturally rises on the in-breath and falls on the out-breath.", "diagram"),
          ("Breathing at roughly six breaths per minute amplifies that reflex.", "dataviz"),
          ("Longer slow exhales are the practical part.", "diagram"),
          ("Follow for practical, evidence-first health.", "cta")], ACADEMIC),
    ])
    def test_a_whole_plan_never_repeats_a_composition_more_than_twice(
            self, lines: list[tuple[str, str]], colors: dict[str, str]) -> None:
        # The creative QC threshold is 2; a composition set that cannot reach it is a blocker, so this
        # is measured on plan sequences rather than on one sentence.
        variants = _plan_variants(lines, colors)
        assert _longest_run(variants) <= 2, variants

    def test_the_reference_small_models_sequence_alternates(self) -> None:
        variants = _plan_variants(SMALL_MODELS)
        assert variants[-1] == "cta"
        assert _longest_run(variants) == 1, variants

    def test_an_avoided_composition_is_only_repeated_when_nothing_else_is_true(self) -> None:
        """`panels` with two stageable subjects has no honest alternative, and repeating it is right.

        The threshold tolerates two in a row precisely because the honest answer is sometimes "the same
        composition again"; inventing an order to avoid the repeat would not be.
        """

        variant = _variant("A robot arm needs thousands of examples to learn one grasp.",
                           category="diagram", avoid=("panels",))
        assert variant not in {"pipeline", "timeline"}
