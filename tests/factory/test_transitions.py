"""Tests for the scene transition policy (T37)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from studio.animation.transitions import (
    CLOSING,
    OPENING,
    TRANSITION,
    ffmpeg_fade_filters,
    plan_transitions,
)


class PolicyTests(unittest.TestCase):
    def test_no_scenes_makes_no_plan(self):
        self.assertEqual(plan_transitions([]), [])

    def test_a_single_scene_opens_and_closes(self):
        self.assertEqual(plan_transitions([{"bg": "jungle_clearing"}]),
                         [(OPENING, CLOSING)])

    def test_a_change_of_location_dips_to_black_on_both_sides(self):
        plan = plan_transitions([{"bg": "a"}, {"bg": "b"}])
        self.assertEqual(plan[0], (OPENING, TRANSITION))
        self.assertEqual(plan[1], (TRANSITION, CLOSING))

    def test_staying_in_one_location_cuts_directly(self):
        plan = plan_transitions([{"bg": "a"}, {"bg": "a"}, {"bg": "a"}])
        self.assertEqual(plan[1], (0.0, 0.0))

    def test_a_mixed_sequence_is_planned_per_boundary(self):
        plan = plan_transitions([{"bg": "a"}, {"bg": "a"}, {"bg": "b"}, {"bg": "b"},
                                 {"bg": "a"}])
        self.assertEqual(plan, [
            (OPENING, 0.0),
            (0.0, TRANSITION),
            (TRANSITION, 0.0),
            (0.0, TRANSITION),
            (TRANSITION, CLOSING),
        ])

    def test_a_missing_background_key_is_treated_as_a_change(self):
        plan = plan_transitions([{}, {"bg": "a"}])
        self.assertEqual(plan[0][1], TRANSITION)
        self.assertEqual(plan[1][0], TRANSITION)

    def test_the_plan_is_one_entry_per_scene(self):
        scenes = [{"bg": "a"}, {"bg": "b"}, {"bg": "a"}]
        self.assertEqual(len(plan_transitions(scenes)), len(scenes))

    def test_durations_can_be_overridden(self):
        plan = plan_transitions([{"bg": "a"}, {"bg": "b"}], transition=0.5, opening=1.0,
                                closing=1.5)
        self.assertEqual(plan, [(1.0, 0.5), (0.5, 1.5)])


class FilterTests(unittest.TestCase):
    def test_plain_cut_produces_no_filters(self):
        self.assertEqual(ffmpeg_fade_filters(0.0, 0.0, 5.0), [])

    def test_fade_in_starts_at_zero(self):
        filters = ffmpeg_fade_filters(0.45, 0.0, 5.0)
        self.assertEqual(len(filters), 1)
        self.assertIn("fade=t=in:st=0:d=0.450", filters[0])

    def test_fade_out_ends_with_the_scene(self):
        filters = ffmpeg_fade_filters(0.0, 0.65, 5.0)
        self.assertEqual(len(filters), 1)
        self.assertIn("fade=t=out:st=4.350:d=0.650", filters[0])

    def test_fades_are_clamped_so_they_cannot_overlap(self):
        filters = ffmpeg_fade_filters(9.0, 9.0, 4.0)
        self.assertIn("d=2.000", filters[0])
        self.assertIn("st=2.000:d=2.000", filters[1])

    def test_a_negative_duration_cannot_produce_a_negative_start(self):
        filters = ffmpeg_fade_filters(0.4, 0.4, 0.0)
        self.assertEqual(filters, [])


class ContentTests(unittest.TestCase):
    def test_the_bundled_episode_fades_at_the_ends_and_location_changes(self):
        series = json.loads(Path("content/series/natkhat-toons.json").read_text(encoding="utf-8"))
        scenes = series["series"][0]["episodes"][0]["scenes"]
        plan = plan_transitions(scenes)
        for index, (fade_in, fade_out) in enumerate(plan):
            expected_in = (
                OPENING if index == 0
                else TRANSITION if scenes[index - 1].get("bg") != scenes[index].get("bg")
                else 0.0
            )
            expected_out = (
                CLOSING if index == len(scenes) - 1
                else TRANSITION if scenes[index].get("bg") != scenes[index + 1].get("bg")
                else 0.0
            )
            self.assertEqual(
                (fade_in, fade_out),
                (expected_in, expected_out),
                "scene transitions should follow location boundaries, while same-location beats cut directly",
            )


if __name__ == "__main__":
    unittest.main()
