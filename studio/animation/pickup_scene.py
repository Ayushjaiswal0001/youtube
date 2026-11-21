"""Driving a world-space pickup inside a production scene (T43 integration).

``studio.characters.pickup`` and ``crouch`` worked, and nothing in the renderer could ask for them, so
they were demonstrated only by a bespoke tool. This is the bridge: a scene declares

    "pickup": {"object": "brass_key", "grip": "small_object", "holder": "chiku",
               "offset": 46, "surface": "ground"}

and the renderer gets a body that bends, an arm that solves toward the object, a prop that moves only
once the hand has actually arrived, and a per-scene record of whether contact was real.

Everything is measured on the wrist that is drawn. The requested hand target is never used as evidence
of contact, which was the mistake that made an earlier version report five successes from five demos.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from studio.animation.grounding import place_on_ground
from studio.characters.crouch import (BodyPose, apply_pose, plan_crouch, restore_pose, save_pose,
                                     solve_crouch)
from studio.characters.ik import ArmSolver, apply_ik, chain_for, shoulder_point, to_world
from studio.characters.pickup import (CONTACT_TOLERANCE, Grip, PickupMachine, PickupState,
                                      WorldObject, contact_error, hand_target, plan_pickup)
from studio.characters.props import PROPS

Point = Tuple[float, float]


@dataclass
class PickupReport:
    """What actually happened, per frame, for QC and for the scene report."""

    character: str
    object_name: str
    grip: str
    bend_deg: float
    reachable: bool
    min_contact_error: float = float("inf")
    states: List[str] = field(default_factory=list)
    claimed_contact_without_touch: int = 0
    max_wrist_step: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "character": self.character,
            "object": self.object_name,
            "grip": self.grip,
            "bend_deg": round(self.bend_deg, 1),
            "reachable": self.reachable,
            "min_contact_error": (None if math.isinf(self.min_contact_error)
                                  else round(self.min_contact_error, 2)),
            "states": self.states,
            "claimed_contact_without_touch": self.claimed_contact_without_touch,
            "max_wrist_step": round(self.max_wrist_step, 2),
        }


class PickupScene:
    """A pickup bound to a scene's timing, rigs and floor."""

    def __init__(self, spec: Dict[str, Any], rigs: Dict[str, Any], total_duration: float,
                 ground_y: float, *, table_height: Optional[float] = None) -> None:
        name = str(spec.get("object") or spec.get("prop") or "brass_key")
        if name not in PROPS:
            raise ValueError(f"unknown pickup object {name!r}")
        self.spec = spec
        self.spec_name = PROPS[name]
        self.rigs = rigs
        self.total_duration = max(0.6, float(total_duration))
        self.ground_y = float(ground_y)
        self.character = str(spec.get("holder") or spec.get("character") or "chiku")
        if self.character not in rigs:
            self.character = next(iter(rigs))
        self.rig = rigs[self.character]
        self.side = str(spec.get("side") or "right")
        self.grip = Grip(str(spec.get("grip") or Grip.SMALL.value))
        self.surface = str(spec.get("surface") or "ground")
        if self.surface not in ("ground", "table"):
            raise ValueError(f"unsupported pickup surface {self.surface!r}")

        # The object is placed relative to the character's own geometry and facing: an object behind
        # a character is a blocking problem, and hard-coding an absolute x reintroduces it silently.
        place_on_ground(self.rig, self.ground_y)
        chain = chain_for(self.rig, self.side)
        offset = float(spec.get("offset") or 46.0) * float(getattr(self.rig, "facing", 1.0))
        if self.surface == "table":
            # `table_height` is an absolute world-space surface y, in the same coordinates as
            # `stage.ground_y`. It must lie between the character's feet and their shoulder: below
            # the feet is underground, above the shoulder is a reach *up*, which this rig cannot do
            # and which is a different action from picking something up. Validating the physical
            # range is what catches an author writing a fraction like 0.62 by mistake.
            if table_height is not None:
                height = float(table_height)
                if not math.isfinite(height) or not (chain.shoulder[1] < height < self.ground_y):
                    raise ValueError(
                        "table_height must be an absolute world y between the shoulder "
                        f"({chain.shoulder[1]:.0f}) and the ground ({self.ground_y:.0f}), "
                        f"got {table_height!r}")
            else:
                height = chain.shoulder[1] - 14.0
            centre = (chain.shoulder[0] + offset, height - self.spec_name.half_h)
        else:
            centre = (chain.shoulder[0] + offset, self.ground_y - self.spec_name.half_h)
        self.obj = WorldObject(name, centre, self.spec_name.half_w, self.spec_name.half_h,
                               rests_on=self.surface)

        hold = float(spec.get("hold") or min(1.1, self.total_duration * 0.42))
        reach = float(spec.get("reach_time") or min(0.55, self.total_duration * 0.22))
        self.plan = plan_pickup(self.rig, self.obj, character=self.character, side=self.side,
                                grip=self.grip, hold_time=hold, reach_time=reach)
        self.machine = PickupMachine(self.plan)
        self.solver = ArmSolver(side=self.side)
        self.entry_pose: BodyPose = save_pose(self.rig)

        grasp = self.obj.grasp_point(self.grip, self.side)
        self.low_pose, comfortable = solve_crouch(self.rig, self.side, grasp)
        # Reachability is about touching the object, not about hitting its exact centre. Measuring
        # the shoulder-to-*surface* distance under the chosen pose is the honest test: a key is a
        # 48 px box, so a hand 14 px inside its edge has clearly reached it, while the previous
        # "distance to the grasp point" test called the same pickup unreachable and failed a QC gate
        # the render met.
        apply_pose(self.rig, self.low_pose)
        try:
            edge = self.obj.distance_to(shoulder_point(self.rig, self.side))
            self.reachable = edge <= chain_for(self.rig, self.side).reach
        finally:
            restore_pose(self.rig, self.entry_pose)
        self.comfortable = bool(comfortable)
        self.surface_gap = edge
        # The bend has to be complete before the hand arrives and must last until the object is up.
        self.bend_start = max(0.0, self.plan.phases[0].end - 0.35)
        self.bend_end = min(self.plan.duration * 0.5,
                            self.plan.phases[1].start + reach * 0.6)
        holding_end = max((phase.end for phase in self.plan.phases
                           if phase.state is PickupState.HOLDING), default=self.plan.duration - 0.4)
        self.stand_start = holding_end
        self.stand_end = min(self.plan.duration, holding_end + 0.4)
        self.report = PickupReport(character=self.character, object_name=name,
                                   grip=self.grip.value,
                                   bend_deg=math.degrees(self.low_pose.bend),
                                   reachable=self.reachable)
        self._last_wrist: Optional[Point] = None
        self._pose_applied = False
        # Where the object ends up once released. It must stay where the hand let go of it: the
        # first version returned to the object's original centre at COMPLETE, so a picked-up key
        # teleported back to the floor it was lifted from.
        self.placed: Optional[Point] = None
        self._done = False
        self._release_at = self.plan.duration

    # -- schedule -----------------------------------------------------------

    def pose_at(self, t: float) -> BodyPose:
        if t <= self.bend_start:
            return self.entry_pose
        if t < self.bend_end:
            u = (t - self.bend_start) / max(1e-6, self.bend_end - self.bend_start)
            return self.entry_pose.blended(self.low_pose, u)
        if t <= self.stand_start:
            return self.low_pose
        if t < self.stand_end:
            u = (t - self.stand_start) / max(1e-6, self.stand_end - self.stand_start)
            return self.low_pose.blended(self.entry_pose, u)
        return self.entry_pose

    def stage_t(self, t: float) -> float:
        """Local time: the pickup occupies the first part of the scene, then the character reacts."""

        return t

    # -- per frame ----------------------------------------------------------

    def update(self, t: float) -> Dict[str, Any]:
        """Pose the body, solve the arm, advance the machine, and return this frame's truth."""

        local = self.stage_t(t)
        if self._done:
            # The interaction finished earlier in the scene: the body is already back on its feet
            # and the object is where it was put down. Nothing to solve, and nothing to re-pose.
            return {"point": self.placed or self.obj.centre, "held": False,
                    "wrist": self._last_wrist or self.obj.centre,
                    "error": self.report.min_contact_error if not math.isinf(
                        self.report.min_contact_error) else 0.0,
                    "state": PickupState.COMPLETE.value, "bend": 0.0}

        apply_pose(self.rig, self.pose_at(local))
        self._pose_applied = True

        chain = chain_for(self.rig, self.side)
        target = hand_target(self.plan, chain, local)
        solution = apply_ik(self.rig, self.side, target, solver=self.solver)
        wrist = to_world(self.rig, self.side, solution.wrist)
        if self._last_wrist is not None:
            self.report.max_wrist_step = max(self.report.max_wrist_step,
                                             math.dist(self._last_wrist, wrist))
        self._last_wrist = wrist

        error = contact_error(self.obj, wrist)
        self.report.min_contact_error = min(self.report.min_contact_error, error)
        state = self.machine.update(local, contact_error=error)
        if not self.report.states or self.report.states[-1] != state.value:
            self.report.states.append(state.value)
        if state in (PickupState.CONTACT, PickupState.GRIPPING, PickupState.HOLDING) \
                and error > CONTACT_TOLERANCE:
            self.report.claimed_contact_without_touch += 1

        holding = state in (PickupState.HOLDING, PickupState.RELEASING)
        if holding:
            point = (wrist[0], wrist[1] - 4.0)
        elif state is PickupState.COMPLETE:
            # Released: the object stays where the hand left it.
            if self.placed is None:
                self.placed = (wrist[0], wrist[1] - 4.0)
            point = self.placed
            if not self._done:
                self._done = True
                self.release()
        else:
            point = self.obj.centre
        return {"point": point, "held": holding, "wrist": wrist, "error": error,
                "state": state.value, "bend": math.degrees(self.pose_at(local).bend)}

    def release(self) -> None:
        """Leave the rig exactly as it was found, so the next scene starts from a clean pose."""

        if self._pose_applied:
            restore_pose(self.rig, self.entry_pose)
            self._pose_applied = False
        from studio.characters.ik import clear_ik
        clear_ik(self.rig, self.side)

    def as_dict(self) -> Dict[str, Any]:
        return {"report": {**self.report.as_dict(),
                           "comfortable": getattr(self, "comfortable", True),
                           "shoulder_to_surface_px": round(getattr(self, "surface_gap", 0.0), 1)},
                "object": {"name": self.obj.name, "centre": [round(v, 1) for v in self.obj.centre],
                           "surface": self.surface},
                "schedule": [{"state": phase.state.value, "start": round(phase.start, 3),
                              "end": round(phase.end, 3)} for phase in self.plan.phases],
                "notes": list(self.plan.notes)}
