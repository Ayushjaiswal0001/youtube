"""Tests for the research engine.

Every test runs offline: the fetcher is injected, so no test depends on a feed being up, on a network
being available, or on what a publisher happened to post today. The scoring tests assert the shape of
the policy (freshness decays, duplicates are rejected, unsafe material for a children's channel is
rejected, a dead feed does not lose the report) rather than a magic number that would have to be
re-baselined every time a weight changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.research import (
    CHILD_UNSAFE,
    FRESHNESS_HALF_LIFE_DAYS,
    Source,
    _freshness,
    discover,
    fetch,
    load_sources,
    parse_feed,
    score_item,
    tokens,
    write_report,
)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>AI models and training data</title><link>https://example.org/ai</link>
<pubDate>Tue, 18 Nov 2026 10:00:00 GMT</pubDate><description>Models need data</description></item>
<item><title>Another AI story</title><link>https://example.org/ai2</link>
<pubDate>Mon, 17 Nov 2026 10:00:00 GMT</pubDate><description>More models</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Protein folding and cells</title><link href="https://example.org/protein"/>
<published>2026-11-19T08:00:00Z</published><summary>Biology research</summary></entry></feed>"""

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def specs():
    return load_channel_specs()


def spec(slug: str):
    return specs()[slug]


# ------------------------------------------------------------------ parsing

def test_parses_rss_items() -> None:
    items = parse_feed(RSS, Source("rss", "https://example.org/feed"))
    assert [item.title for item in items] == ["AI models and training data", "Another AI story"]
    assert items[0].link == "https://example.org/ai"
    assert items[0].published == "2026-11-18"


def test_parses_atom_entries_with_href_links() -> None:
    items = parse_feed(ATOM, Source("atom", "https://example.org/atom"))
    assert len(items) == 1
    assert items[0].link == "https://example.org/protein"
    assert items[0].published == "2026-11-19"


def test_markup_is_stripped_from_titles_and_summaries() -> None:
    xml = RSS.replace("Models need data", "&lt;p&gt;Models &lt;b&gt;need&lt;/b&gt; data&lt;/p&gt;")
    item = parse_feed(xml, Source("rss", "https://example.org/feed"))[0]
    assert "<" not in item.summary
    assert item.summary == "Models need data"


def test_an_unparseable_feed_raises_a_clear_error() -> None:
    with pytest.raises(ValueError) as caught:
        parse_feed("<html>not a feed</html>", Source("bad", "https://example.org/bad"))
    # Either "not parseable" (malformed) or "root element ... is not a feed" (an HTML page): both are
    # an error rather than an empty feed, which is the property that matters.
    message = str(caught.value)
    assert "not a parseable feed" in message or "is not a feed" in message


def test_an_item_without_a_link_is_ignored() -> None:
    xml = """<rss><channel><item><title>No link</title></item></channel></rss>"""
    assert parse_feed(xml, Source("x", "https://example.org")) == []


# ------------------------------------------------------------------ scoring policy

def test_freshness_decays_by_the_stated_half_life() -> None:
    # A date has no time of day, so "today" is up to 24h old by noon; what matters is the ratio over
    # one half-life, not that today equals exactly 1.0.
    fresh = _freshness(NOW.date().isoformat(), NOW)
    old = _freshness((NOW - timedelta(days=FRESHNESS_HALF_LIFE_DAYS)).date().isoformat(), NOW)
    assert 0.9 < fresh <= 1.0
    assert old / fresh == pytest.approx(0.5, abs=0.02)
    assert _freshness(None, NOW) < fresh  # undated is usable, not fresh


def test_a_relevant_item_scores_above_an_irrelevant_one() -> None:
    from factory.research import FeedItem

    relevant = FeedItem("New AI model training data breakthrough", "https://x/1", "s",
                        "2026-11-19", "models and data")
    irrelevant = FeedItem("Local football club wins cup", "https://x/2", "s", "2026-11-19", "sport")
    nexus = spec("nexus-node")
    high = score_item(relevant, nexus, [], NOW)
    low = score_item(irrelevant, nexus, [], NOW)
    assert high.score > low.score
    assert high.relevance > 0 and low.relevance == 0


def test_a_duplicate_of_a_produced_episode_is_rejected() -> None:
    from factory.research import FeedItem

    item = FeedItem("AI models and training data", "https://x/1", "s", "2026-11-19", "models")
    candidate = score_item(item, spec("nexus-node"), ["AI models and training data"], NOW)
    assert candidate.duplicate_of is not None
    assert candidate.score == 0.0
    assert not candidate.acceptable


def test_unsafe_material_is_rejected_for_the_childrens_channel() -> None:
    from factory.research import FeedItem

    item = FeedItem("Cartoon violence and horror for kids", "https://x/1", "s", "2026-11-19",
                    "scary death")
    candidate = score_item(item, spec("natkhat-toons"), [], NOW)
    assert candidate.policy_risk
    assert not candidate.acceptable
    assert set(candidate.policy_risk) <= set(CHILD_UNSAFE)


def test_the_same_rule_does_not_apply_to_the_news_channels() -> None:
    """The blocklist is a children's-channel rule, not a global censorship rule."""

    from factory.research import FeedItem

    item = FeedItem("Security researchers debate a weapon of mass disruption", "https://x/1", "s",
                    "2026-11-19", "weapon")
    assert score_item(item, spec("nexus-node"), [], NOW).policy_risk == []


def test_a_clickbait_shout_is_not_a_good_title() -> None:
    from factory.research import FeedItem

    # Identical text apart from casing, so the only difference the score can see is title quality.
    shouty = FeedItem("AI MODELS TRAIN ON DATA", "https://x/1", "s", "2026-11-19", "ai models data")
    calm = FeedItem("AI models train on data", "https://x/2", "s", "2026-11-19", "ai models data")
    assert score_item(shouty, spec("nexus-node"), [], NOW).score < \
        score_item(calm, spec("nexus-node"), [], NOW).score


# ------------------------------------------------------------------ discovery

def test_sources_are_routed_to_the_channels_they_serve() -> None:
    sources = [Source("arxiv", "https://example.org/a", channels=("nexus-node",)),
               Source("bio", "https://example.org/b", channels=("academic-biohacker",)),
               Source("shared", "https://example.org/c")]
    seen: list[str] = []

    def fetch_text(url: str) -> str:
        seen.append(url)
        return RSS

    discover(spec("academic-biohacker"), sources, fetch_text=fetch_text, now=NOW)
    assert "https://example.org/a" not in seen
    assert "https://example.org/b" in seen
    assert "https://example.org/c" in seen


def test_a_dead_feed_does_not_lose_the_rest_of_the_report() -> None:
    sources = [Source("dead", "https://example.org/dead"), Source("live", "https://example.org/live")]

    def fetch_text(url: str) -> str:
        if "dead" in url:
            raise OSError("connection reset")
        return ATOM

    report = discover(spec("academic-biohacker"), sources, fetch_text=fetch_text, now=NOW)
    assert report.sources == ["live"]
    assert report.errors and "dead" in report.errors[0]
    assert report.candidates, "the live source produced nothing"


def test_the_report_ranks_by_score_and_keeps_rejections_visible() -> None:
    sources = [Source("live", "https://example.org/live")]

    def fetch_text(url: str) -> str:
        return RSS

    report = discover(spec("nexus-node"), sources, fetch_text=fetch_text, now=NOW,
                      history_titles=["AI models and training data"])
    scores = [candidate.score for candidate in report.candidates]
    assert scores == sorted(scores, reverse=True)
    assert any(candidate.duplicate_of for candidate in report.rejected)


def test_the_report_states_what_it_did_not_measure() -> None:
    payload = discover(spec("nexus-node"), [Source("l", "https://e/l")],
                       fetch_text=lambda url: RSS, now=NOW).as_dict()
    assert payload["not_measured"] == ["competition", "predicted views"]
    assert "measured" in payload and payload["measured"]


def test_a_report_round_trips_through_disk(tmp_path: Path) -> None:
    report = discover(spec("nexus-node"), [Source("l", "https://e/l")],
                      fetch_text=lambda url: RSS, now=NOW)
    path = write_report(report, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["channel"] == "nexus-node"
    assert data["candidates"], data
    assert all("score" in candidate for candidate in data["candidates"])


def test_an_item_produces_a_source_ledger_row() -> None:
    report = discover(spec("nexus-node"), [Source("l", "https://e/l", title="Example Feed")],
                      fetch_text=lambda url: RSS, now=NOW)
    row = report.candidates[0].claim_record("models need data", "the feed summary")
    assert row["source_url"].startswith("https://")
    assert row["retrieved"] == NOW.date().isoformat()
    assert row["status"] == "unverified"
    assert row["source_title"] == "Example Feed"


def test_configuration_rejects_a_non_http_source(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [{"id": "x", "url": "ftp://example.org/feed"}]}),
                    encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        load_sources(path)
    assert "http" in str(caught.value)


def test_the_shipped_sources_configuration_is_valid() -> None:
    sources = load_sources()
    assert len(sources) >= 4
    channels = {"nexus-node", "academic-biohacker", "natkhat-toons"}
    for source in sources:
        assert source.url.startswith(("https://", "http://"))
        assert set(source.channels) <= channels


def test_fetching_a_non_http_url_is_refused_before_any_request() -> None:
    with pytest.raises(ValueError):
        fetch("file:///etc/passwd")


def test_tokens_drop_stopwords_and_short_words() -> None:
    # One- and two-letter tokens are dropped on purpose: they are noise in a similarity score.
    assert tokens("The AI and the model") == {"model"}
