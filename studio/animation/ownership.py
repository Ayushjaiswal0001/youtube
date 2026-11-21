"""Object ownership: who is holding what, and under what rule it may change hands.

The renderer could already *animate* a hand-off (`props.PropTrack`) and a pickup
(`animation.pickup_scene`), but nothing in the system knew who owned an object. Two independent
tracks could therefore both hold the same key, and a transfer could complete while the receiver's
hand was still 200 px away - the animation looked like a hand-off and was not one.

This module is the single authority on that question, so the animation, the QC validator and the
continuity report all read the same answer:

* an object has **one** holder (or none),
* a transfer requires the receiver to have made **measured** contact,
* a release is only legal for the current holder,
* and every change is recorded with a time and a reason, so a discontinuity can be explained rather
  than merely detected.

Nothing here draws. It is a state machine plus an audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float]

#: The legal steps of an object interaction, in the order a scene may use them. A sequence does not
#: have to use them all, but it may not use them out of order: a hand-off before a pickup is not a
#: story beat, it is a bug.
APPROACH = "APPROACH"
CROUCH = "CROUCH"
PICKUP = "PICKUP"
HOLD = "HOLD"
TURN = "TURN"
REACH = "REACH"
HANDOFF = "HANDOFF"
RELEASE = "RELEASE"
RECOVERY = "RECOVERY"

SEQUENCE_ORDER: Tuple[str, ...] = (APPROACH, CROUCH, PICKUP, HOLD, TURN, REACH, HANDOFF, RELEASE,
                                   RECOVERY)
_STEP_RANK = {step: index for index, step in enumerate(SEQUENCE_ORDER)}

#: Steps that may be skipped: a table pickup needs no crouch, a sequence may end while the character
#: still holds the object, and nothing has to be released.
OPTIONAL_STEPS = frozenset({CROUCH, TURN, RELEASE, RECOVERY})

GROUND = "ground"
TABLE = "table"
HAND = "hand"
AIR = "air"


class OwnershipError(Exception):
    """Base class for a rule the ledger refuses to break."""


class OwnershipConflict(OwnershipError):
    """Two characters tried to own the same object."""


class IllegalTransfer(OwnershipError):
    """A transfer that the animation has not earned - the receiver never touched the object."""


class UnknownObject(OwnershipError):
    """An object that was never registered."""


@dataclass
class ObjectState:
    name: str
    holder: Optional[str]
    position: Point
    surface: str = GROUND

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "holder": self.holder,
                "position": [round(self.position[0], 1), round(self.position[1], 1)],
                "surface": self.surface}


@dataclass
class Change:
    """One recorded ownership event, kept so a continuity failure can be explained."""

    at: float
    object: str
    action: str
    holder: Optional[str]
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"at": round(self.at, 3), "object": self.object, "action": self.action,
                "holder": self.holder, "detail": self.detail}


@dataclass
class OwnershipLedger:
    """The authority on which character holds which object.

    A ledger is created per episode and shared by every scene, because ownership is exactly the
    property that must survive a scene boundary - a prop that changes hands across a cut has to
    still be in the new owner's hand on the other side.
    """

    characters: Sequence[str]
    objects: Dict[str, ObjectState] = field(default_factory=dict)
    history: List[Change] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.characters = tuple(self.characters)
        if not self.characters:
            raise ValueError("a ledger needs at least one character")

    # -- registration -------------------------------------------------------

    def register(self, name: str, position: Point, surface: str = GROUND,
                 holder: Optional[str] = None, at: float = 0.0) -> ObjectState:
        if holder is not None and holder not in self.characters:
            raise UnknownObject(f"unknown holder {holder!r}")
        state = ObjectState(name=name, holder=holder, position=(float(position[0]),
                                                                float(position[1])),
                            surface=HAND if holder else surface)
        self.objects[name] = state
        self.history.append(Change(at=at, object=name, action="register", holder=holder,
                                   detail=f"surface={surface}"))
        return state

    def state(self, name: str) -> ObjectState:
        if name not in self.objects:
            raise UnknownObject(f"object {name!r} was never registered")
        return self.objects[name]

    def holder_of(self, name: str) -> Optional[str]:
        return self.state(name).holder

    def held_by(self, character: str) -> List[str]:
        return sorted(n for n, state in self.objects.items() if state.holder == character)

    # -- transitions --------------------------------------------------------

    def claim(self, name: str, holder: str, at: float, *,
              contact_confirmed: bool = True, position: Optional[Point] = None) -> ObjectState:
        """Take an unheld object. An object already in someone's hands is a conflict, not a claim."""

        if holder not in self.characters:
            raise UnknownObject(f"unknown character {holder!r}")
        state = self.state(name)
        if state.holder is not None:
            if state.holder == holder:
                return state  # idempotent: claiming what you already hold is a no-op
            raise OwnershipConflict(
                f"{name!r} is held by {state.holder!r}; {holder!r} cannot claim it without a transfer")
        if not contact_confirmed:
            raise IllegalTransfer(
                f"{holder!r} has not touched {name!r}; a claim without contact is not a pickup")
        if position is not None:
            state.position = (float(position[0]), float(position[1]))
        state.holder = holder
        state.surface = HAND
        self.history.append(Change(at=at, object=name, action="claim", holder=holder))
        return state

    def transfer(self, name: str, frm: str, to: str, at: float, *,
                 contact_confirmed: bool, position: Optional[Point] = None) -> ObjectState:
        """Move an object between characters.

        ``contact_confirmed`` must come from a *measurement of the drawn hand* - the renderer passes
        the receiver's real contact error. This is the rule that makes a hand-off a hand-off: the
        giver keeps ownership until the receiver has actually touched the object.
        """

        if to not in self.characters or frm not in self.characters:
            raise UnknownObject(f"unknown character in transfer {frm!r} -> {to!r}")
        if frm == to:
            raise IllegalTransfer("a transfer needs two different characters")
        state = self.state(name)
        if state.holder != frm:
            raise IllegalTransfer(
                f"{name!r} is held by {state.holder!r}, not {frm!r}; the transfer cannot start")
        if not contact_confirmed:
            raise IllegalTransfer(
                f"{to!r} has not touched {name!r} yet; the giver cannot let go")
        if position is not None:
            state.position = (float(position[0]), float(position[1]))
        state.holder = to
        self.history.append(Change(at=at, object=name, action="transfer", holder=to,
                                   detail=f"from {frm}"))
        return state

    def release(self, name: str, holder: str, at: float, *,
                position: Optional[Point] = None, surface: str = GROUND) -> ObjectState:
        """Put an object down. Only the holder may do this, and the object keeps its place."""

        state = self.state(name)
        if state.holder != holder:
            raise IllegalTransfer(
                f"{holder!r} cannot release {name!r}: it is held by {state.holder!r}")
        if position is not None:
            state.position = (float(position[0]), float(position[1]))
        state.holder = None
        state.surface = surface
        self.history.append(Change(at=at, object=name, action="release", holder=None,
                                   detail=f"by {holder} onto {surface}"))
        return state

    def carry(self, name: str, position: Point) -> None:
        """Keep a held object in its holder's hand without changing ownership."""

        self.state(name).position = (float(position[0]), float(position[1]))

    # -- reporting ----------------------------------------------------------

    def snapshot(self, at: float = 0.0) -> Dict[str, Any]:
        return {"at": round(at, 3),
                "objects": {n: s.as_dict() for n, s in sorted(self.objects.items())},
                "held": {c: self.held_by(c) for c in self.characters}}

    def as_dict(self) -> Dict[str, Any]:
        return {"objects": {n: s.as_dict() for n, s in sorted(self.objects.items())},
                "history": [change.as_dict() for change in self.history]}


@dataclass(frozen=True)
class SequenceViolation:
    code: str
    step: str
    detail: str

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "step": self.step, "detail": self.detail}


def validate_sequence(steps: Sequence[str], *, surface: str = GROUND,
                      characters: int = 2) -> List[SequenceViolation]:
    """Check that an authored interaction sequence is physically and structurally possible.

    Deliberately strict about order and deliberately quiet about length: a scene may stop after
    HOLD (the character keeps the object), so a missing RELEASE is not a violation.
    """

    problems: List[SequenceViolation] = []
    rank = -1
    for step in steps:
        if step not in _STEP_RANK:
            problems.append(SequenceViolation("unknown_step", str(step), "not a legal step"))
            continue
        if _STEP_RANK[step] <= rank:
            problems.append(SequenceViolation(
                "out_of_order", step, "appears before a step that must precede it"))
        rank = max(rank, _STEP_RANK[step])

    present = set(steps)
    if HANDOFF in present and characters < 2:
        problems.append(SequenceViolation(
            "handoff_without_partner", HANDOFF, "a hand-off needs a second character"))
    if HANDOFF in present and PICKUP not in present and HOLD not in present:
        problems.append(SequenceViolation(
            "handoff_without_ownership", HANDOFF,
            "nothing establishes who holds the object before it changes hands"))
    if PICKUP in present and surface == GROUND and CROUCH not in present:
        problems.append(SequenceViolation(
            "pickup_without_crouch", PICKUP,
            "a ground pickup needs the body to bend; the arm cannot reach the floor"))
    if RELEASE in present and HOLD not in present and PICKUP not in present:
        problems.append(SequenceViolation(
            "release_without_hold", RELEASE, "nothing is held at the point of release"))
    if HANDOFF in present and REACH not in present:
        problems.append(SequenceViolation(
            "handoff_without_reach", HANDOFF,
            "the receiver must reach for the object before it arrives"))
    return problems
