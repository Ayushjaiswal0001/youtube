"""Conversational cinematography tests (T42).

The planner must derive shots from the conversation, so these tests assert the *rules*, not a
snapshot of one episode's shot list: who owns the line, who is listening, where the cut would break
the axis, and whether the edit earns a close-up. A timer-based alternator would pass a snapshot test
and fail these.
"""

import unittest

from studio.animation.shot_plan import (
    DEFAULT_PARTICIPANTS,
    MIN_SECONDS_PER_CUT,
    ShotDecision,
    ShotPlan,
    apply_plan,
    cut_rate_violations,
    plan_conversation,
    screen_sides,
    validate_plan,
)

ANCHORS = [("chiku", 600.0), ("gappu", 1320.0)]


def _scenes(*lines, bg="haunted_haveli"):
    """(speaker, dialogue) pairs into story-packet scenes."""

    return [
        {"scene_num": index + 1, "speaker": speaker, "dialogue": text, "bg": bg}
        for index, (speaker, text) in enumerate(lines)
    ]


class AxisTests(unittest.TestCase):
    def test_the_left_anchor_is_the_left_side(self):
        self.assertEqual(screen_sides(ANCHORS), {"chiku": "left", "gappu": "right"})

    def test_order_not_name_decides_the_side(self):
        self.assertEqual(screen_sides([("gappu", 100.0), ("chiku", 900.0)]),
                         {"gappu": "left", "chiku": "right"})

    def test_a_single_character_is_centred(self):
        self.assertEqual(screen_sides([("chiku", 600.0)]), {"chiku": "centre"})

    def test_two_characters_sharing_a_side_is_a_violation(self):
        plan = ShotPlan(
            decisions=[
                ShotDecision(1, "medium_chiku", "chiku", "speaker_medium", "chiku", "gappu"),
                ShotDecision(2, "medium_gappu", "gappu", "speaker_medium", "gappu", "chiku"),
            ],
            screen_side={"chiku": "left", "gappu": "left"},
        )
        self.assertTrue(any("share the left side" in item for item in validate_plan(plan)))


class SpeakerCoverageTests(unittest.TestCase):
    def test_the_speaker_gets_a_medium(self):
        plan = plan_conversation(_scenes(("chiku", "मैं जाऊँगा।")), anchors=ANCHORS)
        self.assertEqual(plan.decisions[0].camera, "wide_establishing")  # the episode opens wide
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "मैं जाऊँगा।")),
                                 anchors=ANCHORS)
        self.assertEqual(plan.decisions[1].camera, "medium_chiku")
        self.assertEqual(plan.decisions[1].subject, "chiku")

    def test_two_speakers_alternate_frames(self):
        # This is the reverse shot: turn ownership decides it, so the shots alternate because the
        # speakers do, not because a counter flipped.
        plan = plan_conversation(_scenes(
            ("narrator", "दोनों खड़े थे।"),
            ("chiku", "चलो।"), ("gappu", "रुको।"), ("chiku", "क्यों?"), ("gappu", "देखो।"),
        ), anchors=ANCHORS)
        cameras = plan.cameras()
        self.assertEqual(cameras[1], "medium_chiku")
        self.assertEqual(cameras[2], "medium_gappu")
        self.assertEqual(cameras[3], "close_up_chiku")
        self.assertEqual(cameras[4], "medium_gappu")

    def test_the_listener_is_never_framed_while_the_speaker_talks(self):
        # The real defect: scene 11 of the Haveli episode framed Chiku while Gappu spoke.
        plan = plan_conversation(_scenes(
            ("narrator", "शुरू।"), ("chiku", "मैं जाऊँगा।"),
        ), anchors=ANCHORS)
        self.assertEqual(plan.decisions[1].subject, "chiku")

        broken = ShotPlan(
            decisions=[ShotDecision(1, "medium_chiku", "chiku", "speaker_medium", "gappu", "chiku")],
            screen_side={"chiku": "left", "gappu": "right"},
        )
        self.assertTrue(any("is speaking" in item for item in validate_plan(broken)))

    def test_a_run_with_no_reverse_coverage_is_flagged(self):
        solo = [
            ShotDecision(index, "medium_chiku", "chiku", "speaker_medium", "chiku", "gappu")
            for index in range(1, 5)
        ]
        plan = ShotPlan(decisions=solo, screen_side={"chiku": "left", "gappu": "right"})
        violations = validate_plan(plan)
        self.assertTrue(any("no reverse coverage" in item for item in violations))

    def test_the_same_framing_twice_in_a_row_is_flagged(self):
        plan = ShotPlan(
            decisions=[
                ShotDecision(1, "medium_chiku", "chiku", "speaker_medium", "chiku", "gappu"),
                ShotDecision(2, "medium_chiku", "chiku", "speaker_medium", "chiku", "gappu"),
            ],
            screen_side={"chiku": "left", "gappu": "right"},
        )
        self.assertTrue(any("identical framing" in item for item in validate_plan(plan)))

    def test_the_planner_never_cuts_to_the_same_frame_twice_running(self):
        plan = plan_conversation(_scenes(
            ("narrator", "एक।"), ("narrator", "दो।"), ("narrator", "तीन।"),
        ), anchors=ANCHORS)
        cameras = plan.cameras()
        for previous, current in zip(cameras, cameras[1:]):
            self.assertNotEqual(previous, current)
        self.assertEqual(validate_plan(plan), [])


class NarratorAndLocationTests(unittest.TestCase):
    def test_the_episode_opens_on_the_space(self):
        plan = plan_conversation(_scenes(("chiku", "नमस्ते।")), anchors=ANCHORS)
        self.assertEqual(plan.decisions[0].camera, "wide_establishing")
        self.assertEqual(plan.decisions[0].reason, "episode_open")
        self.assertIsNone(plan.decisions[0].subject)

    def test_a_location_change_cuts_wide(self):
        scenes = _scenes(("chiku", "यहाँ।"), ("gappu", "वहाँ।"))
        scenes[1]["bg"] = "cave_entrance"
        plan = plan_conversation(scenes, anchors=ANCHORS)
        self.assertEqual(plan.decisions[1].camera, "wide_establishing")
        self.assertEqual(plan.decisions[1].reason, "location_change")

    def test_a_narrator_line_holds_both_characters(self):
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "चलो।"),
                                         ("narrator", "वे चले।")), anchors=ANCHORS)
        self.assertEqual(plan.decisions[2].camera, "two_shot")

    def test_two_narrator_lines_in_a_row_do_not_hold_the_same_frame(self):
        plan = plan_conversation(_scenes(("narrator", "एक।"), ("narrator", "दो।")),
                                 anchors=ANCHORS)
        self.assertNotEqual(plan.decisions[0].camera, plan.decisions[1].camera)


class CloseUpTests(unittest.TestCase):
    def _chatter(self, extra):
        base = _scenes(("narrator", "शुरू।"), ("chiku", "एक।"), ("gappu", "दो।"),
                       ("chiku", "तीन।"))
        tail = _scenes(*extra)
        for index, scene in enumerate(tail, start=len(base) + 1):
            scene["scene_num"] = index
        return base + tail

    def test_an_ordinary_full_stop_does_not_earn_a_close_up(self):
        # Hindi ends nearly every line with a danda; treating it as a beat made every turn a
        # close-up.
        plan = plan_conversation(self._chatter([("gappu", "ठीक है।")]), anchors=ANCHORS)
        self.assertEqual(plan.decisions[-1].camera, "medium_gappu")

    def test_a_question_at_the_end_earns_a_close_up(self):
        plan = plan_conversation(self._chatter([("gappu", "क्या तुम डरते हो?")]), anchors=ANCHORS)
        self.assertEqual(plan.decisions[-1].camera, "close_up_gappu")
        self.assertEqual(plan.decisions[-1].reason, "punctuated_turn")

    def test_an_opening_interjection_earns_a_close_up(self):
        plan = plan_conversation(self._chatter([("gappu", "अरे! वह देखो।")]), anchors=ANCHORS)
        self.assertEqual(plan.decisions[-1].camera, "close_up_gappu")

    def test_a_close_up_needs_tenure_not_just_punctuation(self):
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "क्या?")),
                                 anchors=ANCHORS)
        self.assertNotEqual(plan.decisions[1].camera, "close_up_chiku")

    def test_close_ups_do_not_stack_on_top_of_each_other(self):
        plan = plan_conversation(_scenes(
            ("narrator", "शुरू।"), ("chiku", "एक।"), ("gappu", "दो।"),
            ("chiku", "क्या?"),          # close-up: turn 2
            ("gappu", "हाँ?"),           # too soon after - must not be another close-up
        ), anchors=ANCHORS)
        self.assertEqual(plan.decisions[3].camera, "close_up_chiku")
        self.assertNotEqual(plan.decisions[4].camera, "close_up_gappu")


class OrderingTests(unittest.TestCase):
    def test_reordering_the_lines_reorders_the_shots(self):
        first = [("narrator", "शुरू।"), ("chiku", "एक।"), ("gappu", "दो।")]
        swapped = [first[0], first[2], first[1]]
        one = plan_conversation(_scenes(*first), anchors=ANCHORS).cameras()
        two = plan_conversation(_scenes(*swapped), anchors=ANCHORS).cameras()
        self.assertEqual(one[1], "medium_chiku")
        self.assertEqual(two[1], "medium_gappu")

    def test_inserting_a_narrator_beat_changes_the_shot_it_follows(self):
        without = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "क्या?"),
                                            ("chiku", "ठीक है।")), anchors=ANCHORS).cameras()
        with_beat = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "क्या?"),
                                              ("narrator", "वह चुप हो गया।"),
                                              ("chiku", "ठीक है।")), anchors=ANCHORS).cameras()
        self.assertNotEqual(without[-1], with_beat[-1])


class ApplyTests(unittest.TestCase):
    def test_an_auto_camera_is_replaced(self):
        scenes = _scenes(("narrator", "शुरू।"), ("chiku", "एक।"))
        for scene in scenes:
            scene["camera"] = "auto"
        plan = plan_conversation(scenes, anchors=ANCHORS)
        applied = apply_plan(scenes, plan)
        self.assertEqual(applied[1]["camera"], "medium_chiku")
        self.assertEqual(applied[1]["camera_reason"], "speaker_medium")

    def test_an_authored_camera_is_left_alone_by_default(self):
        scenes = _scenes(("narrator", "शुरू।"), ("chiku", "एक।"))
        scenes[1]["camera"] = "two_shot_zoom"
        plan = plan_conversation(scenes, anchors=ANCHORS)
        self.assertEqual(apply_plan(scenes, plan)[1]["camera"], "two_shot_zoom")

    def test_respect_authored_false_rewrites_everything(self):
        scenes = _scenes(("narrator", "शुरू।"), ("chiku", "एक।"))
        scenes[1]["camera"] = "two_shot_zoom"
        plan = plan_conversation(scenes, anchors=ANCHORS)
        applied = apply_plan(scenes, plan, respect_authored=False)
        self.assertEqual(applied[1]["camera"], "medium_chiku")

    def test_the_input_scenes_are_not_mutated(self):
        scenes = _scenes(("narrator", "शुरू।"), ("chiku", "एक।"))
        scenes[1]["camera"] = "auto"
        plan = plan_conversation(scenes, anchors=ANCHORS)
        apply_plan(scenes, plan)
        self.assertEqual(scenes[1]["camera"], "auto")


class CutRateTests(unittest.TestCase):
    def test_a_cut_inside_the_floor_is_flagged(self):
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "एक।")), anchors=ANCHORS)
        violations = cut_rate_violations(None, plan, durations=[5.0, MIN_SECONDS_PER_CUT / 2])
        self.assertTrue(violations)

    def test_a_comfortable_cut_is_not_flagged(self):
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "एक।")), anchors=ANCHORS)
        self.assertEqual(cut_rate_violations(None, plan, durations=[5.0, 5.0]), [])

    def test_no_durations_means_no_opinion(self):
        plan = plan_conversation(_scenes(("narrator", "शुरू।"), ("chiku", "एक।")), anchors=ANCHORS)
        self.assertEqual(cut_rate_violations(None, plan), [])


class RealEpisodeTests(unittest.TestCase):
    def test_the_haveli_episode_directs_cleanly(self):
        from dataclasses import replace

        from factory.config import load_channel_specs
        from factory.content.script import load_plans_for
        from factory.media.landscape_stage import plan_scenes

        spec = replace(load_channel_specs()["natkhat-toons"], format="long")
        plan = next(p for p in load_plans_for(spec) if p.get("id") == "natkhat-haveli-stage-e1")
        shooting = plan_conversation(plan_scenes(plan), anchors=ANCHORS)
        self.assertEqual(validate_plan(shooting), [])
        self.assertEqual(len(shooting.decisions), 12)

    def test_every_directed_frame_names_a_real_participant(self):
        from dataclasses import replace

        from factory.config import load_channel_specs
        from factory.content.script import load_plans_for
        from factory.media.landscape_stage import plan_scenes

        spec = replace(load_channel_specs()["natkhat-toons"], format="long")
        plan = next(p for p in load_plans_for(spec) if p.get("id") == "natkhat-haveli-stage-e1")
        shooting = plan_conversation(plan_scenes(plan), anchors=ANCHORS)
        for decision in shooting.decisions:
            if decision.subject is not None:
                self.assertIn(decision.subject, DEFAULT_PARTICIPANTS)


if __name__ == "__main__":
    unittest.main()
