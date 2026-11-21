"""Story and scene continuity: what the previous scene left behind, and whether the next respects it.

An episode is not twelve independent animations. It is one story that happens to be cut into shots,
and the things that break that illusion are dull and concrete: a prop that is in a character's hand
and then on the floor, a character who swapped sides of the frame between cuts, a key that changed
owner without anyone touching it, a camera that teleported from a wide to a close-up and back.

This module keeps a :class:`SceneState` per scene and compares consecutive states. Everything it
reports is derived from declarations the renderer already respects, so a reported problem is a real
inconsistency in the authored plan rather than a guess about pixels.

Severity follows the directive:

* ``error`` - impossible: ownership without a transfer, a prop that vanishes, an empty line.
* ``warning`` - suspicious but possibly intended: a facing flip, a large camera jump, a repeated line.
* ``info`` - a recorded, legitimate change: a declared lighting or camera change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from studio.animation.ownership import (
    GROUND,
    HAND,
    TABLE,
    OwnershipConflict,
    OwnershipLedger,
    IllegalTransfer,
    UnknownObject,
)

Point = Tuple[float, float]

ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITY_RANK = {ERROR: 0, WARNING: 1, INFO: 2}

#: A character may not move further than this between scenes without a declared reason. Set from the
#: stage: the two slots are 720 px apart in a 1920-wide frame, so a legal walk across the stage fits
#: comfortably inside it while a teleport does not.
MAX_UNDECLARED_MOVE_PX = 260.0
#: A zoom change larger than this between consecutive scenes reads as a jump cut.
MAX_ZOOM_JUMP = 0.55


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    scene: int
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "scene": self.scene,
                "message": self.message, "evidence": self.evidence}


@dataclass
class SceneState:
    """The state at the end of a scene - the contract the next scene inherits."""

    scene: int
    #: object name -> holder (or None). Carried forward across scenes.
    owners: Dict[str, Optional[str]] = field(default_factory=dict)
    #: object name -> world position, so a prop that moves must have moved by an interaction.
    positions: Dict[str, Point] = field(default_factory=dict)
    #: character -> facing sign, so a flip without a turn is visible.
    facing: Dict[str, float] = field(default_factory=dict)
    #: character -> pose name, for the pose-continuity info entries.
    poses: Dict[str, str] = field(default_factory=dict)
    lighting: Optional[str] = None
    camera: Optional[str] = None
    zoom: Optional[float] = None
    speaker: Optional[str] = None
    line: str = ""
    ground_y: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"scene": self.scene,
                "owners": dict(sorted(self.owners.items())),
                "positions": {k: [round(v[0], 1), round(v[1], 1)]
                              for k, v in sorted(self.positions.items())},
                "facing": dict(sorted(self.facing.items())),
                "poses": dict(sorted(self.poses.items())),
                "lighting": self.lighting, "camera": self.camera, "zoom": self.zoom,
                "speaker": self.speaker, "line": self.line}


@dataclass
class ContinuityReport:
    states: List[SceneState] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    def add(self, code: str, severity: str, scene: int, message: str, **evidence) -> None:
        self.issues.append(Issue(code, severity, scene, message, evidence))

    def of(self, severity: str) -> List[Issue]:
        return [issue for issue in self.issues if issue.severity == severity]

    @property
    def errors(self) -> List[Issue]:
        return self.of(ERROR)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok,
                "counts": {severity: len(self.of(severity))
                           for severity in (ERROR, WARNING, INFO)},
                "issues": [issue.as_dict() for issue in self.issues],
                "states": [state.as_dict() for state in self.states]}


def _facing_for(scene: Mapping[str, Any], character: str, default: float) -> float:
    """Facing follows the interaction: a hand-off partner has to be turned toward the giver."""

    interaction = scene.get("interaction") or {}
    if isinstance(interaction, Mapping):
        for key in ("facing", "partner"):
            value = interaction.get(key)
            if isinstance(value, Mapping) and character in value:
                try:
                    return float(value[character])
                except (TypeError, ValueError):
                    break
    return default


def _object_declarations(scene: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Everything in one scene that moves or holds an object, normalised to a small record."""

    found: Dict[str, Dict[str, Any]] = {}
    prop = scene.get("prop")
    if prop:
        record = {"name": str(prop), "holder": scene.get("prop_holder"),
                  "handoff_to": scene.get("prop_handoff_to"), "surface": HAND,
                  "pickup": False}
        found[record["name"]] = record
    pickup = scene.get("pickup")
    if isinstance(pickup, Mapping):
        name = str(pickup.get("object") or "object")
        record = found.setdefault(name, {"name": name, "surface": pickup.get("surface", GROUND),
                                         "handoff_to": None, "pickup": True})
        record["holder"] = pickup.get("holder") or record.get("holder")
        record["surface"] = pickup.get("surface", record.get("surface", GROUND))
        record["handoff_to"] = pickup.get("handoff_to") or record.get("handoff_to")
        record["pickup"] = True
    return found


def build_states(scenes: Sequence[Mapping[str, Any]], *,
                 characters: Sequence[str] = ("chiku", "gappu"),
                 default_facing: Mapping[str, float] | None = None,
                 ground_y: Optional[float] = None) -> ContinuityReport:
    """Walk the plan, carrying state forward, and record everything that does not add up."""

    report = ContinuityReport()
    default_facing = dict(default_facing or {"chiku": 1.0, "gappu": -1.0})
    owners: Dict[str, Optional[str]] = {}
    positions: Dict[str, Point] = {}
    previous: Optional[SceneState] = None

    for index, scene in enumerate(scenes, start=1):
        number = int(scene.get("scene_num") or scene.get("n") or index)
        state = SceneState(scene=number, ground_y=ground_y)
        state.lighting = scene.get("lighting") or (previous.lighting if previous else None)
        state.camera = scene.get("camera") or (previous.camera if previous else None)
        state.speaker = scene.get("speaker") or (previous.speaker if previous else None)
        zoom = scene.get("shot_zoom")
        state.zoom = float(zoom) if isinstance(zoom, (int, float)) else (
            previous.zoom if previous else None)

        # -- dialogue ------------------------------------------------------
        line = (scene.get("line") or scene.get("dialogue") or "").strip()
        if not line:
            report.add("empty_line", ERROR, number, "scene has no dialogue, so nothing carries it",
                       speaker=state.speaker)
        elif previous is not None and line == previous.line:
            report.add("repeated_line", WARNING, number,
                       "the same line as the previous scene", line=line)
        state.line = line

        # -- facing --------------------------------------------------------
        facing: Dict[str, float] = {}
        for character in characters:
            value = _facing_for(scene, character, default_facing.get(character, 1.0))
            facing[character] = value
            if previous is not None:
                before = previous.facing.get(character)
                if before is not None and before != value:
                    declared = bool(scene.get("turn") or scene.get("interaction") or
                                    scene.get("pickup"))
                    report.add("facing_flip", INFO if declared else WARNING, number,
                               f"{character} changed facing from {before:+.0f} to {value:+.0f}",
                               character=character, declared=declared)
        state.facing = facing
        state.poses = {c: str(scene.get(f"{c}_pose") or "") for c in characters}

        # -- objects and ownership ----------------------------------------
        declared = _object_declarations(scene)
        ledger = OwnershipLedger(characters=list(characters))
        for name, holder in owners.items():
            known = positions.get(name, (0.0, 0.0))
            ledger.register(name, known, surface=HAND if holder else GROUND, holder=holder)

        for name, record in declared.items():
            holder = record.get("holder")
            target = record.get("handoff_to")
            # A declared hand-off names who holds the object at the *start* and where it must end
            # up. The end owner is the destination, not the holder - reading it the other way round
            # reported every legitimate hand-off as a conflict.
            end_owner = target or holder
            if holder is not None and holder not in characters:
                # Reported rather than raised: one bad authoring line must not lose the whole
                # report, and the ledger below refuses an unknown holder by design.
                report.add("unknown_character", ERROR, number,
                           f"{name!r} is declared held by {holder!r}, who is not in the cast",
                           object=name)
                holder = None
                end_owner = None
            if name not in owners:
                ledger.register(name, positions.get(name, (0.0, 0.0)),
                                surface=record.get("surface", GROUND), holder=holder,
                                at=float(number))
            before = owners.get(name)
            if target and target == holder:
                report.add("handoff_to_self", ERROR, number,
                           f"{name!r} is handed off to the character already holding it",
                           object=name)
            elif before is not None and end_owner != before:
                if not (target or record.get("pickup")):
                    report.add("ownership_without_transfer", ERROR, number,
                               f"{name!r} moved from {before!r} to {end_owner!r} with no hand-off "
                               f"and no pickup", object=name, before=before, after=end_owner)
                elif before is None and not record.get("pickup"):
                    report.add("prop_appears_in_hand", WARNING, number,
                               f"{name!r} is in {end_owner!r}'s hand without being picked up",
                               object=name)
            elif before is None and end_owner is not None and not record.get("pickup"):
                report.add("prop_appears_in_hand", WARNING, number,
                           f"{name!r} is in {end_owner!r}'s hand without being picked up",
                           object=name)
            if end_owner is not None:
                if end_owner not in characters:
                    report.add("unknown_character", ERROR, number,
                               f"{name!r} is held by {end_owner!r}, who is not in the cast",
                               object=name)
                else:
                    try:
                        ledger.transfer(name, before if before else end_owner, end_owner,
                                        float(number), contact_confirmed=True)
                    except IllegalTransfer:
                        ledger.objects[name].holder = end_owner
            elif target is None and record.get("pickup"):
                try:
                    ledger.claim(name, str(holder or characters[0]), float(number),
                                 contact_confirmed=True)
                except (OwnershipConflict, UnknownObject) as exc:
                    report.add("ownership_conflict", ERROR, number, str(exc), object=name)

        # Two characters cannot own the same object in one scene.
        by_object: Dict[str, List[str]] = {}
        for name, record in declared.items():
            end_owner = record.get("handoff_to") or record.get("holder")
            if end_owner:
                by_object.setdefault(name, []).append(str(end_owner))
        for name, holders in by_object.items():
            if len(set(holders)) > 1:
                report.add("double_ownership", ERROR, number,
                           f"{name!r} is declared held by {sorted(set(holders))}", object=name)

        for name, obj in ledger.objects.items():
            owners[name] = obj.holder
            positions[name] = obj.position
        state.owners = dict(owners)
        state.positions = dict(positions)

        # -- camera and lighting -------------------------------------------
        if previous is not None:
            if previous.zoom is not None and state.zoom is not None:
                jump = abs(state.zoom - previous.zoom)
                if jump > MAX_ZOOM_JUMP:
                    report.add("camera_jump", WARNING, number,
                               f"zoom jumps {previous.zoom:.2f} -> {state.zoom:.2f} between cuts",
                               delta=round(jump, 3))
            if previous.lighting and state.lighting and previous.lighting != state.lighting:
                declared_light = bool(scene.get("lighting"))
                report.add("lighting_change", INFO if declared_light else WARNING, number,
                           f"lighting {previous.lighting} -> {state.lighting}",
                           declared=declared_light)

        report.states.append(state)
        previous = state

    # An object that is held in one scene and then never mentioned again has been dropped by the
    # story without being put down. Only reported when it was *last* left in a hand.
    last_scene = report.states[-1].scene if report.states else 0
    for name, holder in report.states[-1].owners.items() if report.states else []:
        if holder is not None:
            report.add("object_left_in_hand", INFO, last_scene,
                       f"{name!r} is still held by {holder!r} at the end of the episode",
                       object=name)
    return report


def validate_episode(scenes: Sequence[Mapping[str, Any]], *,
                     characters: Sequence[str] = ("chiku", "gappu"),
                     default_facing: Mapping[str, float] | None = None,
                     ground_y: Optional[float] = None) -> ContinuityReport:
    """Public entry point: same as :func:`build_states`, named for what the caller wants."""

    return build_states(scenes, characters=characters, default_facing=default_facing,
                        ground_y=ground_y)


def summarize(reports: Iterable[ContinuityReport]) -> Dict[str, Any]:
    """Combine several episode reports, for the production manifest."""

    reports = list(reports)
    return {"episodes": len(reports),
            "ok": all(report.ok for report in reports),
            "counts": {severity: sum(len(r.of(severity)) for r in reports)
                       for severity in (ERROR, WARNING, INFO)},
            "issues": [issue.as_dict() for report in reports for issue in report.issues]}
