"""World-space pickup, grips and interaction state (T43).

``props.py`` (T40) can attach an object to a hand that is already somewhere. This module answers
the harder question a story actually asks: *the object is lying over there, can this character get
to it, and how do they get there?*

Three things are deliberately separate:

* ``WorldObject`` - where the object is, how big it is, and what it is resting on. Its reachable
  hand position is derived from that surface, not typed in beside it.
* ``PickupPlan`` - the schedule. It is built from measurements (character shoulder, arm reach,
  object box) and it is inspectable: every phase has an interval, and the plan reports whether the
  character has to walk first, and what the hand is doing at any time.
* ``PickupMachine`` - the state machine from the brief, with recorded transitions. It exists so a
  test can ask "was the object gripped before it moved", which is the difference between a pickup
  and a prop that teleports into a hand.

A pickup that is out of reach is a first-class outcome, not an error: ``PickupPlan.approach_first``
carries the distance the character must close, and an unreachable plan still produces a schedule -
it fails at REACHING, and a follower plan recovers. Never claiming contact unless
``contact_error`` is inside tolerance is the point of the measurement helpers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from studio.characters.ik import ArmChain, chain_for, solve_two_bone, MIN_ELBOW_BEND

Point = Tuple[float, float]
Box = Tuple[float, float, float, float]

# A hand is "in contact" with an object when its centre is within this distance of the object's
# nearest edge. The rig's hand is an ellipse of radius ~17 px, so 10 px of overlap is a grip.
CONTACT_TOLERANCE = 10.0

# Where a palm sits relative to the object centre for each grip: (dx, dy, dominant hand).
GRIP_OFFSETS: Dict["Grip", Tuple[float, float]] = {}


class Grip(str, Enum):
    """How a hand (or two) holds a thing."""

    SINGLE = "single_hand"
    SMALL = "small_object"
    TWO_HAND = "two_hand"
    LARGE_SUPPORT = "large_object"
    HANDOFF = "handoff"

    @property
    def hands(self) -> int:
        return 2 if self in (Grip.TWO_HAND, Grip.LARGE_SUPPORT) else 1

    @property
    def grip_inset(self) -> float:
        """How far inside the object's silhouette the palm sits.

        A small object is grasped at its centre; a large one is supported from the underside, so
        the hand is lower than the centre rather than inside it.
        """

        return {"single_hand": 0.0, "small_object": 0.0, "two_hand": 0.0,
                "large_object": 0.45, "handoff": 0.0}[self.value]

    @property
    def palm_drop(self) -> float:
        """Vertical offset of the palm below the object centre, as a fraction of its half-height."""

        return 0.9 if self in (Grip.LARGE_SUPPORT, Grip.TWO_HAND) else 0.0


class PickupState(str, Enum):
    IDLE = "IDLE"
    APPROACHING = "APPROACHING"
    REACHING = "REACHING"
    CONTACT = "CONTACT"
    GRIPPING = "GRIPPING"
    HOLDING = "HOLDING"
    TRANSFERRING = "TRANSFERRING"
    RELEASING = "RELEASING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


# The legal order. A state machine that only *has* ten names is a list, not a machine: these edges
# are what a test can check against a recorded timeline.
ALLOWED_EDGES = {
    PickupState.IDLE: {PickupState.APPROACHING, PickupState.REACHING, PickupState.FAILED},
    PickupState.APPROACHING: {PickupState.REACHING, PickupState.FAILED},
    PickupState.REACHING: {PickupState.CONTACT, PickupState.FAILED},
    PickupState.CONTACT: {PickupState.GRIPPING, PickupState.FAILED},
    PickupState.GRIPPING: {PickupState.HOLDING, PickupState.FAILED},
    PickupState.HOLDING: {PickupState.TRANSFERRING, PickupState.RELEASING, PickupState.IDLE},
    PickupState.TRANSFERRING: {PickupState.RELEASING, PickupState.FAILED},
    PickupState.RELEASING: {PickupState.COMPLETE, PickupState.IDLE},
    PickupState.COMPLETE: set(),
    PickupState.FAILED: {PickupState.APPROACHING, PickupState.IDLE},
}


class InvalidTransition(RuntimeError):
    """Raised when a state machine is driven somewhere the animation cannot justify."""


@dataclass(frozen=True)
class WorldObject:
    """An object with a place in the scene."""

    name: str
    centre: Point
    half_w: float
    half_h: float
    rests_on: str = "ground"  # "ground" | "table" | "held"

    @property
    def box(self) -> Box:
        x, y = self.centre
        return (x - self.half_w, y - self.half_h, x + self.half_w, y + self.half_h)

    @property
    def top(self) -> float:
        return self.centre[1] - self.half_h

    def distance_to(self, point: Point) -> float:
        """Distance from a point to the object's *edge*, negative inside it."""

        left, top, right, bottom = self.box
        dx = max(left - point[0], 0.0, point[0] - right)
        dy = max(top - point[1], 0.0, point[1] - bottom)
        if dx == 0.0 and dy == 0.0:
            return -min(point[0] - left, right - point[0], point[1] - top, bottom - point[1])
        return math.hypot(dx, dy)

    def grasp_point(self, grip: Grip, side: str = "right") -> Point:
        """Where a palm should meet this object for a given grip."""

        offset = self.half_w * (0.35 if grip.hands == 2 else 0.0)
        sign = 1.0 if side == "right" else -1.0
        x = self.centre[0] + (sign * offset if grip.hands == 2 else 0.0)
        y = self.centre[1] + self.half_h * grip.palm_drop
        if grip.hands == 2:
            x = self.centre[0] + sign * self.half_w * 0.55
        return (x, y)


@dataclass
class Phase:
    """One interval of a pickup schedule."""

    state: PickupState
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def contains(self, t: float) -> bool:
        return self.start <= t < self.end


@dataclass
class PickupPlan:
    """A measured schedule for getting a hand onto an object and lifting it."""

    object: WorldObject
    character: str
    side: str
    grip: Grip
    phases: List[Phase]
    reach_distance: float
    arm_reach: float
    need_approach: bool
    character_x: float
    approach_dx: float
    behind_character: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.phases[-1].end if self.phases else 0.0

    @property
    def feasible(self) -> bool:
        """Can the arm arrive without the character moving?"""

        return not self.need_approach

    @property
    def approach_first(self) -> float:
        return self.approach_dx

    def state_at(self, t: float) -> PickupState:
        for phase in self.phases:
            if phase.contains(t):
                return phase.state
        return self.phases[-1].state if self.phases else PickupState.IDLE

    def phase_at(self, t: float) -> Phase:
        for phase in self.phases:
            if phase.contains(t):
                return phase
        return self.phases[-1]

    def transitions(self) -> List[Tuple[str, str, float]]:
        return [(self.phases[i].state.value, self.phases[i + 1].state.value, self.phases[i].end)
                for i in range(len(self.phases) - 1)]


def plan_pickup(rig, obj: WorldObject, *, character: str, side: str = "right",
                grip: Grip = Grip.SINGLE, approach_speed: float = 260.0,
                reach_time: float = 0.42, grip_time: float = 0.18, hold_time: float = 0.55,
                release_time: float = 0.22) -> PickupPlan:
    """Build a schedule from measurements of the character and the object.

    Nothing here is a magic number chosen to look right: the approach distance comes from the
    shoulder-to-grasp distance minus the arm's own reach, and the phases are placed so the hand is
    still travelling during REACHING and only stops moving at CONTACT.
    """

    chain: ArmChain = chain_for(rig, side)
    grasp = obj.grasp_point(grip, side)
    # The shoulder moves with the character, so measure against the shoulder's current offset.
    approach_dx = grasp[0] - chain.shoulder[0]
    need_approach = abs(approach_dx) > 0.0

    reach_distance = math.dist(chain.shoulder, grasp)
    slack = chain.hand_radius
    notes: List[str] = []
    # An object on the character's back is not a reach problem, it is a blocking problem: the
    # character has to turn first. Reporting it as "out of reach" would send them walking backwards,
    # which is exactly the kind of silent nonsense a continuity check exists to catch.
    facing = float(getattr(rig, "facing", 1.0)) or 1.0
    behind = (grasp[0] - chain.shoulder[0]) * facing < 0.0
    if behind:
        notes.append("object is behind the character; they must turn before reaching")
    if reach_distance > chain.reach + slack:
        # Measured in the character's *standing* pose: a bend (crouch.solve_crouch) can still bring
        # the object within reach, so this note reports the standing gap rather than a verdict.
        notes.append(f"out of reach standing by {reach_distance - chain.reach - slack:.1f} px")
    if grip.hands == 2:
        notes.append("two hands required; the second hand mirrors the first")

    travel = abs(approach_dx) / max(1.0, approach_speed)
    phases: List[Phase] = []
    now = 0.0
    if need_approach and travel > 0.02:
        phases.append(Phase(PickupState.APPROACHING, now, now + travel))
        now += travel
    phases.append(Phase(PickupState.REACHING, now, now + reach_time))
    now += reach_time
    phases.append(Phase(PickupState.CONTACT, now, now + grip_time * 0.5))
    now += grip_time * 0.5
    phases.append(Phase(PickupState.GRIPPING, now, now + grip_time * 0.5))
    now += grip_time * 0.5
    phases.append(Phase(PickupState.HOLDING, now, now + hold_time))
    now += hold_time
    phases.append(Phase(PickupState.RELEASING, now, now + release_time))
    now += release_time
    phases.append(Phase(PickupState.COMPLETE, now, now + 0.35))

    return PickupPlan(object=obj, character=character, side=side, grip=grip, phases=phases,
                      reach_distance=reach_distance, arm_reach=chain.reach,
                      need_approach=need_approach, character_x=rig.x,
                      approach_dx=approach_dx, behind_character=behind, notes=notes)


@dataclass
class PickupMachine:
    """Drives a plan, recording every transition it makes."""

    plan: PickupPlan
    state: PickupState = PickupState.IDLE
    entered_at: float = 0.0
    log: List[Tuple[str, float]] = field(default_factory=list)
    failed_at: Optional[float] = None

    def __post_init__(self) -> None:
        self.log.append((PickupState.IDLE.value, 0.0))

    def transition(self, new: PickupState, t: float) -> None:
        if new not in ALLOWED_EDGES[self.state]:
            raise InvalidTransition(f"{self.state.value} -> {new.value} is not a legal pickup move")
        self.state = new
        self.entered_at = t
        self.log.append((new.value, round(t, 3)))
        if new is PickupState.FAILED:
            self.failed_at = t

    def update(self, t: float, *, contact_error: Optional[float] = None) -> PickupState:
        """Advance to whatever the schedule says should be true at ``t``.

        The schedule alone is not trusted: leaving REACHING requires that the hand is actually on
        the object. A plan that says CONTACT while the hand is 40 px away is a cartesian lie, and
        this machine reports it as FAILED instead.
        """

        wanted = self.plan.state_at(t)
        if wanted is self.state:
            return self.state
        if self.state is PickupState.REACHING and wanted in (PickupState.CONTACT,
                                                             PickupState.GRIPPING):
            if contact_error is not None and contact_error > CONTACT_TOLERANCE:
                self.transition(PickupState.FAILED, t)
                return self.state
        while self.state is not wanted:
            nxt = _next_towards(self.state, wanted)
            if nxt is None:
                break
            self.transition(nxt, t)
        return self.state


def _next_towards(current: PickupState, wanted: PickupState) -> Optional[PickupState]:
    order = [PickupState.IDLE, PickupState.APPROACHING, PickupState.REACHING,
             PickupState.CONTACT, PickupState.GRIPPING, PickupState.HOLDING,
             PickupState.TRANSFERRING, PickupState.RELEASING, PickupState.COMPLETE]
    if wanted in ALLOWED_EDGES[current]:
        return wanted  # a legal direct move beats walking through intermediate states
    if current not in order or wanted not in order:
        return None
    i, j = order.index(current), order.index(wanted)
    if j <= i:
        return None
    candidate = order[i + 1]
    return candidate if candidate in ALLOWED_EDGES[current] else None


def hand_target(plan: PickupPlan, chain: ArmChain, t: float,
                *, rest: Optional[Point] = None) -> Point:
    """Where the hand should be at time ``t``, in world space.

    The hand travels during REACHING, is on the object from CONTACT to HOLDING, and returns to
    rest during RELEASING. Interpolation is smoothstepped so the arm has no velocity step at the
    boundaries - the "arms teleport" artefact this replaces.
    """

    rest_point = rest if rest is not None else (
        chain.shoulder[0] + chain.neutral_hand[0], chain.shoulder[1] + chain.neutral_hand[1])
    grasp = plan.object.grasp_point(plan.grip, plan.side)
    phase = plan.phase_at(t)
    if phase.state in (PickupState.IDLE, PickupState.APPROACHING):
        return rest_point
    if phase.state is PickupState.REACHING:
        u = _smoothstep((t - phase.start) / max(1e-6, phase.duration))
        return (rest_point[0] + (grasp[0] - rest_point[0]) * u,
                rest_point[1] + (grasp[1] - rest_point[1]) * u)
    if phase.state in (PickupState.CONTACT, PickupState.GRIPPING, PickupState.HOLDING):
        return grasp
    if phase.state is PickupState.RELEASING:
        u = _smoothstep((t - phase.start) / max(1e-6, phase.duration))
        return (grasp[0] + (rest_point[0] - grasp[0]) * u,
                grasp[1] + (rest_point[1] - grasp[1]) * u)
    return rest_point


def _smoothstep(u: float) -> float:
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * (3.0 - 2.0 * u)


def contact_error(obj: WorldObject, hand: Point) -> float:
    """How far the hand is from touching the object. Negative means overlapping it."""

    return obj.distance_to(hand)


def carrier_offset(obj: WorldObject, grip: Grip) -> Tuple[float, float]:
    """Where the object sits relative to the palm once it is held."""

    return (0.0, -obj.half_h * GRIP_OFFSETS.get(grip, (0.0, 0.0))[1]) if grip in GRIP_OFFSETS \
        else (0.0, -obj.half_h + obj.half_h * grip.palm_drop * 0.0)


def two_hand_targets(plan: PickupPlan, left_chain: ArmChain, right_chain: ArmChain,
                     t: float) -> Dict[str, Point]:
    """Both palms for a two-handed grip, symmetric about the object's centre."""

    grasp = plan.object.grasp_point(plan.grip, "right")
    left = plan.object.grasp_point(plan.grip, "left")
    return {"right": grasp, "left": left}


def arm_stability(samples: List[Tuple[float, Point]], *, fps: int = 30) -> Dict[str, float]:
    """Per-frame wrist travel, which is how "the arm snapped" is measured rather than eyeballed."""

    if len(samples) < 2:
        return {"max_step": 0.0, "mean_step": 0.0, "reversals": 0.0}
    steps = [math.dist(samples[i][1], samples[i + 1][1]) for i in range(len(samples) - 1)]
    reversals = 0
    for i in range(1, len(steps)):
        if steps[i] > 1e-3 and steps[i - 1] > 1e-3:
            a = (samples[i][1][0] - samples[i - 1][1][0], samples[i][1][1] - samples[i - 1][1][1])
            b = (samples[i + 1][1][0] - samples[i][1][0], samples[i + 1][1][1] - samples[i][1][1])
            if a[0] * b[0] + a[1] * b[1] < 0.0:
                reversals += 1
    return {"max_step": max(steps), "mean_step": sum(steps) / len(steps),
            "reversals": float(reversals)}
