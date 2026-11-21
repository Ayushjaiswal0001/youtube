"""Silhouette tests (T41).

The contract is blunt: the framing box must contain the character that is drawn. These tests draw
the rig, measure the drawn pixels, and compare - which is how the T39 box was found to be 62% too
short.
"""

import unittest

import cairo
import numpy as np

from studio.animation.silhouette import clear_cache, measure, subject_from_rig
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

POSES = ("idle", "talking", "wave", "excited_jump", "shocked_freeze", "walk_a", "jump")


def drawn_bounds(rig, pose):
    rig.update_pose(pose, 1.0)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1080, 1920)
    cr = cairo.Context(surface)
    rig.draw(cr)
    surface.flush()
    alpha = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(
        1920, surface.get_stride() // 4, 4)[:, :1080, 3]
    ys, xs = np.nonzero(alpha > 8)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


class ContainmentTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_the_box_contains_the_drawn_character_in_every_pose(self):
        for cls in (ChikuRig, GappuRig):
            for pose in POSES:
                rig = cls()
                try:
                    rig.update_pose(pose, 1.0)
                except Exception:
                    continue  # a pose this rig does not have
                x0, y0, x1, y1 = drawn_bounds(rig, pose)
                subject = subject_from_rig(rig, pose)
                self.assertLessEqual(subject.top, y0 + 1.0,
                                     f"{cls.__name__} {pose}: box top is below the drawn head")
                self.assertGreaterEqual(subject.bottom, y1 - 1.0,
                                        f"{cls.__name__} {pose}: box bottom is above the feet")
                self.assertLessEqual(subject.x - subject.half_w, x0 + 1.0,
                                     f"{cls.__name__} {pose}: box is narrower than the drawing")
                self.assertGreaterEqual(subject.x + subject.half_w, x1 - 1.0,
                                        f"{cls.__name__} {pose}: box is narrower than the drawing")

    def test_the_box_is_not_absurdly_larger_than_the_character(self):
        # A box that contains everything by being enormous would pass containment and break
        # framing, so bound the slack too.
        for cls in (ChikuRig, GappuRig):
            rig = cls()
            x0, y0, x1, y1 = drawn_bounds(rig, "idle")
            subject = subject_from_rig(rig, "idle")
            drawn_h = y1 - y0
            box_h = subject.bottom - subject.top
            self.assertLess(box_h, drawn_h * 1.7, f"{cls.__name__}: box is far too tall")
            self.assertGreater(box_h, drawn_h * 1.0, f"{cls.__name__}: box is too short")


class PlacementTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_the_subject_follows_the_stage_not_the_authored_anchor(self):
        # The T41 landscape puts Chiku at 600, not the 380 written in the character file. The
        # framing has to follow the rig, or it frames empty stage.
        rig = ChikuRig(x=600, y=1028, scale=1.35)
        subject = subject_from_rig(rig, "idle")
        # The box is centred on the drawing, not on the anchor, and its floor sits just under the
        # stage's ground line (plus the safety padding).
        self.assertGreater(subject.x, 400.0)
        self.assertLess(subject.x, 600.0)
        self.assertLess(abs(subject.bottom - 1028.0), 110.0 * 1.35)

    def test_body_motion_moves_the_box(self):
        from studio.characters.locomotion import BodyState
        rig = ChikuRig()
        rest = subject_from_rig(rig, "idle", BodyState())
        jumped = subject_from_rig(rig, "idle", BodyState(hip_x=40.0, jump_y=-120.0))
        self.assertAlmostEqual(jumped.x - rest.x, 40.0)
        self.assertAlmostEqual(jumped.top - rest.top, -120.0)

    def test_measurement_is_cached_but_not_stale(self):
        rig = ChikuRig()
        first = measure(rig, "idle")
        second = measure(rig, "idle")
        self.assertEqual(first, second)
        self.assertNotEqual(measure(rig, "idle"), measure(rig, "excited_jump"))

    def test_a_mirrored_character_measures_the_same_height(self):
        # The rigs mirror about their own pivot rather than about the anchor, so the horizontal
        # extent is not an exact mirror; the height, which is what vertical framing uses, must be.
        left = ChikuRig()
        left.facing = -1.0
        self.assertAlmostEqual(measure(left, "idle").height,
                               measure(ChikuRig(), "idle").height, places=3)
        self.assertLess(measure(left, "idle").left, 0.0)

    def test_the_box_is_in_the_right_place_for_both_characters(self):
        # Regression guard for the T39 defect: these were 278 and 101 units tall and should not
        # quietly go back to that.
        for cls, minimum in ((ChikuRig, 300.0), (GappuRig, 220.0)):
            rig = cls()
            subject = subject_from_rig(rig, "idle")
            self.assertGreater(subject.bottom - subject.top, minimum,
                               f"{cls.__name__}: the subject box is far too short again")


if __name__ == "__main__":
    unittest.main()
