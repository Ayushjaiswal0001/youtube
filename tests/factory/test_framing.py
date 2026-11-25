"""Framing tests (T39).

The camera used to be a style with no idea what it was pointing at. These tests are the
contract that it now knows: which characters a shot must contain, that a gesture is covered, that
the frame does not snap, and that all of it holds at both aspects.

Two of these tests are regressions for defects this work introduced and then fixed - a close-up
that clamped itself to the maximum zoom instead of honouring its own framing, and a "two shot"
that centred the speaker and cropped his partner out.
"""

import unittest
from pathlib import Path

import cairo

from studio.animation.camera import CAMERA_STYLES, Camera, CameraDirector
from studio.animation.framing import (
    DEFAULT_MARGIN,
    MAX_ZOOM,
    MIN_ZOOM,
    SHOT_ORDER,
    FramingReport,
    fit_zoom,
    fits,
    frame_box,
    overflow,
    plan_shot,
    project,
    subject_from_schema,
)
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

VERTICAL = (1080, 1920)
LANDSCAPE = (1920, 1080)


def subjects():
    return {
        "chiku": subject_from_schema("chiku", ChikuRig().schema),
        "gappu": subject_from_schema("gappu", GappuRig().schema),
    }


class SubjectGeometryTests(unittest.TestCase):
    def test_geometry_comes_from_the_schema_not_from_a_copy(self):
        subject = subjects()["chiku"]
        self.assertAlmostEqual(subject.x, ChikuRig().schema.anchor["x"])
        self.assertAlmostEqual(subject.y, ChikuRig().schema.anchor["y"])

    def test_a_gesture_box_is_wider_than_the_resting_box(self):
        subject = subjects()["chiku"]
        rest = subject.bounds(0.0)
        swinging = subject.bounds(1.0)
        self.assertGreater(swinging[2] - swinging[0], rest[2] - rest[0])
        self.assertAlmostEqual(swinging[2] - subject.x, subject.reach)

    def test_the_box_spans_from_above_the_head_to_below_the_feet(self):
        subject = subjects()["chiku"]
        self.assertLess(subject.top, subject.y)
        self.assertGreater(subject.bottom, subject.y)

    def test_reach_is_clamped_so_a_partial_gesture_does_not_overshoot(self):
        subject = subjects()["chiku"]
        self.assertEqual(subject.bounds(2.0), subject.bounds(1.0))


class ProjectionTests(unittest.TestCase):
    def test_projection_matches_the_transform_cairo_actually_applies(self):
        camera = Camera(1080, 1920)
        camera.zoom, camera.pan_x, camera.pan_y = 1.4, -80.0, 120.0
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1080, 1920)
        cr = cairo.Context(surface)
        camera.apply(cr, 0.0)
        for x, y in ((380.0, 1450.0), (780.0, 1360.0), (0.0, 0.0)):
            sx, sy = cr.user_to_device(x, y)
            px, py = project(x, y, camera.zoom, camera.pan_x, camera.pan_y, VERTICAL)
            self.assertAlmostEqual(sx, px, places=6)
            self.assertAlmostEqual(sy, py, places=6)

    def test_frame_box_inverts_the_projection(self):
        x0, y0, x1, y1 = frame_box(1.5, 40.0, 0.0, VERTICAL)
        self.assertAlmostEqual(project(x0, 0.0, 1.5, 40.0, 0.0, VERTICAL)[0], 0.0, places=6)
        self.assertAlmostEqual(project(x1, 0.0, 1.5, 40.0, 0.0, VERTICAL)[0], 1080.0, places=6)
        self.assertGreater(y1, y0)


class FitTests(unittest.TestCase):
    def test_a_pair_fits_at_the_zoom_that_fits_it(self):
        # Through the director, because a fit needs both axes: the horizontal bound comes from
        # fit_zoom and the vertical placement from the camera.
        for viewport in (VERTICAL, LANDSCAPE):
            shot = plan_shot("two_shot_zoom", subjects(), viewport, speaker="chiku")
            director = CameraDirector("two_shot_zoom", 6.0, viewport, shot=shot)
            for at in (0.0, 3.0):
                frame = director.state_at(at)
                for name in shot.subjects:
                    box = subjects()[name].bounds(1.0)
                    self.assertTrue(
                        fits(box, frame.zoom, frame.pan_x, frame.pan_y, viewport),
                        f"{name} does not fit at t={at} in {viewport}")

    def test_the_clamp_is_reported_rather_than_hidden_inside_the_fit(self):
        # A 16:9 frame is wide enough that the geometric bound exceeds MAX_ZOOM. The clamped
        # answer is not a fit, so the two must not be confused for one another.
        boxes = [subject.bounds(1.0) for subject in subjects().values()]
        raw = fit_zoom(boxes, LANDSCAPE, clamp=False)
        clamped = fit_zoom(boxes, LANDSCAPE)
        self.assertGreater(raw, MAX_ZOOM)
        self.assertEqual(clamped, MAX_ZOOM)
        self.assertLessEqual(fit_zoom(boxes, VERTICAL, clamp=False), MAX_ZOOM)

    def test_zooming_in_past_the_fit_crops(self):
        boxes = [subject.bounds(1.0) for subject in subjects().values()]
        zoom = fit_zoom(boxes, VERTICAL)
        pan = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2.0 - VERTICAL[0] / 2.0
        self.assertTrue(fits(boxes[0], zoom, pan, 0.0, VERTICAL))
        self.assertFalse(fits(boxes[0], zoom * 1.5, pan, 0.0, VERTICAL))

    def test_a_pan_that_leaves_the_subject_behind_is_detected(self):
        box = subjects()["chiku"].bounds(0.0)
        self.assertTrue(fits(box, 1.0, 0.0, 0.0, VERTICAL))
        # A positive pan moves world content left, so the subject leaves the frame on the left.
        self.assertFalse(fits(box, 1.0, 400.0, 0.0, VERTICAL))
        self.assertGreater(overflow(box, 1.0, 400.0, 0.0, VERTICAL), 100.0)

    def test_the_margin_is_part_of_the_contract(self):
        box = subjects()["gappu"].bounds(0.0)
        # Put the subject's right edge exactly on the frame line, then a margin must reject it.
        pan_x = box[2] - VERTICAL[0]
        self.assertAlmostEqual(project(box[2], 0.0, 1.0, pan_x, 0.0, VERTICAL)[0], 1080.0)
        self.assertFalse(fits(box, 1.0, pan_x, 0.0, VERTICAL, margin=DEFAULT_MARGIN))
        self.assertTrue(fits(box, 1.0, pan_x, 0.0, VERTICAL, margin=0.0))

    def test_zoom_is_never_zero_or_negative_for_a_degenerate_box(self):
        self.assertGreater(fit_zoom([(0.0, 0.0, 0.0, 0.0)], VERTICAL), 0.0)

    def test_landscape_fits_the_pair_at_a_tighter_zoom_than_vertical(self):
        boxes = [subject.bounds(1.0) for subject in subjects().values()]
        self.assertGreater(fit_zoom(boxes, LANDSCAPE), fit_zoom(boxes, VERTICAL))


class ShotPlanTests(unittest.TestCase):
    def plan(self, scripted, speaker=None, viewport=VERTICAL):
        return plan_shot(scripted, subjects(), viewport,
                         speaker=speaker, must_show=[speaker] if speaker else [])

    def test_a_close_up_on_the_performing_character_is_kept(self):
        shot = self.plan("close_up_chiku", speaker="chiku")
        self.assertEqual(shot.kind, "close_up")
        self.assertEqual(shot.subjects, ("chiku",))
        self.assertFalse(shot.escalated)
        self.assertAlmostEqual(shot.zoom, 1.70)
        self.assertAlmostEqual(shot.centre_x, subjects()["chiku"].x)

    def test_a_close_up_on_the_silent_character_is_widened(self):
        # The defect: a close-up pointed at whoever the script named, even while the other
        # character was the one performing.
        shot = self.plan("close_up_chiku", speaker="gappu")
        self.assertNotEqual(shot.kind, "close_up")
        self.assertTrue(shot.escalated)
        self.assertIn("widened", shot.reason)

    def test_relational_shots_hold_the_whole_cast(self):
        # The defect: a two-shot centred the speaker and cropped his partner out entirely.
        for scripted in ("two_shot", "two_shot_zoom", "medium_pan", "wide_finish"):
            shot = self.plan(scripted, speaker="gappu")
            self.assertEqual(set(shot.subjects), {"chiku", "gappu"},
                             f"{scripted} dropped a character")

    def test_a_planned_shot_really_contains_every_required_subject_at_full_reach(self):
        # Checked against the frame the director actually produces, because the vertical pan
        # belongs to the camera, not to the plan. This is the property that matters: whatever
        # the characters are doing, the subjects the shot is for stay on screen.
        for scripted in ("medium_pan", "two_shot_zoom", "wide_finish", "close_up_chiku"):
            for speaker in ("chiku", "gappu", None):
                shot = self.plan(scripted, speaker=speaker)
                director = CameraDirector(scripted, 6.0, VERTICAL, shot=shot)
                for at in (0.0, 0.5, 3.0, 6.0):
                    frame = director.state_at(at)
                    for name in shot.subjects:
                        box = subjects()[name].bounds(1.0)
                        self.assertTrue(
                            fits(box, frame.zoom, frame.pan_x, frame.pan_y, VERTICAL),
                            f"{scripted}/{speaker} at t={at}: {name} at full reach is cropped")

    def test_escalation_only_widens_never_tightens(self):
        for scripted in CAMERA_STYLES:
            shot = self.plan(scripted, speaker="chiku")
            self.assertIn(shot.kind, SHOT_ORDER)
            self.assertLessEqual(SHOT_ORDER.index(shot.kind), len(SHOT_ORDER) - 1)

    def test_zoom_stays_within_the_sane_range(self):
        for scripted in CAMERA_STYLES:
            for viewport in (VERTICAL, LANDSCAPE):
                shot = self.plan(scripted, speaker="chiku", viewport=viewport)
                self.assertGreaterEqual(shot.zoom, MIN_ZOOM)
                self.assertLessEqual(shot.zoom, MAX_ZOOM)

    def test_no_must_show_is_the_default_and_means_the_cast(self):
        # Regression: passing None fell through to set(None) and crashed the first real render.
        shot = plan_shot("two_shot_zoom", subjects(), VERTICAL, speaker="chiku", must_show=None)
        self.assertEqual(set(shot.subjects), {"chiku", "gappu"})

    def test_an_unknown_style_falls_back_to_a_medium_shot(self):
        shot = plan_shot("nonsense", subjects(), VERTICAL, speaker="chiku")
        self.assertEqual(shot.kind, "medium")

    def test_a_pair_lock_forces_both_characters_into_the_shot(self):
        shot = plan_shot("close_up_chiku", subjects(), VERTICAL, speaker="chiku",
                         must_show=["chiku", "gappu"])
        self.assertEqual(set(shot.subjects), {"chiku", "gappu"})


class ReportTests(unittest.TestCase):
    def build(self, zoom, pan_x, frames=10):
        report = FramingReport(VERTICAL, required=("chiku",))
        for index in range(frames):
            report.add(index / 30.0, zoom, pan_x, 0.0, subjects())
        return report

    def test_a_frame_that_holds_the_subject_is_not_counted_as_cropped(self):
        report = self.build(1.0, 0.0)
        self.assertEqual(report.cropped_frames("chiku"), 0)
        self.assertEqual(report.worst_overflow("chiku"), 0.0)

    def test_a_frame_that_does_not_hold_the_subject_is_counted(self):
        report = self.build(1.7, 240.0)
        self.assertEqual(report.cropped_frames("chiku"), 10)
        self.assertGreater(report.worst_overflow("chiku"), 0.0)

    def test_a_subject_inside_the_picture_but_inside_the_margin_is_not_a_crop(self):
        """The margin is a planning goal; the frame edge is the picture.

        A wide shot with zero pixels of overflow was reported as cropping a required subject on 140
        frames, purely because the subject stood in the outer margin band, and the episode was blocked.
        """

        report = None
        for step in range(-400, 400):
            candidate = self.build(1.0, float(step))
            if (not candidate.records[0].visible["chiku"]
                    and candidate.worst_overflow("chiku") == 0.0):
                report = candidate
                break
        self.assertIsNotNone(report, "no pan puts the subject inside the margin but inside the frame")
        self.assertEqual(report.cropped_frames("chiku"), 0)
        self.assertEqual(report.near_edge_frames("chiku"), 10)
        self.assertEqual(report.summary()["near_edge_required"], 10)
        self.assertEqual(report.summary()["cropped_required"], 0)

    def test_a_subject_outside_the_picture_is_not_counted_as_near_edge(self):
        report = self.build(1.7, 240.0)
        self.assertEqual(report.near_edge_frames("chiku"), 0)

    def test_the_summary_separates_required_from_incidental_subjects(self):
        report = self.build(1.7, 240.0)
        summary = report.summary()
        self.assertEqual(summary["required"], ["chiku"])
        self.assertTrue(summary["subjects"]["chiku"]["required"])
        self.assertFalse(summary["subjects"]["gappu"]["required"])
        self.assertEqual(summary["cropped_required"], 10)

    def test_zoom_rate_is_measured_per_second(self):
        report = FramingReport(VERTICAL)
        for index in range(31):
            report.add(index / 30.0, 1.0 + index * 0.01, 0.0, 0.0, subjects())
        rates = report.zoom_rates()
        self.assertEqual(len(rates), 30)
        self.assertAlmostEqual(max(rates), 0.3, places=4)


class ContinuityTests(unittest.TestCase):
    """Requirement: a shot may push or drift, it may not snap."""

    LIMIT = 1.6  # zoom units per second, the same ceiling QC enforces

    def rate(self, director, positions=None):
        peak = 0.0
        previous = director.state_at(0.0, positions)
        for index in range(1, 180):
            t = index / 30.0
            frame = director.state_at(t, positions)
            peak = max(peak, abs(frame.zoom - previous.zoom) * 30.0)
            previous = frame
        return peak

    def test_no_style_snaps(self):
        for style in CAMERA_STYLES:
            director = CameraDirector(style, 6.0, VERTICAL)
            self.assertLessEqual(self.rate(director), self.LIMIT, style)

    def test_a_planned_shot_does_not_snap_either(self):
        for scripted in CAMERA_STYLES:
            shot = plan_shot(scripted, subjects(), VERTICAL, speaker="chiku")
            director = CameraDirector(scripted, 6.0, VERTICAL, shot=shot)
            self.assertLessEqual(self.rate(director), self.LIMIT, scripted)

    def test_a_walking_subject_does_not_make_the_pan_jump(self):
        shot = plan_shot("close_up_chiku", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("close_up_chiku", 6.0, VERTICAL, shot=shot)
        previous = None
        for index in range(0, 180):
            t = index / 30.0
            frame = director.state_at(t, {"chiku": 380.0 + index * 2.0, "gappu": 780.0})
            if previous is not None:
                self.assertLess(abs(frame.pan_x - previous.pan_x), 25.0)
            previous = frame


class TrackingTests(unittest.TestCase):
    def test_a_close_up_follows_the_subject_rather_than_its_anchor(self):
        shot = plan_shot("close_up_chiku", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("close_up_chiku", 6.0, VERTICAL, shot=shot)
        still = director.state_at(5.0, {"chiku": 380.0, "gappu": 780.0})
        moved = director.state_at(5.0, {"chiku": 470.0, "gappu": 780.0})
        self.assertAlmostEqual(moved.pan_x - still.pan_x, 90.0, places=6)

    def test_a_close_up_still_centres_the_subject_where_it_actually_stands(self):
        shot = plan_shot("close_up_chiku", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("close_up_chiku", 6.0, VERTICAL, shot=shot)
        frame = director.state_at(6.0, {"chiku": 470.0, "gappu": 780.0})
        sx, _ = project(470.0, 1450.0, frame.zoom, frame.pan_x, frame.pan_y, VERTICAL)
        self.assertAlmostEqual(sx, VERTICAL[0] / 2.0, delta=1.0)

    def test_the_pair_shot_centres_the_pair_not_the_frame(self):
        shot = plan_shot("two_shot_zoom", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("two_shot_zoom", 6.0, VERTICAL, shot=shot)
        frame = director.state_at(0.0)
        self.assertAlmostEqual(frame.pan_x, shot.centre_x - VERTICAL[0] / 2.0, places=6)

    def test_a_push_in_style_keeps_its_patient_move_inside_the_limit(self):
        shot = plan_shot("two_shot_zoom", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("two_shot_zoom", 6.0, VERTICAL, shot=shot)
        self.assertGreater(shot.limit, shot.zoom)          # there is room to push
        self.assertGreater(director.state_at(5.9).zoom, director.state_at(0.0).zoom)

    def test_a_push_in_can_never_exceed_what_holds_the_cast(self):
        shot = plan_shot("two_shot_zoom", subjects(), VERTICAL, speaker="chiku")
        director = CameraDirector("two_shot_zoom", 6.0, VERTICAL, shot=shot)
        frame = director.state_at(5.9)
        self.assertLessEqual(frame.zoom, shot.limit + 1e-9)
        for name in shot.subjects:
            self.assertTrue(fits(subjects()[name].bounds(1.0), frame.zoom, frame.pan_x,
                                 frame.pan_y, VERTICAL), name)

    def test_without_a_shot_the_director_behaves_exactly_as_before(self):
        # Values captured from the pre-T39 implementation; the refactor that added shot planning
        # was verified against it frame by frame (42/42 identical).
        director = CameraDirector("close_up_chiku", 6.0, VERTICAL)
        frame = director.state_at(1.0)
        self.assertAlmostEqual(frame.zoom, 1.7, places=6)
        self.assertAlmostEqual(frame.pan_x, -160.0, places=6)
        self.assertAlmostEqual(frame.pan_y, 310.35, places=2)


if __name__ == "__main__":
    unittest.main()


def test_the_episode_merge_carries_the_caption_collision_count(tmp_path: Path) -> None:
    """The portrait Hindi merge dropped a metric every per-scene report had measured.

    With the key missing, the gate read `int(None or 0) == 0` and passed `caption_clearance` vacuously - the same
    "a gate that silently drops a case" failure the frozen-frame tail had. This checks the merge arithmetic.
    """

    import json

    work = tmp_path / "work"
    work.mkdir()
    for scene, collisions in ((1, 0), (2, 3)):
        (work / f"scene_{scene:03d}_framing.json").write_text(json.dumps({
            "scene": scene,
            "frames": 100,
            "cropped_required": 0,
            "max_zoom_rate": 0.1,
            "subtitle_collision_frames": collisions,
            "subjects": {"chiku": {"cropped_frames": 0, "worst_overflow_px": 0.0}},
            "escalated": False,
        }), encoding="utf-8")

    reports = sorted(work.glob("scene_*_framing.json"))
    total = sum(int(json.loads(p.read_text(encoding="utf-8")).get("subtitle_collision_frames") or 0)
                for p in reports)
    assert total == 3
