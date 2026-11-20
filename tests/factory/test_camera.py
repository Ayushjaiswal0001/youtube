"""Tests for camera direction (T35) and the lens vignette."""

from __future__ import annotations

import unittest

import cairo

from studio.animation.camera import CAMERA_STYLES, Camera, CameraDirector
from studio.animation.effects import draw_vignette

W, H = 1080, 1920
CHIKU_FACE = (380.0, 1180.0)
GAPPU_FACE = (780.0, 1180.0)


class StyleTests(unittest.TestCase):
    def test_unknown_style_falls_back_to_the_two_shot_drift(self):
        director = CameraDirector("interpretive_dance", duration=6.0)
        self.assertEqual(director.style, "medium_pan")

    def test_subject_is_reported_for_close_ups_only(self):
        self.assertEqual(CameraDirector("close_up_chiku").subject, "chiku")
        self.assertEqual(CameraDirector("close_up_gappu").subject, "gappu")
        for style in CAMERA_STYLES:
            if not style.startswith("close_up"):
                self.assertIsNone(CameraDirector(style).subject)

    def test_every_style_stays_in_a_believable_range(self):
        for style in CAMERA_STYLES:
            director = CameraDirector(style, duration=6.0)
            for step in range(60):
                frame = director.state_at(step * 0.1)
                self.assertGreaterEqual(frame.zoom, 0.99, style)
                self.assertLessEqual(frame.zoom, 2.0, style)
                self.assertLessEqual(abs(frame.pan_x), W, style)
                self.assertLessEqual(abs(frame.pan_y), H, style)

    def test_frames_are_deterministic(self):
        one = CameraDirector("medium_pan", duration=6.0)
        two = CameraDirector("medium_pan", duration=6.0)
        for step in range(40):
            self.assertEqual(one.state_at(step * 0.15), two.state_at(step * 0.15))


class FramingTests(unittest.TestCase):
    def test_close_up_centres_chiku_and_pushes_him_out_of_the_two_shot(self):
        director = CameraDirector("close_up_chiku", duration=6.0, viewport=(W, H))
        frame = director.state_at(3.0)
        face_x, face_y = director.project(*CHIKU_FACE, frame)
        self.assertAlmostEqual(face_x, W / 2, delta=1.0)
        self.assertGreater(frame.zoom, 1.5)
        # The partner must be fully outside the frame, not a sliver at the edge.
        partner_x, _ = director.project(*GAPPU_FACE, frame)
        self.assertGreater(partner_x, W + 100)
        # Face above centre, feet still inside the frame.
        self.assertLess(face_y, H / 2)
        self.assertLess(director.project(380.0, 1539.0, frame)[1], H * 0.8)

    def test_close_up_gappu_is_the_mirror_case(self):
        director = CameraDirector("close_up_gappu", duration=6.0, viewport=(W, H))
        frame = director.state_at(3.0)
        self.assertAlmostEqual(director.project(*GAPPU_FACE, frame)[0], W / 2, delta=1.0)
        self.assertLess(director.project(*CHIKU_FACE, frame)[0], -100)

    def test_close_up_eases_in_over_the_first_second(self):
        director = CameraDirector("close_up_chiku", duration=6.0, viewport=(W, H))
        zooms = [director.state_at(t / 10).zoom for t in range(0, 12)]
        self.assertLess(zooms[0], 1.10)
        self.assertGreater(zooms[-1], 1.65)
        self.assertEqual(zooms, sorted(zooms), "the push-in must be monotonic")

    def test_two_shot_zoom_pushes_in_monotonically(self):
        director = CameraDirector("two_shot_zoom", duration=6.0)
        zooms = [director.state_at(t / 10).zoom for t in range(0, 60, 5)]
        self.assertAlmostEqual(zooms[0], 1.0, places=3)
        self.assertGreater(zooms[-1], 1.12)
        self.assertEqual(zooms, sorted(zooms))

    def test_wide_finish_pulls_out(self):
        director = CameraDirector("wide_finish", duration=6.0)
        zooms = [director.state_at(t / 10).zoom for t in range(0, 60, 5)]
        self.assertGreater(zooms[0], 1.1)
        self.assertEqual(zooms, sorted(zooms, reverse=True))
        # The move completes exactly at the end of the scene, not before it.
        self.assertAlmostEqual(director.state_at(6.0).zoom, 1.0, places=3)

    def test_medium_pan_drifts_without_running_away(self):
        director = CameraDirector("medium_pan", duration=6.0)
        pans = [director.state_at(t / 30).pan_x for t in range(180)]
        self.assertLess(max(pans), 30.0)
        self.assertGreater(min(pans), -30.0)
        jumps = [abs(b - a) for a, b in zip(pans, pans[1:])]
        self.assertLess(max(jumps), 1.0, "a pan must not jump between frames")

    def test_project_matches_the_cairo_transform(self):
        director = CameraDirector("close_up_chiku", duration=6.0, viewport=(W, H))
        frame = director.state_at(3.0)
        expected_x, expected_y = director.project(*CHIKU_FACE, frame)

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        cr = cairo.Context(surface)
        camera = Camera(W, H)
        camera.zoom, camera.pan_x, camera.pan_y = frame.zoom, frame.pan_x, frame.pan_y
        camera.apply(cr, 0.0)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.rectangle(CHIKU_FACE[0] - 4, CHIKU_FACE[1] - 4, 8, 8)
        cr.fill()
        surface.flush()

        data = surface.get_data()
        stride = surface.get_stride()
        hits = [(x, y) for y in range(int(expected_y) - 20, int(expected_y) + 20)
                for x in range(int(expected_x) - 20, int(expected_x) + 20)
                if data[y * stride + x * 4] > 250]
        self.assertTrue(hits, "the marker is not where project() says it is")
        centre_x = sum(x for x, _ in hits) / len(hits)
        centre_y = sum(y for _, y in hits) / len(hits)
        self.assertAlmostEqual(centre_x, expected_x, delta=2.0)
        self.assertAlmostEqual(centre_y, expected_y, delta=2.0)


class VignetteTests(unittest.TestCase):
    def _render(self, width=270, height=480):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()
        draw_vignette(cr, width, height, strength=0.30)
        surface.flush()
        return surface

    def _pixel(self, surface, x, y):
        data = surface.get_data()
        return data[y * surface.get_stride() + x * 4]

    def test_centre_is_untouched_and_corners_are_darker(self):
        surface = self._render()
        centre = self._pixel(surface, 135, 240)
        corner = self._pixel(surface, 2, 2)
        edge = self._pixel(surface, 135, 2)
        self.assertGreater(centre, 250)
        self.assertLess(corner, centre - 40)
        self.assertLess(edge, centre - 20)
        self.assertGreater(corner, 0)

    def test_zero_strength_draws_nothing(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 200)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()
        draw_vignette(cr, 120, 200, strength=0.0)
        surface.flush()
        self.assertEqual(self._pixel(surface, 2, 2), 255)


if __name__ == "__main__":
    unittest.main()
