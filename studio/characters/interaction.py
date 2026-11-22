"""Character-to-character interaction (T35b).

Two rigs used to animate *near* each other, never *with* each other: nothing stopped their
bodies from overlapping, orientation was fixed by the character file even if the partner moved
to the other side, and a speaker's emphasis never reached the listener.

This layer adds the three things that make a two-character shot read as a performance:

* **separation** - bodies are pushed apart until there is a minimum gap, so a walk or a drift can
  never push one character through the other;
* **orientation** - a character turns toward its partner, with hysteresis so a near-tie cannot
  flip it back and forth every frame;
* **gesture** - a speaker's emphasis extends both arms toward the partner for a beat, and the
  partner answers with a small lean-in.

Everything is translation/angle addition, so with no plan active the output is exactly the input
and the golden frames stay byte-identical.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, replace
from typing import Optional

from studio.characters.locomotion import BodyState

# Minimum distance between body centres, in pixels at scale 1.0. The rigs are ~150 px wide at
# their anchors, so this leaves a visible gap without pushing them out of frame.
MIN_SEPARATION = 210.0

# A character only turns around once the partner is this far past the centre line. Without it a
# character standing exactly beside its partner would flip every frame.
FLIP_HYSTERESIS = 45.0

# How far the arms swing when gesturing toward the partner, in radians.
REACH_SPAN = 0.85
REST_ARM = 0.15

# A gesture ramps in and out rather than snapping.
GESTURE_ATTACK = 0.18
GESTURE_RELEASE = 0.24


def resolve_separation(x_a: float, x_b: float, min_gap: float = MIN_SEPARATION
                       ) -> tuple[float, float]:
    """Push two body centres apart symmetrically until they clear ``min_gap``."""

    gap = float(x_b) - float(x_a)
    if abs(gap) >= min_gap:
        return float(x_a), float(x_b)
    push = (min_gap - abs(gap)) / 2.0
    sign = 1.0 if gap >= 0 else -1.0
    return float(x_a) - push * sign, float(x_b) + push * sign


class FacingTracker:
    """Which way a character should face, given where its partner is."""

    def __init__(self, direction: int = 1, hysteresis: float = FLIP_HYSTERESIS):
        self.direction = 1 if direction >= 0 else -1
        self.hysteresis = float(hysteresis)

    def update(self, self_x: float, partner_x: float) -> int:
        delta = float(partner_x) - float(self_x)
        if self.direction > 0 and delta < -self.hysteresis:
            self.direction = -1
        elif self.direction < 0 and delta > self.hysteresis:
            self.direction = 1
        return self.direction


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@dataclass(frozen=True)
class Gesture:
    """One arm gesture toward the partner, in seconds from the start of the scene."""

    at: float
    duration: float
    strength: float = 1.0
    kind: str = "present"

    @property
    def end(self) -> float:
        return self.at + self.duration

    def amount_at(self, t: float) -> float:
        if t < self.at - GESTURE_ATTACK or t > self.end + GESTURE_RELEASE:
            return 0.0
        if t < self.at:
            return self.strength * _ease((t - (self.at - GESTURE_ATTACK)) / GESTURE_ATTACK)
        if t <= self.end:
            return self.strength
        return self.strength * _ease(1.0 - (t - self.end) / GESTURE_RELEASE)


@dataclass
class InteractionPlan:
    """Gestures for both characters across one scene."""

    speaker: str
    listener: str
    gestures: dict[str, list[Gesture]]

    def gesture_at(self, t: float, character: str) -> float:
        total = 0.0
        for gesture in self.gestures.get(character, ()):
            total = max(total, gesture.amount_at(t))
        return min(1.0, total)

    @property
    def gesture_count(self) -> int:
        return sum(len(items) for items in self.gestures.values())

    def frames_with_gesture(self, duration: float, fps: int) -> int:
        return sum(
            1 for index in range(int(duration * fps))
            if self.gesture_at(index / fps, self.speaker) > 0.0
            or self.gesture_at(index / fps, self.listener) > 0.0
        )


def replace_body_hip(state: BodyState, hip_x: float) -> BodyState:
    """Copy of a body state with a different horizontal offset."""

    return replace(state, hip_x=float(hip_x))


# The rigs are drawn mirrored by `facing`, so *local* +x is "in front of the character" for both
# of them, and the right-arm angle with a negative delta is the forward pinion. This was
# measured with a probe render (both rigs, four delta combinations) rather than assumed: the
# mirrored result - chiku pointing screen-right, gappu pointing screen-left, each at its partner
# - is what proved it. The near arm tucks slightly so the silhouette is a point, not a T-pose.
NEAR_ARM_TUCK = 0.30


def gesture_body(amount: float) -> Optional[BodyState]:
    """The forward arm swings toward the partner while ``amount`` is non-zero.

    Additive, so it composes with whatever the pose is doing instead of replacing the pose's
    arm angles.
    """

    if amount <= 0.0:
        return None
    swing = REACH_SPAN * max(0.0, min(1.0, amount))
    return BodyState(arm_r_delta=-swing, arm_l_delta=-NEAR_ARM_TUCK * min(1.0, amount))


def reaction_body(amount: float, toward: int = 1) -> Optional[BodyState]:
    """A small lean toward the speaker, used while the partner is being addressed."""

    if amount <= 0.0:
        return None
    lean = 0.05 * amount * (1 if toward >= 0 else -1)
    return BodyState(lean=lean, head_tilt=0.03 * amount)


def _emphasis_marks(dialogue: str) -> list[tuple[float, str]]:
    """Fractional positions of the marks in a line that deserve a gesture."""

    marks: list[tuple[float, str]] = []
    length = max(1, len(dialogue))
    for index, character in enumerate(dialogue):
        if character in "!?!।":
            marks.append((index / length, "point"))
        elif character == ",":
            marks.append((index / length, "present"))
    return marks


def plan_interaction(dialogue: str, duration: float, speaker: str, listener: str,
                     seed: int = 0, *, max_gestures: int = 3) -> InteractionPlan:
    """Derive both characters' gestures from the shape of the line.

    Punctuation is the only reliable signal the script carries, so an exclamation or a question
    gets a pointing beat and a comma gets an open-handed one. Placement is proportional inside
    the line, in the same spirit (and with the same limitation) as the viseme timing.
    """

    rng = random.Random(seed)
    gestures: dict[str, list[Gesture]] = {speaker: [], listener: []}
    if duration <= 0.0 or max_gestures <= 0:
        return InteractionPlan(speaker=speaker, listener=listener, gestures=gestures)

    usable = max(0.4, duration - 0.4)
    marks = _emphasis_marks(dialogue)[:max_gestures]
    if not marks:
        return InteractionPlan(speaker=speaker, listener=listener, gestures=gestures)

    for fraction, kind in marks:
        at = 0.25 + fraction * usable + rng.uniform(-0.06, 0.06)
        at = max(0.10, min(duration - 0.45, at))
        length = 0.55 if kind == "point" else 0.40
        gestures[speaker].append(
            Gesture(at=at, duration=length, strength=0.9 + rng.uniform(0.0, 0.1), kind=kind)
        )
        # The listener answers slightly later, and more subtly.
        gestures[listener].append(
            Gesture(at=at + 0.18, duration=min(0.5, length),
                    strength=0.45 + rng.uniform(0.0, 0.15), kind="reaction")
        )
    return InteractionPlan(speaker=speaker, listener=listener, gestures=gestures)


class InteractionDirector:
    """Per-scene resolver: keeps the cast apart, oriented, and gesturing."""

    def __init__(self, anchor_a: float, anchor_b: float, plan: Optional[InteractionPlan] = None,
                 facing_a: int = 1, facing_b: int = -1,
                 min_gap: float = MIN_SEPARATION):
        self.anchor_a = float(anchor_a)
        self.anchor_b = float(anchor_b)
        self.plan = plan
        self.min_gap = float(min_gap)
        self.facing_a = FacingTracker(facing_a)
        self.facing_b = FacingTracker(facing_b)
        self.enabled = os.environ.get("FACTORY_NO_INTERACTION") != "1"

    def resolve(self, hip_a: float, hip_b: float) -> tuple[float, float]:
        """Return hip offsets adjusted so the bodies never overlap."""

        if not self.enabled:
            return hip_a, hip_b
        # Return the inputs untouched when no clamp is needed. Round-tripping through
        # anchor + offset and back perturbs hip_x by floating-point ulps, which is harmless
        # on screen but breaks the "identity means bit-identical" property that the golden
        # frames rely on.
        if abs((self.anchor_b + hip_b) - (self.anchor_a + hip_a)) >= self.min_gap:
            return hip_a, hip_b
        x_a, x_b = resolve_separation(self.anchor_a + hip_a, self.anchor_b + hip_b,
                                      self.min_gap)
        return x_a - self.anchor_a, x_b - self.anchor_b

    def facing(self, hip_a: float, hip_b: float) -> tuple[int, int]:
        if not self.enabled:
            return self.facing_a.direction, self.facing_b.direction
        x_a, x_b = self.resolve(hip_a, hip_b)
        return (self.facing_a.update(self.anchor_a + x_a, self.anchor_b + x_b),
                self.facing_b.update(self.anchor_b + x_b, self.anchor_a + x_a))

    def amount_at(self, t: float, index: int) -> float:
        """How strongly character 0 (chiku) or 1 (gappu) is gesturing at time ``t``."""

        if not self.enabled or self.plan is None:
            return 0.0
        return self.plan.gesture_at(t, "chiku" if index == 0 else "gappu")

    def gestures_in(self, index: int) -> int:
        if self.plan is None:
            return 0
        return len(self.plan.gestures.get("chiku" if index == 0 else "gappu", ()))

    def bodies(self, t: float, hip_a: float, hip_b: float,
               speaker: str) -> tuple[Optional[BodyState], Optional[BodyState]]:
        """Gesture layers for both characters, or ``None`` when nothing is happening."""

        if not self.enabled or self.plan is None:
            return None, None
        amount_a = self.plan.gesture_at(t, "chiku")
        amount_b = self.plan.gesture_at(t, "gappu")
        layer_a = (gesture_body(amount_a) if speaker == "chiku"
                   else reaction_body(amount_a, 1))
        layer_b = (gesture_body(amount_b) if speaker == "gappu"
                   else reaction_body(amount_b, -1))
        return layer_a, layer_b
