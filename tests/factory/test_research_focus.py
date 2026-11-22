"""A channel must state what it is about, and an unrelated item must not outrank a relevant one.

The defect this pins down: a Nature astronomy story scored 0.62 and became the top candidate for
Academic Biohacker, because relevance was a generic overlap against a short niche string and freshness plus
title quality carried the rest. Relevance is now gated by the channel's own focus terms.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from factory import research
from factory.config import load_channel_specs

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def _item(title: str, summary: str = "") -> research.FeedItem:
    return research.FeedItem(title=title, link="https://example.invalid/a", source_id="test",
                             published="2026-11-21", summary=summary)


def test_the_two_source_driven_channels_declare_focus_terms() -> None:
    specs = load_channel_specs()
    assert len(specs["academic-biohacker"].focus_terms) >= 15
    assert len(specs["nexus-node"].focus_terms) >= 15


def test_an_astronomy_story_is_not_a_learning_science_topic() -> None:
    spec = load_channel_specs()["academic-biohacker"]
    assert research._focus_hits(_item("Voyager 1 is now one light day from Earth",
                                      "Astronomers report a cosmic record."), spec) == []


def test_a_learning_science_story_is_one() -> None:
    spec = load_channel_specs()["academic-biohacker"]
    hits = research._focus_hits(_item("Spaced retrieval beats re-reading for exam recall",
                                      "A study of memory and learning in students."), spec)
    assert "learn" in hits or "memor" in hits or "retriev" in hits


def test_an_off_niche_item_scores_zero_and_says_why() -> None:
    spec = load_channel_specs()["academic-biohacker"]
    item = _item("BepiColombo finally reaches Mercury after eight-year odyssey",
                 "The European and Japanese probe entered orbit.")
    candidate = research.score_item(item, spec, (), NOW)
    assert candidate.score == 0.0
    assert any("off-niche" in reason for reason in candidate.reasons)


def test_an_on_niche_item_keeps_a_positive_score_and_records_the_match() -> None:
    spec = load_channel_specs()["academic-biohacker"]
    item = _item("Sleep loss blunts memory consolidation", "A study of hippocampal activity.")
    candidate = research.score_item(item, spec, (), NOW)
    assert candidate.score > 0.0
    assert any("on-niche" in reason for reason in candidate.reasons)


def test_matching_is_prefix_based_so_word_forms_are_caught() -> None:
    spec = load_channel_specs()["academic-biohacker"]
    assert research._focus_hits(_item("Learners who test themselves remember more"), spec)
    assert research._focus_hits(_item("Memorisation techniques that work"), spec)


def test_the_focus_gate_cannot_be_satisfied_by_the_word_science_alone() -> None:
    """The old failure in one line: 'science' appeared in the niche string and matched everything."""

    spec = load_channel_specs()["academic-biohacker"]
    assert research._focus_hits(_item("A science story about nothing in particular",
                                      "Generic science coverage."), spec) == []


def test_a_channel_without_focus_terms_is_unaffected() -> None:
    spec = load_channel_specs()["natkhat-toons"]
    assert spec.focus_terms == ()
    item = _item("Chiku finds a brass key in the haveli", "An original Hindi children's story.")
    assert research._focus_hits(item, spec) == []
    # no gate means the item is not rejected for being off-niche
    candidate = research.score_item(item, spec, (), NOW)
    assert not any("off-niche" in reason for reason in candidate.reasons)


def test_the_gate_is_case_insensitive() -> None:
    spec = load_channel_specs()["nexus-node"]
    assert research._focus_hits(_item("AI agents that write their own tools"), spec)
    assert research._focus_hits(_item("ai agents that write their own tools"), spec)
