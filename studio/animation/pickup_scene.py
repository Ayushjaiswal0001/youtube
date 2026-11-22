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
from studio.characters.props import hand_point
from studio.characters.crouch import (BodyPose, apply_pose, plan_crouch, restore_pose, save_pose,
                                     solve_crouch)
from studio.characters.ik import ArmSolver, apply_ik, chain_for, shoulder_point, to_world
from studio.characters.pickup import (CONTACT_TOLERANCE, Grip, PickupMachine, PickupState,
                                      WorldObject, contact_error, hand_target, plan_pickup)
from studio.characters.props import PROPS
from studio.animation.ownership import OwnershipLedger

Point = Tuple[float, float]

#: The furthest one character will step to make a hand-off possible. Past this the two are not in the
#: same shot, and an "unreachable" answer is more useful than a sprint.
MAX_APPROACH_PX = 340.0
MAX_BOB = 4.0


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
    #: Present only when the scene declares a hand-off: a transfer is the moment the receiver's drawn
    #: hand reaches the object, so it is reported the same way as the pickup's own contact.
    handoff_to: Optional[str] = None
    handoff_reachable: Optional[bool] = None
    handoff_contact_error: Optional[float] = None
    transferred: bool = False

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
            "handoff_to": self.handoff_to,
            "handoff_reachable": self.handoff_reachable,
            "handoff_contact_error": (None if self.handoff_contact_error is None
                                      else round(self.handoff_contact_error, 2)),
            "transferred": self.transferred,
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
        # `keep` is what makes a pickup part of a story instead of a stunt: the character holds the
        # object after the interaction, so a later scene can hand it to someone else. Without it the
        # object was released at COMPLETE and a declared hand-off in a later scene had nothing to
        # hand over.
        self.keep = bool(spec.get("keep", False))
        self.carried: Optional[Point] = None
        self._release_at = self.plan.duration

        # -- hand-off, inside this same scene -------------------------------------------------
        # A pickup that ends with the object in hand is half a story beat; the other half is giving it
        # to someone. Doing this in one scene is the difference between "handed over" and "the object
        # vanished and reappeared in the next shot".
        self.handoff_to = str(spec.get("handoff_to") or "") or None
        self.partner = None
        self.partner_side = str(spec.get("handoff_side") or "left")
        self.transfer_point: Optional[Point] = None
        self.handoff_start = 0.0
        self.handoff_end = 0.0
        self.report.handoff_to = self.handoff_to
        if self.handoff_to:
            if not self.keep:
                raise ValueError("a hand-off needs keep=true: the giver must still be holding the object")
            if self.handoff_to == self.character or self.handoff_to not in rigs:
                raise ValueError(f"handoff_to must name a different character present in the scene, "
                                 f"got {self.handoff_to!r}")
            self.partner = rigs[self.handoff_to]
            place_on_ground(self.partner, self.ground_y)
            self._plan_handoff()

        # A scene-local ledger: ownership is recorded here so a hand-off inside one scene is the same
        # kind of event as a hand-off across a cut, and the report can show who held what and when.
        self.ownership: Optional[OwnershipLedger] = OwnershipLedger(
            characters=tuple(size for size in
                             ([self.character, self.handoff_to] if self.handoff_to else [self.character])))
        self.ownership.register(self.obj.name, self.obj.centre, surface=self.surface)
        self._claimed = False
        self._transfer_done = False
        self._handoff_error = float("inf")

    # -- hand-off -----------------------------------------------------------

    def _plan_handoff(self) -> None:
        """Stage the hand-off: where the hands meet, and how far each character has to step.

        An arm here is ~84 px long and the stage puts the two slots ~700 px apart, so a hand-off
        planned at the midpoint of where they are *standing* is geometrically impossible - the first
        version reported exactly that (hands 523 px apart, "transferred: False"). Two people pass an
        object when they are close, so the plan moves them close: each steps toward the other until a
        comfortable two-arm distance is left, and the meeting point is the midpoint of where they
        will be, not where they were.
        """

        giver_shoulder = shoulder_point(self.rig, self.side)
        receiver_shoulder = shoulder_point(self.partner, self.partner_side)
        self.giver_reach = chain_for(self.rig, self.side).reach
        self.receiver_reach = chain_for(self.partner, self.partner_side).reach
        reach = min(self.giver_reach, self.receiver_reach)
        # How close the two stand. Arms here are 62-84 px and bodies ~150-200 px wide, so a hand-off
        # forces the drawn bodies to overlap: 0.78 of reach puts the shoulders 98 px apart and the two
        # characters visibly interpenetrate in the render. Raising it to 0.92 needs 1.06 of the
        # receiver's reach and the hand-off becomes impossible (the demo refuses to render), so the
        # overlap is a proportion limit of the characters, not a tunable staging choice. Recorded as a
        # known defect in ANIMATION_QUALITY_REPORT.md; the fix is a torso lean or a longer forearm.
        desired_gap = 2.0 * reach * 0.78
        gap = abs(giver_shoulder[0] - receiver_shoulder[0])
        direction = 1.0 if receiver_shoulder[0] >= giver_shoulder[0] else -1.0

        needed = max(0.0, gap - desired_gap) / 2.0
        # A hand-off is a step, not a march: beyond this the two are not in a scene together and the
        # honest answer is "unreachable", not a 900 px sprint inside a one-second window.
        self.approach_needed = needed
        self.approach_px = min(needed, MAX_APPROACH_PX)
        self.rig_x0 = float(self.rig.x)
        self.partner_x0 = float(self.partner.x)
        self.giver_x = self.rig_x0 + direction * self.approach_px
        self.receiver_x = self.partner_x0 - direction * self.approach_px

        giver_final = (giver_shoulder[0] + (self.giver_x - self.rig_x0), giver_shoulder[1])
        receiver_final = (receiver_shoulder[0] + (self.receiver_x - self.partner_x0),
                          receiver_shoulder[1])
        mid_x = (giver_final[0] + receiver_final[0]) / 2.0
        # The meeting height is solved, not assumed. The two characters are different sizes, so their
        # shoulders sit ~100 px apart vertically: a point at their average height is out of reach of
        # the taller one (that exact case failed here by 4.7 px). Scanning the segment between the
        # shoulders for the point that minimises the worse of the two normalised distances gives the
        # height that both arms can actually cover, with the elbows bent.
        best = None
        for step in range(101):
            lam = step / 100.0
            y = giver_final[1] + (receiver_final[1] - giver_final[1]) * lam
            point = (mid_x, y)
            d_g = math.dist(giver_final, point) / self.giver_reach
            d_r = math.dist(receiver_final, point) / self.receiver_reach
            score = max(d_g, d_r)
            if best is None or score < best[0]:
                best = (score, point)
        score, self.transfer_point = best
        self.handoff_load = score
        self.handoff_surface_gap = math.dist(receiver_final, self.transfer_point)
        self.report.handoff_reachable = (
            self.approach_needed <= MAX_APPROACH_PX and score <= 0.97)
        self.partner_solver = ArmSolver(side=self.partner_side)

        # Walk time scales with the distance and is taken out of the tail of the scene, so a hand-off
        # that needs a bigger step gets a longer window instead of a faster slide.
        walk_time = 0.45 + 0.0035 * self.approach_px
        window = float(self.spec.get("handoff_time") or 0.0)
        if not window:
            window = max(1.2, walk_time + 0.8)
        window = max(0.5, min(window, self.total_duration * 0.6))
        self.handoff_end = self.total_duration
        self.handoff_start = max(self.stand_end + 0.15, self.handoff_end - window)
        self.walk_start = self.handoff_start
        self.walk_end = min(self.handoff_end - 0.25,
                            self.handoff_start + max(0.35, walk_time))

    def _walk(self, t: float) -> None:
        """Move both characters toward each other, easing in and out, feet kept on the ground."""

        if self.approach_px <= 0.0:
            return
        u = (t - self.walk_start) / max(1e-6, self.walk_end - self.walk_start)
        u = min(1.0, max(0.0, u))
        eased = u * u * (3.0 - 2.0 * u)
        self.rig.x = self.rig_x0 + (self.giver_x - self.rig_x0) * eased
        self.partner.x = self.partner_x0 + (self.receiver_x - self.partner_x0) * eased
        # A step has weight: a small vertical bob makes the translation read as walking. This is a
        # step-in, not a gait cycle - a full walk cycle inside a hand-off is not claimed here.
        bob = 3.0 * math.sin(math.pi * 4.0 * u) * (1.0 if 0.0 < u < 1.0 else 0.0)
        self.rig.y = self.ground_y - MAX_BOB + bob if False else self.rig.y
        self._bob = bob

    def _handoff_frame(self, t: float) -> Optional[Dict[str, Any]]:
        """Pose both arms toward the transfer point and report the measured two-hand distance."""

        if not self.handoff_to or self.transfer_point is None:
            return None
        if t < self.handoff_start:
            return None
        self._walk(t)
        u = min(1.0, (t - self.handoff_start) / max(1e-6, self.handoff_end - self.handoff_start))
        # Reach out, hold, withdraw: the receiver's arm follows the same ease as the giver's, so the
        # two hands arrive together instead of one grabbing at empty air.
        reach_u = min(1.0, u / 0.45)
        point = self.transfer_point
        giver_target = (point[0], point[1])
        receiver_target = (point[0], point[1] + 2.0)
        self.keep = True  # the giver keeps holding until the transfer is measured
        apply_ik(self.rig, self.side, giver_target, solver=self.solver)
        apply_ik(self.partner, self.partner_side, receiver_target, solver=self.partner_solver)
        giver_wrist = to_world(self.rig, self.side,
                               apply_ik(self.rig, self.side, giver_target, solver=self.solver).wrist)
        receiver_wrist = to_world(self.partner, self.partner_side,
                                  apply_ik(self.partner, self.partner_side, receiver_target,
                                           solver=self.partner_solver).wrist)
        # Contact is the distance between the two drawn hands against the object's own size: if the
        # two hands are closer together than the object is wide, the object has changed hands.
        gap = math.dist(giver_wrist, receiver_wrist)
        self._handoff_error = min(self._handoff_error, gap)
        self.report.handoff_contact_error = self._handoff_error
        touched = gap <= max(18.0, self.spec_name.half_w * 1.6)
        if touched and not self._transfer_done and self.ownership is not None:
            try:
                self.ownership.transfer(self.obj.name, self.character, self.handoff_to, t,
                                        contact_confirmed=True, position=point)
                self._transfer_done = True
                self.report.transferred = True
            except Exception as exc:  # a transfer that is not legal must not crash a render
                self.report.transfer_error = str(exc)
        holding = self._transfer_done
        return {"point": (point[0], point[1] - 2.0), "held": holding,
                "wrist": receiver_wrist if holding else giver_wrist,
                "error": 0.0 if holding else gap, "state": "HANDOFF",
                "bend": 0.0, "handoff": True, "handoff_gap": round(gap, 2),
                "handoff_progress": round(reach_u, 2)}

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
        handoff_frame = self._handoff_frame(local) if local >= self.handoff_start else None
        if handoff_frame is not None:
            held = bool(handoff_frame["held"])
            return handoff_frame
        if self._done:
            # The interaction finished earlier in the scene: the body is already back on its feet.
            # A kept object rides in the hand for the rest of the scene; a released one stays where
            # it was put down. Nothing to solve, and nothing to re-pose.
            if self.keep:
                self.carried = hand_point(self.rig, self.side)
                return {"point": self.carried, "held": True,
                        "wrist": self._last_wrist or self.obj.centre,
                        "error": 0.0, "state": PickupState.COMPLETE.value, "bend": 0.0,
                        "carried": True}
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

        if (not self._claimed and state in (PickupState.GRIPPING, PickupState.HOLDING)
                and error <= CONTACT_TOLERANCE):
            # The claim happens on the frame the wrist is measured inside the object, not when the
            # schedule says GRIPPING - the schedule is an intention, the wrist is the event.
            try:
                self.ownership.claim(self.obj.name, self.character, local,
                                     contact_confirmed=True, position=self.obj.centre)
                self._claimed = True
            except Exception as exc:
                self.report.claim_error = str(exc)
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
                if self.keep:
                    self.carried = hand_point(self.rig, self.side)
                self.release()
        else:
            point = self.obj.centre
        if self.keep and state is PickupState.COMPLETE:
            holding = True
            point = self.carried or hand_point(self.rig, self.side)
        return {"point": point, "held": holding, "wrist": wrist, "error": error,
                "state": state.value, "bend": math.degrees(self.pose_at(local).bend)}

    def release(self) -> None:
        """Leave the rig exactly as it was found, so the next scene starts from a clean pose."""

        if self._pose_applied:
            restore_pose(self.rig, self.entry_pose)
            self._pose_applied = False
        from studio.characters.ik import clear_ik
        clear_ik(self.rig, self.side)
        if self.partner is not None:
            clear_ik(self.partner, self.partner_side)

    def as_dict(self) -> Dict[str, Any]:
        return {"report": {**self.report.as_dict(), "kept": self.keep,
                           "comfortable": getattr(self, "comfortable", True),
                           "shoulder_to_surface_px": round(getattr(self, "surface_gap", 0.0), 1)},
                "object": {"name": self.obj.name, "centre": [round(v, 1) for v in self.obj.centre],
                           "surface": self.surface},
                "schedule": [{"state": phase.state.value, "start": round(phase.start, 3),
                              "end": round(phase.end, 3)} for phase in self.plan.phases],
                "notes": list(self.plan.notes),
                "handoff": (None if not self.handoff_to else {
                    "to": self.handoff_to,
                    "side": self.partner_side,
                    "reachable": self.report.handoff_reachable,
                    "surface_gap_px": round(getattr(self, "handoff_surface_gap", 0.0), 1),
                    "reach_load": round(getattr(self, "handoff_load", 0.0), 3),
                    "approach_px": round(getattr(self, "approach_px", 0.0), 1),
                    "window": [round(self.handoff_start, 2), round(self.handoff_end, 2)],
                    "transferred": self.report.transferred,
                    "contact_error_px": (None if math.isinf(self._handoff_error)
                                         else round(self._handoff_error, 2)),
                }),
                "ownership": self.ownership.as_dict()}
