"""Read-side verbs must agree with the render path about a plan's format.

Found on the long-form run: `validate --plan-id long-academic-study-protocol` (no `--format`, which is how
an operator types it) built the 627-word 16:9 script against the *shorts* bounds and failed with
"too long (627 words, shorts allows 140)" — a message about the wrong problem. Two rules were missing:

* a plan that declares its own format is authoritative, exactly as it is on the render path;
* a read-side verb without `--format` should look at both composition profiles, not just the channel's
  native one, or it reports "plan not in this repository" for a plan sitting on disk.
"""

from __future__ import annotations

import argparse

import pytest

from factory.cli import _iter_requested_plans
from factory.config import load_channel_specs
from factory.content.plans import load_longform_plans
from factory.orchestrator import build_script


def long_plan(slug: str = "academic-biohacker") -> dict:
    return load_longform_plans(load_channel_specs()[slug])[0]


class TestPlanFormatWins:
    def test_a_long_plan_builds_under_a_shorts_spec(self) -> None:
        spec = load_channel_specs()["academic-biohacker"]
        assert spec.format == "shorts"
        script = build_script(spec, long_plan())
        assert script.format == "long"
        assert sum(len(line.text.split()) for line in script.lines) > 300

    def test_the_word_limit_follows_the_plan_not_the_spec(self) -> None:
        """The exact failure: neither the `shorts allows 140` error nor a silent truncation."""

        spec = load_channel_specs()["academic-biohacker"]
        script = build_script(spec, long_plan())
        words = sum(len(line.text.split()) for line in script.lines)
        assert words > 140, "a 16:9 episode is allowed more words than a Short"

    def test_a_short_plan_is_unaffected(self) -> None:
        """Topic-bank plans carry no format key, so the caller's spec still decides."""

        from factory.content.plans import generate_plan

        spec = load_channel_specs()["nexus-node"]
        plan = generate_plan(spec, write=False)["plan"]
        script = build_script(spec, plan)
        assert script.format == "shorts"


class TestReadSideProfileWalk:
    def test_a_long_plan_is_found_without_a_format_flag(self) -> None:
        args = argparse.Namespace(channel="academic-biohacker",
                                  plan_id="long-academic-study-protocol", format=None)
        found = list(_iter_requested_plans(args))
        assert found, "the long-form plan must be reachable without --format"
        spec, plan = found[0]
        assert spec.format == "long"
        assert plan["id"] == "long-academic-study-protocol"

    def test_a_shorts_plan_is_still_found_without_a_format_flag(self) -> None:
        args = argparse.Namespace(channel="nexus-node", plan_id="nexus-small-models", format=None)
        found = list(_iter_requested_plans(args))
        assert found and found[0][0].format == "shorts"

    def test_an_explicit_wrong_format_is_a_clear_error(self) -> None:
        args = argparse.Namespace(channel="academic-biohacker",
                                  plan_id="long-academic-study-protocol", format="shorts")
        with pytest.raises(ValueError, match="not in this repository"):
            list(_iter_requested_plans(args))

    def test_every_plan_is_walked_once(self) -> None:
        args = argparse.Namespace(channel="nexus-node", plan_id=None, format=None)
        ids = [plan["id"] for _spec, plan in _iter_requested_plans(args)]
        assert len(ids) == len(set(ids)), ids
