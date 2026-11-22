"""Gaze, saccades, blinking and eye expressions.

Why this exists
---------------
The rigs used to render eyes as an ellipse scaled by ``sin()`` on a fixed period, with
look direction hard-wired to zero. That is the "robotic stare" look: perfectly periodic
blinks, pupils that never move, and no way to say "Chiku looks at Gappu".

This module supplies the missing layer. Everything is a deterministic function of time,
seeded per character per scene, so a frame can be rendered in isolation and two runs of
the same plan produce the same animation.

    BlinkPattern      corrected blink rhythm: jittered intervals, double blinks,
                      asymmetric close/open, suppression during shock
    SaccadeSchedule   where the eyes point: scripted targets plus idle scanning,
                      fast travel, micro-saccades, target repeat avoidance
    EyeExpression     per-emotion eyelid/brow/pupil/gaze parameters
    FaceController    blends expressions over time and combines all of the above
                      into an EyeState the renderer can consume

``EyeState`` is data only: no cairo, no drawing. ``studio/characters/eyes.py`` renders it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from studio.characters.schema import CharacterSchema, EyeConfig

Gaze = Tuple[float, float]

# Screen-space anchors, in gaze units (-1 left .. +1 right, -1 up .. +1 down).
ANCHOR_CAMERA: Gaze = (0.0, -0.04)
ANCHOR_LEFT: Gaze = (-0.62, 0.02)
ANCHOR_RIGHT: Gaze = (0.62, 0.02)
ANCHOR_UP: Gaze = (0.06, -0.5)
ANCHOR_UP_LEFT: Gaze = (-0.38, -0.42)
ANCHOR_DOWN: Gaze = (-0.05, 0.42)
ANCHOR_DOWN_RIGHT: Gaze = (0.36, 0.4)

IDLE_ANCHORS: Tuple[Gaze, ...] = (
    ANCHOR_LEFT, ANCHOR_RIGHT, ANCHOR_UP, ANCHOR_UP_LEFT,
    ANCHOR_DOWN, ANCHOR_DOWN_RIGHT,
)


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


# --- expressions -------------------------------------------------------------


@dataclass(frozen=True)
class EyeExpression:
    """How one emotion poses the eyes and brows.

    ``lid_closed`` is the resting closure (0 open, 1 shut). ``lower_lid`` raises the lower
    lid (squint) and may go negative to drop it (wide-eyed shock). ``brow_asymmetry``
    raises the character's left brow more than the right, which is what makes a look
    sceptical instead of angry.
    """

    lid_closed: float = 0.0
    lower_lid: float = 0.0
    brow_y: float = 0.0
    brow_tilt: float = 0.0
    brow_asymmetry: float = 0.0
    pupil_scale: float = 1.0
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    saccade_scale: float = 1.0
    blink_scale: float = 1.0
    suppress_blinks: bool = False
    closed_style: str = "curve"

    def blended(self, other: "EyeExpression", weight: float) -> "EyeExpression":
        """Interpolate towards ``other``; used for emotional transitions."""

        w = clamp(weight, 0.0, 1.0)
        if w <= 0.0:
            return self
        if w >= 1.0:
            return other
        return EyeExpression(
            lid_closed=self.lid_closed + (other.lid_closed - self.lid_closed) * w,
            lower_lid=self.lower_lid + (other.lower_lid - self.lower_lid) * w,
            brow_y=self.brow_y + (other.brow_y - self.brow_y) * w,
            brow_tilt=self.brow_tilt + (other.brow_tilt - self.brow_tilt) * w,
            brow_asymmetry=self.brow_asymmetry + (other.brow_asymmetry - self.brow_asymmetry) * w,
            pupil_scale=self.pupil_scale + (other.pupil_scale - self.pupil_scale) * w,
            gaze_x=self.gaze_x + (other.gaze_x - self.gaze_x) * w,
            gaze_y=self.gaze_y + (other.gaze_y - self.gaze_y) * w,
            saccade_scale=self.saccade_scale + (other.saccade_scale - self.saccade_scale) * w,
            blink_scale=self.blink_scale + (other.blink_scale - self.blink_scale) * w,
            suppress_blinks=other.suppress_blinks if w > 0.5 else self.suppress_blinks,
            closed_style=other.closed_style if w > 0.5 else self.closed_style,
        )


EXPRESSIONS: Dict[str, EyeExpression] = {
    "neutral": EyeExpression(),
    "happy": EyeExpression(lid_closed=0.30, lower_lid=0.45, brow_y=-2.0,
                           brow_tilt=0.05, pupil_scale=1.05),
    "excited": EyeExpression(lid_closed=0.12, lower_lid=0.2, brow_y=-7.0,
                             brow_tilt=0.0, pupil_scale=1.18, saccade_scale=1.3,
                             blink_scale=0.85),
    "surprised": EyeExpression(lid_closed=0.0, lower_lid=-0.22, brow_y=-11.0,
                               brow_tilt=0.18, pupil_scale=0.92, saccade_scale=0.4,
                               suppress_blinks=True),
    "suspicious": EyeExpression(lid_closed=0.42, lower_lid=0.15, brow_y=3.0,
                                brow_tilt=-0.18, brow_asymmetry=0.75,
                                pupil_scale=0.92, gaze_x=0.5, saccade_scale=1.1,
                                closed_style="flat"),
    "thinking": EyeExpression(lid_closed=0.18, brow_y=-2.0, brow_tilt=0.07,
                              gaze_x=0.35, gaze_y=-0.5, saccade_scale=0.55),
    "sad": EyeExpression(lid_closed=0.34, lower_lid=0.05, brow_y=-1.0,
                         brow_tilt=-0.3, gaze_x=-0.15, gaze_y=0.45,
                         blink_scale=1.2),
    "angry": EyeExpression(lid_closed=0.38, lower_lid=0.5, brow_y=5.0,
                           brow_tilt=0.3, pupil_scale=0.9, saccade_scale=0.8,
                           closed_style="flat"),
    "fear": EyeExpression(lid_closed=0.0, lower_lid=-0.18, brow_y=-9.0,
                          brow_tilt=0.22, pupil_scale=0.88, saccade_scale=1.7,
                          blink_scale=0.7),
    "confused": EyeExpression(lid_closed=0.16, brow_y=-1.0, brow_tilt=0.12,
                               brow_asymmetry=1.0, gaze_x=0.2, gaze_y=-0.12,
                               saccade_scale=0.7),
    "shy": EyeExpression(lid_closed=0.36, lower_lid=0.3, brow_y=2.0,
                         brow_tilt=-0.1, gaze_y=0.35, blink_scale=1.15),
    "proud": EyeExpression(lid_closed=0.22, lower_lid=0.15, brow_y=-4.0,
                           brow_tilt=0.06, gaze_y=-0.2, pupil_scale=1.05),
    "listening": EyeExpression(lid_closed=0.05, blink_scale=1.2, saccade_scale=0.5),
}

# Story poses predate expressions; map them so existing series keep working.
POSE_EXPRESSIONS: Dict[str, str] = {
    "idle": "neutral",
    "excited_jump": "excited",
    "boast_proud": "proud",
    "shocked_freeze": "surprised",
    "embarrassed_smile": "shy",
    "spinning_slip": "fear",
    "observing": "thinking",
    "skeptical_eyebrow": "suspicious",
    "laughing_point": "happy",
    "satisfied_nod": "happy",
    "curious_tilt": "thinking",
    "brave_stance": "proud",
    "worried_look": "sad",
    "panic_run": "fear",
}


def expression_for_pose(pose: str) -> str:
    return POSE_EXPRESSIONS.get(pose, "neutral")


# --- blinking ----------------------------------------------------------------


@dataclass(frozen=True)
class _Blink:
    start: float
    duration: float
    amplitude: float


class BlinkPattern:
    """A deterministic, non-periodic blink rhythm.

    Real blinks are not a metronome: intervals vary roughly 2:1, people double-blink, and
    the eyelid closes faster than it opens. ``BlinkPattern`` reproduces that with a seeded
    schedule so it stays reproducible.

    ``amplitude`` below 1.0 gives a partial blink, which is what makes a character look
    tired or unfocused rather than robotic.
    """

    MIN_INTERVAL = 0.32

    def __init__(self, base_period: float, base_duration: float, seed: int = 0, *,
                 cfg: EyeConfig | None = None, span: float = 90.0,
                 start: float = 0.0) -> None:
        cfg = cfg or EyeConfig.from_dict({})
        self.base_period = max(0.4, float(base_period))
        self.base_duration = clamp(float(base_duration), 0.06, 0.5)
        self.jitter = cfg.blink_jitter
        self.close_fraction = cfg.blink_close_fraction
        self.double_chance = cfg.double_blink_chance
        self._blinks = self._build(random.Random(seed), span, start)

    def _build(self, rng: random.Random, span: float, start: float) -> List[_Blink]:
        blinks: List[_Blink] = []
        t = start + rng.uniform(0.15, 1.4)
        while t < span:
            # Most blinks close the eye fully; the remainder are lazy half-blinks.
            amplitude = rng.choice((1.0, 1.0, 1.0, 1.0, 0.92, 0.86))
            blinks.append(_Blink(t, self.base_duration * rng.uniform(0.85, 1.25), amplitude))
            if rng.random() < self.double_chance:
                gap = rng.uniform(0.10, 0.22)
                blinks.append(_Blink(t + self.base_duration + gap,
                                     self.base_duration * rng.uniform(0.6, 0.9), 0.85))
            interval = self.base_period * (1.0 - self.jitter) + rng.random() * 2.0 * self.jitter * self.base_period
            t += max(self.MIN_INTERVAL, interval)
        return blinks

    def count(self, start: float = 0.0, end: float | None = None) -> int:
        end = math.inf if end is None else end
        return sum(1 for blink in self._blinks if start <= blink.start < end)

    def intervals(self) -> List[float]:
        return [b.start - a.start for a, b in zip(self._blinks, self._blinks[1:])]

    def lid_at(self, t: float, scale: float = 1.0) -> float:
        """Closure amount 0..1 at time ``t``."""

        for blink in self._blinks:
            if blink.start > t:
                break
            if t < blink.start + blink.duration:
                return clamp(blink.amplitude * scale, 0.0, 1.0) * self._envelope(t - blink.start, blink.duration)
        return 0.0

    def _envelope(self, local: float, duration: float) -> float:
        close_time = duration * self.close_fraction
        if local < close_time:
            return math.sin(0.5 * math.pi * clamp(local / close_time, 0.0, 1.0))
        opened = clamp((local - close_time) / max(1e-6, duration - close_time), 0.0, 1.0)
        return math.cos(0.5 * math.pi * opened)


# --- saccades ----------------------------------------------------------------


@dataclass(frozen=True)
class _Saccade:
    start: float
    duration: float
    frm: Gaze
    to: Gaze


class SaccadeSchedule:
    """Where a character looks over time.

    Scripted targets win; between them the eyes scan the room. Travel is a fast eased
    jump (60-140 ms) because that is what a real saccade looks like, and the resting
    position gets a small tremor so the eyes never look frozen.
    """

    def __init__(self, seed: int = 0, *, rate: float = 0.55, travel: float = 0.09,
                 span: float = 90.0, start: Gaze = ANCHOR_CAMERA,
                 anchors: Sequence[Gaze] = IDLE_ANCHORS,
                 scripted: Iterable[Tuple[float, Gaze]] | None = None,
                 micro: float = 0.03) -> None:
        self.rate = max(0.05, float(rate))
        self.travel = clamp(float(travel), 0.04, 0.2)
        self.micro = max(0.0, float(micro))
        self.start_target = start
        self._events = self._build(random.Random(seed), span, anchors, scripted or ())

    def _build(self, rng: random.Random, span: float, anchors: Sequence[Gaze],
               scripted: Sequence[Tuple[float, Gaze]]) -> List[_Saccade]:
        events: List[_Saccade] = []
        current: Gaze = self.start_target
        t = 0.0
        scripted = sorted((float(at), (float(p[0]), float(p[1]))) for at, p in scripted)
        pending = list(scripted)

        def add(at: float, target: Gaze, duration: float) -> None:
            nonlocal current
            if abs(target[0] - current[0]) < 1e-3 and abs(target[1] - current[1]) < 1e-3:
                return
            events.append(_Saccade(at, duration, current, target))
            current = target

        while t < span:
            while pending and pending[0][0] <= t:
                at, target = pending.pop(0)
                add(at, target, self.travel)
            interval = (1.0 / self.rate) * rng.uniform(0.55, 1.85)
            t += interval
            if pending and pending[0][0] < t + self.travel:
                continue
            if rng.random() < 0.45:
                add(t, ANCHOR_CAMERA, self.travel * rng.uniform(0.85, 1.3))
                continue
            options = [a for a in anchors
                       if abs(a[0] - current[0]) > 0.12 or abs(a[1] - current[1]) > 0.12]
            if not options:
                options = list(anchors)
            add(t, options[rng.randrange(len(options))], self.travel * rng.uniform(0.8, 1.4))
        return events

    @property
    def moves(self) -> int:
        return len(self._events)

    def base_gaze_at(self, t: float) -> Gaze:
        previous: Gaze = self.start_target
        for event in self._events:
            if event.start > t:
                break
            previous = event.to
            if t < event.start + event.duration:
                progress = clamp((t - event.start) / event.duration, 0.0, 1.0)
                eased = 1.0 - (1.0 - progress) ** 3  # fast out, gentle settle
                return (
                    event.frm[0] + (event.to[0] - event.frm[0]) * eased,
                    event.frm[1] + (event.to[1] - event.frm[1]) * eased,
                )
        return previous

    def tremor(self, t: float) -> Gaze:
        if self.micro <= 0.0:
            return (0.0, 0.0)
        x = (math.sin(t * 7.3) * 0.5 + math.sin(t * 11.7 + 1.2) * 0.3
             + math.sin(t * 17.1 + 2.4) * 0.2) * self.micro
        y = (math.sin(t * 6.1 + 0.7) * 0.5 + math.sin(t * 13.3 + 2.1) * 0.3
             + math.sin(t * 19.7 + 0.3) * 0.2) * self.micro
        return (x, y)


def gaze_toward(own_x: float, other_x: float, other_y: float, eye_y: float,
                *, deadzone: float = 6.0) -> Gaze:
    """Gaze offset for looking at another character standing on the same plane.

    Returns gaze units, clamped to the range a cartoon eye can actually show. The
    horizontal sign is expressed in *screen* space and the caller mirrors it by facing.
    """

    dx = other_x - own_x
    dy = other_y - eye_y
    if abs(dx) < deadzone:
        dx = 0.0
    horizontal = clamp(dx / 220.0, -0.85, 0.85)
    vertical = clamp(dy / 420.0, -0.5, 0.5)
    return (horizontal, vertical)


# --- controller --------------------------------------------------------------


@dataclass(frozen=True)
class EyeState:
    """Everything the eye renderer needs for one frame."""

    lid_left: float = 0.0
    lid_right: float = 0.0
    lower_lid: float = 0.0
    pupil_left: Gaze = (0.0, 0.0)
    pupil_right: Gaze = (0.0, 0.0)
    pupil_scale: float = 1.0
    closed_style: str = "curve"
    expression: str = "neutral"
    brow_y: float = 0.0
    brow_tilt_left: float = 0.0
    brow_tilt_right: float = 0.0


class FaceController:
    """Turns (time, emotion, gaze plan) into an :class:`EyeState` each frame.

    Expression changes cross-fade over ``transition`` seconds, so a character does not
    snap from happy to terrified; the eyelid, brow, pupil and gaze all move together.
    """

    def __init__(self, schema: CharacterSchema, *, seed: int = 0, span: float = 90.0,
                 expression: str = "neutral",
                 schedule: Optional[Sequence[Tuple[float, str]]] = None,
                 gaze_start: Gaze = ANCHOR_CAMERA,
                 scripted_gaze: Optional[Iterable[Tuple[float, Gaze]]] = None,
                 transition: float = 0.35) -> None:
        self.schema = schema
        self.cfg = schema.eyes
        self.transition = max(0.0, transition)
        self._schedule = sorted(
            [(0.0, expression if not schedule else schedule[0][1])] + list(schedule or []),
            key=lambda item: item[0],
        )
        self._merged: Dict[str, EyeExpression] = {
            name: self._merge(name, profile) for name, profile in EXPRESSIONS.items()
        }
        for name in {name for _, name in self._schedule}:
            if name not in self._merged:
                self._merged[name] = self._merge(name, EXPRESSIONS["neutral"])
        self.gaze = SaccadeSchedule(seed, rate=self.cfg.saccade_rate,
                                   travel=self.cfg.saccade_travel, span=span,
                                   start=gaze_start, scripted=scripted_gaze,
                                   micro=self.cfg.micro_saccade)
        self.blink = BlinkPattern(schema.timing.blink_period, schema.timing.blink_duration,
                                  seed=seed + 7919, cfg=self.cfg, span=span)

    # -- helpers -----------------------------------------------------------

    def _merge(self, name: str, profile: EyeExpression) -> EyeExpression:
        """Apply the character's per-expression overrides from JSON, if any."""

        overrides = (self.schema.expressions or {}).get(name)
        if not overrides:
            return profile
        return replace(profile, **overrides)  # type: ignore[arg-type]

    def expression_at(self, t: float) -> Tuple[str, EyeExpression]:
        previous_name, previous_at = self._schedule[0]
        for at, name in self._schedule:
            if at > t:
                break
            previous_name, previous_at = name, at
        current = self._merged.get(previous_name, self._merged["neutral"])
        if self.transition > 0.0 and t < previous_at + self.transition:
            index = self._schedule.index((previous_at, previous_name))
            if index > 0:
                prior_name = self._schedule[index - 1][1]
                prior = self._merged.get(prior_name, self._merged["neutral"])
                weight = clamp((t - previous_at) / self.transition, 0.0, 1.0)
                return previous_name, prior.blended(current, weight)
        return previous_name, current

    def _entered_expression_at(self, t: float) -> float:
        entered = 0.0
        for at, _ in self._schedule:
            if at > t:
                break
            entered = at
        return entered

    # -- public ------------------------------------------------------------

    def state_at(self, t: float) -> EyeState:
        name, profile = self.expression_at(t)
        engaged = self._entered_expression_at(t)
        suppress = profile.suppress_blinks and (t - engaged) < 1.1
        blink = 0.0 if suppress else self.blink.lid_at(t, profile.blink_scale)

        gx, gy = self.gaze.base_gaze_at(t)
        tx, ty = self.gaze.tremor(t)
        # Intense emotions narrow the scan (shock) or widen it (fear) instead of staring.
        scale = clamp(profile.saccade_scale, 0.1, 2.5)
        gx = clamp(gx * scale + tx + profile.gaze_x, -1.0, 1.0)
        gy = clamp(gy * scale + ty + profile.gaze_y, -1.0, 1.0)

        # Independent eyes: a small divergence keeps the pair from looking like one sprite,
        # and eye contact converges the pupils slightly.
        divergence = 0.045
        depth = clamp(math.hypot(gx, gy), 0.0, 1.0)
        converge = 0.05 * (1.0 - depth)
        left = (clamp(gx + converge, -1.0, 1.0), clamp(gy, -1.0, 1.0))
        right = (clamp(gx - converge, -1.0, 1.0), clamp(gy, -1.0, 1.0))

        asymmetry = profile.brow_asymmetry
        return EyeState(
            lid_left=clamp(blink if blink > 0 else profile.lid_closed, 0.0, 1.0),
            lid_right=clamp(blink if blink > 0 else profile.lid_closed, 0.0, 1.0),
            lower_lid=profile.lower_lid,
            pupil_left=left,
            pupil_right=right,
            pupil_scale=profile.pupil_scale,
            closed_style=profile.closed_style,
            expression=name,
            brow_y=profile.brow_y,
            brow_tilt_left=profile.brow_tilt + asymmetry * 0.12,
            brow_tilt_right=profile.brow_tilt - asymmetry * 0.12,
        )

    def with_lids(self, t: float, lid_left: float, lid_right: float) -> EyeState:
        """Override the eyelid closure, e.g. for a scripted wink."""

        state = self.state_at(t)
        return replace(state, lid_left=clamp(lid_left, 0.0, 1.0),
                       lid_right=clamp(lid_right, 0.0, 1.0))
