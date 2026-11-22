"""Performance direction: reaction beats and speech-driven accents.

T32 gave the characters eyes, T33 gave them bodies, but the two were driven separately: the
speaker performed an authored pose while the listener stood in an authored pose. Real
conversation is full of small overlays — a nod while being spoken to, a blink at the end of a
sentence, a lean back at a shocking line, a bounce when you insist on something.

This module adds one thin layer above pose, motion and face:

    Beat              "at 4.2 s, nod, strength 0.8" (data, no drawing)
    Accent            the offsets that beat produces on one frame
    PerformanceTrack  beats -> accent at time t
    PerformanceFace   a FaceController wrapper that adds brow / lid / pupil accents
    plan_performance  dialogue -> beats for the speaker and for the listener

Design rules
------------
* Additive only. With no beats the accent is empty and every frame is bit-identical to the
  ungarnished render, which is how the existing goldens stay valid.
* Deterministic. Jitter comes from a seeded RNG keyed on the scene, so a re-render matches.
* Beats are bounded: at most six per character per scene and never closer than 0.55 s,
  because the failure mode of a system like this is over-animated clowns.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from studio.characters.locomotion import BodyState

BEAT_KINDS: Tuple[str, ...] = (
    "nod", "shake", "lean_in", "recoil", "chuckle", "bounce", "blink", "widen",
    "point_beat",
)

# Default seconds each beat lasts, and how strong it reads.
_DEFAULT_DURATION = {
    "nod": 0.70,
    "shake": 0.62,
    "lean_in": 0.90,
    "recoil": 0.85,
    "chuckle": 0.75,
    "bounce": 0.52,
    "blink": 0.18,
    "widen": 0.80,
    "point_beat": 0.70,
}

MAX_BEATS = 6
MIN_GAP = 0.55


@dataclass(frozen=True)
class Beat:
    at: float
    kind: str
    strength: float = 1.0
    duration: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in BEAT_KINDS:
            raise ValueError(f"unknown beat kind '{self.kind}' (known: {', '.join(BEAT_KINDS)})")

    @property
    def span(self) -> float:
        return self.duration or _DEFAULT_DURATION[self.kind]


@dataclass(frozen=True)
class Accent:
    """Offsets one beat family contributes to a single frame."""

    head_tilt: float = 0.0
    lean: float = 0.0
    squash: float = 1.0
    jump_y: float = 0.0
    brow_y: float = 0.0
    lid: float = 0.0
    pupil_scale: float = 1.0
    source: str = ""

    def is_empty(self) -> bool:
        return (
            self.head_tilt == 0.0
            and self.lean == 0.0
            and self.squash == 1.0
            and self.jump_y == 0.0
            and self.brow_y == 0.0
            and self.lid == 0.0
            and self.pupil_scale == 1.0
        )

    def merged_with(self, other: "Accent") -> "Accent":
        return Accent(
            head_tilt=self.head_tilt + other.head_tilt,
            lean=self.lean + other.lean,
            squash=self.squash * other.squash,
            jump_y=self.jump_y + other.jump_y,
            brow_y=self.brow_y + other.brow_y,
            lid=max(self.lid, other.lid),
            pupil_scale=max(self.pupil_scale, other.pupil_scale),
            source=other.source or self.source,
        )

    def on_body(self, body: BodyState) -> BodyState:
        """Layer the accent on a locomotion frame without stealing the motion's identity."""

        if self.is_empty():
            return body
        return BodyState(
            hip_x=body.hip_x,
            jump_y=body.jump_y + self.jump_y,
            lean=body.lean + self.lean,
            leg_l=body.leg_l,
            leg_r=body.leg_r,
            arm_l=body.arm_l,
            arm_r=body.arm_r,
            head_tilt=body.head_tilt + self.head_tilt,
            squash=body.squash * self.squash,
            mode=body.mode,
        )

    def on_face(self, state):
        """Layer the accent on an EyeState (brows, lids, pupils)."""

        if self.is_empty() or state is None:
            return state
        lid_left = min(1.0, state.lid_left + self.lid)
        lid_right = min(1.0, state.lid_right + self.lid)
        return replace(
            state,
            lid_left=lid_left,
            lid_right=lid_right,
            brow_y=max(-1.0, min(1.0, state.brow_y + self.brow_y)),
            pupil_scale=state.pupil_scale * self.pupil_scale,
        )


def _envelope(kind: str, u: float, strength: float) -> Accent:
    """Accent for one beat at normalised progress ``u`` in [0, 1]."""

    if u <= 0.0 or u >= 1.0:
        return Accent()

    if kind == "nod":
        decay = (1.0 - u) ** 1.4
        return Accent(head_tilt=-0.30 * strength * math.sin(2 * math.pi * 2.2 * u) * decay,
                      brow_y=0.06 * strength * decay, source=kind)
    if kind == "shake":
        decay = (1.0 - u) ** 1.2
        return Accent(head_tilt=0.26 * strength * math.sin(2 * math.pi * 2.6 * u) * decay,
                      source=kind)
    if kind == "lean_in":
        env = math.sin(math.pi * u) ** 0.7
        return Accent(lean=0.10 * strength * env, head_tilt=-0.05 * strength * env,
                      source=kind)
    if kind == "recoil":
        if u < 0.18:
            env = u / 0.18
        else:
            env = math.exp(-3.4 * (u - 0.18))
        return Accent(lean=-0.20 * strength * env, head_tilt=0.12 * strength * env,
                      jump_y=-0.008 * strength * env,
                      brow_y=0.42 * strength * env, lid=-0.10 * strength * env,
                      pupil_scale=1.0 + 0.14 * strength * env, source=kind)
    if kind == "chuckle":
        decay = (1.0 - u) ** 1.3
        return Accent(squash=1.0 + 0.035 * strength * math.sin(2 * math.pi * 6.0 * u) * decay,
                      jump_y=-0.02 * strength * abs(math.sin(2 * math.pi * 3.0 * u)) * decay,
                      brow_y=0.10 * strength * decay, source=kind)
    if kind == "bounce":
        env = math.sin(math.pi * u)
        return Accent(jump_y=-0.05 * strength * env, squash=1.0 + 0.05 * strength * env,
                      brow_y=0.16 * strength * env, source=kind)
    if kind == "blink":
        env = min(1.0, 1.35 * math.sin(math.pi * u))
        return Accent(lid=env * strength, source=kind)
    if kind == "widen":
        env = math.sin(math.pi * min(1.0, u * 1.15)) if u < 0.87 else 0.0
        return Accent(brow_y=0.40 * strength * env, lid=-0.08 * strength * env,
                      pupil_scale=1.0 + 0.12 * strength * env, source=kind)
    if kind == "point_beat":
        env = math.sin(math.pi * u)
        return Accent(lean=0.06 * strength * env, head_tilt=0.05 * strength * env,
                      source=kind)
    return Accent()


class PerformanceTrack:
    """Deterministic beat player for one character in one scene."""

    def __init__(self, beats: Iterable[Beat] = (), duration: float = 5.0) -> None:
        self.duration = max(0.0, float(duration))
        self.beats: Tuple[Beat, ...] = tuple(
            sorted((beat for beat in beats if beat.at < self.duration),
                   key=lambda beat: beat.at)
        )

    def accent_at(self, t: float) -> Accent:
        accent = Accent()
        for beat in self.beats:
            if t < beat.at:
                break
            span = beat.span
            if t > beat.at + span:
                continue
            accent = accent.merged_with(_envelope(beat.kind, (t - beat.at) / span,
                                                  beat.strength))
        return accent

    def active_kinds(self, t: float) -> Tuple[str, ...]:
        return tuple(
            beat.kind for beat in self.beats if beat.at <= t <= beat.at + beat.span
        )


class PerformanceFace:
    """FaceController decorator: same API, plus the beat accents."""

    def __init__(self, controller, track: PerformanceTrack) -> None:
        self.controller = controller
        self.track = track

    def __getattr__(self, name):
        return getattr(self.controller, name)

    def state_at(self, t: float):
        return self.track.accent_at(t).on_face(self.controller.state_at(t))


# -- dialogue analysis ---------------------------------------------------------

_SENTENCE_ENDINGS = ("।", "?", "!", ".")
_SOFT_BREAKS = (",", ";", "—", "–")


def _segments(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, terminator) for each sentence, terminator excluded from the span."""

    segments: List[Tuple[int, int, str]] = []
    start = 0
    for index, char in enumerate(text):
        if char in _SENTENCE_ENDINGS:
            segments.append((start, index, char))
            start = index + 1
    if start < len(text) and text[start:].strip():
        segments.append((start, len(text), ""))
    return segments


def _time_at(index: int, text: str, duration: float) -> float:
    span = max(1, len(text))
    return max(0.0, min(duration, duration * index / span))


class PerformancePlan:
    """Beats for both characters in a scene."""

    def __init__(self, chiku: Sequence[Beat] = (), gappu: Sequence[Beat] = ()) -> None:
        self.chiku = tuple(chiku)
        self.gappu = tuple(gappu)

    def for_character(self, character: str) -> Tuple[Beat, ...]:
        return self.chiku if character == "chiku" else self.gappu

    def as_dict(self) -> Mapping[str, Tuple[Beat, ...]]:
        return {"chiku": self.chiku, "gappu": self.gappu}


def _thin(beats: Sequence[Beat]) -> List[Beat]:
    """Keep the strongest beats, enforce a minimum gap, cap the count."""

    kept: List[Beat] = []
    for beat in sorted(beats, key=lambda b: (-b.strength, b.at)):
        if len(kept) >= MAX_BEATS:
            break
        if all(abs(beat.at - other.at) >= MIN_GAP for other in kept):
            kept.append(beat)
    return sorted(kept, key=lambda b: b.at)


def plan_performance(dialogue: str, *, duration: float, speaker: str = "narrator",
                     seed: int = 0) -> PerformancePlan:
    """Derive reaction beats from the spoken line.

    Rules, deliberately simple and explainable:
      * a question or an exclamation makes the *listener* widen or recoil;
      * a plain sentence end makes the listener nod (every sentence, thinned later);
      * the speaker bounces when a clause is shouted and tilts on a question;
      * a long sentence earns a weight shift about halfway through;
      * commas are soft beats, so a list does not look frozen.
    """

    text = (dialogue or "").strip()
    if not text or duration <= 0:
        return PerformancePlan()

    rng = random.Random(seed)
    listener = "gappu" if speaker == "chiku" else "chiku"
    both_listen = speaker == "narrator"

    chiku: List[Beat] = []
    gappu: List[Beat] = []

    def add(character: str, at: float, kind: str, strength: float) -> None:
        jitter = rng.uniform(-0.06, 0.06)
        moment = max(0.0, min(duration - 0.05, at + jitter))
        beat = Beat(at=moment, kind=kind, strength=max(0.35, min(1.0, strength)))
        if character == "chiku":
            chiku.append(beat)
        else:
            gappu.append(beat)

    for order, (start, end, terminator) in enumerate(_segments(text)):
        sentence = text[start:end]
        end_time = _time_at(end, text, duration)
        sentence_span = max(0.4, end_time - _time_at(start, text, duration))

        if terminator == "?":
            target = listener
            add(target, end_time, "widen", 0.85)
            if not both_listen:
                add(speaker, end_time, "point_beat", 0.7)
        elif terminator == "!":
            target = listener
            add(target, end_time, "recoil", 0.8)
            if not both_listen:
                add(speaker, end_time, "bounce", 0.7)
        elif terminator:
            add(listener, end_time, "nod", 0.55 + 0.05 * (order % 3))
            if both_listen:
                other = "gappu" if listener == "chiku" else "chiku"
                add(other, end_time + 0.18, "nod", 0.45)

        if sentence_span >= 4.5:
            middle = _time_at(start + len(sentence) // 2, text, duration)
            add(listener, middle, "lean_in", 0.5)

        for break_index, char in enumerate(sentence):
            if char in _SOFT_BREAKS:
                add(listener, _time_at(start + break_index, text, duration), "nod", 0.4)

        # A shouted clause shakes the speaker loose rather than leaving them wooden.
        if "!" in sentence and not both_listen:
            shouted = sentence.split("!")[0]
            add(speaker, _time_at(start + max(1, len(shouted) - 3), text, duration),
                "bounce", 0.6)

    # Everyone blinks once at a natural pause if the scene is long enough, so a listener
    # is not a portrait while someone else talks.
    if duration >= 3.0:
        for character in ("chiku", "gappu"):
            add(character, duration * 0.55, "blink", 0.9)

    return PerformancePlan(chiku=_thin(chiku), gappu=_thin(gappu))
