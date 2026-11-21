"""Render the T43 object-interaction demonstrations to real 1920x1080 video.

Five clips, all driven by the production rigs, the landscape stage, the landscape environment and the
new IK/pickup modules - no mock characters, no composite of stills:

1. Chiku picks a key up off the ground.
2. Gappu picks a cup up off a table.
3. Chiku hands the key to Gappu.
4. Two hands lift a heavy pot.
5. A reach that fails, then recovers by stepping closer.

Every clip also writes a JSON record of the state timeline and the measured hand-to-object distance
per frame, so "the hand touched the object" is a number here rather than an impression.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairo

from studio.animation.environment import ForegroundLayer, LandscapeEnvironment
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.ik import (ArmSolver, apply_ik, chain_for, clear_ik,
                                  reload_neutral, to_world)
from studio.characters.pickup import (Grip, PickupMachine, PickupState, WorldObject,
                                      contact_error, hand_target, plan_pickup)
from studio.characters.props import draw_prop
from studio.characters.schema import load_schema

WIDTH, HEIGHT = 1920, 1080
FPS = 30
OUT = Path("build/interaction-demos")

STAGE = stage_for(WIDTH, HEIGHT)


def _surface() -> cairo.ImageSurface:
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)


def _encoder(path: Path, frames: int):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostats",
           "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS),
           "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def _write_frame(encoder, surface: cairo.ImageSurface) -> None:
    surface.flush()
    stride = surface.get_stride()
    row_bytes = WIDTH * 4
    raw = surface.get_data()
    if stride == row_bytes:
        payload = bytes(raw)
    else:
        payload = b"".join(raw[r * stride: r * stride + row_bytes] for r in range(HEIGHT))
    encoder.stdin.write(payload)


def _draw_table(cr, x: float, top: float, width: float = 260.0) -> None:
    """A small table the cup stands on, so the object has a surface rather than a coordinate."""

    cr.save()
    cr.set_source_rgb(0.36, 0.24, 0.15)
    cr.rectangle(x - width / 2, top, width, 22)
    cr.fill()
    cr.set_source_rgb(0.28, 0.18, 0.11)
    for leg in (x - width / 2 + 18, x + width / 2 - 34):
        cr.rectangle(leg, top + 22, 16, STAGE.ground_y - top - 22)
        cr.fill()
    cr.set_source_rgb(0.44, 0.31, 0.19)
    cr.rectangle(x - width / 2, top, width, 6)
    cr.fill()
    cr.restore()


def render_demo(name: str, *, background: str, cast: List[dict], duration: float,
                setup) -> dict:
    """Render one demo. ``setup`` returns a per-frame callback plus a summary dict."""

    out = OUT / f"{name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)
    foreground = ForegroundLayer(WIDTH, HEIGHT, STAGE.ground_y)

    rigs: Dict[str, object] = {}
    for spec in cast:
        cls = ChikuRig if spec["who"] == "chiku" else GappuRig
        rig = cls(**STAGE.anchor(spec["who"]))
        rig.facing = spec.get("facing", 1.0)
        rigs[spec["who"]] = rig

    frame_cb, summary = setup(rigs)
    total = int(round(duration * FPS))
    encoder = _encoder(out, total)
    surface = _surface()
    samples: List[dict] = []

    try:
        for index in range(total):
            t = index / FPS
            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgb(0.10, 0.12, 0.16)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            environment.render_by_name(background, cr, t)

            record = frame_cb(t, rigs, cr) or {}
            samples.append({"t": round(t, 3), **{k: (round(v, 2) if isinstance(v, float) else v)
                                                 for k, v in record.items()}})

            for who, rig in rigs.items():
                environment.draw_character_shadow(
                    cr, rig.x, STAGE.ground_y, getattr(rig, "torso_rx", 68.0) * rig.scale * 0.8,
                    height=0.0)
            # Cast (or the contact shadow's owner) first, then draw the near-camera layer on top.
            for who, rig in rigs.items():
                cr.save()
                rig.draw(cr)
                cr.restore()
            for item in summary.get("props_drawn", []):
                pass
            foreground.render_by_name(background, cr, t)
            _write_frame(encoder, surface)
        encoder.stdin.close()
        err = encoder.stderr.read().decode("utf-8", "replace") if encoder.stderr else ""
        if encoder.wait() != 0:
            raise RuntimeError(f"{name}: ffmpeg failed: {err[-800:]}")
    finally:
        if encoder.poll() is None:
            encoder.kill()

    record = {
        "demo": name,
        "fps": FPS,
        "frames": total,
        "duration": round(total / FPS, 3),
        "path": str(out),
        "bytes": out.stat().st_size,
        **{k: v for k, v in summary.items() if k != "props_drawn"},
        "frames_sampled": samples[:: max(1, total // 40)],
    }
    (OUT / f"{name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def demo_ground_pickup(*_) -> dict:
    def setup(rigs):
        rig = rigs["chiku"]
        chain = chain_for(rig, "right")
        obj = WorldObject("brass_key", (chain.shoulder[0] + 52, STAGE.ground_y - 14), 30, 16)
        plan = plan_pickup(rig, obj, character="chiku", grip=Grip.SMALL, hold_time=0.9)
        machine = PickupMachine(plan)
        solver = ArmSolver(side="right")
        state = {"held": False, "errors": [], "wrist": []}

        def frame(t, rigs, cr):
            rig = rigs["chiku"]
            target = hand_target(plan, chain_for(rig, "right"), t)
            sol = apply_ik(rig, "right", target, solver=solver)
            wrist = to_world(rig, "right", sol.wrist)
            target = wrist          # the hand that is drawn, not the hand that was asked for
            state["wrist"].append((t, wrist))
            err = contact_error(obj, wrist)
            state["errors"].append(err)
            state["held"] = machine.update(t, contact_error=err) in (
                PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE)
            lift = 0.0
            if state["held"]:
                u = min(1.0, max(0.0, (t - plan.phase_at(t).start) / 0.4))
                lift = 70.0 * u
            point = (target[0], target[1] - 6 - lift)
            draw_prop(cr, "brass_key", point, angle=-0.35 * (1.0 - lift / 70.0 if lift else 1.0))
            return {"state": machine.state.value, "contact_error": err,
                    "hand": point}

        return frame, {}

    return setup


def demo_table_pickup(*_) -> dict:
    def setup(rigs):
        rig = rigs["gappu"]
        chain = chain_for(rig, "right")
        top = STAGE.ground_y - 210.0
        cup = WorldObject("cup", (chain.shoulder[0] + 46, top - 26), 22, 26, rests_on="table")
        plan = plan_pickup(rig, cup, character="gappu", grip=Grip.SINGLE, hold_time=0.8,
                           reach_time=0.5)
        machine = PickupMachine(plan)
        solver = ArmSolver(side="right")

        def frame(t, rigs, cr):
            rig = rigs["gappu"]
            _draw_table(cr, cup.centre[0], top)
            target = hand_target(plan, chain_for(rig, "right"), t)
            target = to_world(rig, "right", apply_ik(rig, "right", target,
                                                     solver=solver).wrist)
            err = contact_error(cup, target)
            held = machine.update(t, contact_error=err) in (PickupState.HOLDING,
                                                            PickupState.RELEASING,
                                                            PickupState.COMPLETE)
            point = (target[0], target[1] - 4 - (26.0 if held else 0.0))
            cr.save()
            cr.set_source_rgb(0.86, 0.80, 0.62)
            cr.arc(point[0], point[1], cup.half_w, 0, math.tau)
            cr.fill()
            cr.set_source_rgb(0.42, 0.30, 0.20)
            cr.set_line_width(3)
            cr.arc(point[0], point[1], cup.half_w, 0, math.tau)
            cr.stroke()
            cr.restore()
            return {"state": machine.state.value, "contact_error": err, "hand": point,
                    "object_y": point[1]}

        return frame, {}

    return setup


def demo_handoff(*_) -> dict:
    def setup(rigs):
        chiku, gappu = rigs["chiku"], rigs["gappu"]
        # The landscape slots are 720 px apart, which is a 2.7 s walk: too far for a hand-off to
        # read. Bring Gappu to conversational distance first.
        gappu.x = chiku.x + 250.0
        # Gappu reaches for the key in Chiku's hand: the target is the other character's palm.
        chiku_chain = chain_for(chiku, "right")
        chiku_grasp = (chiku_chain.shoulder[0] + 46, chiku_chain.shoulder[1] + 58)
        key = WorldObject("brass_key", chiku_grasp, 30, 16)
        plan = plan_pickup(gappu, key, character="gappu", grip=Grip.HANDOFF, hold_time=0.7,
                           reach_time=0.75)
        machine = PickupMachine(plan)
        chiku_solver = ArmSolver(side="right")
        gappu_solver = ArmSolver(side="right")
        state = {"owner": "chiku"}

        def frame(t, rigs, cr):
            # Chiku offers the key at a fixed spot; Gappu's hand travels to it.
            apply_ik(chiku, "right", chiku_grasp, solver=chiku_solver)
            target = hand_target(plan, chain_for(gappu, "right"), t)
            target = to_world(gappu, "right", apply_ik(gappu, "right", target,
                                                       solver=gappu_solver).wrist)
            err = contact_error(key, target)
            state_now = machine.update(t, contact_error=err)
            if state_now in (PickupState.GRIPPING, PickupState.HOLDING) and state["owner"] == "chiku":
                state["owner"] = "gappu"
            point = target if state["owner"] == "gappu" else chiku_grasp
            draw_prop(cr, "brass_key", (point[0], point[1] - 4), angle=0.1)
            return {"state": state_now.value, "contact_error": err, "owner": state["owner"]}

        return frame, {}

    return setup


def demo_two_hand(*_) -> dict:
    def setup(rigs):
        chiku = rigs["chiku"]
        pot = WorldObject("pot", (chiku.x + 20, STAGE.ground_y - 40), 46, 38)
        plan = plan_pickup(chiku, pot, character="chiku", grip=Grip.LARGE_SUPPORT,
                           hold_time=1.0, reach_time=0.6)
        machine = PickupMachine(plan)
        solvers = {"left": ArmSolver(side="left"), "right": ArmSolver(side="right")}
        state = {"held": False}

        def frame(t, rigs, cr):
            chiku = rigs["chiku"]
            targets = {"right": hand_target(plan, chain_for(chiku, "right"), t),
                       "left": hand_target(plan, chain_for(chiku, "left"), t)}
            errors = {}
            for side in ("left", "right"):
                wrist = to_world(chiku, side, apply_ik(chiku, side, targets[side],
                                                       solver=solvers[side]).wrist)
                targets[side] = wrist
                errors[side] = contact_error(pot, wrist)
            state["held"] = machine.update(t, contact_error=min(errors.values())) in (
                PickupState.HOLDING, PickupState.RELEASING, PickupState.COMPLETE)
            lift = 0.0
            if state["held"]:
                lift = 90.0 * min(1.0, max(0.0, (t - plan.phase_at(t).start) / 0.45))
            centre = (pot.centre[0], pot.centre[1] - lift)
            cr.save()
            cr.set_source_rgb(0.72, 0.42, 0.24)
            cr.rectangle(centre[0] - pot.half_w, centre[1] - pot.half_h,
                         pot.half_w * 2, pot.half_h * 2)
            cr.fill()
            cr.set_source_rgb(0.40, 0.22, 0.12)
            cr.set_line_width(4)
            cr.rectangle(centre[0] - pot.half_w, centre[1] - pot.half_h,
                         pot.half_w * 2, pot.half_h * 2)
            cr.stroke()
            cr.restore()
            return {"state": machine.state.value,
                    "contact_error": min(errors.values()),
                    "left_error": errors["left"], "right_error": errors["right"],
                    "object_y": centre[1]}

        return frame, {}

    return setup


def demo_failed_reach(*_) -> dict:
    def setup(rigs):
        chiku = rigs["chiku"]
        chain = chain_for(chiku, "right")
        # Deliberately far: beyond the arm, so the plan must fail before it can succeed.
        far = WorldObject("brass_key", (chain.shoulder[0] + 330, STAGE.ground_y - 14), 30, 16)
        plan = plan_pickup(chiku, far, character="chiku", grip=Grip.SMALL,
                           approach_speed=190.0, hold_time=0.7)
        machine = PickupMachine(plan)
        solver = ArmSolver(side="right")
        near = WorldObject("brass_key", (0.0, far.centre[1]), far.half_w, far.half_h)
        state = {"x0": chiku.x, "moved": 0.0, "retry": None, "phase": "attempt"}

        def frame(t, rigs, cr):
            chiku = rigs["chiku"]
            if state["phase"] == "attempt":
                # Walk toward the object during APPROACHING; the reach then genuinely falls short.
                phase = plan.phase_at(t)
                if phase.state is PickupState.APPROACHING:
                    u = min(1.0, (t - phase.start) / max(1e-6, phase.duration))
                    chiku.x = state["x0"] + (50.0 * u)
                target = hand_target(plan, chain_for(chiku, "right"), t)
                wrist = to_world(chiku, "right", apply_ik(chiku, "right", target,
                                                          solver=solver).wrist)
                err = contact_error(far, wrist)
                target = wrist
                now = machine.update(t, contact_error=err)
                point = (target[0], target[1] - 4)
                draw_prop(cr, "brass_key", point, angle=0.0)
                if now is PickupState.FAILED:
                    state["phase"] = "recover"
                    state["failed_at"] = round(t, 3)
                return {"state": now.value, "contact_error": err, "x": chiku.x}
            # Recovery: step the rest of the way in and take it.
            retry = state["retry"]
            if retry is None:
                near = WorldObject("brass_key", (chiku.x + 78, far.centre[1]),
                                   far.half_w, far.half_h)
                retry = state["retry"] = {
                    "plan": plan_pickup(chiku, near, character="chiku", grip=Grip.SMALL,
                                        hold_time=0.8),
                    "machine": PickupMachine(plan_pickup(chiku, near, character="chiku",
                                                         grip=Grip.SMALL, hold_time=0.8)),
                    "obj": near,
                }
            # Step the last of the way in while the retry schedules the reach.
            chiku.x = min(chiku.x + 6.0, retry["obj"].centre[0] - 50.0)
            solver.reset()
            target = hand_target(retry["plan"], chain_for(chiku, "right"), t)
            target = to_world(chiku, "right", apply_ik(chiku, "right", target,
                                                       solver=solver).wrist)
            err = contact_error(retry["obj"], target)
            now = retry["machine"].update(t, contact_error=err)
            draw_prop(cr, "brass_key", (target[0], target[1] - 4), angle=0.0)
            return {"state": f"recovered:{now.value}", "contact_error": err, "x": chiku.x}

        return frame, {}

    return setup


DEMOS = [
    ("01_chiku_ground_pickup", dict(background="jungle_clearing", duration=2.6,
                                    cast=[{"who": "chiku"}], setup=demo_ground_pickup())),
    ("02_gappu_table_pickup", dict(background="haunted_haveli", duration=2.8,
                                   cast=[{"who": "gappu"}], setup=demo_table_pickup())),
    ("03_chiku_to_gappu_handoff", dict(background="village_night", duration=2.9,
                                       cast=[{"who": "chiku"},
                                             {"who": "gappu", "facing": -1.0}],
                                       setup=demo_handoff())),
    ("04_two_hand_pot", dict(background="riverbank", duration=2.8,
                             cast=[{"who": "chiku"}], setup=demo_two_hand())),
    ("05_failed_reach_recovery", dict(background="forest_path", duration=3.4,
                                      cast=[{"who": "chiku"}], setup=demo_failed_reach())),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, spec in DEMOS:
        record = render_demo(name, **spec)
        records.append(record)
        print(f"[Demo] {name}: {record['frames']} frames, {record['duration']} s, "
              f"{record['bytes']} B")
    (OUT / "index.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
