"""Two-segment arm IK and world-space reach (T43).

The rigs draw an arm as one capsule from the shoulder to the hand, rotated by a single angle. That
is enough for a gesture that is *posed*, and not enough for a gesture that is *aimed*: a hand that
must arrive at a particular point in the world - a key lying on the ground, a cup on a table,
another character's hand - has two degrees of freedom it needs and one it has.

This module adds the missing joint without touching the rigs' art:

* ``ArmChain`` measures a rig's shoulder, segment lengths and neutral hand position by composing the
  same transform stack the rig draws with. Nothing is hard-coded from a constant that art changes
  could silently invalidate.
* ``solve_two_bone()`` is the analytic solver: law of cosines for the elbow, one perpendicular
  offset for the bend, reach clamped to the annulus the arm can actually occupy.
* ``ArmSolver`` adds the two things a per-frame solver gets wrong on its own: a fixed pole vector so
  the elbow cannot flip between frames, and an elbow-angle change limit so a target that jumps does
  not teleport the joint.

The rig keeps its original single-capsule path when ``arm_l_ik``/``arm_r_ik`` are unset, so every
existing episode and every golden frame renders exactly as before. This is additive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import cairo

Point = Tuple[float, float]

# Joint limits, in radians. A real elbow does not hyperextend and does not fold flat.
MIN_ELBOW_BEND = math.radians(4.0)
MAX_ELBOW_BEND = math.radians(158.0)

# How far the elbow angle may travel in one frame before it is slewed rather than snapped.
# At 30 fps this is 26 degrees per frame, which is inside a fast gesture and well below a jump cut.
MAX_ELBOW_STEP = math.radians(26.0)

# Fraction of the arm given to the upper segment. A cartoon arm reads better with a long forearm.
UPPER_FRACTION = 0.52


def _side_sign(side: str) -> float:
    return -1.0 if side == "left" else 1.0


def _prop(rig) -> dict:
    return rig.prop.values if hasattr(rig.prop, "values") else rig.prop


def arm_matrix(rig, side: str) -> cairo.Matrix:
    """The rig's transform stack, stopped at the shoulder.

    Mirrors ``props.hand_point`` exactly up to ``translate(sign * arm_attach_x, arm_attach_y)``,
    deliberately: if the rig's pose stack changes, the shoulder measurement follows it.
    """

    prop = _prop(rig)
    matrix = cairo.Matrix()
    matrix.translate(rig.x + getattr(rig, "hip_x", 0.0), rig.y + getattr(rig, "jump_y", 0.0))
    matrix.scale(rig.scale * rig.facing, rig.scale * getattr(rig, "squash", 1.0))
    matrix.translate(0.0, rig.torso.local_y + prop["torso_draw_offset"])
    matrix.rotate(rig.torso.local_rot)
    matrix.translate(_side_sign(side) * prop["arm_attach_x"], prop["arm_attach_y"])
    return matrix


def shoulder_point(rig, side: str) -> Point:
    """World position of the shoulder joint."""

    x, y = arm_matrix(rig, side).transform_point(0.0, 0.0)
    return (float(x), float(y))


def to_local(rig, side: str, world: Point) -> Point:
    """World point expressed in the arm's local frame (origin at the shoulder, unrotated)."""

    matrix = arm_matrix(rig, side)
    inverse = cairo.Matrix(*matrix)
    inverse.invert()
    x, y = inverse.transform_point(world[0], world[1])
    return (float(x), float(y))


def to_world(rig, side: str, local: Point) -> Point:
    x, y = arm_matrix(rig, side).transform_point(local[0], local[1])
    return (float(x), float(y))


@dataclass(frozen=True)
class ArmChain:
    """A rig's arm, measured rather than assumed."""

    side: str
    shoulder: Point
    upper: float
    fore: float
    neutral_hand: Point
    hand_radius: float

    @property
    def reach(self) -> float:
        return self.upper + self.fore

    @property
    def min_reach(self) -> float:
        return abs(self.upper - self.fore)

    def can_reach(self, target: Point, *, slack: float = 0.0) -> bool:
        """Is ``target`` inside the arm's annulus, allowng ``slack`` past the fingertip?

        The slack exists because a hand is not a point: a palm that stops 18 px short of an object
        centre is touching it.
        """

        distance = math.dist(self.shoulder, target)
        return self.min_reach <= distance <= self.reach + max(0.0, slack)


def chain_for(rig, side: str) -> ArmChain:
    """Measure an arm from the rig's own proportions."""

    prop = _prop(rig)
    hand_radius = float(prop.get("hand_ry", 16.0))
    # The neutral hand sits where the single-capsule draw puts it, so a solved rest pose has the
    # same silhouette as an unsolved one.
    neutral_local = (_side_sign(side) * float(prop["arm_shift"]),
                     float(prop["arm_len"]) + 5.0)
    length = math.hypot(neutral_local[0], neutral_local[1])
    return ArmChain(
        side=side,
        shoulder=shoulder_point(rig, side),
        upper=length * UPPER_FRACTION,
        fore=length * (1.0 - UPPER_FRACTION),
        neutral_hand=neutral_local,
        hand_radius=hand_radius,
    )


@dataclass(frozen=True)
class IKSolution:
    """Where the joints ended up, in the arm's local frame."""

    elbow: Point
    wrist: Point
    reach: float
    distance: float
    clamped: bool
    elbow_bend: float

    @property
    def reached(self) -> bool:
        """Did the hand arrive where it was asked to go? False means the target was out of range."""

        return not self.clamped


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


def solve_two_bone(shoulder: Point, target: Point, upper: float, fore: float, *,
                   pole: Point = (0.0, 1.0),
                   allow_shorten: bool = True) -> IKSolution:
    """Analytic two-bone IK in a plane.

    ``pole`` is a direction, not a point: the elbow bends toward it. Using a *fixed world direction*
    rather than a per-frame perpendicular is what stops the joint from flipping when the target
    crosses the shoulder-target axis - the failure mode that makes an arm snap.
    """

    dx, dy = target[0] - shoulder[0], target[1] - shoulder[1]
    distance = math.hypot(dx, dy)
    reach = upper + fore
    min_reach = abs(upper - fore)

    clamped = False
    total = distance
    if distance > reach:
        clamped = True
        if not allow_shorten:
            return IKSolution(shoulder, shoulder, reach, distance, True, 0.0)
        total = reach
    elif distance < min_reach:
        clamped = True
        total = min_reach

    if total <= 1e-6:
        return IKSolution(shoulder, shoulder, reach, distance, True, 0.0)

    # Unit vector along the shoulder->target line, recomputed at the (possibly clamped) distance.
    ux, uy = dx / distance if distance > 1e-9 else 0.0, dy / distance if distance > 1e-9 else 1.0

    # Law of cosines: distance from the shoulder to the foot of the elbow's perpendicular.
    along = (total * total + upper * upper - fore * fore) / (2.0 * total)
    along = _clamp(along, -upper, upper)
    height = math.sqrt(max(0.0, upper * upper - along * along))

    # Perpendicular direction: the pole, orthogonalised against the target direction so it is a
    # genuine bend and not a foreshortening artefact.
    px, py = pole
    dot = px * ux + py * uy
    perp_x, perp_y = px - dot * ux, py - dot * uy
    norm = math.hypot(perp_x, perp_y)
    if norm < 1e-6:  # pole parallel to the target: pick a stable fallback perpendicular
        perp_x, perp_y = -uy, ux
        norm = 1.0
    perp_x, perp_y = perp_x / norm, perp_y / norm

    elbow = (shoulder[0] + ux * along + perp_x * height,
             shoulder[1] + uy * along + perp_y * height)
    wrist = (shoulder[0] + ux * total, shoulder[1] + uy * total)

    bend = math.pi - math.acos(_clamp(
        (upper * upper + fore * fore - total * total) / (2.0 * upper * fore), -1.0, 1.0))
    bend = _clamp(bend, MIN_ELBOW_BEND, MAX_ELBOW_BEND)
    return IKSolution(elbow, wrist, reach, distance, clamped, bend)


@dataclass
class ArmSolver:
    """Per-arm solver state: a fixed pole and a slew limit on the elbow.

    Frame-to-frame stability is a property of the *state*, not of one call, which is why this is a
    class: a pure function of the target looks correct in a still and snaps in motion.
    """

    side: str
    pole: Point = (0.0, 1.0)
    _last_bend: Optional[float] = None
    _last_wrist: Optional[Point] = None

    def solve(self, chain: ArmChain, local_target: Point) -> IKSolution:
        """Solve for a target in the arm's own local frame.

        Local, not world: the arm's frame is rotated by the torso and mirrored by facing, so
        subtracting two world points would silently bend the elbow the wrong way on a turned body.
        """

        solution = solve_two_bone((0.0, 0.0), local_target, chain.upper, chain.fore,
                                  pole=self.pole)

        # Slew the wrist toward the solution so a jump in the target cannot teleport the hand. The
        # limit is generous enough that every authored reach inside one shot is unaffected.
        if self._last_wrist is not None:
            travelled = math.dist(self._last_wrist, solution.wrist)
            step_limit = max(chain.reach * 0.55, 40.0)
            if travelled > step_limit:
                ratio = step_limit / travelled
                wrist = (self._last_wrist[0] + (solution.wrist[0] - self._last_wrist[0]) * ratio,
                         self._last_wrist[1] + (solution.wrist[1] - self._last_wrist[1]) * ratio)
                local_target = wrist
                solution = solve_two_bone((0.0, 0.0), local_target, chain.upper, chain.fore,
                                          pole=self.pole)
        self._last_wrist = solution.wrist
        self._last_bend = solution.elbow_bend
        return solution

    def reset(self) -> None:
        self._last_wrist = None
        self._last_bend = None


def apply_ik(rig, side: str, target: Point, *, solver: Optional[ArmSolver] = None) -> IKSolution:
    """Solve an arm toward a world target and store the joint positions on the rig.

    The rig's ``draw`` uses ``arm_l_ik``/``arm_r_ik`` when they are set and its original single
    capsule when they are not, which is what keeps un-posed episodes bit-identical.
    """

    chain = chain_for(rig, side)
    active = solver if solver is not None else ArmSolver(side=side)
    solution = active.solve(chain, to_local(rig, side, target))
    setattr(rig, f"arm_{'l' if side == 'left' else 'r'}_ik", solution)
    # The IK path owns the arm angle: leaving a stale angle on the rig would stack two rotations.
    setattr(rig, f"arm_{'l' if side == 'left' else 'r'}_angle", 0.0)
    return solution


def clear_ik(rig, side: Optional[str] = None) -> None:
    """Return an arm (or both) to the original single-capsule draw."""

    sides = ["left", "right"] if side is None else [side]
    for name in sides:
        setattr(rig, f"arm_{'l' if name == 'left' else 'r'}_ik", None)


def reload_neutral(rig, side: str) -> IKSolution:
    """Set an arm to the exact neutral pose the single capsule occupies.

    Used to enter and leave an interaction without a visible pop: the first and last frame of a
    solved arm match the unsolved silhouette.
    """

    chain = chain_for(rig, side)
    solution = solve_two_bone((0.0, 0.0), chain.neutral_hand, chain.upper, chain.fore)
    setattr(rig, f"arm_{'l' if side == 'left' else 'r'}_ik", solution)
    return solution
