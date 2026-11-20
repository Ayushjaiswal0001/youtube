"""Text-to-viseme timing for the 2D rigs.

Edge-TTS gives us **sentence** boundaries (offset + duration per sentence) and, for some
voices, word boundaries. It does **not** give phoneme offsets, and the Hindi neural voices
we use emit no ``WordBoundary`` events at all. So this module is explicit about what it
does:

* it maps graphemes to *viseme classes* with a hand-written Hindi (Devanagari) and English
  table — this is a phone *class* approximation, not a phonetic transcription;
* it distributes those classes over the sentence window **proportionally to their weight**,
  then snaps the window onto the actually-voiced part of the audio when an envelope is
  available;
* it removes flicker with a median filter, a minimum hold time and one-frame transitions.

Result: mouth shape changes roughly 3-6 times a second and lands on the right part of the
line, not phoneme-accurate but visibly articulated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .lipsync import SILENCE_FLOOR, VisemeTrack
from .rig_base import Viseme

# --- viseme vocabulary -------------------------------------------------------------

DEFAULT_OPEN: Dict[str, float] = {
    Viseme.CLOSED: 0.0,
    Viseme.NEUTRAL: 0.18,
    Viseme.SMILE: 0.25,
    Viseme.WIDE: 0.40,      # E / I — spread lips, teeth showing
    Viseme.TEETH: 0.22,     # F / V — upper teeth on lower lip
    Viseme.TONGUE: 0.38,    # L / D / T / N — tongue tip visible
    Viseme.OPEN_SMALL: 0.55,  # schwa, short vowels
    Viseme.OPEN_WIDE: 0.90,   # A / AA — jaw drop
    Viseme.ROUND: 0.70,       # O / U — rounded
    Viseme.SURPRISED: 1.0,
}

MIN_HOLD_MS = 70.0

# --- grapheme tables ---------------------------------------------------------------

# Devanagari independent vowels
_HI_VOWELS: Dict[str, str] = {
    "अ": Viseme.OPEN_SMALL,
    "आ": Viseme.OPEN_WIDE,
    "इ": Viseme.WIDE,
    "ई": Viseme.WIDE,
    "उ": Viseme.ROUND,
    "ऊ": Viseme.ROUND,
    "ऋ": Viseme.OPEN_SMALL,
    "ए": Viseme.WIDE,
    "ऐ": Viseme.WIDE,
    "ओ": Viseme.ROUND,
    "औ": Viseme.ROUND,
    "ऑ": Viseme.OPEN_WIDE,
}

# Devanagari dependent vowel signs (matras)
_HI_MATRAS: Dict[str, str] = {
    "ा": Viseme.OPEN_WIDE,
    "ि": Viseme.WIDE,
    "ी": Viseme.WIDE,
    "ु": Viseme.ROUND,
    "ू": Viseme.ROUND,
    "ृ": Viseme.OPEN_SMALL,
    "े": Viseme.WIDE,
    "ै": Viseme.WIDE,
    "ो": Viseme.ROUND,
    "ौ": Viseme.ROUND,
    "ॉ": Viseme.OPEN_WIDE,
    "ँ": Viseme.NEUTRAL,
    "ं": Viseme.NEUTRAL,
    "ः": Viseme.NEUTRAL,
}

# Devanagari consonants by place/manner
_HI_CONSONANTS: Dict[str, str] = {
    # labials — lips actually close
    "प": Viseme.CLOSED, "फ": Viseme.CLOSED, "ब": Viseme.CLOSED, "भ": Viseme.CLOSED,
    "म": Viseme.CLOSED,
    # dentals / retroflex / laterals — tongue visible
    "त": Viseme.TONGUE, "थ": Viseme.TONGUE, "द": Viseme.TONGUE, "ध": Viseme.TONGUE,
    "न": Viseme.TONGUE, "ट": Viseme.TONGUE, "ठ": Viseme.TONGUE, "ड": Viseme.TONGUE,
    "ढ": Viseme.TONGUE, "ण": Viseme.TONGUE, "ल": Viseme.TONGUE, "ड़": Viseme.TONGUE,
    "ढ़": Viseme.TONGUE,
    # sibilants / fricatives — teeth showing
    "स": Viseme.TEETH, "श": Viseme.TEETH, "ष": Viseme.TEETH, "ह": Viseme.OPEN_SMALL,
    "व": Viseme.TEETH, "ज़": Viseme.TEETH, "फ़": Viseme.TEETH, "क़": Viseme.NEUTRAL,
    "ख़": Viseme.NEUTRAL, "ग़": Viseme.NEUTRAL,
    # palatals — spread
    "च": Viseme.WIDE, "छ": Viseme.WIDE, "ज": Viseme.WIDE, "झ": Viseme.WIDE, "ञ": Viseme.WIDE,
    # velars
    "क": Viseme.NEUTRAL, "ख": Viseme.NEUTRAL, "ग": Viseme.NEUTRAL, "घ": Viseme.NEUTRAL, "ङ": Viseme.NEUTRAL,
    "य": Viseme.NEUTRAL, "र": Viseme.NEUTRAL,
}

_HI_NUKTA_FORMS: Dict[str, str] = {
    "फ": Viseme.TEETH,   # फ़ /f/
    "ज": Viseme.TEETH,   # ज़ /z/
    "क": Viseme.NEUTRAL,  # क़ /q/
    "ख": Viseme.NEUTRAL,  # ख़ /x/
    "ग": Viseme.NEUTRAL,  # ग़ /ɣ/
    "ड": Viseme.TONGUE,   # ड़ /ɽ/
    "ढ": Viseme.TONGUE,   # ढ़ /ɽʰ/
}

_HI_VIRAMA = "्"
_HI_NUKTA = "़"

# Latin letters / digraphs
_EN_DIGRAPHS: Dict[str, str] = {
    "sh": Viseme.WIDE, "ch": Viseme.WIDE, "th": Viseme.TONGUE, "ph": Viseme.TEETH,
    "wh": Viseme.ROUND, "ck": Viseme.NEUTRAL, "ng": Viseme.NEUTRAL, "qu": Viseme.ROUND,
}

_EN_LETTERS: Dict[str, str] = {
    "a": Viseme.OPEN_WIDE, "e": Viseme.WIDE, "i": Viseme.WIDE, "o": Viseme.ROUND,
    "u": Viseme.ROUND, "y": Viseme.WIDE,
    "m": Viseme.CLOSED, "b": Viseme.CLOSED, "p": Viseme.CLOSED,
    "f": Viseme.TEETH, "v": Viseme.TEETH,
    "t": Viseme.TONGUE, "d": Viseme.TONGUE, "n": Viseme.TONGUE, "l": Viseme.TONGUE,
    "s": Viseme.TEETH, "z": Viseme.TEETH, "c": Viseme.NEUTRAL, "j": Viseme.WIDE,
    "k": Viseme.NEUTRAL, "g": Viseme.NEUTRAL, "h": Viseme.OPEN_SMALL,
    "r": Viseme.NEUTRAL, "w": Viseme.ROUND, "q": Viseme.NEUTRAL, "x": Viseme.TEETH,
}

_VOWELS = set("aeiouy") | set(_HI_VOWELS) | set(_HI_MATRAS)

_TIME_WEIGHT = {"vowel": 1.0, "consonant": 0.55, "pause": 1.1, "comma": 0.45}


@dataclass(frozen=True)
class VisemeUnit:
    """One grapheme-scale speech unit with a relative weight."""

    shape: str
    weight: float
    kind: str


@dataclass
class VisemeTimeline:
    """Per-frame mouth shapes for one dialogue line."""

    fps: float
    shapes: List[str] = field(default_factory=list)
    scales: List[float] = field(default_factory=list)
    unit_count: int = 0
    source: str = "text"

    def __len__(self) -> int:
        return len(self.shapes)

    @property
    def duration(self) -> float:
        return len(self.shapes) / self.fps if self.fps else 0.0

    def shape_at(self, t: float) -> str:
        if not self.shapes or t < 0:
            return Viseme.SMILE
        index = min(len(self.shapes) - 1, int(t * self.fps))
        return self.shapes[index]

    def scale_at(self, t: float) -> float:
        if not self.scales or t < 0:
            return DEFAULT_OPEN.get(Viseme.SMILE, 0.25)
        index = min(len(self.scales) - 1, int(t * self.fps))
        return self.scales[index]

    def composition(self) -> Dict[str, float]:
        """Fraction of frames spent in each shape — handy for diagnostics/tests."""

        counts: Dict[str, int] = {}
        for shape in self.shapes:
            counts[shape] = counts.get(shape, 0) + 1
        total = len(self.shapes) or 1
        return {shape: count / total for shape, count in sorted(counts.items())}

    def change_rate(self) -> float:
        """Shape changes per second (flicker metric)."""

        if len(self.shapes) < 2:
            return 0.0
        changes = sum(1 for a, b in zip(self.shapes, self.shapes[1:]) if a != b)
        return changes / self.duration if self.duration else 0.0

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_text(
        cls,
        text: str,
        duration: float,
        fps: float = 30.0,
        *,
        boundaries: Optional[Sequence[dict]] = None,
        envelope: Optional[VisemeTrack] = None,
        min_hold_ms: float = MIN_HOLD_MS,
    ) -> "VisemeTimeline":
        if fps <= 0:
            raise ValueError("fps must be positive")
        units = parse_units(text)
        if not units or duration <= 0:
            return cls(fps=fps, shapes=[], scales=[], unit_count=len(units), source="empty")

        total_frames = max(1, int(round(duration * fps)))
        windows = _sentence_windows(text, units, boundaries, duration, envelope, fps)
        timeline = ["neutral"] * total_frames
        scales = [DEFAULT_OPEN[Viseme.NEUTRAL]] * total_frames

        for start_time, end_time, window_units in windows:
            first = max(0, min(total_frames - 1, int(round(start_time * fps))))
            last = max(first + 1, min(total_frames, int(round(end_time * fps))))
            _fill_window(timeline, scales, first, last, window_units)

        min_frames = max(1, int(round(min_hold_ms / 1000.0 * fps)))
        _median_filter(timeline, scales)
        _enforce_min_hold(timeline, scales, min_frames)
        _soften_transitions(timeline, scales)

        if envelope is not None and len(envelope):
            for index in range(total_frames):
                if envelope.at(index / fps) <= SILENCE_FLOOR:
                    timeline[index] = Viseme.CLOSED
                    scales[index] = 0.0
            # Silence masking can leave one-frame speaking shapes at the edges of a word;
            # merge those so the mouth does not flash for a single frame.
            _enforce_min_hold(timeline, scales, min_frames, speech_only=True)
        return cls(fps=fps, shapes=timeline, scales=scales, unit_count=len(units), source="text+audio")


# --- text parsing ------------------------------------------------------------------

def _normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip().lower())


def _split_words(text: str) -> List[str]:
    """Split on whitespace and punctuation but keep the punctuation as its own token."""

    return re.findall(r"[^\s]+", text)


def parse_units(text: str) -> List[VisemeUnit]:
    """Map narration text onto weighted viseme units (Hindi + Latin)."""

    units: List[VisemeUnit] = []
    for word in _split_words(_normalise(text)):
        trailing = ""
        while word and word[-1] in ",;:!?.-—…।॥":
            trailing = word[-1] + trailing
            word = word[:-1]
        if word:
            units.extend(_word_units(word))
        for mark in trailing:
            kind = "pause" if mark in ".!?।॥…" else "comma"
            units.append(VisemeUnit(Viseme.NEUTRAL, _TIME_WEIGHT[kind], kind))
    return units


def _word_units(word: str) -> List[VisemeUnit]:
    if any("\u0900" <= ch <= "\u097f" for ch in word):
        return _hindi_units(word)
    return _latin_units(word)


def _hindi_units(word: str) -> List[VisemeUnit]:
    units: List[VisemeUnit] = []
    index = 0
    length = len(word)
    while index < length:
        char = word[index]
        if char in _HI_CONSONANTS:
            shape = _HI_CONSONANTS[char]
            # A consonant with a nukta or virama is still one cluster.
            following = word[index + 1] if index + 1 < length else ""
            if following == _HI_NUKTA:
                # फ + ़ is /f/ (teeth), ड + ़ is a retroflex flap — the nukta changes the phone
                shape = _HI_NUKTA_FORMS.get(char, shape)
                index += 1
                following = word[index + 1] if index + 1 < length else ""
            if following == _HI_VIRAMA:
                # conjunct: consonant is unreleased and carries no vowel
                units.append(VisemeUnit(shape, _TIME_WEIGHT["consonant"] * 0.7, "consonant"))
                index += 2
                continue
            if following in _HI_MATRAS:
                matra_shape = _HI_MATRAS[following]
                if matra_shape == Viseme.NEUTRAL:  # anusvara/visarga on top of the consonant
                    units.append(VisemeUnit(shape, _TIME_WEIGHT["consonant"], "consonant"))
                    units.append(VisemeUnit(matra_shape, 0.3, "consonant"))
                    index += 2
                    continue
                units.append(VisemeUnit(shape, _TIME_WEIGHT["consonant"] * 0.85, "consonant"))
                units.append(VisemeUnit(matra_shape, _TIME_WEIGHT["vowel"], "vowel"))
                index += 2
                continue
            # Bare consonant: inherent 'a', but Hindi drops it word-finally.
            at_end = index + 1 >= length
            if at_end:
                units.append(VisemeUnit(_final_shape(shape), _TIME_WEIGHT["consonant"], "consonant"))
            else:
                units.append(VisemeUnit(shape, _TIME_WEIGHT["consonant"], "consonant"))
                units.append(VisemeUnit(Viseme.OPEN_SMALL, _TIME_WEIGHT["vowel"] * 0.55, "vowel"))
            index += 1
            continue
        if char in _HI_VOWELS:
            units.append(VisemeUnit(_HI_VOWELS[char], _TIME_WEIGHT["vowel"], "vowel"))
        elif char in _HI_MATRAS:
            shape = _HI_MATRAS[char]
            units.append(VisemeUnit(shape, _TIME_WEIGHT["vowel"], "vowel"))
        elif char.isspace():
            pass
        index += 1
    return units


def _final_shape(shape: str) -> str:
    """Word-final consonants are unreleased — keep them closed-ish."""

    if shape in (Viseme.CLOSED, Viseme.TEETH, Viseme.TONGUE):
        return shape
    return Viseme.NEUTRAL


def _latin_units(word: str) -> List[VisemeUnit]:
    units: List[VisemeUnit] = []
    index = 0
    length = len(word)
    while index < length:
        pair = word[index : index + 2]
        if pair in _EN_DIGRAPHS:
            units.append(VisemeUnit(_EN_DIGRAPHS[pair], _TIME_WEIGHT["consonant"], "consonant"))
            index += 2
            continue
        char = word[index]
        if char == "e" and index == length - 1 and length > 2:
            # silent final 'e'
            index += 1
            continue
        if char in _EN_LETTERS:
            shape = _EN_LETTERS[char]
            kind = "vowel" if char in _VOWELS else "consonant"
            units.append(VisemeUnit(shape, _TIME_WEIGHT[kind], kind))
        index += 1
    return units


# --- windowing ---------------------------------------------------------------------

def _sentence_windows(
    text: str,
    units: List[VisemeUnit],
    boundaries: Optional[Sequence[dict]],
    duration: float,
    envelope: Optional[VisemeTrack],
    fps: float,
) -> List[Tuple[float, float, List[VisemeUnit]]]:
    """Group units into time windows, using sentence boundaries when they are usable."""

    usable = [
        item for item in (boundaries or [])
        if isinstance(item, dict)
        and float(item.get("end", 0.0)) > float(item.get("start", 0.0))
        and str(item.get("text", "")).strip()
    ]
    if len(usable) >= 2 and _boundaries_cover_text(usable, text, duration):
        windows: List[Tuple[float, float, List[VisemeUnit]]] = []
        for item in usable:
            window_units = parse_units(str(item.get("text", "")))
            start = float(item["start"])
            end = float(item["end"])
            windows.append(_snap_to_voice(start, end, window_units, envelope, fps))
        if windows:
            return windows
    # Single window over the whole line
    return [_snap_to_voice(0.0, duration, units, envelope, fps)]


def _boundaries_cover_text(boundaries: Sequence[dict], text: str, duration: float) -> bool:
    """Reject boundaries that clearly do not describe this text (e.g. stale cache)."""

    joined = " ".join(str(item.get("text", "")).strip() for item in boundaries)
    if len(joined) < max(3, int(len(text.strip()) * 0.5)):
        return False
    total = sum(float(item["end"]) - float(item["start"]) for item in boundaries)
    return 0.5 <= total <= duration * 1.2 + 0.5


def _snap_to_voice(
    start: float,
    end: float,
    units: List[VisemeUnit],
    envelope: Optional[VisemeTrack],
    fps: float,
) -> Tuple[float, float, List[VisemeUnit]]:
    """Trim a window onto the frames that actually contain speech."""

    if envelope is None or not len(envelope):
        return start, end, units
    first_voiced = None
    last_voiced = None
    index = int(start * fps)
    limit = int(end * fps)
    while index < limit and index < len(envelope):
        if envelope.openness[index] > SILENCE_FLOOR:
            first_voiced = index
            break
        index += 1
    index = min(limit, len(envelope)) - 1
    while index >= int(start * fps):
        if envelope.openness[index] > SILENCE_FLOOR:
            last_voiced = index + 1
            break
        index -= 1
    if first_voiced is None or last_voiced is None or last_voiced - first_voiced < 2:
        return start, end, units
    trimmed_start = first_voiced / fps
    trimmed_end = last_voiced / fps
    if trimmed_end - trimmed_start < 0.08:
        return start, end, units
    return trimmed_start, trimmed_end, units


def _fill_window(
    timeline: List[str],
    scales: List[float],
    first: int,
    last: int,
    units: List[VisemeUnit],
) -> None:
    total_weight = sum(unit.weight for unit in units) or 1.0
    span = max(1, last - first)
    cursor = float(first)
    for unit in units:
        length = max(1.0, span * (unit.weight / total_weight))
        start_index = int(round(cursor))
        end_index = min(last, max(start_index + 1, int(round(cursor + length))))
        shape = unit.shape
        for index in range(max(0, start_index), min(len(timeline), end_index)):
            timeline[index] = shape
            scales[index] = DEFAULT_OPEN.get(shape, 0.3)
        cursor += length
        if cursor >= last:
            break


# --- smoothing ---------------------------------------------------------------------

def _median_filter(timeline: List[str], scales: List[float], width: int = 3) -> None:
    half = width // 2
    original = list(timeline)
    for index in range(len(timeline)):
        lo = max(0, index - half)
        hi = min(len(timeline), index + half + 1)
        window = original[lo:hi]
        counts: Dict[str, int] = {}
        for shape in window:
            counts[shape] = counts.get(shape, 0) + 1
        timeline[index] = max(counts.items(), key=lambda item: (item[1], -abs(window.index(item[0]) - (index - lo))))[0]
    for index, shape in enumerate(timeline):
        scales[index] = DEFAULT_OPEN.get(shape, scales[index])


def _enforce_min_hold(
    timeline: List[str],
    scales: List[float],
    min_frames: int,
    speech_only: bool = False,
) -> None:
    """Absorb runs that are shorter than the minimum hold into a neighbour.

    With ``speech_only`` a run made of closed frames is left alone — those come from
    genuine silence and should stay short rather than be stretched over speech.
    """

    if min_frames <= 1 or not timeline:
        return
    changed = True
    passes = 0
    while changed and passes < 8:
        changed = False
        passes += 1
        index = 0
        while index < len(timeline):
            run_start = index
            while index < len(timeline) and timeline[index] == timeline[run_start]:
                index += 1
            run_length = index - run_start
            if run_length >= min_frames:
                continue
            if speech_only and timeline[run_start] == Viseme.CLOSED:
                continue
            before = timeline[run_start - 1] if run_start > 0 else None
            after = timeline[index] if index < len(timeline) else None
            if before is None and after is None:
                continue
            replacement = before if before is not None else after
            if before is not None and after is not None and before != after:
                # grow the neighbouring run that is already longer
                before_len = 0
                cursor = run_start - 1
                while cursor >= 0 and timeline[cursor] == before:
                    before_len += 1
                    cursor -= 1
                after_len = 0
                cursor = index
                while cursor < len(timeline) and timeline[cursor] == after:
                    after_len += 1
                    cursor += 1
                replacement = before if before_len >= after_len else after
            for cursor in range(run_start, index):
                timeline[cursor] = replacement  # type: ignore[assignment]
                scales[cursor] = DEFAULT_OPEN.get(replacement, 0.3)  # type: ignore[arg-type]
            changed = True


def _soften_transitions(timeline: List[str], scales: List[float]) -> None:
    """Coarticulation: one transition frame carries a partial opening.

    Real speech blends neighbouring targets; without this the mouth snaps between shapes
    at full amplitude, which reads as a mechanical flip.
    """

    if len(timeline) < 3:
        return
    original = list(timeline)
    for index in range(1, len(timeline) - 1):
        if original[index] != original[index - 1] and original[index] != original[index + 1]:
            continue  # already handled by the hold filter
    for index in range(1, len(timeline)):
        if original[index] != original[index - 1]:
            scale = min(scales[index], DEFAULT_OPEN.get(original[index], 0.3) * 0.55)
            scales[index] = scale
    for index in range(0, len(timeline) - 1):
        if original[index] != original[index + 1]:
            scales[index] = min(scales[index], DEFAULT_OPEN.get(original[index], 0.3) * 0.7)
