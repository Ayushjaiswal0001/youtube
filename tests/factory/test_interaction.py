"""Tests for the two-character interaction layer (T35b)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from studio.characters.interaction import (
    FLIP_HYSTERESIS,
    MIN_SEPARATION,
    FacingTracker,
    InteractionDirector,
    InteractionPlan,
    Gesture,
    gesture_body,
    plan_interaction,
    reaction_body,
    replace_body_hip,
    resolve_separation,
)
from studio.characters.locomotion import BodyState


class SeparationTests(unittest.TestCase):
    def test_bodies_that_already_clear_the_gap_are_untouched(self):
        self.assertEqual(resolve_separation(380, 780), (380.0, 780.0))

    def test_overlapping_bodies_are_pushed_apart_to_the_minimum(self):
        left, right = resolve_separation(400, 500)
        self.assertAlmostEqual(right - left, MIN_SEPARATION)

    def test_the_push_is_symmetric(self):
        left, right = resolve_separation(400, 500)
        self.assertAlmostEqual(400 - left, right - 500)

    def test_the_centre_of_mass_is_preserved(self):
        left, right = resolve_separation(400, 500)
        self.assertAlmostEqual(left + right, 900.0)

    def test_identical_positions_resolve_deterministically(self):
        first = resolve_separation(500, 500)
        second = resolve_separation(500, 500)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first[1] - first[0], MIN_SEPARATION)

    def test_reversed_order_is_handled(self):
        # The two values are returned in argument order, so the second is now on the left.
        first, second = resolve_separation(800, 700)
        self.assertAlmostEqual(abs(second - first), MIN_SEPARATION)
        self.assertGreater(first, second)

    def test_a_custom_gap_is_respected(self):
        left, right = resolve_separation(0, 10, min_gap=50)
        self.assertAlmostEqual(right - left, 50.0)


class FacingTests(unittest.TestCase):
    def test_a_partner_to_the_right_keeps_the_default_direction(self):
        self.assertEqual(FacingTracker(1).update(0, 400), 1)

    def test_a_near_tie_does_not_flip(self):
        tracker = FacingTracker(1)
        self.assertEqual(tracker.update(0, -FLIP_HYSTERESIS / 2), 1)

    def test_a_partner_far_to_the_left_flips_once(self):
        tracker = FacingTracker(1)
        self.assertEqual(tracker.update(0, -FLIP_HYSTERESIS - 5), -1)
        self.assertEqual(tracker.update(0, -FLIP_HYSTERESIS - 6), -1)

    def test_hysteresis_stops_oscillation_around_the_line(self):
        tracker = FacingTracker(1)
        # Every offset stays inside the +/-45 band, so the direction must not change once.
        seen = [tracker.update(0, offset) for offset in (-40, -20, -44, 0, 10, -30)]
        self.assertEqual(seen, [1, 1, 1, 1, 1, 1])

    def test_it_flips_back_when_the_partner_crosses(self):
        tracker = FacingTracker(1)
        tracker.update(0, -100)
        self.assertEqual(tracker.update(0, 100), 1)


class GestureTests(unittest.TestCase):
    def test_outside_the_window_nothing_happens(self):
        gesture = Gesture(at=1.0, duration=0.5)
        self.assertEqual(gesture.amount_at(0.0), 0.0)
        self.assertEqual(gesture.amount_at(5.0), 0.0)

    def test_it_reaches_full_strength_in_the_window(self):
        gesture = Gesture(at=1.0, duration=0.5, strength=0.8)
        self.assertAlmostEqual(gesture.amount_at(1.25), 0.8)

    def test_attack_and_release_are_gradual(self):
        gesture = Gesture(at=1.0, duration=0.5)
        attack = gesture.amount_at(0.91)
        full = gesture.amount_at(1.1)
        release = gesture.amount_at(1.6)
        self.assertTrue(0.0 < attack < full)
        self.assertTrue(0.0 < release < full)

    def test_zero_amount_produces_no_body_layer(self):
        self.assertIsNone(gesture_body(0.0))
        self.assertIsNone(reaction_body(0.0))

    def test_a_gesture_extends_the_forward_arm_and_tucks_the_near_one(self):
        # Measured convention: a negative right-arm delta is the forward pinion, because the
        # rigs are mirrored by `facing` so local +x is "in front" for both characters.
        body = gesture_body(1.0)
        self.assertLess(body.arm_r_delta, -0.5)
        self.assertLess(body.arm_l_delta, 0.0)
        self.assertGreater(body.arm_l_delta, body.arm_r_delta)

    def test_a_gesture_is_additive_so_it_cannot_discard_the_pose(self):
        body = gesture_body(1.0)
        self.assertIsNone(body.arm_l)
        self.assertIsNone(body.arm_r)

    def test_a_reaction_leans_and_tilts_but_does_not_gesture(self):
        body = reaction_body(1.0, toward=-1)
        self.assertLess(body.lean, 0.0)
        self.assertGreater(body.head_tilt, 0.0)
        self.assertEqual(body.arm_r_delta, 0.0)


class PlanTests(unittest.TestCase):
    def test_a_flat_line_produces_no_gestures(self):
        plan = plan_interaction("plain words without punctuation", 5.0, "chiku", "gappu")
        self.assertEqual(plan.gesture_count, 0)

    def test_an_exclamation_produces_a_speaker_and_listener_beat(self):
        plan = plan_interaction("देखा! यह चाबी है।", 5.0, "chiku", "gappu")
        self.assertTrue(plan.gestures["chiku"])
        self.assertTrue(plan.gestures["gappu"])

    def test_the_listener_reacts_after_the_speaker(self):
        plan = plan_interaction("देखा! यह चाबी है।", 5.0, "chiku", "gappu", seed=3)
        self.assertGreater(plan.gestures["gappu"][0].at,
                           plan.gestures["chiku"][0].at)

    def test_the_listener_gestures_more_softly(self):
        plan = plan_interaction("सुनो! रुको!", 6.0, "gappu", "chiku", seed=1)
        self.assertLess(plan.gestures["chiku"][0].strength,
                        plan.gestures["gappu"][0].strength)

    def test_placement_stays_inside_the_scene(self):
        plan = plan_interaction("अरे! देखो! रुको! जाओ!", 3.0, "chiku", "gappu", seed=9)
        for gestures in plan.gestures.values():
            for gesture in gestures:
                self.assertGreaterEqual(gesture.at, 0.10)
                self.assertLessEqual(gesture.at, 3.0)

    def test_the_plan_is_deterministic_for_a_seed(self):
        first = plan_interaction("अरे! देखो!", 5.0, "chiku", "gappu", seed=42)
        second = plan_interaction("अरे! देखो!", 5.0, "chiku", "gappu", seed=42)
        self.assertEqual([g.at for g in first.gestures["chiku"]],
                         [g.at for g in second.gestures["chiku"]])

    def test_a_zero_duration_scene_has_no_events(self):
        self.assertEqual(plan_interaction("अरे!", 0.0, "chiku", "gappu").gesture_count, 0)

    def test_gestures_are_capped(self):
        plan = plan_interaction("!" * 20, 10.0, "chiku", "gappu", max_gestures=2)
        self.assertLessEqual(len(plan.gestures["chiku"]), 2)

    def test_frames_with_gesture_counts_real_frames(self):
        plan = InteractionPlan(speaker="chiku", listener="gappu",
                               gestures={"chiku": [Gesture(at=1.0, duration=1.0)], "gappu": []})
        self.assertGreater(plan.frames_with_gesture(3.0, 30), 30)
        self.assertEqual(plan.frames_with_gesture(0.5, 30), 0)


class DirectorTests(unittest.TestCase):
    def _director(self, **kwargs):
        defaults = dict(anchor_a=380.0, anchor_b=780.0)
        defaults.update(kwargs)
        return InteractionDirector(**defaults)

    def test_anchors_that_are_already_apart_are_a_no_op(self):
        self.assertEqual(self._director().resolve(0.0, 0.0), (0.0, 0.0))

    def test_a_drift_toward_the_partner_is_clamped(self):
        hip_a, hip_b = self._director().resolve(200.0, -200.0)
        self.assertGreaterEqual((780.0 + hip_b) - (380.0 + hip_a), MIN_SEPARATION - 1e-6)

    def test_no_clamp_returns_the_exact_same_floats(self):
        # Regression: anchor + hip -> anchor conversion perturbed hip_x by ulps, so a scene
        # that needed no clamping was still not bit-identical to its uninteracted form.
        hip_a, hip_b = 0.1, -0.7
        resolved = self._director().resolve(hip_a, hip_b)
        self.assertEqual(resolved, (hip_a, hip_b))
        self.assertIs(type(resolved[0]), float)

    def test_a_large_separation_is_left_alone(self):
        self.assertEqual(self._director().resolve(-300.0, 300.0), (-300.0, 300.0))

    def test_the_kill_switch_disables_the_layer(self):
        with mock.patch.dict(os.environ, {"FACTORY_NO_INTERACTION": "1"}):
            director = self._director()
            self.assertEqual(director.resolve(200.0, -200.0), (200.0, -200.0))
            self.assertEqual(director.bodies(1.0, 0.0, 0.0, "chiku"), (None, None))

    def test_bodies_are_empty_without_a_plan(self):
        self.assertEqual(self._director(plan=None).bodies(1.0, 0.0, 0.0, "chiku"),
                         (None, None))

    def test_the_speaker_gestures_and_the_listener_reacts(self):
        plan = InteractionPlan(speaker="chiku", listener="gappu",
                               gestures={"chiku": [Gesture(at=1.0, duration=0.6)],
                                         "gappu": [Gesture(at=1.2, duration=0.5)]})
        layer_a, layer_b = self._director(plan=plan).bodies(1.2, 0.0, 0.0, "chiku")
        self.assertLess(layer_a.arm_r_delta, -0.5)   # forward arm extended
        self.assertEqual(layer_b.arm_r_delta, 0.0)   # a lean, not a gesture
        self.assertLess(layer_b.lean, 0.0)

    def test_the_listener_gestures_when_it_speaks(self):
        plan = InteractionPlan(speaker="gappu", listener="chiku",
                               gestures={"gappu": [Gesture(at=1.0, duration=0.6)],
                                         "chiku": [Gesture(at=1.0, duration=0.6)]})
        layer_a, layer_b = self._director(plan=plan).bodies(1.1, 0.0, 0.0, "gappu")
        self.assertLess(layer_b.arm_r_delta, -0.5)
        self.assertEqual(layer_a.arm_r_delta, 0.0)


class HelperTests(unittest.TestCase):
    def test_hip_replacement_keeps_everything_else(self):
        state = BodyState(hip_x=5.0, lean=0.2, mode="walk")
        moved = replace_body_hip(state, 42.0)
        self.assertEqual(moved.hip_x, 42.0)
        self.assertEqual(moved.lean, 0.2)
        self.assertEqual(moved.mode, "walk")
        self.assertEqual(state.hip_x, 5.0)  # the original is untouched

    def test_the_cast_is_two_characters_so_no_crowd_helper_exists(self):
        # A pairwise multi-body clamp was written, measured, and found to under-separate
        # (265 vs 450 against a 210 gap) because each body accumulated shifts independently.
        # The product has exactly two characters, so it was deleted rather than shipped wrong.
        import studio.characters.interaction as module
        self.assertFalse(hasattr(module, "separate"))


if __name__ == "__main__":
    unittest.main()
