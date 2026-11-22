"""Body mechanics: bending, crouching and standing back up (T43b).

T43 ended with a measured fact: an arm reaches 83.8 px while the shoulder sits 195.8 px above the
ground, so a character could not reach anything on the floor. The fix is not a longer arm and not a
target moved closer to the hand - it is the body the arm hangs from.

The rigs already support everything needed, and none of it was being driven:

* ``torso.local_rot`` rotates the head and both arms about the torso pivot, which is what lowers the
  shoulder in a forward bend.
* ``squash`` scales the whole body about the rig's anchor, which is the ground contact point, so a
  squat compresses the character without pushing their feet through the floor.

``solve_crouch()`` searches that two-parameter space for the *smallest* pose that brings the actual,
transformed shoulder within reach of an actual world target, and ``CrouchTrack`` schedules the bend
so the character bends as they reach and straightens as they recover. Nothing here moves the target.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

from studio.characters.ik import chain_for, shoulder_point

Point = Tuple[float, float]

# A bend beyond this reads as a fall rather than as bending over. Gappu is the binding case: his
# shoulder is only 106 px above the ground but his arm reaches 62.6 px, so he needs 109 degrees.
MAX_BEND = math.radians(120.0)
# A squat below this makes the character look like they are sinking into the floor.
MIN_SQUASH = 0.72
# Aim to leave this fraction of the arm unused at full stretch: a fully locked elbow looks broken.
REACH_MARGIN = 0.92


# How much of the torso fold the head gives back, so the character keeps looking at what they are
# reaching for instead of at the floor. Animators call this "keeping the face alive"; without it a
# deep bend reads as a character falling over, which is exactly how the first render of T43b looked.
HEAD_COUNTER = 0.78


@dataclass(frozen=True)
class BodyPose:
    """Body-mechanics parameters, plus the consequence of applying them."""

    bend: float = 0.0
    squash: float = 1.0

    def blended(self, other: "BodyPose", u: float) -> "BodyPose":
        u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
        u = u * u * (3.0 - 2.0 * u)  # smoothstep: no velocity step at either end
        return BodyPose(self.bend + (other.bend - self.bend) * u,
                        self.squash + (other.squash - self.squash) * u)

    @property
    def is_upright(self) -> bool:
        return abs(self.bend) < 1e-6 and abs(self.squash - 1.0) < 1e-6


STANDING = BodyPose()


def apply_pose(rig, pose: BodyPose, *, counter_head: bool = True) -> None:
    """Put a pose on a rig.

    Touches the torso, the body squash and - when ``counter_head`` is set - the head joint, which
    gives back most of the fold so the character's face stays readable and aimed at the object. That
    counter-rotation is the difference between "bending down" and "lying on the floor".
    """

    rig.torso.local_rot = pose.bend
    rig.squash = pose.squash
    if counter_head:
        rig.head.local_rot = -pose.bend * HEAD_COUNTER


def save_pose(rig) -> BodyPose:
    return BodyPose(bend=float(getattr(rig.torso, "local_rot", 0.0)),
                    squash=float(getattr(rig, "squash", 1.0)))


def restore_pose(rig, pose: BodyPose) -> None:
    """Undo :func:`apply_pose`, including the head counter-rotation."""

    rig.torso.local_rot = pose.bend
    rig.squash = pose.squash
    rig.head.local_rot = 0.0


def shoulder_reach(rig, side: str, pose: BodyPose, target: Point) -> Tuple[float, float, Point]:
    """Distance from the shoulder to ``target`` if ``pose`` were applied, without applying it."""

    saved = save_pose(rig)
    apply_pose(rig, pose)
    chain = chain_for(rig, side)
    distance = math.dist(chain.shoulder, target)
    apply_pose(rig, saved)
    return distance, chain.reach, chain.shoulder


def solve_crouch(rig, side: str, target: Point, *, max_bend: float = MAX_BEND,
                 min_squash: float = MIN_SQUASH,
                 margin: float = REACH_MARGIN) -> Tuple[BodyPose, bool]:
    """The smallest bend/squat that makes ``target`` reachable.

    Returns ``(pose, ok)``. ``ok`` is False when even a deep bend and a full squat cannot reach,
    which is information the caller must act on rather than hide.

    The search is coarse-then-fine over two parameters rather than a closed form, because the
    shoulder's world position is the result of a rotation inside a scaled, mirrored matrix stack -
    and because a measured answer cannot drift away from the drawing code.
    """

    saved = save_pose(rig)
    try:
        # Smallest fold first, spending squash before folding further. A squat lowers the shoulder
        # while keeping the feet planted, so it reads as knees bending; a fold rotates the whole
        # upper body and reads as falling over once it passes ~60 degrees.
        for bend_i in range(0, 31):
            bend = max_bend * bend_i / 30.0
            for squash_i in range(0, 15):
                squash = 1.0 - (1.0 - min_squash) * squash_i / 14.0
                pose = BodyPose(bend=bend, squash=squash)
                distance, reach, _ = shoulder_reach(rig, side, pose, target)
                if distance <= reach * margin:
                    return (pose, True)
        # 3. Comfort is stricter than reach: the search above stops at 92% extension so an elbow
        #    never locks. A target that needs the last 8% is still physically touchable, and
        #    reporting it as unreachable made a real pickup fail a gate it met. Try the full reach
        #    before giving up.
        for bend_i in range(0, 31):
            bend = max_bend * bend_i / 30.0
            for squash_i in range(0, 15):
                squash = 1.0 - (1.0 - min_squash) * squash_i / 14.0
                pose = BodyPose(bend=bend, squash=squash)
                distance, reach, _ = shoulder_reach(rig, side, pose, target)
                if distance <= reach:
                    return (pose, True)

        # Nothing worked: report the closest pose attempted so the caller can still animate a
        # credible attempt, and say plainly that it is not enough.
        best, best_gap = BodyPose(bend=max_bend, squash=min_squash), float("inf")
        for i in range(21):
            pose = BodyPose(bend=max_bend * (0.6 + 0.4 * i / 20.0), squash=min_squash)
            distance, reach, _ = shoulder_reach(rig, side, pose, target)
            gap = distance - reach * margin
            if gap < best_gap:
                best, best_gap = pose, gap
        return (best, False)
    finally:
        restore_pose(rig, saved)


@dataclass
class CrouchTrack:
    """Bend down for a reach, hold it, and stand back up - as a function of time."""

    entry: BodyPose
    low: BodyPose
    bend_start: float
    bend_end: float
    stand_start: float
    stand_end: float
    reachable: bool = True

    def pose_at(self, t: float) -> BodyPose:
        if t <= self.bend_start:
            return self.entry
        if t < self.bend_end:
            u = (t - self.bend_start) / max(1e-6, self.bend_end - self.bend_start)
            return self.entry.blended(self.low, u)
        if t <= self.stand_start:
            return self.low
        if t < self.stand_end:
            u = (t - self.stand_start) / max(1e-6, self.stand_end - self.stand_start)
            return self.low.blended(self.entry, u)
        return self.entry

    @property
    def total_bend(self) -> float:
        return self.low.bend


def plan_crouch(rig, side: str, target: Point, *, reach_start: float, reach_end: float,
                hold_until: float, recover_at: float, recover_by: float) -> CrouchTrack:
    """Build a bend schedule around an interaction's reach window.

    The character must be fully bent *before* the hand arrives, and must still be bent while the
    object is lifted - otherwise the arm is asked to reach a point the shoulder has already left.
    """

    pose, reachable = solve_crouch(rig, side, target)
    return CrouchTrack(
        entry=save_pose(rig),
        low=pose,
        bend_start=max(0.0, reach_start - 0.30),
        bend_end=reach_start + (reach_end - reach_start) * 0.55,
        stand_start=max(hold_until, reach_end),
        stand_end=max(recover_by, recover_by),
        reachable=reachable,
    )


def ground_target(ground_y: float, x: float, *, half_height: float = 14.0) -> Point:
    """Where a hand must be to grasp an object resting on the ground at ``x``."""

    return (x, ground_y - half_height)


def furniture_target(surface_y: float, x: float, *, half_height: float = 20.0) -> Point:
    """Where a hand must be to grasp an object standing on a table."""

    return (x, surface_y - half_height)
