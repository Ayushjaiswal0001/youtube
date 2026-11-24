"""Regression tests for the four HIGH-severity release blockers found in the independent audit.

Each test names the defect it prevents from coming back:

H1  a package can carry scenes.json/creative.json and fail its own manifest verification
H2  an inter-line pause made the card show the last line's headline and counter
H3  a composition indexed a second entity that did not exist and crashed the render
H4  a plate labelled STUDY for a sentence about learning from videos, and cost drawn as a stage
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.content.models import Script, ScriptLine, WordTiming
from factory.media.assets.generated import (
    _DRAWERS,
    ATTRIBUTE_ENTITIES,
    LEXICON,
    entities_in,
    render_diagram,
    spec_for,
)
from factory.media.english_renderer import _active_line

COLORS = load_channel_specs()["nexus-node"].colors


def line(text: str, start: float, end: float, headline: str = "") -> ScriptLine:
    tokens = text.split()
    span = (end - start) / max(1, len(tokens))
    words = [WordTiming(token, start + i * span, start + (i + 1) * span - 0.01)
             for i, token in enumerate(tokens)]
    return ScriptLine(text=text, headline=headline, start=start, end=end, words=words)


# ---------------------------------------------------------------- H1: manifest coverage
class TestH1ProductionManifest:
    def test_the_orchestrator_declares_every_canonical_artifact(self) -> None:
        """A file listed in CANONICAL but missing from the production manifest fails verify()."""

        import inspect

        from factory import orchestrator
        from factory.manifesting import CANONICAL

        # The packaging step lives in `_render_tracked`, which `render_episode` calls.
        source = inspect.getsource(orchestrator)
        missing = [filename for _, filename in CANONICAL
                   if filename not in source and filename not in {"video.mp4", "thumbnail.jpg",
                                                                  "captions.srt", "qc.json",
                                                                  "timeline.json"}]
        assert not missing, f"render_episode does not declare {missing}"

    def test_a_package_with_the_visual_artifacts_verifies_clean(self, tmp_path: Path) -> None:
        """Built through production_manifest, the way render_episode builds it."""

        from factory.reliability import production_manifest
        from factory.manifesting import verify

        artifacts = {}
        for name, filename in (("video", "video.mp4"), ("thumbnail", "thumbnail.jpg"),
                               ("captions", "captions.srt"), ("qc_report", "qc.json"),
                               ("timeline", "timeline.json"), ("story", "story.json"),
                               ("framing", "framing.json"), ("scene_plan", "scenes.json"),
                               ("creative_qc", "creative.json")):
            path = tmp_path / filename
            path.write_text("{}", encoding="utf-8")
            artifacts[name] = path
        manifest = production_manifest(channel="nexus-node", plan_id="p", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert verify(tmp_path) == []
        names = {entry["name"] for entry in manifest["artifacts"]}
        assert {"scene_plan", "creative_qc"} <= names

    def test_a_legacy_package_without_the_visual_artifacts_still_verifies(self, tmp_path: Path) -> None:
        from factory.reliability import production_manifest
        from factory.manifesting import verify

        artifacts = {}
        for name, filename in (("video", "video.mp4"), ("thumbnail", "thumbnail.jpg"),
                               ("captions", "captions.srt"), ("qc_report", "qc.json"),
                               ("timeline", "timeline.json"), ("story", "story.json"),
                               ("framing", "framing.json")):
            path = tmp_path / filename
            path.write_text("{}", encoding="utf-8")
            artifacts[name] = path
        manifest = production_manifest(channel="academic-biohacker", plan_id="p", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        assert verify(tmp_path) == []

    def test_declaring_the_visual_artifacts_is_what_makes_verify_pass(self, tmp_path: Path) -> None:
        """The negative control: same files on disk, manifest without them, verify complains."""

        from factory.reliability import production_manifest
        from factory.manifesting import verify

        artifacts = {}
        for name, filename in (("video", "video.mp4"), ("thumbnail", "thumbnail.jpg"),
                               ("captions", "captions.srt"), ("qc_report", "qc.json"),
                               ("timeline", "timeline.json")):
            path = tmp_path / filename
            path.write_text("{}", encoding="utf-8")
            artifacts[name] = path
        for filename in ("scenes.json", "creative.json"):
            (tmp_path / filename).write_text("{}", encoding="utf-8")
        manifest = production_manifest(channel="nexus-node", plan_id="p", engine="shorts",
                                       format="shorts", artifacts=artifacts, qc={"ok": True})
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        problems = verify(tmp_path)
        assert "scene_plan: unlisted artifact on disk" in problems
        assert "creative_qc: unlisted artifact on disk" in problems


# ---------------------------------------------------------------- H2: active line
class TestH2ActiveLine:
    LINES = [line("First line here", 0.2, 5.0, "ONE"),
             line("Second line here", 5.3, 11.0, "TWO"),
             line("Third line here", 11.4, 17.0, "THREE")]

    def test_every_inter_line_gap_keeps_the_preceding_line(self) -> None:
        for previous, following in zip(self.LINES, self.LINES[1:]):
            for offset in (0.01, 0.05, 0.12, 0.25):
                moment = previous.end + offset
                if moment >= following.start:
                    continue
                active, index = _active_line(self.LINES, moment)
                assert active.headline == previous.headline, (
                    f"t={moment:.2f} in the gap after {previous.headline} chose {active.headline}")

    def test_after_the_last_line_the_last_line_remains(self) -> None:
        after, index = _active_line(self.LINES, self.LINES[-1].end + 0.5)
        assert after.headline == "THREE" and index == len(self.LINES) - 1

    def test_inside_a_line_the_right_line_is_active(self) -> None:
        for expected, moment in (("ONE", 2.0), ("TWO", 8.0), ("THREE", 14.0)):
            assert _active_line(self.LINES, moment)[0].headline == expected

    def test_before_the_first_line_the_first_line_is_active(self) -> None:
        assert _active_line(self.LINES, 0.0)[0].headline == "ONE"

    def test_the_card_headline_and_counter_come_from_the_same_line(self) -> None:
        """The counter is derived from the same index, so a gap cannot desynchronise them."""

        for previous, following in zip(self.LINES, self.LINES[1:]):
            moment = previous.end + 0.05
            if moment >= following.start:
                continue
            active, index = _active_line(self.LINES, moment)
            assert (active.headline, index) == (previous.headline, self.LINES.index(previous))

    def test_a_real_timeline_has_no_gap_that_selects_the_final_line(self) -> None:
        timeline = Path("C:/Users/DELL/AppData/Local/Temp/x100new/nexus-node/nexus-robot-video/timeline.json")
        if not timeline.is_file():
            pytest.skip("rendered timeline not present on this machine")
        data = json.loads(timeline.read_text(encoding="utf-8"))
        lines = [ScriptLine.from_dict(item) for item in data["lines"]]
        for previous, following in zip(lines, lines[1:]):
            moment = (previous.end + following.start) / 2
            if not previous.end < moment < following.start:
                continue
            active, _ = _active_line(lines, moment)
            assert active.headline == previous.headline


# ---------------------------------------------------------------- H3: single entity
class TestH3SingleEntity:
    @pytest.mark.parametrize("entities", [(), ("data",), ("data", "video"), ("robot", "video", "model")])
    def test_every_composition_renders_with_that_many_entities(self, entities) -> None:
        for variant in sorted(_DRAWERS):
            base = spec_for(concept="T", narration="x", objective="", colors=COLORS, variant=variant)
            spec = type(base)(variant=variant, title=base.title, entities=entities,
                              emphasis="idea", palette=base.palette)
            image = render_diagram(spec)
            assert image.size == (912, 600)

    def test_one_entity_never_selects_a_two_subject_composition(self) -> None:
        spec = spec_for(concept="That is the whole point", narration="That is the whole point.",
                        objective="", colors=COLORS, avoid=("pipeline",))
        assert spec.variant in {"statement", "timeline", "pipeline"}
        render_diagram(spec)

    def test_a_no_entity_sentence_following_a_pipeline_scene_does_not_crash(self) -> None:
        """The exact reachable path: the diversity ladder used to step from pipeline to topology."""

        previous = spec_for(concept="Video", narration="Video pretraining lets a model watch.",
                            objective="", colors=COLORS)
        assert previous.variant == "pipeline"
        following = spec_for(concept="That is the whole point",
                             narration="That is the whole point.", objective="",
                             colors=COLORS, avoid=(previous.variant,))
        assert following.variant != "pipeline"
        render_diagram(following)

    def test_gap_and_topology_are_guarded_at_the_drawer(self) -> None:
        """Belt and braces: even if a caller forces the variant, the drawer must not index [1]."""

        for variant in ("gap", "topology", "comparison"):
            base = spec_for(concept="T", narration="x", objective="", colors=COLORS, variant=variant)
            spec = type(base)(variant=variant, title=base.title, entities=("data",),
                              emphasis="idea", palette=base.palette)
            assert render_diagram(spec) is not None


# ---------------------------------------------------------------- H4: semantic labels
class TestH4SemanticCorrectness:
    def test_learning_from_videos_is_not_study(self) -> None:
        """The audited narration. The plate said ROBOT -> DEMOS -> STUDY; it must say VIDEO."""

        narration = ("Robots used to need demonstrations Now they are learning from videos anyone "
                     "can record")
        entities = entities_in(narration)
        assert "study" not in entities, f"study was inferred from a sentence about videos: {entities}"
        assert "video" in entities
        spec = spec_for(concept="WATCH AND LEARN", narration=narration, objective="", colors=COLORS,
                        on_screen="WATCH AND LEARN")
        assert "study" not in spec.entities
        assert "video" in spec.entities
        assert spec.variant == "pipeline"
        labels = [LEXICON[entity][0] for entity in spec.entities]
        assert "study" not in labels and "video" in labels

    def test_a_plural_finds_its_entity(self) -> None:
        assert "video" in entities_in("learning from videos")
        assert "model" in entities_in("other models follow")
        assert "study" in entities_in("the studies were small")

    def test_a_property_is_not_a_pipeline_stage(self) -> None:
        """The other audited narration: cost was drawn as a stage (DEMOS -> COST -> DATA)."""

        spec = spec_for(concept="THE DATA PROBLEM",
                        narration="and human demonstrations are slow and costly",
                        objective="", colors=COLORS, on_screen="THE DATA PROBLEM")
        assert spec.variant == "statement", spec.variant
        subject = next(entity for entity in spec.entities if entity not in ATTRIBUTE_ENTITIES)
        assert subject == "demonstration"
        assert "cost" in spec.entities

    def test_a_quantity_is_not_a_comparison(self) -> None:
        """The real render drew "ROBOT vs DATA / TWO ROUTES TO THE SAME RESULT" here."""

        spec = spec_for(concept="THE DATA PROBLEM",
                        narration="A robot arm needs thousands of examples to learn one grasp",
                        objective="", colors=COLORS, on_screen="THE DATA PROBLEM")
        assert spec.variant == "panels", spec.variant
        render_diagram(spec)

    def test_no_composition_claims_a_shared_result(self) -> None:
        """The comparison footer asserted a relationship the narration never states."""

        import inspect

        from factory.media.assets import generated

        source = inspect.getsource(generated)
        assert "TWO ROUTES TO THE SAME RESULT" not in source
        assert "WHAT THE SENTENCE CONTRASTS" in source
        assert "WHAT THE SENTENCE MENTIONS" in source

    def test_panels_draws_no_versus_badge(self) -> None:
        import inspect

        from factory.media.assets import generated

        body = inspect.getsource(generated._draw_panels)
        assert '"vs",' not in body and '"vs")' not in body, "a versus badge asserts a contest"
        assert "canvas.line(" not in body, "a connector arrow would assert a relation"

    def test_an_explicit_comparison_still_gets_a_comparison(self) -> None:
        spec = spec_for(concept="Demos versus video",
                        narration="Demonstrations cost more than video footage.",
                        objective="", colors=COLORS)
        assert spec.variant == "comparison"

    def test_no_diagram_invents_numbers(self) -> None:
        """A plate cannot assert a magnitude, because no spec field can carry one."""

        spec = spec_for(concept="Anything", narration="A robot arm needs many examples.",
                        objective="", colors=COLORS)
        # The invariant is structural: DiagramSpec has no numeric channel, so no plate can assert a
        # magnitude. (Palette hex values contain digits, which is why this is not a text scan.)
        fields = (spec.title, spec.emphasis, *spec.entities, *spec.palette)
        assert all(isinstance(value, str) for value in fields)
        assert not hasattr(spec, "value") and not hasattr(spec, "magnitude")
