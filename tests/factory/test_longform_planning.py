"""Selecting the next long-form episode, so the nightly 16:9 job has something to render.

Before this, `plan new` only ever produced a Short: the long-form bank lives in `content/longform/` and
nothing selected from it, so a scheduled long-form job would have had to be given an explicit plan id
forever. The selector is deterministic (file order), never writes, never repeats an uploaded episode, and
fails loudly when the bank is exhausted rather than producing nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.content.plans import (
    LONGFORM_DIR,
    PlanGenerationError,
    generate_plan,
    load_longform_plans,
    next_longform_plan,
)
from factory.state import ChannelState

CHANNELS = ("nexus-node", "academic-biohacker", "natkhat-toons")


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    """Keep the history a test writes out of the real pipeline_state directory."""

    monkeypatch.setenv("FACTORY_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def _state(slug: str, state_root: Path) -> ChannelState:
    return ChannelState(slug, root=state_root)


class TestLongformBank:
    @pytest.mark.parametrize("slug", CHANNELS)
    def test_every_channel_has_a_longform_bank(self, slug: str) -> None:
        path = LONGFORM_DIR / f"{slug}.json"
        assert path.is_file(), f"{slug} has no long-form bank at {path}"
        plans = load_longform_plans(load_channel_specs()[slug])
        assert plans, f"{slug} long-form bank is empty"
        for plan in plans:
            assert plan["id"]
            assert plan.get("format") == "long"

    def test_a_missing_bank_is_an_error_not_an_empty_list(self, tmp_path, monkeypatch) -> None:
        import factory.content.plans as plans_module

        monkeypatch.setattr(plans_module, "LONGFORM_DIR", tmp_path / "gone")
        with pytest.raises(PlanGenerationError, match="no long-form bank"):
            load_longform_plans(load_channel_specs()["nexus-node"])


class TestSelection:
    @pytest.mark.parametrize("slug", CHANNELS)
    def test_a_fresh_channel_gets_the_first_plan_in_the_bank(self, slug: str, state_root) -> None:
        spec = load_channel_specs()[slug]
        expected = load_longform_plans(spec)[0]["id"]
        plan = next_longform_plan(spec, _state(slug, state_root))
        assert plan["id"] == expected

    def test_selection_is_deterministic_across_calls(self, state_root) -> None:
        spec = load_channel_specs()["nexus-node"]
        state = _state("nexus-node", state_root)
        first = next_longform_plan(spec, state)["id"]
        second = next_longform_plan(spec, state)["id"]
        # Nothing was recorded, so the answer cannot drift between two runs of the same nightly job.
        assert first == second

    def test_an_uploaded_plan_is_skipped(self, state_root, monkeypatch) -> None:
        """The bank is walked in order and an uploaded episode is not offered again.

        Two synthetic plans are used because each real bank currently starts with a single authored
        episode; the behaviour under test is the selector, not the size of the bank.
        """

        import factory.content.plans as plans_module

        spec = load_channel_specs()["nexus-node"]
        fake = [{"id": str(plan["id"]), "format": "long", "title": plan.get("title", "")}
                for plan in load_longform_plans(spec)][:1]
        fake.append({"id": "long-synthetic-second", "format": "long", "title": "Second"})
        monkeypatch.setattr(plans_module, "load_longform_plans", lambda _spec: list(fake))

        state = _state("nexus-node", state_root)
        assert next_longform_plan(spec, state)["id"] == fake[0]["id"]
        # Distinct topics: `record` replaces an entry with the same topic fingerprint, so reusing one
        # topic would silently drop the first record.
        state.record(topic="first", title="T", status="uploaded", plan_id=fake[0]["id"])
        assert next_longform_plan(spec, state)["id"] == fake[1]["id"]
        state.record(topic="second", title="T", status="uploaded", plan_id=fake[1]["id"])
        with pytest.raises(PlanGenerationError, match="author the next long-form episode"):
            next_longform_plan(spec, state)

    def test_a_rendered_but_unpublished_plan_is_picked_again(self, state_root) -> None:
        """A failed upload must resume the same episode, not start another one."""

        spec = load_channel_specs()["nexus-node"]
        plans = load_longform_plans(spec)
        state = _state("nexus-node", state_root)
        state.record(topic="t", title="T", status="rendered", plan_id=str(plans[0]["id"]))
        assert next_longform_plan(spec, state)["id"] == plans[0]["id"]

    def test_an_exhausted_bank_explains_itself(self, state_root) -> None:
        spec = load_channel_specs()["nexus-node"]
        state = _state("nexus-node", state_root)
        for plan in load_longform_plans(spec):
            state.record(topic=f"topic-{plan['id']}", title="T", status="uploaded",
                         plan_id=str(plan["id"]))
        with pytest.raises(PlanGenerationError, match="author the next long-form episode"):
            next_longform_plan(spec, state)

    def test_natkhat_long_form_uses_the_stage_engine(self, state_root) -> None:
        spec = load_channel_specs()["natkhat-toons"]
        plan = next_longform_plan(spec, _state("natkhat-toons", state_root))
        assert plan.get("engine") == "stage"


class TestGeneratePlanFormat:
    def test_long_form_generation_writes_nothing_into_content(self, state_root) -> None:
        spec = load_channel_specs()["nexus-node"]
        before = sorted(p.name for p in Path("content").glob("batch_*.json"))
        result = generate_plan(spec, format="long", write=False)
        after = sorted(p.name for p in Path("content").glob("batch_*.json"))
        assert before == after
        assert result["created"] is False
        assert "authored" in result["reason"]

    def test_long_form_generation_reports_the_selected_plan(self, state_root) -> None:
        spec = load_channel_specs()["academic-biohacker"]
        result = generate_plan(spec, format="long", write=False)
        assert result["plan_id"] == load_longform_plans(spec)[0]["id"]
        assert result["channel"] == "academic-biohacker"

    def test_the_default_format_still_generates_a_short(self, state_root) -> None:
        spec = load_channel_specs()["nexus-node"]
        result = generate_plan(spec, write=False)
        assert result["plan"].get("format") in (None, "shorts")


class TestCli:
    def test_plan_new_accepts_the_format_flag(self, state_root) -> None:
        from factory import cli

        out = state_root / "out.json"
        code = cli.main(["plan", "new", "--channel", "natkhat-toons", "--format", "long",
                         "--no-write", "--json"])
        assert code == 0, out

    def test_plan_new_long_selects_the_bank_plan(self, state_root, capsys) -> None:
        from factory import cli

        cli.main(["plan", "new", "--channel", "nexus-node", "--format", "long", "--no-write",
                  "--json"])
        captured = capsys.readouterr().out
        payload = json.loads(captured)
        item = payload[0] if isinstance(payload, list) else payload
        assert item["plan_id"] == load_longform_plans(load_channel_specs()["nexus-node"])[0]["id"]
