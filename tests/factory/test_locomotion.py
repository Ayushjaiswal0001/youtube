"""Locomotion tests (T33).

Motion is checked as motion: cycles must repeat on a plausible period, feet must alternate,
a jump must leave the ground and come back, a walk-in must arrive, and no motion may produce
a NaN or an impossible angle.
"""

from __future__ import annotations

import math
import unittest

from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.gaze import FaceController
from studio.characters.locomotion import (
    MOTIONS,
    BodyState,
    MotionController,
    motions_for,
)
from studio.characters.schema import load_schema


def steps(duration: float, fps: int = 30):
    return [i / fps for i in range(int(duration * fps))]


class MotionTableTests(unittest.TestCase):
    def test_every_motion_is_finite_and_bounded(self) -> None:
        for mode in MOTIONS:
            controller = MotionController(mode, duration=4.0, seed=7)
            for t in steps(4.0):
                state = controller.state_at(t)
                self.assertEqual(state.mode, mode)
                for value in (state.hip_x, state.jump_y, state.lean, state.leg_l,
                              state.leg_r, state.head_tilt, state.squash):
                    self.assertTrue(math.isfinite(value), f"{mode} produced {value}")
                self.assertLess(abs(state.leg_l), 1.6, mode)
                self.assertLess(abs(state.leg_r), 1.6, mode)
                self.assertGreater(state.squash, 0.7)
                self.assertLess(state.squash, 1.2)

    def test_unknown_motion_falls_back_to_idle(self) -> None:
        self.assertEqual(MotionController("moonwalk").state_at(1.0), BodyState(mode="idle"))

    def test_idle_is_a_no_op(self) -> None:
        state = MotionController("idle", duration=3.0).state_at(1.5)
        self.assertEqual(state, BodyState(mode="idle"))
        self.assertIsNone(state.arm_l)


class GaitTests(unittest.TestCase):
    def test_walk_alternates_the_legs(self) -> None:
        controller = MotionController("walk", duration=4.0, seed=0)
        samples = [controller.state_at(t) for t in steps(2.0)]
        # the two legs are never in phase, and each crosses zero
        opposed = sum(1 for s in samples if s.leg_l * s.leg_r < 0)
        self.assertGreater(opposed, len(samples) * 0.55)
        self.assertGreater(max(s.leg_l for s in samples), 0.3)
        self.assertLess(min(s.leg_l for s in samples), -0.3)

    def test_walk_period_is_plausible(self) -> None:
        controller = MotionController("walk", duration=4.0, seed=0)
        # find upward crossings of the leg angle: two per stride cycle
        crossings = []
        previous = controller.state_at(0.0).leg_l
        for t in steps(6.0, fps=120):
            value = controller.state_at(t).leg_l
            if previous < 0.0 <= value:
                crossings.append(t)
            previous = value
        gaps = [b - a for a, b in zip(crossings, crossings[1:])]
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertAlmostEqual(gap, 1.05, delta=0.08)

    def test_bounce_keeps_feet_on_the_ground(self) -> None:
        controller = MotionController("walk", duration=4.0, seed=0)
        self.assertTrue(all(controller.state_at(t).jump_y <= 0.01 for t in steps(3.0)))

    def test_run_is_faster_and_bigger_than_walk(self) -> None:
        walk = MotionController("walk", duration=4.0, seed=0)
        run = MotionController("run", duration=4.0, seed=0)
        walk_amp = max(abs(walk.state_at(t).leg_l) for t in steps(2.0))
        run_amp = max(abs(run.state_at(t).leg_l) for t in steps(2.0))
        self.assertGreater(run_amp, walk_amp)
        self.assertGreater(run.state_at(0.5).lean, walk.state_at(0.5).lean)

    def test_walk_in_arrives_and_walk_out_leaves(self) -> None:
        enter = MotionController("walk_in", duration=3.0, seed=0, distance=300.0, facing=1.0)
        exit_ = MotionController("walk_out", duration=3.0, seed=0, distance=300.0, facing=1.0)
        self.assertLess(enter.state_at(0.0).hip_x, -280.0)
        self.assertAlmostEqual(enter.state_at(3.0).hip_x, 0.0, places=6)
        self.assertAlmostEqual(exit_.state_at(0.0).hip_x, 0.0, places=6)
        self.assertLess(exit_.state_at(3.0).hip_x, -280.0)

    def test_walk_in_mirrors_for_a_left_facing_character(self) -> None:
        enter = MotionController("walk_in", duration=3.0, seed=0, distance=300.0, facing=-1.0)
        self.assertGreater(enter.state_at(0.0).hip_x, 280.0)
        self.assertAlmostEqual(enter.state_at(3.0).hip_x, 0.0, places=6)
        leave = MotionController("walk_out", duration=3.0, seed=0, distance=300.0, facing=-1.0)
        self.assertGreater(leave.state_at(3.0).hip_x, 280.0)


class JumpTests(unittest.TestCase):
    def test_jump_leaves_the_ground_and_returns(self) -> None:
        controller = MotionController("jump", duration=1.2, seed=0)
        heights = [controller.state_at(t).jump_y for t in steps(1.2, fps=60)]
        self.assertGreater(min(heights), -130.0)
        self.assertLess(min(heights), -100.0)
        self.assertGreater(heights[-1], -6.0)
        self.assertGreaterEqual(heights[0], 0.0)
        self.assertGreater(controller.state_at(0.12).jump_y, 2.0,
                           "a jump should start with a crouch, not a hop")

    def test_jump_anticipates_then_stretches(self) -> None:
        controller = MotionController("jump", duration=1.2, seed=0)
        crouch = controller.state_at(0.18).squash
        air = controller.state_at(0.6).squash
        self.assertLess(crouch, 0.95)
        self.assertGreater(air, 1.0)

    def test_landing_settles(self) -> None:
        controller = MotionController("land", duration=0.9, seed=0)
        early = controller.state_at(0.2)
        late = controller.state_at(0.85)
        self.assertLess(early.squash, 0.97)
        self.assertGreater(late.squash, early.squash)
        self.assertLess(abs(late.jump_y), abs(early.jump_y) + 0.1)


class GestureTests(unittest.TestCase):
    def test_wave_raises_one_arm(self) -> None:
        controller = MotionController("wave", duration=2.0, seed=0)
        state = controller.state_at(1.0)
        self.assertLess(state.arm_r, -1.0)
        self.assertIsNotNone(state.arm_l)
        self.assertGreater(state.arm_l, 0.0)

    def test_point_holds_a_direction(self) -> None:
        controller = MotionController("point", duration=2.0, seed=0)
        values = [controller.state_at(t).arm_r for t in steps(1.5) if t >= 0.4]
        self.assertTrue(all(v is not None and v < -1.0 for v in values))

    def test_sit_and_stand_up_are_mirror_images(self) -> None:
        sit = MotionController("sit", duration=2.0, seed=0)
        stand = MotionController("stand_up", duration=2.0, seed=0)
        self.assertGreater(sit.state_at(2.0).jump_y, 20.0)
        self.assertGreater(sit.state_at(2.0).leg_l, 1.0)
        self.assertLess(stand.state_at(2.0).jump_y, 6.0)
        self.assertLess(stand.state_at(2.0).leg_l, 0.2)

    def test_nod_and_shake_reverse_direction(self) -> None:
        nod = MotionController("nod", duration=2.0, seed=0)
        shake = MotionController("shake_head", duration=2.0, seed=0)
        nod_values = [nod.state_at(t).head_tilt for t in steps(2.0)]
        shake_values = [shake.state_at(t).head_tilt for t in steps(2.0)]
        self.assertLess(min(nod_values), 0.0)
        self.assertLess(min(shake_values), 0.0)
        self.assertGreater(max(shake_values), 0.0)


class CompositionTests(unittest.TestCase):
    def test_pose_and_motion_compose(self) -> None:
        rig = ChikuRig()
        motion = MotionController("walk", duration=4.0, seed=1)
        rig.update_pose("boast_proud", 1.0, body=motion.state_at(1.0))
        walk_only = ChikuRig()
        walk_only.update_pose("idle", 1.0, body=motion.state_at(1.0))
        self.assertNotAlmostEqual(rig.head.local_rot, walk_only.head.local_rot)
        self.assertAlmostEqual(rig.jump_y, walk_only.jump_y)

    def test_muscle_pose_keeps_its_arms_when_motion_is_idle(self) -> None:
        rig = ChikuRig()
        rig.update_pose("boast_proud", 0.5)
        pose_arm = rig.arm_l_angle
        rig.update_pose("boast_proud", 0.5, body=MotionController("idle").state_at(0.5))
        self.assertEqual(rig.arm_l_angle, pose_arm)

    def test_walk_overrides_arm_swing(self) -> None:
        rig = ChikuRig()
        rig.update_pose("boast_proud", 0.5, body=MotionController("walk", duration=2, seed=0).state_at(0.5))
        self.assertNotEqual(rig.arm_l_angle, -0.8)

    def test_lipsync_and_eyes_survive_locomotion(self) -> None:
        schema = load_schema("chiku")
        rig = ChikuRig()
        rig.attach_face(FaceController(schema, seed=2, span=10))
        motion = MotionController("run", duration=3.0, seed=2)
        rig.face_state_at(1.0)
        rig.update_pose("idle", 1.0, is_talking=True, phoneme_intensity=0.9,
                        body=motion.state_at(1.0))
        self.assertIsNotNone(rig.eye_state)
        self.assertGreater(rig.mouth_open, 0.0)
        self.assertNotAlmostEqual(rig.leg_l_angle, 0.0)

    def test_golden_path_is_untouched_without_a_body(self) -> None:
        for rig in (ChikuRig(), GappuRig()):
            rig.update_pose("idle", 0.7)
            self.assertEqual(rig.hip_x, 0.0)
            self.assertEqual(rig.squash, 1.0)

    def test_motion_list_is_read_from_the_scene(self) -> None:
        self.assertEqual(motions_for({"chiku_motion": "walk"}, "chiku"), ["walk"])
        self.assertEqual(motions_for({"chiku_motion": ["jump", "wave"]}, "chiku"),
                         ["jump", "wave"])
        self.assertEqual(motions_for({}, "gappu"), ["idle"])

    def test_merge_stacks_translations(self) -> None:
        a = BodyState(hip_x=10.0, jump_y=-5.0, lean=0.1)
        b = BodyState(hip_x=-3.0, jump_y=-7.0, lean=0.2, arm_l=-1.0)
        merged = a.merged_with(b)
        self.assertAlmostEqual(merged.hip_x, 7.0)
        self.assertAlmostEqual(merged.jump_y, -12.0)
        self.assertAlmostEqual(merged.lean, 0.3)
        self.assertEqual(merged.arm_l, -1.0)

    def test_determinism(self) -> None:
        first = MotionController("walk", duration=3.0, seed=42)
        second = MotionController("walk", duration=3.0, seed=42)
        self.assertEqual([first.state_at(t) for t in steps(3.0)],
                         [second.state_at(t) for t in steps(3.0)])

    def test_seed_offsets_the_phase(self) -> None:
        a = MotionController("walk", duration=3.0, seed=1)
        b = MotionController("walk", duration=3.0, seed=2)
        self.assertNotEqual(a.phase_offset, b.phase_offset)
        self.assertNotAlmostEqual(a.state_at(0.7).leg_l, b.state_at(0.7).leg_l)


if __name__ == "__main__":
    unittest.main()
