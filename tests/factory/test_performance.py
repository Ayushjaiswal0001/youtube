"""Tests for the performance layer (T34): reaction beats and speech-driven accents."""

from __future__ import annotations

import unittest

from studio.characters.locomotion import BodyState
from studio.characters.performance import (
    MAX_BEATS,
    MIN_GAP,
    Accent,
    Beat,
    PerformanceFace,
    PerformancePlan,
    PerformanceTrack,
    plan_performance,
)


class BeatTests(unittest.TestCase):
    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            Beat(at=1.0, kind="cartwheel")

    def test_span_defaults_to_the_kind_duration(self):
        self.assertAlmostEqual(Beat(at=0.0, kind="blink").span, 0.18)
        self.assertAlmostEqual(Beat(at=0.0, kind="lean_in").span, 0.90)

    def test_explicit_duration_wins(self):
        self.assertAlmostEqual(Beat(at=0.0, kind="nod", duration=2.0).span, 2.0)


class AccentTests(unittest.TestCase):
    def test_empty_accent_is_the_identity(self):
        body = BodyState(hip_x=12.0, leg_l=0.4, arm_r=0.3, mode="walk")
        self.assertIs(Accent().on_body(body), body)
        self.assertIsNone(Accent().on_face(None))

    def test_on_body_adds_offsets_and_keeps_the_motion(self):
        body = BodyState(hip_x=12.0, jump_y=3.0, lean=0.1, leg_l=0.4, leg_r=-0.4,
                         arm_l=0.2, arm_r=0.3, head_tilt=0.05, squash=0.95, mode="walk")
        accent = Accent(head_tilt=0.2, lean=0.1, squash=1.05, jump_y=2.0)
        merged = accent.on_body(body)
        self.assertAlmostEqual(merged.head_tilt, 0.25)
        self.assertAlmostEqual(merged.lean, 0.2)
        self.assertAlmostEqual(merged.jump_y, 5.0)
        self.assertAlmostEqual(merged.squash, 0.95 * 1.05)
        self.assertEqual(merged.hip_x, 12.0)
        self.assertEqual((merged.leg_l, merged.leg_r), (0.4, -0.4))
        self.assertEqual((merged.arm_l, merged.arm_r), (0.2, 0.3))
        self.assertEqual(merged.mode, "walk")

    def test_merged_accents_accumulate_and_clamp(self):
        a = Accent(head_tilt=0.1, lid=0.8, pupil_scale=1.1)
        b = Accent(head_tilt=0.05, lid=0.6, pupil_scale=1.05)
        merged = a.merged_with(b)
        self.assertAlmostEqual(merged.head_tilt, 0.15)
        self.assertAlmostEqual(merged.lid, 0.8)
        self.assertAlmostEqual(merged.pupil_scale, 1.1)


class TrackTests(unittest.TestCase):
    def test_accent_is_zero_outside_the_beat(self):
        track = PerformanceTrack([Beat(at=1.0, kind="nod")], duration=5.0)
        self.assertTrue(track.accent_at(0.5).is_empty())
        self.assertTrue(track.accent_at(4.0).is_empty())
        self.assertFalse(track.accent_at(1.3).is_empty())

    def test_track_ignores_beats_past_the_end_and_sorts(self):
        track = PerformanceTrack(
            [Beat(at=9.0, kind="nod"), Beat(at=2.0, kind="blink"),
             Beat(at=0.5, kind="widen")], duration=5.0)
        self.assertEqual([round(b.at, 2) for b in track.beats], [0.5, 2.0])

    def test_active_kinds_reports_the_beat_under_the_playhead(self):
        track = PerformanceTrack([Beat(at=2.0, kind="nod")], duration=5.0)
        self.assertEqual(track.active_kinds(2.1), ("nod",))
        self.assertEqual(track.active_kinds(4.9), ())

    def test_track_is_deterministic(self):
        beats = [Beat(at=1.0, kind="recoil"), Beat(at=2.2, kind="nod")]
        one = PerformanceTrack(beats, duration=5.0)
        two = PerformanceTrack(beats, duration=5.0)
        for step in range(50):
            t = step * 0.1
            self.assertEqual(one.accent_at(t), two.accent_at(t))


class EnvelopeTests(unittest.TestCase):
    def _track(self, kind, strength=1.0, duration=4.0):
        return PerformanceTrack([Beat(at=1.0, kind=kind, strength=strength)], duration=duration)

    def test_nod_oscillates_and_decays(self):
        track = self._track("nod")
        samples = [track.accent_at(1.0 + i * 0.05).head_tilt for i in range(14)]
        self.assertLess(min(samples), 0.0)
        self.assertGreater(max(samples), 0.0)
        early = max(abs(value) for value in samples[:7])
        late = max(abs(value) for value in samples[7:])
        self.assertGreater(early, late)

    def test_shake_oscillates_faster_than_a_nod(self):
        nod = self._track("nod")
        shake = self._track("shake")
        def crossings(track):
            samples = [track.accent_at(1.0 + i * 0.02).head_tilt for i in range(30)]
            return sum(1 for a, b in zip(samples, samples[1:]) if a * b < 0)
        self.assertGreater(crossings(shake), crossings(nod))

    def test_recoil_leans_back_and_raises_brows(self):
        accent = self._track("recoil").accent_at(1.1)
        self.assertLess(accent.lean, 0.0)
        self.assertGreater(accent.brow_y, 0.0)
        self.assertGreater(accent.pupil_scale, 1.0)

    def test_blink_closes_and_reopens(self):
        track = self._track("blink")
        self.assertAlmostEqual(track.accent_at(1.0).lid, 0.0, places=6)
        self.assertGreater(track.accent_at(1.09).lid, 0.9)
        self.assertLess(track.accent_at(1.17).lid, 0.3)

    def test_bounce_leaves_the_ground_and_stretches(self):
        accent = self._track("bounce").accent_at(1.26)
        self.assertLess(accent.jump_y, 0.0)
        self.assertGreater(accent.squash, 1.0)

    def test_chuckle_shakes_without_moving_the_root(self):
        track = self._track("chuckle")
        samples = [track.accent_at(1.0 + i * 0.03).squash for i in range(20)]
        self.assertGreater(max(samples), 1.0)
        self.assertLess(min(samples), 1.0)
        self.assertEqual(track.accent_at(1.3).lean, 0.0)

    def test_widen_raises_brows_and_dilates(self):
        accent = self._track("widen").accent_at(1.4)
        self.assertGreater(accent.brow_y, 0.2)
        self.assertGreater(accent.pupil_scale, 1.05)

    def test_strength_scales_the_accent(self):
        weak = self._track("recoil", strength=0.3).accent_at(1.1)
        strong = self._track("recoil", strength=1.0).accent_at(1.1)
        self.assertLess(abs(weak.right) if hasattr(weak, "right") else abs(weak.lean),
                        abs(strong.lean))


class FaceWrapperTests(unittest.TestCase):
    class _FakeFace:
        def __init__(self):
            self.calls = []

        def state_at(self, t):
            self.calls.append(t)
            return _state(lid_left=0.2, lid_right=0.1, brow_y=0.0, pupil_scale=1.0)

    def test_empty_track_changes_nothing(self):
        face = self._FakeFace()
        wrapper = PerformanceFace(face, PerformanceTrack([], duration=3.0))
        self.assertEqual(wrapper.state_at(1.0), face.state_at(1.0))

    def test_lid_is_clamped_to_fully_closed(self):
        face = self._FakeFace()
        wrapper = PerformanceFace(face, PerformanceTrack(
            [Beat(at=1.0, kind="blink")], duration=3.0))
        state = wrapper.state_at(1.09)
        self.assertLessEqual(state.lid_left, 1.0)
        self.assertEqual(state.lid_left, 1.0)

    def test_attributes_delegate_to_the_controller(self):
        face = self._FakeFace()
        face.schema = "schema-object"
        wrapper = PerformanceFace(face, PerformanceTrack([], duration=3.0))
        self.assertEqual(wrapper.schema, "schema-object")


class PlanTests(unittest.TestCase):
    STATEMENT = "पीतल की चाबी घूमी और छत का दरवाज़ा धीरे से खुल गया।"
    QUESTION = "यह क्या है?"
    SHOUT = "रुको चीकू! वहाँ कोई है!"

    def test_empty_dialogue_makes_an_empty_plan(self):
        plan = plan_performance("", duration=3.0, speaker="chiku")
        self.assertEqual(plan.chiku, ())
        self.assertEqual(plan.gappu, ())

    def test_question_makes_the_listener_widen(self):
        plan = plan_performance(self.QUESTION, duration=3.0, speaker="chiku", seed=1)
        kinds = [beat.kind for beat in plan.gappu]
        self.assertIn("widen", kinds)

    def test_shout_makes_the_listener_recoil_and_the_speaker_bounce(self):
        plan = plan_performance(self.SHOUT, duration=4.0, speaker="chiku", seed=2)
        self.assertIn("recoil", [beat.kind for beat in plan.gappu])
        self.assertIn("bounce", [beat.kind for beat in plan.chiku])

    def test_statement_makes_the_listener_nod(self):
        plan = plan_performance(self.STATEMENT, duration=5.0, speaker="gappu", seed=3)
        self.assertIn("nod", [beat.kind for beat in plan.chiku])

    def test_narrator_scenes_animate_both_listeners(self):
        plan = plan_performance(self.STATEMENT, duration=5.0, speaker="narrator", seed=4)
        self.assertTrue(plan.chiku)
        self.assertTrue(plan.gappu)

    def test_beats_are_bounded_and_spaced(self):
        plan = plan_performance(self.SHOUT * 4, duration=30.0, speaker="chiku", seed=5)
        for character in (plan.chiku, plan.gappu):
            self.assertLessEqual(len(character), MAX_BEATS)
            times = [beat.at for beat in character]
            for a, b in zip(times, times[1:]):
                self.assertGreaterEqual(b - a, MIN_GAP - 1e-9)

    def test_beats_stay_inside_the_scene(self):
        plan = plan_performance(self.SHOUT, duration=2.0, speaker="chiku", seed=6)
        for character in (plan.chiku, plan.gappu):
            for beat in character:
                self.assertGreaterEqual(beat.at, 0.0)
                self.assertLess(beat.at, 2.0)

    def test_same_seed_is_reproducible_and_a_different_seed_jitters_timing(self):
        one = plan_performance(self.SHOUT, duration=4.0, speaker="chiku", seed=7)
        two = plan_performance(self.SHOUT, duration=4.0, speaker="chiku", seed=7)
        self.assertEqual(one.chiku, two.chiku)
        # A different seed shifts every beat by up to 60 ms. The kinds may differ because
        # a shifted beat can fall inside the minimum gap and be dropped, which is intended:
        # the plan is thinned after jitter, not before.
        other = plan_performance(self.SHOUT, duration=4.0, speaker="chiku", seed=8)
        self.assertNotEqual([round(beat.at, 4) for beat in other.chiku],
                            [round(beat.at, 4) for beat in one.chiku])

    def test_plan_reports_and_indexes_by_character(self):
        plan = plan_performance(self.SHOUT, duration=4.0, speaker="chiku", seed=9)
        self.assertEqual(plan.for_character("chiku"), plan.as_dict()["chiku"])
        self.assertEqual(plan.for_character("gappu"), plan.as_dict()["gappu"])

    def test_a_real_episode_line_produces_motion(self):
        line = ("रुको चीकू! सीढ़ियों पर पुराने पैरों के निशान हैं। "
                "कोई यहाँ आता है।")
        plan = plan_performance(line, duration=6.9, speaker="gappu", seed=11)
        self.assertTrue(plan.chiku and plan.gappu)
        track = PerformanceTrack(plan.for_character("chiku"), 6.9)
        moving = [t * 0.1 for t in range(69)
                  if not track.accent_at(t * 0.1).is_empty()]
        self.assertGreater(len(moving), 10)
        self.assertGreater(len(moving), 0)
        self.assertLess(max(moving), 6.9)


class LayerScopeTests(unittest.TestCase):
    """The layer must move pixels only while a beat is active.

    This renders real rig frames rather than encoded video, because a video codec's
    lookahead can shift the quantisation of frames *before* a change and make the diff look
    wider than it is.
    """

    def _frames(self, plan, character, times):
        import hashlib
        import cairo
        from studio.characters.gaze import FaceController
        from studio.characters.chiku import ChikuRig
        from studio.characters.gappu import GappuRig
        from studio.characters.locomotion import MotionController

        rig_cls = ChikuRig if character == "chiku" else GappuRig
        schema = rig_cls().schema
        track = PerformanceTrack(plan.for_character(character), 6.9)
        hashes = []
        for t in times:
            rig = rig_cls()
            face = FaceController(schema, seed=99, span=10.0, schedule=[(0.0, "neutral")])
            rig.attach_face(PerformanceFace(face, track))
            body = MotionController("idle", duration=6.9, seed=5).state_at(t)
            bare = MotionController("idle", duration=6.9, seed=5).state_at(t)
            digests = []
            for accent in (Accent(), track.accent_at(t)):
                rig.update_pose("idle", t, body=accent.on_body(
                    body if not accent.is_empty() else bare))
                rig.face_state_at(t)
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1080, 1920)
                cr = cairo.Context(surface)
                rig.draw(cr)
                surface.flush()
                digests.append(hashlib.sha256(bytes(surface.get_data())).hexdigest())
            hashes.append((t, digests[0] == digests[1]))
        return hashes

    def test_frames_are_untouched_before_the_first_beat(self):
        line = ("रुको चीकू! सीढ़ियों पर पुराने पैरों के निशान हैं। कोई यहाँ आता है।")
        plan = plan_performance(line, duration=6.9, speaker="gappu", seed=11)
        first = min(beat.at for beat in plan.for_character("chiku"))
        quiet = [t / 10 for t in range(int(first * 10) - 1)]
        self.assertTrue(quiet, "test needs at least one frame before the first beat")
        for t, same in self._frames(plan, "chiku", quiet):
            self.assertTrue(same, f"frame at {t:.2f}s changed before the first beat at {first:.2f}s")

    def test_frames_change_inside_a_beat(self):
        plan = PerformancePlan(chiku=[Beat(at=1.0, kind="recoil", strength=1.0)])
        changed = [t for t, same in self._frames(plan, "chiku", [1.05, 1.3]) if not same]
        self.assertEqual(len(changed), 2)


def _state(**kwargs):
    from studio.characters.gaze import EyeState
    return EyeState(**kwargs)


if __name__ == "__main__":
    unittest.main()
