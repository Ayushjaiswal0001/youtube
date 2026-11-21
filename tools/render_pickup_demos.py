"""T43b interaction demonstrations: real 1920x1080 video with measured contact.

Rewritten after the first version's own inspection found three defects: props were drawn *behind*
the cast, the cast occupied a small corner of the frame, and a ground pickup was geometrically
impossible because nothing bent the body.

This version:
* composites with a painter's algorithm keyed on world depth (an object further down the floor is
  nearer the camera, so it is drawn later) instead of a fixed order that puts every prop behind every
  character;
* frames the action with a camera that zooms and centres on the interaction rather than on the stage
  slot;
* bends the body with ``studio.characters.crouch`` before solving the arm, so the shoulder is where
  the arm needs it to be - and reports the bend it had to use;
* measures contact against the wrist that is actually drawn, every frame.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairo

from studio.animation.environment import ForegroundLayer, LandscapeEnvironment
from studio.animation.grounding import place_on_ground
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.crouch import BodyPose, apply_pose, plan_crouch, save_pose, solve_crouch
from studio.characters.gappu import GappuRig
from studio.characters.ik import ArmSolver, apply_ik, chain_for, to_world
from studio.characters.pickup import (CONTACT_TOLERANCE, Grip, PickupMachine, PickupState,
                                      WorldObject, contact_error, hand_target, plan_pickup)
from studio.characters.props import draw_prop

WIDTH, HEIGHT = 1920, 1080
FPS = 30
OUT = Path("build/interaction-demos")
STAGE = stage_for(WIDTH, HEIGHT)

Draw = Tuple[float, Callable[[cairo.Context], None]]


class Camera:
    """A minimal pan/zoom camera so the interaction is the subject of the frame."""

    def __init__(self, focus: Tuple[float, float], zoom: float = 1.85):
        self.focus = focus
        self.zoom = zoom

    def apply(self, cr: cairo.Context) -> None:
        cr.translate(WIDTH / 2.0, HEIGHT * 0.56)
        cr.scale(self.zoom, self.zoom)
        cr.translate(-self.focus[0], -self.focus[1])


def _encode(path: Path):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostats",
           "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def _push(encoder, surface: cairo.ImageSurface) -> None:
    surface.flush()
    stride = surface.get_stride()
    row = WIDTH * 4
    raw = surface.get_data()
    payload = bytes(raw) if stride == row else b"".join(
        raw[r * stride: r * stride + row] for r in range(HEIGHT))
    encoder.stdin.write(payload)


class Scene:
    """A frame builder: world-space drawables sorted by depth, then the near layer on top."""

    def __init__(self, background: str, camera: Camera):
        self.background = background
        self.camera = camera
        self.environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)
        self.foreground = ForegroundLayer(WIDTH, HEIGHT, STAGE.ground_y)

    def draw(self, cr: cairo.Context, t: float, cast: Dict[str, object],
             items: List[Draw]) -> None:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgb(0.08, 0.10, 0.13)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.environment.render_by_name(self.background, cr, t)

        cr.save()
        self.camera.apply(cr)
        # Contact shadows first: they belong to the floor, not to the object standing on it.
        for rig in cast.values():
            self.environment.draw_character_shadow(
                cr, rig.x, STAGE.ground_y,
                getattr(getattr(rig, "prop", None), "values", {}).get("torso_rx", 68.0)
                * rig.scale * 0.85, height=0.0)
        # Painter's algorithm: larger world y is nearer the camera. A character's feet and an
        # object's centre are compared on the same axis, so a key on the floor in front of a
        # character draws over their feet and a key behind them draws under.
        order: List[Draw] = [(float(rig.y), (lambda c, r=rig: (c.save(), r.draw(c), c.restore())))
                             for rig in cast.values()]
        order.extend(items)
        for _, fn in sorted(order, key=lambda pair: pair[0]):
            fn(cr)
        cr.restore()

        self.foreground.render_by_name(self.background, cr, t)


def _prop_draw(name: str, point, angle: float = 0.0, depth: float | None = None,
               scale: float = 1.0) -> Draw:
    def fn(cr):
        draw_prop(cr, name, point, angle=angle, scale=scale)
    return (depth if depth is not None else point[1], fn)


def _circle_draw(centre, radius, fill, depth=None) -> Draw:
    def fn(cr):
        cr.save()
        cr.set_source_rgb(*fill)
        cr.arc(centre[0], centre[1], radius, 0, math.tau)
        cr.fill()
        cr.set_source_rgb(0.34, 0.24, 0.16)
        cr.set_line_width(3)
        cr.arc(centre[0], centre[1], radius, 0, math.tau)
        cr.stroke()
        cr.restore()
    return (depth if depth is not None else centre[1], fn)


def _table_draw(character_x: float, top: float, width: float = 230.0) -> Draw:
    """A table positioned *relative to the character*, so it cannot detach from them."""

    x = character_x

    def fn(cr):
        cr.save()
        cr.set_source_rgb(0.34, 0.22, 0.14)
        for leg in (x - width / 2 + 20, x + width / 2 - 36):
            cr.rectangle(leg, top + 18, 16, STAGE.ground_y - top - 18)
            cr.fill()
        cr.set_source_rgb(0.46, 0.31, 0.19)
        cr.rectangle(x - width / 2, top, width, 18)
        cr.fill()
        cr.set_source_rgb(0.56, 0.39, 0.24)
        cr.rectangle(x - width / 2, top, width, 6)
        cr.fill()
        cr.restore()

    return (float(STAGE.ground_y - 1.0), fn)


def render_demo(name: str, *, background: str, cast: List[dict], duration: float,
                setup) -> dict:
    out = OUT / f"{name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    rigs: Dict[str, object] = {}
    for spec in cast:
        cls = ChikuRig if spec["who"] == "chiku" else GappuRig
        rig = cls(**STAGE.anchor(spec["who"]))
        place_on_ground(rig, STAGE.ground_y)
        rig.facing = spec.get("facing", 1.0)
        if "x" in spec:
            rig.x = spec["x"]
        rigs[spec["who"]] = rig

    focus, build, summary = setup(rigs)
    scene = Scene(background, Camera(focus))
    total = int(round(duration * FPS))
    encoder = _encode(out)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    samples: List[dict] = []

    try:
        for index in range(total):
            t = index / FPS
            cr = cairo.Context(surface)
            items, record = build(t, rigs)
            scene.draw(cr, t, rigs, items)
            samples.append({"t": round(t, 3),
                            **{k: (round(v, 2) if isinstance(v, float) else v)
                               for k, v in record.items()}})
            _push(encoder, surface)
        encoder.stdin.close()
        err = encoder.stderr.read().decode("utf-8", "replace") if encoder.stderr else ""
        if encoder.wait() != 0:
            raise RuntimeError(f"{name}: ffmpeg failed: {err[-900:]}")
    finally:
        if encoder.poll() is None:
            encoder.kill()

    record = {"demo": name, "fps": FPS, "frames": total, "duration": round(total / FPS, 3),
              "path": str(out), "bytes": out.stat().st_size,
              **summary, "samples": samples[:: max(1, total // 48)]}
    (OUT / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _reach_cycle(rigs, who: str, obj: WorldObject, grip: Grip, *, side: str = "right",
                 hold: float = 0.8, reach: float = 0.5):
    """Shared scaffolding: plan the pickup, plan the bend around it, drive both per frame."""

    rig = rigs[who]
    plan = plan_pickup(rig, obj, character=who, grip=grip, hold_time=hold, reach_time=reach)
    machine = PickupMachine(plan)
    solver = ArmSolver(side=side)
    grasp = obj.grasp_point(grip, side)
    crouch = plan_crouch(rig, side, grasp,
                         reach_start=plan.phases[min(1, len(plan.phases) - 1)].start,
                         reach_end=plan.phases[min(1, len(plan.phases) - 1)].end,
                         hold_until=max(p.end for p in plan.phases
                                        if p.state is PickupState.HOLDING),
                         recover_at=plan.phases[-2].start if len(plan.phases) > 1 else 0.0,
                         recover_by=plan.duration)
    return plan, machine, solver, crouch


def demo_ground_pickup(*_) -> tuple:
    def setup(rigs):
        rig = rigs["chiku"]
        obj = WorldObject("brass_key", (rig.x + 46 * rig.facing, STAGE.ground_y - 12), 30, 14)
        plan, machine, solver, crouch = _reach_cycle(rigs, "chiku", obj, Grip.SMALL, hold=0.9)
        state = {"err": None}

        def build(t, rigs):
            rig = rigs["chiku"]
            apply_pose(rig, crouch.pose_at(t))
            target = hand_target(plan, chain_for(rig, "right"), t)
            wrist = to_world(rig, "right", apply_ik(rig, "right", target, solver=solver).wrist)
            err = contact_error(obj, wrist)
            held = machine.update(t, contact_error=err)
            state["err"] = err
            if held in (PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE):
                point = (wrist[0], wrist[1] - 6)
            else:
                point = obj.centre
            # Held props must composite in front of the character they are held against; a prop on
            # the floor keeps its own depth so a character standing in front of it covers it.
            items = [_prop_draw("brass_key", point, angle=0.0,
                                depth=point[1] + 400.0 if held else obj.centre[1])]
            return items, {"state": machine.state.value, "contact_error": err,
                           "bend_deg": math.degrees(crouch.pose_at(t).bend)}

        return (rig.x + 20, STAGE.ground_y - 90), build, {
            "plan": {"states": [p.state.value for p in plan.phases],
                     "duration": round(plan.duration, 3)},
            "crouch_ok": crouch.reachable,
            "bend_deg": round(math.degrees(crouch.total_bend), 1)}

    return setup


def demo_table_pickup(*_) -> tuple:
    def setup(rigs):
        rig = rigs["gappu"]
        # Furniture height follows the character: a 205 px table is above this mouse's shoulder.
        top = chain_for(rig, "right").shoulder[1] - 14.0
        obj = WorldObject("cup", (rig.x + 40 * rig.facing, top - 24), 20, 24,
                          rests_on="table")
        plan, machine, solver, crouch = _reach_cycle(rigs, "gappu", obj, Grip.SINGLE, hold=0.8)

        def build(t, rigs):
            rig = rigs["gappu"]
            apply_pose(rig, crouch.pose_at(t))
            target = hand_target(plan, chain_for(rig, "right"), t)
            wrist = to_world(rig, "right", apply_ik(rig, "right", target, solver=solver).wrist)
            err = contact_error(obj, wrist)
            now = machine.update(t, contact_error=err)
            held = now in (PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE)
            point = (wrist[0], wrist[1] - 4) if held else obj.centre
            items = [_table_draw(rig.x, top),
                     _circle_draw(point, obj.half_w, (0.86, 0.80, 0.62),
                                  depth=point[1] + 400.0 if held else obj.centre[1])]
            return items, {"state": now.value, "contact_error": err,
                           "bend_deg": math.degrees(crouch.pose_at(t).bend)}

        return (rig.x + 10, STAGE.ground_y - 120), build, {
            "plan": {"states": [p.state.value for p in plan.phases]},
            "crouch_ok": crouch.reachable,
            "table_top": top}

    return setup


def demo_handoff(*_) -> tuple:
    def setup(rigs):
        chiku, gappu = rigs["chiku"], rigs["gappu"]
        # Conversational distance, and facing each other: the hand-off has to be a shared frame.
        gappu.x = chiku.x + 235.0
        chiku.facing, gappu.facing = 1.0, -1.0
        chiku_chain = chain_for(chiku, "right")
        offer = (chiku_chain.shoulder[0] + 40, chiku_chain.shoulder[1] + 55)
        key = WorldObject("brass_key", offer, 30, 14)
        plan = plan_pickup(gappu, key, character="gappu", grip=Grip.HANDOFF, hold_time=0.7,
                           reach_time=0.8)
        machine = PickupMachine(plan)
        chiku_solver, gappu_solver = ArmSolver(side="right"), ArmSolver(side="right")
        owner = {"who": "chiku"}

        def build(t, rigs):
            chiku, gappu = rigs["chiku"], rigs["gappu"]
            apply_ik(chiku, "right", offer, solver=chiku_solver)
            target = hand_target(plan, chain_for(gappu, "right"), t)
            wrist = to_world(gappu, "right", apply_ik(gappu, "right", target,
                                                      solver=gappu_solver).wrist)
            err = contact_error(key, wrist)
            now = machine.update(t, contact_error=err)
            if now in (PickupState.GRIPPING, PickupState.HOLDING) and owner["who"] == "chiku":
                owner["who"] = "gappu"
            point = wrist if owner["who"] == "gappu" else offer
            items = [_prop_draw("brass_key", (point[0], point[1] - 2), angle=0.12,
                                depth=point[1] + 400.0)]
            return items, {"state": now.value, "contact_error": err, "owner": owner["who"]}

        return ((chiku.x + gappu.x) / 2.0, STAGE.ground_y - 210), build, {
            "plan": {"states": [p.state.value for p in plan.phases]},
            "separation": round(gappu.x - chiku.x, 1)}

    return setup


def demo_two_hand(*_) -> tuple:
    def setup(rigs):
        rig = rigs["chiku"]
        obj = WorldObject("pot", (rig.x + 18 * rig.facing, STAGE.ground_y - 34), 44, 32)
        plan = plan_pickup(rig, obj, character="chiku", grip=Grip.LARGE_SUPPORT, hold_time=1.0,
                           reach_time=0.65)
        machine = PickupMachine(plan)
        solvers = {s: ArmSolver(side=s) for s in ("left", "right")}
        pose, ok = solve_crouch(rig, "right", obj.grasp_point(Grip.LARGE_SUPPORT, "right"))
        entry = save_pose(rig)
        bend_start, bend_end = 0.02, 0.42
        stand_start, stand_end = max(p.end for p in plan.phases
                                    if p.state is PickupState.HOLDING), plan.duration

        def pose_at(t):
            if t <= bend_start:
                return entry
            if t < bend_end:
                return entry.blended(pose, (t - bend_start) / (bend_end - bend_start))
            if t <= stand_start:
                return pose
            if t < stand_end:
                return pose.blended(entry, (t - stand_start) / (stand_end - stand_start))
            return entry

        def build(t, rigs):
            rig = rigs["chiku"]
            apply_pose(rig, pose_at(t))
            wrists, errs = {}, {}
            for side in ("left", "right"):
                target = hand_target(plan, chain_for(rig, side), t)
                wrists[side] = to_world(rig, side, apply_ik(rig, side, target,
                                                            solver=solvers[side]).wrist)
                errs[side] = contact_error(obj, wrists[side])
            now = machine.update(t, contact_error=min(errs.values()))
            held = now in (PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE)
            centre = obj.centre if not held else (
                (wrists["left"][0] + wrists["right"][0]) / 2.0,
                (wrists["left"][1] + wrists["right"][1]) / 2.0 - obj.half_h * 0.8)

            def pot(cr):
                cr.save()
                cr.set_source_rgb(0.70, 0.40, 0.22)
                cr.rectangle(centre[0] - obj.half_w, centre[1] - obj.half_h,
                             obj.half_w * 2, obj.half_h * 2)
                cr.fill()
                cr.set_source_rgb(0.38, 0.20, 0.10)
                cr.set_line_width(4)
                cr.rectangle(centre[0] - obj.half_w, centre[1] - obj.half_h,
                             obj.half_w * 2, obj.half_h * 2)
                cr.stroke()
                cr.restore()

            # A held pot is in front of the body holding it, like every other held prop.
            return [(centre[1] + (400.0 if held else 0.0), pot)], {"state": now.value,
                                        "contact_error": min(errs.values()),
                                        "bend_deg": math.degrees(pose_at(t).bend)}

        return (rig.x + 10, STAGE.ground_y - 110), build, {
            "plan": {"states": [p.state.value for p in plan.phases]},
            "crouch_ok": ok, "bend_deg": round(math.degrees(pose.bend), 1)}

    return setup


def demo_failed_reach(*_) -> tuple:
    def setup(rigs):
        rig = rigs["chiku"]
        far = WorldObject("brass_key", (rig.x + 340, STAGE.ground_y - 12), 30, 14)
        plan = plan_pickup(rig, far, character="chiku", grip=Grip.SMALL, approach_speed=170.0,
                           hold_time=0.7)
        machine = PickupMachine(plan)
        solver = ArmSolver(side="right")
        state = {"phase": "attempt", "retry": None, "failed_at": None, "t0": None}

        def build(t, rigs):
            rig = rigs["chiku"]
            if state["phase"] == "attempt":
                target = hand_target(plan, chain_for(rig, "right"), t)
                # No bend: this attempt is meant to be a straight-armed stretch that cannot span
                # the distance, which is what makes the failure honest rather than staged.
                wrist = to_world(rig, "right",
                                 apply_ik(rig, "right", target, solver=solver).wrist)
                err = contact_error(far, wrist)
                now = machine.update(t, contact_error=err)
                if now is PickupState.FAILED:
                    state["phase"], state["failed_at"], state["t0"] = "recover", t, t
                    solver.reset()
                return [_prop_draw("brass_key", far.centre)], {
                    "state": now.value, "contact_error": err, "character_x": rig.x}

            if state["retry"] is None:
                near = WorldObject("brass_key", (rig.x + 120, far.centre[1]), 30, 14)
                rplan = plan_pickup(rig, near, character="chiku", grip=Grip.SMALL, hold_time=0.8)
                state["retry"] = {"obj": near, "plan": rplan, "machine": PickupMachine(rplan),
                                  "crouch": plan_crouch(rig, "right", near.grasp_point(Grip.SMALL),
                                                        reach_start=rplan.phases[0].end,
                                                        reach_end=rplan.phases[1].end,
                                                        hold_until=rplan.duration - 0.5,
                                                        recover_at=rplan.duration - 0.4,
                                                        recover_by=rplan.duration)}
            retry = state["retry"]
            local_t = t - state["t0"]
            apply_pose(rig, retry["crouch"].pose_at(local_t))
            target = hand_target(retry["plan"], chain_for(rig, "right"), local_t)
            wrist = to_world(rig, "right", apply_ik(rig, "right", target, solver=solver).wrist)
            err = contact_error(retry["obj"], wrist)
            now = retry["machine"].update(local_t, contact_error=err)
            held = now in (PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE)
            point = (wrist[0], wrist[1] - 4) if held else retry["obj"].centre
            return [_prop_draw("brass_key", point,
                               depth=point[1] + 400.0 if held else retry["obj"].centre[1])], {
                "state": f"recovered:{now.value}", "contact_error": err,
                "bend_deg": math.degrees(retry["crouch"].pose_at(local_t).bend)}

        return (rig.x + 90, STAGE.ground_y - 120), build, {
            "first_attempt": "expected to fail", "recovery": "bend + walk closer"}

    return setup


DEMOS = [
    ("01_ground_pickup", dict(background="jungle_clearing", duration=3.0,
                              cast=[{"who": "chiku"}], setup=demo_ground_pickup())),
    ("02_table_pickup", dict(background="haunted_haveli", duration=3.0,
                             cast=[{"who": "gappu"}], setup=demo_table_pickup())),
    ("03_handoff", dict(background="village_night", duration=3.0,
                        cast=[{"who": "chiku"}, {"who": "gappu"}], setup=demo_handoff())),
    ("04_two_hand_pot", dict(background="riverbank", duration=3.2,
                             cast=[{"who": "chiku"}], setup=demo_two_hand())),
    ("05_failed_reach_recovery", dict(background="forest_path", duration=4.2,
                                      cast=[{"who": "chiku"}], setup=demo_failed_reach())),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, spec in DEMOS:
        record = render_demo(name, **spec)
        records.append(record)
        print(f"[Demo] {name}: {record['frames']}f {record['duration']}s "
              f"{record['bytes']}B bend={record.get('bend_deg')} "
              f"crouch_ok={record.get('crouch_ok')}")
    (OUT / "index.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
