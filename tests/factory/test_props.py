"""Prop and hand-contact tests (T40).

An object in a scene is only believable if a hand is actually holding it, so most of these tests
are about geometry that can be measured: where the hand is, whether the prop follows it, whether
the crossing between two hands stays continuous, and whether the caption band hides it.

The hand position is checked against rendered pixels, not against the same formula it was
computed with, so the test would fail if a rig's arm art moved.
"""

import math
import unittest

import cairo
import numpy as np

from studio.animation.framing import (
    fit_zoom,
    opaque_rect,
    overlap_area,
    plan_shot,
    project,
    screen_box,
    subject_from_schema,
    world_y_for_screen,
)
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.props import (
    PROPS,
    PropTrack,
    contact_error,
    draw_prop,
    hand_point,
    max_step,
    prop_box,
    raise_arm_for_clearance,
)

VERTICAL = (1080, 1920)
SPEC = PROPS["brass_key"]


def render(rig, width=1080, height=1920):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    rig.update_pose("idle", 1.0)
    rig.draw(cr)
    surface.flush()
    return np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(
        height, surface.get_stride() // 4, 4)[:, :width, :3][:, :, ::-1].astype(int)


class HandGeometryTests(unittest.TestCase):
    def test_the_computed_hand_is_where_the_hand_is_drawn(self):
        # The hand is painted in the muzzle colour, which neither fur nor vest shares, so the
        # drawn hand can be found by colour and compared with the computed point.
        # Each rig paints its hands in a different palette entry: chiku in muzzle, gappu in
        # ear_inner.
        cases = ((ChikuRig, (0.99, 0.85, 0.71)), (GappuRig, (0.95, 0.80, 0.84)))
        for cls, colour in cases:
            rig = cls()
            frame = render(rig)
            for side in ("left", "right"):
                hx, hy = hand_point(rig, side)
                patch = frame[int(hy) - 26:int(hy) + 26, int(hx) - 26:int(hx) + 26]
                mask = np.abs(patch - np.array([c * 255 for c in colour])).sum(axis=2) < 40
                self.assertGreater(int(mask.sum()), 50, f"{cls.__name__} {side}: no hand pixels")
                ys, xs = np.nonzero(mask)
                drawn = (xs.mean() + int(hx) - 26, ys.mean() + int(hy) - 26)
                self.assertLess(math.dist(drawn, (hx, hy)), 6.0,
                                f"{cls.__name__} {side}: computed hand is off the drawn hand")

    def test_the_two_rigs_do_not_put_their_left_hands_in_the_same_place(self):
        # Gappu faces left, so his left hand is on the right of the frame; this is a mirror, not
        # a bug, and it is why a raising direction cannot be hard-coded per side.
        chiku, gappu = ChikuRig(), GappuRig()
        chiku.update_pose("idle", 1.0)
        gappu.update_pose("idle", 1.0)
        self.assertLess(hand_point(chiku, "left")[0], hand_point(gappu, "left")[0])

    def test_an_angle_override_does_not_disturb_the_rig(self):
        rig = ChikuRig()
        rig.update_pose("idle", 1.0)
        before = (rig.arm_l_angle, rig.arm_r_angle)
        hand_point(rig, "right", angle=1.0)
        self.assertEqual((rig.arm_l_angle, rig.arm_r_angle), before)

    def test_the_hand_moves_when_the_arm_moves(self):
        rig = ChikuRig()
        rig.update_pose("idle", 1.0)
        base = hand_point(rig, "right")
        moved = hand_point(rig, "right", angle=rig.arm_r_angle + 0.8)
        self.assertGreater(math.dist(base, moved), 10.0)


class PropGeometryTests(unittest.TestCase):
    def test_a_box_is_centred_on_the_prop(self):
        x0, y0, x1, y1 = prop_box((100.0, 200.0), SPEC)
        self.assertAlmostEqual((x0 + x1) / 2.0, 100.0)
        self.assertAlmostEqual((y0 + y1) / 2.0, 200.0)
        self.assertAlmostEqual(x1 - x0, 2 * SPEC.half_w)

    def test_the_key_reads_at_delivery_size(self):
        # A prop smaller than the hand holding it is a speck, not an object.
        chiku = ChikuRig()
        hand_diameter = 2 * chiku.prop.values["hand_rx"] * chiku.schema.anchor["scale"]
        self.assertGreater(2 * SPEC.half_w, hand_diameter)

    def test_an_unknown_prop_is_a_loud_error(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        with self.assertRaises(KeyError):
            draw_prop(cairo.Context(surface), "banana", (5.0, 5.0))

    def test_the_key_draws_something(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        cr = cairo.Context(surface)
        draw_prop(cr, "brass_key", (100.0, 100.0))
        surface.flush()
        alpha = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(
            200, surface.get_stride() // 4, 4)[:, :200, 3]
        self.assertGreater(int((alpha > 10).sum()), 200)


class PropTrackTests(unittest.TestCase):
    def track(self, **kwargs):
        return PropTrack(SPEC, holder="chiku", side="right", handoff_to="gappu",
                         handoff_side="left", handoff_at=2.0, handoff_duration=0.5, **kwargs)

    def hands(self, t):
        # Two hands drifting apart, so a stale position is indistinguishable from a wrong one.
        return {"chiku": (400.0 + t, 1200.0), "gappu": (800.0 - t, 1300.0)}

    def test_the_holder_is_reported_before_during_and_after_the_crossing(self):
        track = self.track()
        self.assertEqual(track.held_by(1.0), "chiku")
        self.assertIsNone(track.held_by(2.2))
        self.assertEqual(track.held_by(2.6), "gappu")

    def test_without_a_handoff_the_prop_never_leaves_its_holder(self):
        track = PropTrack(SPEC, holder="gappu", side="left")
        self.assertEqual(track.held_by(99.0), "gappu")
        self.assertEqual(track.point_at(1.0, self.hands(1.0)), self.hands(1.0)["gappu"])

    def test_the_prop_sits_in_the_giving_hand_until_the_crossing(self):
        track = self.track()
        self.assertEqual(track.point_at(1.9, self.hands(1.9)), self.hands(1.9)["chiku"])

    def test_the_prop_ends_in_the_receiving_hand(self):
        track = self.track()
        self.assertEqual(track.point_at(3.0, self.hands(3.0)), self.hands(3.0)["gappu"])

    def test_the_crossing_arcs_above_the_straight_line(self):
        track = self.track()
        hands = self.hands(2.25)
        point = track.point_at(2.25, hands)
        straight = ((hands["chiku"][0] + hands["gappu"][0]) / 2.0,
                    (hands["chiku"][1] + hands["gappu"][1]) / 2.0)
        self.assertLess(point[1], straight[1] - 5.0)
        self.assertAlmostEqual(point[0], straight[0], delta=6.0)

    def test_the_crossing_is_continuous(self):
        track = self.track()
        peak = max_step(track, self.hands, duration=4.0, fps=30)
        # The crossing covers ~400 px in 0.5 s (15 frames), so ~27 px/frame is inherent, and the
        # arc adds a little. A step far beyond that would be a teleport, which is what this
        # bounds.
        self.assertLess(peak, 60.0)

    def test_an_angle_can_be_animated_but_starts_at_zero(self):
        track = self.track(angle_rate=0.5)
        self.assertEqual(track.angle_at(0.0), 0.0)
        self.assertAlmostEqual(track.angle_at(2.0), 1.0)


class ContactTests(unittest.TestCase):
    def test_a_held_prop_touches_the_hand_that_holds_it(self):
        track = PropTrack(SPEC, holder="chiku", side="right")
        hands = {"chiku": (500.0, 1250.0), "gappu": (800.0, 1400.0)}
        self.assertEqual(contact_error(track, 1.0, hands), 0.0)

    def test_the_receiver_is_far_from_the_prop_until_it_is_handed_over(self):
        # What a pick-up has to be timed against: the distance from the hand that is about to
        # take it, which is not zero until the object is actually there.
        track = PropTrack(SPEC, holder="chiku", side="right", handoff_to="gappu",
                          handoff_side="left", handoff_at=2.0, handoff_duration=0.5)
        hands = {"chiku": (400.0, 1250.0), "gappu": (800.0, 1400.0)}
        self.assertGreater(contact_error(track, 1.0, hands, character="gappu"), 300.0)
        self.assertEqual(contact_error(track, 3.0, hands, character="gappu"), 0.0)


class BandClearanceTests(unittest.TestCase):
    def test_a_hand_that_already_clears_the_band_is_left_alone(self):
        rig = ChikuRig()
        rig.update_pose("idle", 1.0)
        self.assertEqual(raise_arm_for_clearance(rig, "right", SPEC, band_top_world=2000.0), 0.0)

    def test_a_hand_in_the_band_is_raised_until_the_prop_clears_it(self):
        rig = GappuRig()
        rig.update_pose("idle", 1.0)
        band_top = 1389.0
        delta = raise_arm_for_clearance(rig, "left", SPEC, band_top_world=band_top)
        self.assertNotEqual(delta, 0.0, "a hand inside the band must be raised")
        rig.arm_l_angle += delta
        bottom = hand_point(rig, "left")[1] + SPEC.half_h
        self.assertLessEqual(bottom, band_top - 14.0 + 1e-6)
        # ... and the raise is the smallest that works.
        rig2 = GappuRig()
        rig2.update_pose("idle", 1.0)
        bigger_step = raise_arm_for_clearance(rig2, "left", SPEC, band_top_world=band_top,
                                              step=0.12)
        self.assertLessEqual(abs(delta), abs(bigger_step) + 1e-9)

    def test_a_band_the_arm_cannot_reach_leaves_the_arm_alone(self):
        # Gappu's arms are short. When the target is out of reach the solver returns 0 rather
        # than wrenching the arm to its limit and pretending; the camera lift is what has to
        # save that frame, and the render log records how often it does.
        rig = GappuRig()
        rig.update_pose("idle", 1.0)
        self.assertEqual(raise_arm_for_clearance(rig, "left", SPEC, band_top_world=1200.0), 0.0)

    def test_no_band_means_no_solver(self):
        rig = GappuRig()
        rig.update_pose("idle", 1.0)
        self.assertEqual(raise_arm_for_clearance(rig, "left", SPEC, band_top_world=None), 0.0)


class BandOcclusionTests(unittest.TestCase):
    def test_the_band_is_measured_from_the_overlay_not_from_a_constant(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
        cr = cairo.Context(surface)
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.7)
        cr.rectangle(10, 60, 120, 30)
        cr.fill()
        surface.flush()
        self.assertEqual(opaque_rect(surface), (10.0, 60.0, 130.0, 90.0))

    def test_an_empty_overlay_has_no_band(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 40, 40)
        surface.flush()
        self.assertIsNone(opaque_rect(surface))

    def test_overlap_is_zero_unless_the_rectangles_share_area(self):
        self.assertEqual(overlap_area((0, 0, 10, 10), (20, 20, 30, 30)), 0.0)
        self.assertEqual(overlap_area((0, 0, 10, 10), (5, 5, 15, 15)), 25.0)

    def test_a_prop_box_is_projected_like_everything_else(self):
        box = prop_box((500.0, 1300.0), SPEC)
        screen = screen_box(box, 1.0, 0.0, 0.0, VERTICAL)
        self.assertAlmostEqual(screen[0], box[0])
        self.assertAlmostEqual(screen[3], box[3])

    def test_the_screen_to_world_conversion_inverts_the_projection(self):
        for zoom, pan_y in ((1.0, -43.5), (1.7, 310.25), (1.12, 0.0)):
            screen_y = 900.0
            world_y = world_y_for_screen(screen_y, zoom, pan_y, VERTICAL)
            self.assertAlmostEqual(project(0.0, world_y, zoom, 0.0, pan_y, VERTICAL)[1],
                                   screen_y, places=6)


class PropFramingTests(unittest.TestCase):
    def subjects(self):
        return {"chiku": subject_from_schema("chiku", ChikuRig().schema),
                "gappu": subject_from_schema("gappu", GappuRig().schema)}

    def test_a_prop_widens_the_shot_but_does_not_change_the_cast(self):
        subjects = self.subjects()
        plain = plan_shot("two_shot", subjects, VERTICAL, speaker="chiku")
        far_prop = prop_box((1500.0, 1300.0), SPEC)
        with_prop = plan_shot("two_shot", subjects, VERTICAL, speaker="chiku", extras=[far_prop])
        self.assertEqual(set(with_prop.subjects), set(plain.subjects))
        self.assertLessEqual(with_prop.limit, plain.limit)
        self.assertAlmostEqual(with_prop.centre_x, (plain.centre_x + 1500.0) / 2.0, delta=200.0)

    def test_the_fit_includes_the_prop(self):
        subjects = self.subjects()
        far_prop = prop_box((1000.0, 1300.0), SPEC)
        boxes = [subjects[name].bounds(1.0) for name in subjects] + [far_prop]
        shot = plan_shot("two_shot", subjects, VERTICAL, speaker="chiku", extras=[far_prop])
        self.assertLessEqual(shot.limit, fit_zoom(boxes, VERTICAL) + 1e-9)


if __name__ == "__main__":
    unittest.main()
