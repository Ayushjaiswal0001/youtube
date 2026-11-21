"""Props and hand contact (T40).

An object in this studio was, until now, a shape drawn at a hard-coded coordinate: the story
mentions a brass key, the renderer draws sparkles near (460, 1150), and nothing connects the two.
A prop that no hand holds cannot be picked up, carried, or handed over, and a story about finding
a key has nothing to find.

This module makes the connection explicit:

* ``hand_point()`` computes where a rig's hand actually is in world space, by composing the same
  transform stack the rig draws with (body translate/scale, torso offset, arm attach, arm angle).
  It is not an estimate: a pixel probe in the tests finds the drawn hand and checks the distance.
* ``PropTrack`` attaches a prop to a hand, and moves it to another character's hand on cue, with
  an arc so it cannot slide through either body.
* ``contact_error()`` answers "how far is the hand from the prop right now", which is what a grab
  needs to be timed against.

Everything is opt-in through scene data (`prop`, `prop_holder`, ...), so an episode that carries
no prop renders exactly as it did before.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

import cairo

Point = Tuple[float, float]

# The rigs draw the hand ellipse one pixel outboard on chiku only. This mirrors `draw()`; the
# pixel-probe test is what keeps the mirror honest if a rig's arm art changes.
HAND_OFFSET_X = {"chiku": 1.0, "gappu": 0.0}

# How far a hand may be from a prop and still count as holding it, in world pixels.
GRAB_TOLERANCE = 26.0

# A handed-over prop rises slightly between the two hands instead of travelling in a straight line.
TRANSFER_ARC = 18.0


def _side_sign(side: str) -> float:
    return -1.0 if side == "left" else 1.0


def hand_point(rig, side: str = "right", angle: Optional[float] = None) -> Point:
    """World position of a rig's hand centre, following the rig's own draw transform.

    ``rig.draw`` does: translate(rig.x + hip_x, rig.y + jump_y), scale(scale * facing,
    scale * squash), then for the torso translate(0, torso.local_y + torso_draw_offset) and
    rotate(torso.local_rot), then per arm translate(±arm_attach_x, arm_attach_y),
    rotate(arm_angle), and draws the hand at (±(arm_shift + off), arm_len + 5).
    """

    prop = rig.prop.values if hasattr(rig.prop, "values") else rig.prop
    name = getattr(rig.schema, "id", "")
    off = HAND_OFFSET_X.get(name, 0.0)
    sign = _side_sign(side)
    if angle is None:
        angle = rig.arm_r_angle if side == "right" else rig.arm_l_angle

    matrix = cairo.Matrix()
    matrix.translate(rig.x + getattr(rig, "hip_x", 0.0), rig.y + getattr(rig, "jump_y", 0.0))
    matrix.scale(rig.scale * rig.facing, rig.scale * getattr(rig, "squash", 1.0))
    matrix.translate(0.0, rig.torso.local_y + prop["torso_draw_offset"])
    matrix.rotate(rig.torso.local_rot)
    matrix.translate(sign * prop["arm_attach_x"], prop["arm_attach_y"])
    matrix.rotate(angle)
    x, y = matrix.transform_point(sign * (prop["arm_shift"] + off), prop["arm_len"] + 5.0)
    return (float(x), float(y))


@dataclass(frozen=True)
class PropSpec:
    """How big a prop is drawn, so its bounding box can be framed and tested."""

    name: str
    half_w: float
    half_h: float


# The drawn key is 38 units long, scaled up so it reads at delivery size: it has to be clearly
# bigger than the hand holding it, or it is a speck of noise in the frame.
KEY_DRAW_SCALE = 1.6

PROPS: Mapping[str, PropSpec] = {
    "brass_key": PropSpec("brass_key", 26.0 * KEY_DRAW_SCALE, 13.0 * KEY_DRAW_SCALE),
}


def prop_box(point: Point, spec: PropSpec) -> Tuple[float, float, float, float]:
    """World bounding box of a prop at ``point``."""

    x, y = point
    return (x - spec.half_w, y - spec.half_h, x + spec.half_w, y + spec.half_h)


def draw_prop(cr: cairo.Context, name: str, point: Point, angle: float = 0.0,
              scale: float = 1.0) -> None:
    """Draw a prop at a world point. The caller has already applied the camera."""

    if name == "brass_key":
        _draw_brass_key(cr, point, angle, scale)
        return
    raise KeyError(f"unknown prop {name!r}")


def _draw_brass_key(cr: cairo.Context, point: Point, angle: float, scale: float) -> None:
    x, y = point
    cr.save()
    cr.translate(x, y)
    cr.rotate(angle)
    cr.scale(scale * KEY_DRAW_SCALE, scale * KEY_DRAW_SCALE)
    brass = (0.83, 0.66, 0.27)
    highlight = (0.97, 0.85, 0.45)
    outline = (0.32, 0.24, 0.10)
    # Bow (the ring you hold).
    cr.set_line_width(3.0)
    cr.set_source_rgb(*brass)
    cr.arc(-14.0, 0.0, 11.0, 0.0, math.tau)
    cr.fill_preserve()
    cr.set_source_rgb(*outline)
    cr.stroke()
    cr.set_source_rgb(1.0, 1.0, 1.0)
    cr.arc(-14.0, 0.0, 5.0, 0.0, math.tau)
    cr.fill()
    # Shaft and teeth.
    cr.set_source_rgb(*brass)
    cr.rectangle(-4.0, -3.4, 26.0, 6.8)
    cr.fill_preserve()
    cr.set_source_rgb(*outline)
    cr.stroke()
    for tooth_x, height in ((14.0, 9.0), (20.0, 7.0)):
        cr.set_source_rgb(*brass)
        cr.rectangle(tooth_x, 2.0, 4.0, height)
        cr.fill_preserve()
        cr.set_source_rgb(*outline)
        cr.stroke()
    cr.set_source_rgb(*highlight)
    cr.rectangle(-2.0, -2.6, 18.0, 2.0)
    cr.fill()
    cr.restore()


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


class PropTrack:
    """Where a prop is, and whose hand it is in, at any time in the scene.

    A track is deliberately small: the prop is held by one character until a ``handoff_at``
    second, then it crosses to the other character over ``handoff_duration``. The crossing rises
    by ``TRANSFER_ARC`` so the object arcs between the hands instead of sliding through the
    bodies. If no handoff is configured the prop simply follows its holder.
    """

    def __init__(self, spec: PropSpec, holder: str = "chiku", side: str = "right",
                 handoff_to: Optional[str] = None, handoff_side: str = "left",
                 handoff_at: Optional[float] = None, handoff_duration: float = 0.45,
                 angle_rate: float = 0.0) -> None:
        self.spec = spec
        self.holder = holder
        self.side = side
        self.handoff_to = handoff_to
        self.handoff_side = handoff_side
        self.handoff_at = handoff_at
        self.handoff_duration = max(0.05, float(handoff_duration))
        self.angle_rate = float(angle_rate)

    # -- queries ----------------------------------------------------------

    def transferring(self, t: float) -> bool:
        return (self.handoff_to is not None and self.handoff_at is not None
                and self.handoff_at <= t < self.handoff_at + self.handoff_duration)

    def held_by(self, t: float) -> Optional[str]:
        """Which character holds the prop at ``t`` - ``None`` mid-transfer."""

        if self.handoff_to is not None and self.handoff_at is not None:
            if t >= self.handoff_at + self.handoff_duration:
                return self.handoff_to
            if t >= self.handoff_at:
                return None
        return self.holder

    def hand_for(self, character: str) -> str:
        if character == self.holder:
            return self.side
        if character == self.handoff_to:
            return self.handoff_side
        return "right"

    def point_at(self, t: float, hands: Mapping[str, Point]) -> Point:
        """World position of the prop, given each character's current hand position."""

        start: Optional[Point] = hands.get(self.holder)
        if self.handoff_to is None or self.handoff_at is None:
            return start or (0.0, 0.0)

        end: Optional[Point] = hands.get(self.handoff_to)
        if t < self.handoff_at:
            return start or (0.0, 0.0)
        if t >= self.handoff_at + self.handoff_duration or end is None or start is None:
            return end or start or (0.0, 0.0)

        progress = _ease((t - self.handoff_at) / self.handoff_duration)
        x = start[0] + (end[0] - start[0]) * progress
        y = start[1] + (end[1] - start[1]) * progress
        # Arc upward at the midpoint of the crossing.
        y -= TRANSFER_ARC * math.sin(math.pi * progress)
        return (x, y)

    def angle_at(self, t: float) -> float:
        return self.angle_rate * max(0.0, t)

    def box_at(self, t: float, hands: Mapping[str, Point]) -> Tuple[float, float, float, float]:
        return prop_box(self.point_at(t, hands), self.spec)


# How much clear air a held prop needs above the caption band, in world pixels.
BAND_CLEARANCE = 14.0


def raise_arm_for_clearance(rig, side: str, spec: PropSpec, band_top_world: Optional[float],
                            clearance: float = BAND_CLEARANCE,
                            max_delta: float = 1.25,
                            step: float = 0.06) -> float:
    """Arm angle change needed so a prop held at ``side`` clears the caption band.

    A caption band is painted over the character layer, so an object held low is simply hidden.
    Rather than report that, the receiver is made to reach: this returns the smallest change to
    the arm angle that lifts the prop's box above the band, searching both rotation directions
    because the two rigs are mirrored and do not share a raising sign.

    Returns ``0.0`` when the prop already clears it, or when no reach is enough.
    """

    if band_top_world is None:
        return 0.0
    target = band_top_world - clearance
    if hand_point(rig, side)[1] + spec.half_h <= target:
        return 0.0

    angle = rig.arm_l_angle if side == "left" else rig.arm_r_angle
    # Which way raises the hand depends on the rig: the two characters are drawn mirrored, so a
    # left arm does not have one raising sign. Both directions are searched and the smallest
    # change that clears the band wins, so the pose is disturbed as little as possible.
    best: Optional[float] = None
    for direction in (-1.0, 1.0):
        delta = step
        while delta <= max_delta:
            point = hand_point(rig, side, angle=angle + direction * delta)
            if point[1] + spec.half_h <= target:
                if best is None or delta < abs(best):
                    best = direction * delta
                break
            delta += step
    return best if best is not None else 0.0


def contact_error(track: PropTrack, t: float, hands: Mapping[str, Point],
                  character: Optional[str] = None) -> float:
    """Distance between a character's hand and the prop at ``t``.

    A grab is only believable when this is small, so this is the number to time a pick-up
    against: measure it for the character who is *about* to take the prop, not for the holder,
    whose distance is zero by construction.
    """

    position = track.point_at(t, hands)
    hand = hands.get(character or track.holder)
    if hand is None:
        return float("inf")
    return math.dist(position, hand)


def max_step(track: PropTrack, hands_at, duration: float, fps: int = 30) -> float:
    """Largest per-frame movement of the prop over a scene, for continuity checks."""

    frames = max(2, int(duration * fps))
    previous = track.point_at(0.0, hands_at(0.0))
    peak = 0.0
    for index in range(1, frames):
        t = index / fps
        point = track.point_at(t, hands_at(t))
        peak = max(peak, math.dist(point, previous))
        previous = point
    return peak
