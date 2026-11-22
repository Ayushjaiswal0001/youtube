"""Topic discovery and a source ledger for a public, three-channel factory.

The factory used to start from a hand-written topic bank. That is fine for the first few episodes and
useless at channel scale: nothing finds a new story, nothing records where a claim came from, and
nothing stops the same idea being produced twice under a different title.

This module does the part that can be automated honestly:

* fetch permitted sources (official RSS/Atom feeds - no scraping, no paywall, no rate-limit games);
* extract candidate topics from the items those feeds publish;
* score them on things that are actually measurable (niche term overlap, freshness, title quality)
  and refuse to invent the ones that are not (competition and "predicted views" are not measured here,
  and the report says so);
* deduplicate against everything the channel has already produced;
* write a research record per candidate with a source ledger: claim, source title, URL, publication
  date, retrieval date, verification status.

What it does not do is write beats. A candidate becomes an episode only when a human authors its
beats into the topic bank, because "generate a script from a headline" is exactly how a channel ends up
with twelve videos that say the same nothing.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import math
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

SOURCES_PATH = Path("content/research/sources.json")
REPORTS_DIR = Path("build/research")

#: How fast freshness decays. Half of the score is gone after this many days.
FRESHNESS_HALF_LIFE_DAYS = 6.0

#: Terms that make a candidate unsuitable for a children's channel regardless of its score.
CHILD_UNSAFE = ("murder", "kill", "suicide", "weapon", "drug", "gambling", "violence",
                "horror", "terror", "death", "sex", "alcohol")

#: Words that carry no topical signal and would otherwise inflate similarity.
STOPWORDS = frozenset("""a an the and or but of for to in on at by with from as is are was were be been
being this that these those it its into over under about after before more most other some such no nor
not only own same so than too very can will just should now new""".split())

USER_AGENT = "X100-Factory/1.0 (research; +https://github.com/Ayushjaiswal0001/youtube)"


# --------------------------------------------------------------------------- sources


@dataclass(frozen=True)
class Source:
    """A permitted feed. ``channels`` says which channels may use it."""

    id: str
    url: str
    title: str = ""
    kind: str = "rss"
    channels: tuple[str, ...] = ()

    def serves(self, slug: str) -> bool:
        return not self.channels or slug in self.channels


@dataclass
class FeedItem:
    title: str
    link: str
    source_id: str
    published: Optional[str] = None
    summary: str = ""


def load_sources(path: Path | str = SOURCES_PATH) -> List[Source]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = []
    for entry in data.get("sources", []):
        url = str(entry.get("url", "")).strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"source {entry.get('id')!r} is not an http(s) URL")
        sources.append(Source(id=str(entry["id"]), url=url, title=str(entry.get("title", "")),
                              kind=str(entry.get("kind", "rss")),
                              channels=tuple(entry.get("channels", ()))))
    if not sources:
        raise ValueError("no research sources configured")
    return sources


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_text: str, source: Source) -> List[FeedItem]:
    """RSS 2.0, RSS 1.0 and Atom, without a dependency.

    Feeds in the wild disagree about everything, so this reads by local tag name and takes the first
    non-empty value it finds rather than assuming a namespace.
    """

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"{source.id}: not a parseable feed: {exc}") from exc

    root_name = _local(root.tag)
    if root_name not in ("rss", "feed", "rdf"):
        # A block page or an error page is well-formed XML with no items, so an unchecked parse makes
        # a dead or blocked source look like a feed that simply had nothing to say.
        raise ValueError(f"{source.id}: root element <{root_name}> is not a feed")

    items: List[FeedItem] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = link = published = summary = ""
        for child in node:
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "title" and not title:
                title = text
            elif name == "link" and not link:
                link = (child.attrib.get("href") or text).strip()
            elif name in ("pubdate", "published", "updated", "date") and not published:
                published = text
            elif name in ("description", "summary", "content") and not summary:
                summary = text
        if title and link:
            items.append(FeedItem(title=_strip_markup(title), link=link, source_id=source.id,
                                  published=_iso_date(published), summary=_strip_markup(summary)[:400]))
    return items


def _strip_markup(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").replace("&amp;", "&").replace("&quot;", '"').strip()


def _iso_date(value: str) -> Optional[str]:
    if not value:
        return None
    for parser in (email.utils.parsedate_to_datetime, _parse_iso):
        try:
            parsed = parser(value)
        except (TypeError, ValueError):
            continue
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    return None


def _parse_iso(value: str) -> Optional[datetime]:
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fetch(url: str, *, timeout: float = 12.0, max_bytes: int = 2_000_000) -> str:
    """Read one permitted feed. Public sources only; no credentials are ever sent."""

    if not url.startswith(("https://", "http://")):
        raise ValueError(f"refusing to fetch a non-http(s) URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed http(s)
        payload = response.read(max_bytes)
    return payload.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- scoring


def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower())
            if word not in STOPWORDS and len(word) > 2}


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Candidate:
    title: str
    link: str
    source_id: str
    source_title: str
    published: Optional[str]
    retrieved: str
    summary: str
    relevance: float
    freshness: float
    score: float
    reasons: List[str] = field(default_factory=list)
    duplicate_of: Optional[str] = None
    policy_risk: List[str] = field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        return not self.policy_risk and self.duplicate_of is None and self.score > 0

    def claim_record(self, claim: str, evidence: str, status: str = "unverified") -> Dict[str, Any]:
        """One row of the source ledger: what is asserted, and where it came from."""

        return {"claim": claim, "source_title": self.source_title or self.source_id,
                "source_url": self.link, "published": self.published,
                "retrieved": self.retrieved, "evidence": evidence, "status": status}

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["acceptable"] = self.acceptable
        return payload


@dataclass
class ResearchReport:
    channel: str
    generated_at: str
    sources: List[str]
    candidates: List[Candidate]
    rejected: List[Candidate]

    def as_dict(self) -> Dict[str, Any]:
        return {"channel": self.channel, "generated_at": self.generated_at,
                "sources": self.sources,
                "candidates": [c.as_dict() for c in self.candidates],
                "rejected": [c.as_dict() for c in self.rejected],
                "counts": {"candidates": len(self.candidates), "rejected": len(self.rejected)},
                "measured": ["relevance", "freshness", "title quality"],
                "not_measured": ["competition", "predicted views"],
                "note": ("Scores rank leads; they do not predict performance. Nothing becomes an "
                         "episode until its beats are authored and its claims are verified.")}


def _freshness(published: Optional[str], now: datetime) -> float:
    if not published:
        return 0.4  # undated items are usable but not fresh
    try:
        when = datetime.fromisoformat(published).replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.4
    age_days = max(0.0, (now - when).total_seconds() / 86400.0)
    return round(0.5 ** (age_days / FRESHNESS_HALF_LIFE_DAYS), 4)


def _relevance(item: FeedItem, spec) -> tuple[float, List[str]]:
    """Overlap between the item and the channel's niche, queries and tags."""

    wanted = tokens(" ".join([getattr(spec, "niche", ""), " ".join(getattr(spec, "queries", ())),
                              " ".join(getattr(spec, "tags", ()))]))
    have = tokens(f"{item.title} {item.summary}")
    if not wanted or not have:
        return 0.0, ["no niche terms configured"]
    overlap = wanted & have
    base = len(overlap) / math.sqrt(len(wanted) * len(have)) * 2.0  # cosine-ish, 0..1 in practice
    title_hits = tokens(item.title) & wanted
    bonus = 0.25 if title_hits else 0.0
    reasons = [f"matched {', '.join(sorted(overlap)[:5])}"] if overlap else ["no niche match"]
    return round(min(1.0, base + bonus), 4), reasons


def _title_quality(title: str) -> float:
    words = len(title.split())
    if not 4 <= words <= 16:
        return 0.0
    if title.isupper() or title.endswith("!!!"):
        return 0.2
    return 1.0


def score_item(item: FeedItem, spec, history_titles: Sequence[str], now: datetime) -> Candidate:
    relevance, reasons = _relevance(item, spec)
    freshness = _freshness(item.published, now)
    quality = _title_quality(item.title)
    lowered = f"{item.title} {item.summary}".lower()
    risk = sorted({word for word in CHILD_UNSAFE if word in lowered}) if spec.slug == "natkhat-toons" else []

    duplicate_of = None
    for previous in history_titles:
        if jaccard(tokens(item.title), tokens(previous)) >= 0.6:
            duplicate_of = previous
            break

    # Weights are a stated editorial policy, not a measurement of audience demand.
    score = round(0.55 * relevance + 0.30 * freshness + 0.15 * quality, 4)
    if risk or duplicate_of:
        score = 0.0
    if quality == 0.0:
        reasons.append("title length outside 4-16 words")
    return Candidate(title=item.title, link=item.link, source_id=item.source_id,
                     source_title="", published=item.published,
                     retrieved=now.date().isoformat(), summary=item.summary,
                     relevance=relevance, freshness=freshness, score=score, reasons=reasons,
                     duplicate_of=duplicate_of, policy_risk=risk)


# --------------------------------------------------------------------------- discovery


def discover(spec, sources: Sequence[Source], *, fetch_text: Callable[[str], str] = fetch,
             now: Optional[datetime] = None, history_titles: Sequence[str] = (),
             limit: int = 20) -> ResearchReport:
    """Fetch every permitted source, score what it published, and rank the survivors."""

    now = now or datetime.now(timezone.utc)
    used: List[str] = []
    candidates: List[Candidate] = []
    errors: List[str] = []
    for source in sources:
        if not source.serves(spec.slug):
            continue
        try:
            items = parse_feed(fetch_text(source.url), source)
        except (ValueError, OSError, urllib.error.URLError) as exc:
            # A dead feed must not stop the run: the report records it and the other sources still work.
            errors.append(f"{source.id}: {exc}")
            continue
        used.append(source.id)
        for item in items:
            candidate = score_item(item, spec, history_titles, now)
            candidate.source_title = source.title or source.id
            candidates.append(candidate)

    candidates.sort(key=lambda c: (-c.score, c.title))
    accepted = [c for c in candidates if c.acceptable][:limit]
    rejected = [c for c in candidates if not c.acceptable][:limit]
    report = ResearchReport(channel=spec.slug, generated_at=now.isoformat(timespec="seconds"),
                            sources=used, candidates=accepted, rejected=rejected)
    report.errors = errors  # type: ignore[attr-defined]
    return report


def write_report(report: ResearchReport, directory: Path | str = REPORTS_DIR) -> Path:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at[:10]
    path = out / f"{report.channel}-{stamp}.json"
    payload = report.as_dict()
    payload["errors"] = list(getattr(report, "errors", []))
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def digest(report: ResearchReport) -> str:
    """Stable identity for a report, for the run journal."""

    body = json.dumps([c.link for c in report.candidates], sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
