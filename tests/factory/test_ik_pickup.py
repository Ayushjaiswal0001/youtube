"""Tests for two-segment IK, body mechanics and world-space pickup (T43/T43b)."""

from __future__ import annotations

import math
import unittest

from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.crouch import (BodyPose, HEAD_COUNTER, apply_pose, ground_target,
                                     plan_crouch, restore_pose, save_pose, shoulder_reach,
                                     solve_crouch, STANDING)
from studio.characters.gappu import GappuRig
from studio.characters.ik import (MAX_ELBOW_BEND, MIN_ELBOW_BEND, ArmSolver, chain_for,
                                  clear_ik, reload_neutral, shoulder_point, solve_two_bone,
                                  to_local, to_world)
from studio.characters.pickup import (ALLOWED_EDGES, CONTACT_TOLERANCE, Grip, InvalidTransition,
                                      PickupMachine, PickupState, WorldObject, contact_error,
                                      hand_target, plan_pickup)

STAGE = stage_for(1920, 1080)
RIGS = {"chiku": ChikuRig, "gappu": GappuRig}


def rig_for(name: str):
    return RIGS[name](**STAGE.anchor(name))


class TwoBoneSolverTests(unittest.TestCase):
    def test_full_extension_is_collinear(self) -> None:
        upper, fore = 44.0, 40.0
        sol = solve_two_bone((0.0, 0.0), (0.0, 84.0), upper, fore)
        self.assertFalse(sol.clamped)
        # At exactly full reach the elbow lies on the shoulder-wrist line: no visible bend.
        cross = (sol.elbow[0] * sol.wrist[1] - sol.elbow[1] * sol.wrist[0])
        self.assertAlmostEqual(cross, 0.0, places=6)

    def test_out_of_reach_is_clamped_and_reported(self) -> None:
        sol = solve_two_bone((0.0, 0.0), (0.0, 400.0), 44.0, 40.0)
        self.assertTrue(sol.clamped)
        self.assertFalse(sol.reached)
        self.assertAlmostEqual(math.dist((0.0, 0.0), sol.wrist), 84.0, places=6)

    def test_wrist_lands_on_reachable_target(self) -> None:
        for target in ((10.0, 60.0), (-35.0, 40.0), (0.0, 20.0), (55.0, 10.0)):
            sol = solve_two_bone((0.0, 0.0), target, 44.0, 40.0)
            self.assertAlmostEqual(math.dist(sol.wrist, target), 0.0, places=6)

    def test_elbow_angle_stays_inside_joint_limits(self) -> None:
        for target in ((0.001, 84.0), (0.0, 5.0), (2.0, 3.0), (80.0, 80.0)):
            sol = solve_two_bone((0.0, 0.0), target, 44.0, 40.0)
            self.assertGreaterEqual(sol.elbow_bend, MIN_ELBOW_BEND - 1e-9)
            self.assertLessEqual(sol.elbow_bend, MAX_ELBOW_BEND + 1e-9)

    def test_pole_side_is_stable_across_the_axis(self) -> None:
        """A target crossing the shoulder must not flip the elbow to the other side."""

        pole = (0.0, 1.0)

        def side_of_line(point, target):
            """Signed distance of ``point`` from the shoulder->target line."""
            length = math.hypot(*target) or 1.0
            return (target[0] * point[1] - target[1] * point[0]) / length

        for target in ((0.0, 60.0), (0.0, -60.0), (-60.0, 0.0), (40.0, 40.0), (-40.0, 45.0)):
            sol = solve_two_bone((0.0, 0.0), target, 44.0, 40.0, pole=pole)
            elbow_side = side_of_line(sol.elbow, target)
            pole_side = side_of_line(pole, target)
            self.assertEqual(math.copysign(1.0, elbow_side), math.copysign(1.0, pole_side),
                             f"elbow flipped to the wrong side of the axis for {target}")

    def test_degenerate_target_does_not_raise(self) -> None:
        sol = solve_two_bone((5.0, 5.0), (5.0, 5.0), 44.0, 40.0)
        self.assertTrue(sol.clamped)


class ArmChainTests(unittest.TestCase):
    def test_chain_measures_the_drawn_rig(self) -> None:
        for name in RIGS:
            rig = rig_for(name)
            chain = chain_for(rig, "right")
            self.assertGreater(chain.reach, 20.0)
            # The shoulder must be where the arm matrix puts it, not a copied constant.
            self.assertAlmostEqual(chain.shoulder[0], shoulder_point(rig, "right")[0], places=6)

    def test_local_world_round_trip(self) -> None:
        for name in RIGS:
            rig = rig_for(name)
            rig.facing = -1.0
            rig.torso.local_rot = 0.3
            point = (900.0, 500.0)
            back = to_world(rig, "right", to_local(rig, "right", point))
            self.assertAlmostEqual(back[0], point[0], places=4)
            self.assertAlmostEqual(back[1], point[1], places=4)

    def test_mirrored_arms_are_symmetric(self) -> None:
        rig = rig_for("chiku")
        left, right = chain_for(rig, "left"), chain_for(rig, "right")
        self.assertAlmostEqual(left.upper, right.upper, places=6)
        self.assertAlmostEqual(abs(left.shoulder[0] - rig.x),
                               abs(right.shoulder[0] - rig.x), places=6)
        self.assertAlmostEqual(left.shoulder[1], right.shoulder[1], places=6)

    def test_neutral_reload_places_the_hand_at_the_rig_neutral_point(self) -> None:
        """The IK rest pose must sit where an un-angled single capsule sits, so entering an
        interaction does not pop the hand somewhere else."""

        for name in RIGS:
            rig = rig_for(name)
            chain = chain_for(rig, "left")
            reload_neutral(rig, "left")
            solved = to_world(rig, "left", rig.arm_l_ik.wrist)
            expected = to_world(rig, "left", chain.neutral_hand)
            self.assertLess(math.dist(solved, expected), 2.5, name)

    def test_clear_ik_restores_the_legacy_path(self) -> None:
        rig = rig_for("chiku")
        reload_neutral(rig, "right")
        self.assertIsNotNone(rig.arm_r_ik)
        clear_ik(rig)
        self.assertIsNone(rig.arm_r_ik)
        self.assertIsNone(rig.arm_l_ik)


class ArmSolverContinuityTests(unittest.TestCase):
    def test_slew_limit_prevents_a_wrist_teleport(self) -> None:
        rig = rig_for("chiku")
        chain = chain_for(rig, "right")
        solver = ArmSolver(side="right")
        first = solver.solve(chain, chain.neutral_hand)
        far = (chain.neutral_hand[0] - 400.0, chain.neutral_hand[1] + 400.0)
        second = solver.solve(chain, far)
        self.assertLess(math.dist(first.wrist, second.wrist), chain.reach)

    def test_repeated_solve_is_stable(self) -> None:
        rig = rig_for("chiku")
        chain = chain_for(rig, "right")
        solver = ArmSolver(side="right")
        target = (chain.neutral_hand[0] - 20.0, chain.neutral_hand[1] * 0.6)
        positions = [solver.solve(chain, target).wrist for _ in range(5)]
        for a, b in zip(positions, positions[1:]):
            self.assertLess(math.dist(a, b), 1e-6)


class BodyMechanicsTests(unittest.TestCase):
    def test_standing_pose_leaves_the_rig_alone(self) -> None:
        rig = rig_for("chiku")
        before = (rig.torso.local_rot, rig.squash, rig.head.local_rot)
        apply_pose(rig, STANDING)
        self.assertAlmostEqual(rig.torso.local_rot, before[0], places=9)
        self.assertAlmostEqual(rig.squash, 1.0, places=9)
        self.assertAlmostEqual(rig.head.local_rot, 0.0, places=9)

    def test_head_counter_rotation_keeps_the_face_up(self) -> None:
        rig = rig_for("chiku")
        apply_pose(rig, BodyPose(bend=math.radians(60.0)))
        self.assertAlmostEqual(rig.head.local_rot, -math.radians(60.0) * HEAD_COUNTER, places=6)

    def test_restore_pose_undoes_the_counter_rotation(self) -> None:
        rig = rig_for("chiku")
        saved = save_pose(rig)
        apply_pose(rig, BodyPose(bend=0.8, squash=0.8))
        restore_pose(rig, saved)
        self.assertAlmostEqual(rig.head.local_rot, 0.0, places=9)
        self.assertAlmostEqual(rig.squash, 1.0, places=9)

    def test_shoulder_reach_does_not_mutate_the_rig(self) -> None:
        rig = rig_for("chiku")
        before = save_pose(rig)
        shoulder_reach(rig, "right", BodyPose(bend=0.7, squash=0.8), (700.0, 700.0))
        after = save_pose(rig)
        self.assertAlmostEqual(before.bend, after.bend, places=9)
        self.assertAlmostEqual(before.squash, after.squash, places=9)

    def test_ground_pickup_is_reachable_for_both_rigs(self) -> None:
        for name in RIGS:
            rig = rig_for(name)
            target = ground_target(STAGE.ground_y, rig.x + 46)
            pose, ok = solve_crouch(rig, "right", target)
            self.assertTrue(ok, f"{name} cannot reach the ground")
            distance, reach, _ = shoulder_reach(rig, "right", pose, target)
            self.assertLessEqual(distance, reach * 0.95)

    def test_table_height_target_is_reachable_standing(self) -> None:
        for name in RIGS:
            rig = rig_for(name)
            shoulder = shoulder_point(rig, "right")
            chest = shoulder[1] - 14.0
            # On the facing side: Gappu faces left, so an object at x+40 is behind him.
            pose, ok = solve_crouch(rig, "right",
                                    (shoulder[0] + 40.0 * rig.facing, chest - 24))
            self.assertTrue(ok, f"{name} cannot reach a chest-height surface")

    def test_prefers_a_shallow_fold_over_a_deep_one(self) -> None:
        """A squat lowers the shoulder without rotating the whole body, so it is spent first."""

        rig = rig_for("chiku")
        pose, ok = solve_crouch(rig, "right", ground_target(STAGE.ground_y, rig.x + 46))
        self.assertTrue(ok)
        self.assertLessEqual(math.degrees(pose.bend), 70.0)

    def test_impossible_target_is_reported_not_faked(self) -> None:
        rig = rig_for("gappu")
        pose, ok = solve_crouch(rig, "right", (rig.x + 900.0, STAGE.ground_y - 900.0))
        self.assertFalse(ok)

    def test_crouch_track_returns_to_standing(self) -> None:
        rig = rig_for("chiku")
        track = plan_crouch(rig, "right", ground_target(STAGE.ground_y, rig.x + 46),
                            reach_start=0.4, reach_end=0.9, hold_until=1.4,
                            recover_at=1.5, recover_by=2.0)
        self.assertTrue(track.reachable)
        self.assertLess(track.pose_at(0.5).bend, track.total_bend)
        self.assertAlmostEqual(track.pose_at(track.bend_end + 0.01).bend, track.total_bend,
                               places=6)
        self.assertAlmostEqual(track.pose_at(2.5).bend, track.pose_at(0.0).bend, places=6)


class WorldObjectTests(unittest.TestCase):
    def test_edge_distance_is_negative_inside(self) -> None:
        obj = WorldObject("box", (100.0, 100.0), 10.0, 10.0)
        self.assertAlmostEqual(contact_error(obj, (100.0, 100.0)), -10.0, places=6)
        self.assertAlmostEqual(contact_error(obj, (110.0, 100.0)), 0.0, places=6)
        self.assertAlmostEqual(contact_error(obj, (130.0, 100.0)), 20.0, places=6)

    def test_two_handed_grips_use_two_hands(self) -> None:
        self.assertEqual(Grip.TWO_HAND.hands, 2)
        self.assertEqual(Grip.LARGE_SUPPORT.hands, 2)
        self.assertEqual(Grip.SINGLE.hands, 1)
        self.assertEqual(Grip.HANDOFF.hands, 1)

    def test_grasp_points_differ_per_grip(self) -> None:
        obj = WorldObject("pot", (100.0, 100.0), 40.0, 30.0)
        single = obj.grasp_point(Grip.SINGLE, "right")
        large = obj.grasp_point(Grip.LARGE_SUPPORT, "right")
        self.assertNotAlmostEqual(single[1], large[1])
        left = obj.grasp_point(Grip.TWO_HAND, "left")
        right = obj.grasp_point(Grip.TWO_HAND, "right")
        self.assertLess(left[0], obj.centre[0])
        self.assertGreater(right[0], obj.centre[0])


class PickupMachineTests(unittest.TestCase):
    def _plan(self, name: str = "chiku", *, reach: float = 46.0):
        rig = rig_for(name)
        obj = WorldObject("key", (rig.x + reach, STAGE.ground_y - 12), 30.0, 14.0)
        return rig, obj, plan_pickup(rig, obj, character=name, grip=Grip.SMALL)

    def test_full_cycle_passes_through_every_state_in_order(self) -> None:
        rig, obj, plan = self._plan()
        machine = PickupMachine(plan)
        for i in range(int(plan.duration * 30)):
            t = i / 30.0
            hand = hand_target(plan, chain_for(rig, "right"), t)
            machine.update(t, contact_error=contact_error(obj, hand))
        self.assertIs(machine.state, PickupState.COMPLETE)
        names = [name for name, _ in machine.log]
        self.assertEqual(names[0], "IDLE")
        for expected in ("REACHING", "CONTACT", "GRIPPING", "HOLDING", "RELEASING", "COMPLETE"):
            self.assertIn(expected, names)

    def test_illegal_transition_is_refused(self) -> None:
        _, _, plan = self._plan()
        machine = PickupMachine(plan)
        with self.assertRaises(InvalidTransition):
            machine.transition(PickupState.PUBLISHED if hasattr(PickupState, "PUBLISHED")
                               else PickupState.COMPLETE, 0.0)

    def test_reaching_an_out_of_range_object_is_recorded_as_failed(self) -> None:
        rig, obj, plan = self._plan()
        machine = PickupMachine(plan)
        # Driving the schedule while reporting a hand far from the object must not produce a grip.
        failed = False
        for i in range(int(plan.duration * 30)):
            t = i / 30.0
            state = machine.update(t, contact_error=40.0)
            if state is PickupState.FAILED:
                failed = True
                break
        self.assertTrue(failed, "machine claimed contact for a hand 40 px from the object")
        self.assertGreater(40.0, CONTACT_TOLERANCE)

    def test_legal_edges_only_contain_defined_states(self) -> None:
        for source, targets in ALLOWED_EDGES.items():
            for target in targets:
                self.assertIsInstance(target, PickupState)
                self.assertNotEqual(source, target)

    def test_object_behind_the_character_is_reported_as_a_turn(self) -> None:
        rig = rig_for("gappu")  # faces left
        shoulder = shoulder_point(rig, "right")
        # Gappu faces -x, so "behind" is +x from his shoulder - the opposite of Chiku's.
        behind = WorldObject("cup", (shoulder[0] + 45.0, shoulder[1] + 10.0), 16.0, 16.0)
        plan = plan_pickup(rig, behind, character="gappu")
        self.assertTrue(plan.behind_character)
        self.assertTrue(any("behind" in note for note in plan.notes))

    def test_plan_reports_infeasibility_rather_than_raising(self) -> None:
        rig = rig_for("chiku")
        far = WorldObject("key", (rig.x + 400, STAGE.ground_y - 12), 30.0, 14.0)
        plan = plan_pickup(rig, far, character="chiku")
        self.assertFalse(plan.feasible)
        self.assertTrue(any("out of reach" in note for note in plan.notes))

    def test_hand_travel_has_no_discontinuity(self) -> None:
        """A jump is an isolated spike against its neighbours, not merely a fast frame: the release
        stroke is legitimately quick, and a flat speed cap would forbid that."""

        rig, _, plan = self._plan()
        chain = chain_for(rig, "right")
        points = [hand_target(plan, chain, i / 120.0) for i in range(int(plan.duration * 120))]
        steps = [math.dist(a, b) for a, b in zip(points, points[1:])]
        median = sorted(steps)[len(steps) // 2]
        for i, step in enumerate(steps):
            neighbours = steps[max(0, i - 3):i] + steps[i + 1:i + 4]
            local = max(neighbours) if neighbours else median
            self.assertLessEqual(step, max(local * 3.0, median * 6.0, 2.0),
                                 f"hand jumped at frame {i} ({step:.2f} vs local {local:.2f})")


if __name__ == "__main__":
    unittest.main()
