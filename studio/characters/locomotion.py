"""Locomotion and body mechanics.

The rigs already had the joints for this: legs, arms, torso rotation, head tilt and a
vertical root offset. What was missing was a *system* that drives them coherently over
time, so "walking" is a cycle with contact and passing phases rather than a sine wave.

    BodyState          what the body is doing on one frame (data only)
    MotionController   turns (mode, t) into a BodyState for twelve motions

Design rules
------------
* Pose and motion compose. A named pose sets the *attitude* (arms up in joy, hand on hip),
  the motion controller sets the *movement*. Motion is applied after the pose, and only
  touches the arms when the motion is actually about the arms (walk, run, wave, point).
* Everything is a deterministic function of ``t`` and a seed, so a frame can be rendered
  in isolation and a re-render is identical.
* Nothing here draws. The rigs read ``BodyState`` and set their existing joints, which
  keeps the golden frames valid when no motion is requested.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from studio.characters.gaze import clamp

MOTIONS: Tuple[str, ...] = (
    "idle", "walk", "walk_in", "walk_out", "run", "run_in", "jump", "land",
    "turn", "lean", "sit", "stand_up", "wave", "point", "shake_head", "nod",
)

# Seconds for one full stride cycle, and how far the body travels during it.
WALK_PERIOD = 1.05
RUN_PERIOD = 0.52


@dataclass(frozen=True)
class BodyState:
    """One frame of body motion, in rig-local units and radians."""

    hip_x: float = 0.0
    jump_y: float = 0.0
    lean: float = 0.0
    leg_l: float = 0.0
    leg_r: float = 0.0
    arm_l: Optional[float] = None   # None = leave the pose's arm angle alone
    arm_r: Optional[float] = None
    head_tilt: float = 0.0
    squash: float = 1.0
    mode: str = "idle"

    def merged_with(self, other: "BodyState") -> "BodyState":
        """Stack two motions: translations add, the later motion wins on angles."""

        return BodyState(
            hip_x=self.hip_x + other.hip_x,
            jump_y=self.jump_y + other.jump_y,
            lean=self.lean + other.lean,
            leg_l=self.leg_l + other.leg_l,
            leg_r=self.leg_r + other.leg_r,
            arm_l=other.arm_l if other.arm_l is not None else self.arm_l,
            arm_r=other.arm_r if other.arm_r is not None else self.arm_r,
            head_tilt=self.head_tilt + other.head_tilt,
            squash=self.squash * other.squash,
            mode=other.mode,
        )


def _stride(t: float, period: float, amplitude: float) -> Tuple[float, float]:
    """Leg angles for a gait: one leg forward while the other trails."""

    phase = 2.0 * math.pi * t / period
    return amplitude * math.sin(phase), -amplitude * math.sin(phase)


def _bounce(t: float, period: float, height: float) -> float:
    """Vertical bob: two rises per stride, floored at 0 so the feet stay on the ground."""

    phase = 2.0 * math.pi * t / period
    return -abs(math.sin(phase)) * height


class MotionController:
    """Deterministic body animation for one character in one scene."""

    def __init__(self, mode: str = "idle", duration: float = 5.0, seed: int = 0,
                 *, distance: float = 320.0, facing: float = 1.0) -> None:
        self.mode = mode if mode in MOTIONS else "idle"
        self.duration = max(0.1, float(duration))
        self.distance = float(distance)
        self.facing = 1.0 if facing >= 0 else -1.0
        # A small seeded phase offset keeps two characters from marching in lockstep.
        self.phase_offset = (seed % 1000) / 1000.0 * 2.0 * math.pi

    # -- public ------------------------------------------------------------

    def state_at(self, t: float) -> BodyState:
        mode = self.mode
        if mode == "idle":
            return BodyState(mode="idle")
        if mode in ("walk", "walk_in", "walk_out"):
            return self._gait(t, WALK_PERIOD, 0.42, 3.0)
        if mode in ("run", "run_in"):
            return self._gait(t, RUN_PERIOD, 0.78, 7.0, lean=0.1)
        if mode == "jump":
            return self._jump(t)
        if mode == "land":
            return self._land(t)
        if mode == "turn":
            return self._turn(t)
        if mode == "lean":
            return BodyState(lean=0.12 * math.sin(t * 1.4) + 0.08, head_tilt=0.05,
                             mode="lean")
        if mode == "sit":
            return self._sit(t, entering=True)
        if mode == "stand_up":
            return self._sit(t, entering=False)
        if mode == "wave":
            return self._wave(t)
        if mode == "point":
            return self._point(t)
        if mode == "shake_head":
            return BodyState(head_tilt=0.22 * math.sin(t * 9.0), mode="shake_head")
        if mode == "nod":
            return BodyState(head_tilt=0.16 * math.sin(t * 7.0) + 0.08, mode="nod")
        return BodyState(mode=mode)

    # -- motions -----------------------------------------------------------

    def _gait(self, t: float, period: float, amplitude: float, bounce: float,
              lean: float = 0.04) -> BodyState:
        legs_l, legs_r = _stride(t + self.phase_offset, period, amplitude)
        swing = 0.55 * amplitude
        hip_x = 0.0
        if self.mode in ("walk_in", "walk_out", "run_in"):
            progress = clamp(t / self.duration, 0.0, 1.0)
            eased = progress * progress * (3.0 - 2.0 * progress)
            if self.mode == "walk_out":
                # Leave away from the partner instead of walking through them.
                hip_x = -self.facing * self.distance * eased
            else:
                hip_x = -self.facing * self.distance * (1.0 - eased)
        return BodyState(
            hip_x=hip_x,
            jump_y=_bounce(t + self.phase_offset, period, bounce) - (bounce * 0.5),
            lean=lean,
            leg_l=legs_l,
            leg_r=legs_r,
            arm_l=-legs_l * swing,
            arm_r=-legs_r * swing,
            head_tilt=0.04 * math.sin(t * 2.0 * math.pi / period),
            mode=self.mode,
        )

    def _jump(self, t: float) -> BodyState:
        """Anticipation crouch, launch, apex, touchdown."""

        crouch_end, air_end = 0.22, 0.78
        u = clamp(t / self.duration, 0.0, 1.0)
        if u < crouch_end:
            k = u / crouch_end
            return BodyState(jump_y=6.0 * k, squash=1.0 - 0.12 * k,
                             leg_l=-0.25 * k, leg_r=0.25 * k, lean=0.06 * k,
                             arm_l=0.35 * k, arm_r=-0.35 * k, mode="jump")
        if u < air_end:
            k = (u - crouch_end) / (air_end - crouch_end)
            arc = math.sin(math.pi * k)
            return BodyState(jump_y=-120.0 * arc, squash=1.0 + 0.06 * arc,
                             leg_l=-0.35 * arc, leg_r=0.35 * arc,
                             arm_l=-1.1 * arc, arm_r=1.1 * arc,
                             head_tilt=-0.08 * arc, mode="jump")
        k = clamp((u - air_end) / (1.0 - air_end), 0.0, 1.0)
        settle = math.sin(math.pi * k) * math.exp(-3.0 * k)
        return BodyState(jump_y=8.0 * settle, squash=1.0 - 0.14 * settle,
                         leg_l=-0.18 * settle, leg_r=0.18 * settle, mode="jump")

    def _land(self, t: float) -> BodyState:
        k = clamp(t / self.duration, 0.0, 1.0)
        settle = math.sin(math.pi * k) * math.exp(-4.0 * k)
        return BodyState(jump_y=10.0 * settle, squash=1.0 - 0.16 * settle,
                         leg_l=-0.2 * settle, leg_r=0.2 * settle,
                         arm_l=0.4 * settle, arm_r=-0.4 * settle, mode="land")

    def _turn(self, t: float) -> BodyState:
        k = clamp(t / max(0.4, self.duration * 0.5), 0.0, 1.0)
        eased = 1.0 - (1.0 - k) ** 2
        lift = math.sin(math.pi * clamp(k, 0.0, 1.0))
        return BodyState(lean=-0.16 * eased, head_tilt=-0.28 * eased,
                         leg_l=0.25 * lift, leg_r=-0.25 * lift, mode="turn")

    def _sit(self, t: float, entering: bool) -> BodyState:
        k = clamp(t / max(0.4, self.duration * 0.6), 0.0, 1.0)
        eased = k * k * (3.0 - 2.0 * k)
        amount = eased if entering else 1.0 - eased
        return BodyState(jump_y=28.0 * amount, lean=0.1 * amount,
                         leg_l=1.15 * amount, leg_r=1.15 * amount,
                         arm_l=0.3 * amount, arm_r=-0.3 * amount,
                         squash=1.0 - 0.04 * amount, mode=self.mode)

    def _wave(self, t: float) -> BodyState:
        lift = clamp(t / 0.45, 0.0, 1.0)
        lift = 1.0 - (1.0 - lift) ** 2
        return BodyState(arm_r=-(1.45 * lift) + math.sin(t * 7.0) * 0.35 * lift,
                         arm_l=0.18, head_tilt=0.05 * math.sin(t * 3.0),
                         lean=-0.03 * lift, mode="wave")

    def _point(self, t: float) -> BodyState:
        lift = clamp(t / 0.35, 0.0, 1.0)
        lift = 1.0 - (1.0 - lift) ** 2
        return BodyState(arm_r=-(1.15 * lift) + math.sin(t * 2.2) * 0.04,
                         arm_l=0.2, lean=0.05 * lift, head_tilt=-0.06 * lift,
                         mode="point")


def motions_for(scene_data: dict, character: str) -> Sequence[str]:
    """Read a character's motion list from a scene, newest format first."""

    value = scene_data.get(f"{character}_motion")
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return ["idle"]
