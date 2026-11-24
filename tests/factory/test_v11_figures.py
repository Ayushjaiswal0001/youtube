"""P1-1: a chart may only draw a number the narration states, and a vague one draws nothing."""

from __future__ import annotations

import re

import pytest

from factory.config import load_channel_specs
from factory.content.figures import Figure, chart_kind, chartable, extract
from factory.content.scene_plan import plan_scenes
from factory.media.assets.generated import render_diagram, spec_for

COLORS = load_channel_specs()["nexus-node"].colors
DIGITS = re.compile(r"\d")


def figures(text: str) -> tuple[tuple[str, int | float | None, str], ...]:
    return tuple((figure.phrase, figure.value, figure.unit) for figure in extract(text))


def spec(narration: str, *, category: str = "dataviz", figures_=None):
    values = figures_ if figures_ is not None else figures(narration)
    return spec_for(concept="T", narration=narration, objective="", colors=COLORS,
                    figures=values, category=category)


class TestExtraction:
    @pytest.mark.parametrize("text,value,unit", [
        ("Video is 40 percent cheaper.", 40, "%"),
        ("Video is 40% cheaper.", 40, "%"),
        ("It is 2x faster.", 2, "x"),
        ("It needs 1,200 examples.", 1200, ""),
        ("Train for 3 hours.", 3, "h"),
        ("It needs 1200 clips.", 1200, ""),
    ])
    def test_a_stated_figure_is_extracted(self, text: str, value: float, unit: str) -> None:
        found = extract(text)
        assert [(figure.value, figure.unit) for figure in found] == [(value, unit)]

    @pytest.mark.parametrize("text", [
        "It needs thousands of examples.",
        "Half the cost.",
        "Dozens of demos.",
        "Hundreds of robots.",
    ])
    def test_a_vague_quantifier_carries_no_value(self, text: str) -> None:
        found = extract(text)
        assert found, text
        assert all(figure.value is None for figure in found)

    def test_a_year_is_not_a_measurement(self) -> None:
        assert extract("In 2026 the model changed.") == []

    def test_an_ordinal_is_not_a_measurement(self) -> None:
        assert extract("The second robot arrived.") == []

    def test_a_number_needs_a_unit_or_a_counted_noun(self) -> None:
        assert extract("It needs 1200 clips.")[0].value == 1200
        assert extract("The arm has 7 axes of freedom.") == []

    def test_the_phrase_is_the_text_the_narration_contains(self) -> None:
        text = "Video is 40 percent cheaper."
        assert all(figure.phrase in text for figure in extract(text))

    def test_the_figure_is_frozen(self) -> None:
        figure = extract("Video is 40 percent cheaper.")[0]
        assert isinstance(figure, Figure)
        with pytest.raises(Exception):
            figure.value = 41  # type: ignore[misc]

    def test_the_character_offsets_are_recorded(self) -> None:
        text = "Video is 40 percent cheaper."
        figure = extract(text)[0]
        assert text[figure.start:figure.end] == figure.phrase


class TestChartChoice:
    def test_one_percentage_is_a_ratio(self) -> None:
        assert chart_kind(extract("Video is 40 percent cheaper.")) == "ratio"

    def test_two_percentages_are_bars(self) -> None:
        assert chart_kind(extract("Demos are 80 percent and video is 20 percent.")) == "bars"

    def test_two_values_of_the_same_unit_are_bars(self) -> None:
        assert chart_kind(extract("Demos take 6 hours and video takes 2 hours.")) == "bars"

    def test_mixed_units_are_not_charted(self) -> None:
        assert chart_kind(extract("It is 40 percent cheaper after 3 hours.")) is None

    def test_a_lone_count_is_not_charted(self) -> None:
        assert chart_kind(extract("It needs 1,200 examples.")) is None

    def test_a_vague_quantifier_is_not_charted(self) -> None:
        assert chart_kind(extract("It needs thousands of examples.")) is None

    def test_a_vague_word_does_not_block_a_stated_figure(self) -> None:
        found = extract("Thousands of clips, 40 percent cheaper.")
        assert [figure.value for figure in found if figure.numeric] == [40]
        assert chartable(found) is True

    def test_an_empty_sentence_is_not_chartable(self) -> None:
        assert chart_kind(extract("That is the whole point.")) is None


class TestChartsDrawOnlyStatedNumbers:
    def test_a_ratio_plate_labels_the_stated_figure(self) -> None:
        text = "Video is 40 percent cheaper."
        planned = spec(text, category="dataviz")
        assert planned.variant == "ratio"
        assert render_diagram(planned).size == (912, 600)

    def test_a_bars_plate_labels_both_stated_figures(self) -> None:
        text = "Demos are 80 percent and video is 20 percent."
        planned = spec(text, category="dataviz")
        assert planned.variant == "bars"
        assert render_diagram(planned).size == (912, 600)

    @pytest.mark.parametrize("text", [
        "It needs thousands of examples.",
        "Half the cost of a real demo.",
        "Dozens of robots.",
    ])
    def test_a_vague_quantifier_draws_no_chart(self, text: str) -> None:
        planned = spec(text, category="dataviz")
        assert planned.variant not in {"bars", "ratio"}
        assert planned.note and "vague" in planned.note
        assert render_diagram(planned).size == (912, 600)

    def test_a_chart_spec_carries_the_figures_it_draws(self) -> None:
        text = "Video is 40 percent cheaper."
        planned = spec(text, category="dataviz")
        assert planned.figures == figures(text)
        assert all(str(figure[1]) in planned.canonical() for figure in planned.figures)

    def test_two_charts_of_the_same_figures_are_the_same_asset(self) -> None:
        text = "Video is 40 percent cheaper."
        first, second = spec(text, category="dataviz"), spec(text, category="dataviz")
        assert first.asset_id == second.asset_id
        assert first.canonical() == second.canonical()

    def test_a_chart_does_not_share_an_asset_with_a_diagram(self) -> None:
        text = "Video is 40 percent cheaper."
        chart = spec(text, category="dataviz")
        diagram = spec_for(concept="T", narration=text, objective="", colors=COLORS,
                           figures=figures(text), category="diagram")
        assert chart.asset_id != diagram.asset_id or chart.variant == diagram.variant


class TestPlanWiring:
    def _plan(self, text: str):
        from factory.config import load_channel_specs
        from factory.content.models import Script, ScriptLine, WordTiming

        tokens = [token.strip(".,;:!?") for token in text.split()]
        span = 4.0 / max(1, len(tokens))
        line = ScriptLine(text=text, headline="HEADLINE", start=0.0, end=4.0,
                          words=[WordTiming(text=token, start=index * span,
                                            end=(index + 1) * span - 0.02)
                                 for index, token in enumerate(tokens)])
        script = Script(channel="nexus-node", language="en", format="shorts", topic="t",
                        title="T", hook=text, lines=[line], description="")
        return plan_scenes(load_channel_specs()["nexus-node"], script)

    def test_a_planned_dataviz_scene_receives_its_figures(self) -> None:
        planned = self._plan("Video is 40 percent cheaper than a real demo.")
        dataviz = [item for item in planned.scenes if item.visual_category == "dataviz"]
        assert dataviz, [item.visual_category for item in planned.scenes]
        assert dataviz[0].figures, dataviz[0].figures

    def test_the_plan_records_every_figure_it_found(self) -> None:
        planned = self._plan("Demos are 80 percent and video is 20 percent.")
        found = [figure for scene in planned.scenes for figure in scene.figures]
        assert found
        assert {figure["value"] for figure in found} == {80, 20}

    def test_a_vague_sentence_records_no_number(self) -> None:
        planned = self._plan("It needs thousands of examples to learn one grasp.")
        found = [figure for scene in planned.scenes for figure in scene.figures]
        assert found
        assert all(figure["value"] is None for figure in found)
