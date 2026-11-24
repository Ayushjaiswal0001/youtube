"""Figures a sentence actually states, and nothing else.

A chart is the most authoritative-looking object on a card, so an invented bar is the most damaging
thing the visual engine could draw. This module exists to make that structurally hard: it finds only
figures that are present in the narration, keeps the exact phrase and its character offsets, and
refuses to turn vague language ("thousands", "half") into a number.

Nothing here converts between units, rounds, or infers a baseline. "40 percent" is 40 percent; "2x
faster" is a multiplier of 2; "thousands of examples" is a magnitude with no value at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Numeric magnitudes need a unit or a counted noun, otherwise a year or a product name becomes a chart.
_UNIT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("percent", "%"),
    ("per cent", "%"),
    ("%", "%"),
    ("times", "x"),
    ("x", "x"),
    ("seconds", "s"),
    ("second", "s"),
    ("minutes", "min"),
    ("minute", "min"),
    ("hours", "h"),
    ("hour", "h"),
    ("milliseconds", "ms"),
    ("ms", "ms"),
)

# Words that name a magnitude without stating one. They may be drawn as "many", never as a ratio.
_VAGUE_QUANTIFIERS: tuple[str, ...] = ("thousands", "hundreds", "millions", "billions", "dozens",
                                       "half", "double", "triple", "twice", "a fraction")

_COUNTED_NOUNS = ("examples", "robots", "demos", "demonstrations", "videos", "models", "hours",
                  "years", "people", "studies", "samples", "datasets", "cameras", "jobs", "tasks",
                  "clips", "frames", "images", "tests", "prompts", "tokens", "parameters", "gpus",
                  "cores", "lines", "slides", "pages")

_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
                    r"(?=$|[^\w]|[xX%](?![A-Za-z0-9]))")
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class Figure:
    """One stated figure. ``value`` is None unless the sentence states a number."""

    phrase: str
    value: float | None
    unit: str
    kind: str          # "percent" | "multiplier" | "duration" | "count" | "vague"
    start: int
    end: int

    @property
    def numeric(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict:
        return {"phrase": self.phrase, "value": self.value, "unit": self.unit, "kind": self.kind,
                "start": self.start, "end": self.end}


def _unit_for(text: str, number_end: int) -> tuple[str, str] | None:
    """The unit that follows a number, as (kind, symbol), or None when nothing qualifies.

    Attached symbols count: "40%" and "2x" are as explicit as "40 percent" and "2 times".
    """

    attached = text[number_end:number_end + 1]
    if attached == "%":
        return "percent", "%"
    if attached.lower() == "x" and (len(text) <= number_end + 1
                                    or not text[number_end + 1].isalpha()):
        return "multiplier", "x"

    tail = text[number_end:number_end + 24].strip().lower()
    if not tail:
        return None
    tail = " " + tail
    for word, symbol in _UNIT_PATTERNS:
        if tail.startswith(" " + word):
            if symbol == "%":
                return "percent", symbol
            if symbol == "x":
                return "multiplier", symbol
            return "duration", symbol
    for noun in _COUNTED_NOUNS:
        if tail.startswith(" " + noun):
            return "count", ""
    return None


def extract(text: str) -> list[Figure]:
    """Every figure the sentence states, in the order it states them. Never invents one."""

    narration = str(text or "")
    lowered = narration.lower()
    figures: list[Figure] = []
    taken: list[tuple[int, int]] = []

    for match in _NUMBER.finditer(narration):
        raw = match.group(1)
        digits = raw.replace(",", "")
        if _YEAR.match(digits):
            # A year is a date, not a magnitude: "in 2026" is not a chart.
            continue
        unit = _unit_for(narration, match.end())
        if unit is None:
            continue
        kind, symbol = unit
        value = float(digits)
        if value.is_integer():
            value = int(value)  # type: ignore[assignment]
        phrase_start = match.start()
        phrase_end = min(len(narration), match.end() + 1 + len(_phrase_tail(lowered, match.end())))
        figures.append(Figure(phrase=narration[phrase_start:phrase_end].strip(),
                              value=float(value), unit=symbol, kind=kind,
                              start=phrase_start, end=phrase_end))
        taken.append((phrase_start, phrase_end))

    for word in _VAGUE_QUANTIFIERS:
        for match in re.finditer(rf"\b{re.escape(word)}\b", lowered):
            if any(start <= match.start() < end for start, end in taken):
                continue
            phrase = _vague_phrase(narration, match.start(), match.end())
            figures.append(Figure(phrase=phrase, value=None, unit="", kind="vague",
                                  start=match.start(), end=match.start() + len(phrase)))
            taken.append((match.start(), match.start() + len(phrase)))

    figures.sort(key=lambda figure: figure.start)
    return figures


def _phrase_tail(lowered: str, end: int) -> str:
    """The unit word after a number, so the phrase on the plate is the phrase that was spoken."""

    if lowered[end:end + 1] in {"%"}:
        return "%"
    if lowered[end:end + 1] == "x":
        return "x"
    tail = lowered[end:end + 24].strip()
    for word, _ in _UNIT_PATTERNS:
        if tail.startswith(word):
            return word
    for noun in _COUNTED_NOUNS:
        if tail.startswith(noun):
            return noun
    return ""


def _vague_phrase(narration: str, start: int, end: int) -> str:
    """A vague quantifier plus the noun it quantifies: "thousands of examples"."""

    rest = narration[end:end + 40]
    match = re.match(r"\s+(?:of\s+)?(?:(?:the|a|an)\s+)?([A-Za-z][A-Za-z'-]*)", rest)
    if not match:
        return narration[start:end]
    return narration[start:end + match.end()].strip()


def numeric_figures(figures: list[Figure]) -> list[Figure]:
    """Only the figures that carry a number. The chart decision itself lives in the asset layer."""

    return [figure for figure in figures if figure.numeric]
