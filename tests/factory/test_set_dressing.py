"""Tests for near-camera set dressing and the depth model it depends on (T45b / T45c).

The defect these guard against is not a crash: the previous foreground layer measured **0.0**
occlusion of the cast in all six locations, so every character stood in front of the scenery no
matter where they were. A location that cannot occlude anything is a backdrop.
"""

from __future__ import annotations

import math
import unittest

import cairo

from studio.animation import set_dressing
from studio.animation.compositor import DrawQueue, Layer
from studio.animation.environment import LOCATIONS
from studio.animation.set_dressing import dressing_for, measure_occlusion
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

STAGE = stage_for(1920, 1080)
W, H = 1920, 1080


def _surface(width: int = W, height: int = H) -> cairo.ImageSurface:
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)


def _actor_surfaces() -> list:
    surfaces = []
    for rig in (ChikuRig(**STAGE.anchor("chiku")), GappuRig(**STAGE.anchor("gappu"))):
        surface = _surface()
        context = cairo.Context(surface)
        rig.draw(context)
        surface.flush()
        surfaces.append(surface)
    return surfaces


class DressingTests(unittest.TestCase):
    def test_every_location_gets_a_set(self) -> None:
        for name in LOCATIONS:
            items = dressing_for(name, W, H, STAGE.ground_y)
            self.assertGreaterEqual(len(items), 6, name)

    def test_the_set_contains_foreground_and_world_objects(self) -> None:
        items = dressing_for("jungle_clearing", W, H, STAGE.ground_y)
        layers = {item.layer for item in items}
        self.assertIn(Layer.FOREGROUND, layers)
        self.assertIn(Layer.ACTOR, layers, "nothing stands on the world plane, so nothing can hide anyone")

    def test_placement_is_deterministic(self) -> None:
        a = [item.as_dict() for item in dressing_for("riverbank", W, H, STAGE.ground_y)]
        b = [item.as_dict() for item in dressing_for("riverbank", W, H, STAGE.ground_y)]
        self.assertEqual(a, b)

    def test_locations_get_different_sets(self) -> None:
        # A cave mouth is dressed with rock and a jungle with bushes: the six locations must not
        # share one set, or they differ only by palette.
        cave = {item.kind for item in dressing_for("cave_entrance", W, H, STAGE.ground_y)}
        jungle = {item.kind for item in dressing_for("jungle_clearing", W, H, STAGE.ground_y)}
        self.assertNotEqual(cave, jungle, "every location was dressed identically")
        haveli = {item.kind for item in dressing_for("haunted_haveli", W, H, STAGE.ground_y)}
        self.assertIn(set_dressing.PILLAR, haveli, "the haveli has no pillar to stand behind")

    def test_foreground_stays_clear_of_the_upper_frame(self) -> None:
        """Nothing near the camera may cover a face, measured where the character was drawn.

        A frame-height threshold was the first attempt and it was a proxy: it failed a grass clump
        that reaches the middle of the frame while covering nobody's head, and it would have passed an
        object that happened to sit below the line and still covered a short character's face.
        """

        actors = _actor_surfaces()
        for name in LOCATIONS:
            fractions = measure_occlusion(W, H, dressing_for(name, W, H, STAGE.ground_y), actors)
            for key, value in fractions.items():
                if key.endswith("_head"):
                    self.assertLess(value, 0.02, f"{name}/{key} covers a face: {value:.3f}")

    def test_foreground_stays_clear_of_the_caption_band(self) -> None:
        """The caption band occupies the bottom of the frame; foreground is drawn under it anyway,
        but an object whose whole body sits inside the band is hidden scenery."""

        for name in LOCATIONS:
            for item in dressing_for(name, W, H, STAGE.ground_y):
                if item.layer is not Layer.FOREGROUND:
                    continue
                self.assertGreater(item.height, 40.0, f"{name}/{item.kind} is too small to read")

    def test_a_foreground_object_may_not_bury_a_character(self) -> None:
        cast_box = (500.0, 500.0, 240.0, 300.0)
        items = dressing_for("jungle_clearing", W, H, STAGE.ground_y, cast_boxes=[cast_box])
        for item in items:
            if item.layer is not Layer.FOREGROUND:
                continue
            ox, oy, ow, oh = item.box
            overlap = (max(0.0, min(ox + ow, cast_box[0] + cast_box[2]) - max(ox, cast_box[0])) *
                       max(0.0, min(oy + oh, cast_box[1] + cast_box[3]) - max(oy, cast_box[1])))
            self.assertLessEqual(overlap / (cast_box[2] * cast_box[3]), 0.5)


class OcclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.actors = _actor_surfaces()

    def test_the_foreground_actually_covers_the_cast(self) -> None:
        worst = 0.0
        for name in LOCATIONS:
            items = dressing_for(name, W, H, STAGE.ground_y)
            fractions = measure_occlusion(W, H, items, self.actors)
            worst = max(worst, max(fractions.values(), default=0.0))
        # The previous foreground layer measured 0.0 here in every location.
        self.assertGreater(worst, 0.05, "the near layer still cannot reach the cast")

    def test_occlusion_stays_legible(self) -> None:
        for name in LOCATIONS:
            items = dressing_for(name, W, H, STAGE.ground_y)
            fractions = measure_occlusion(W, H, items, self.actors)
            for actor, value in fractions.items():
                self.assertLess(value, 0.40, f"{name}/{actor} is buried: {value:.2f}")

    def test_both_characters_are_reached(self) -> None:
        items = dressing_for("forest_path", W, H, STAGE.ground_y)
        fractions = measure_occlusion(W, H, items, self.actors)
        for actor in ("actor0", "actor1"):
            self.assertGreater(fractions[actor], 0.0, fractions)
            self.assertEqual(fractions[f"{actor}_head"], 0.0, "a face was covered: " + str(fractions))

    def test_no_dressing_means_no_occlusion(self) -> None:
        self.assertEqual(measure_occlusion(W, H, [], self.actors), {})

    def test_measurement_is_two_sided(self) -> None:
        """An object that shares a bounding box with a character but not its pixels must not count."""

        items = [set_dressing.Dressing(set_dressing.ROCK, W / 2.0, 40.0, H * 0.3, 3.0,
                                       Layer.FOREGROUND, base_y=H * 0.35)]
        fractions = measure_occlusion(W, H, items, self.actors)
        # The rock sits in the empty middle of the frame, above the cast's feet and below their
        # heads; a box comparison would call this overlap, a pixel comparison does not.
        self.assertTrue(all(value < 0.5 for value in fractions.values()), fractions)

    def test_an_object_at_the_frame_edge_occludes_nothing(self) -> None:
        items = [set_dressing.Dressing(set_dressing.BUSH, 8.0, 200.0, 200.0, 3.0,
                                       Layer.FOREGROUND, base_y=H - 20.0)]
        fractions = measure_occlusion(W, H, items, self.actors)
        for actor in ("actor0", "actor1"):
            self.assertLess(fractions[actor], 0.05, fractions)


class DepthModelTests(unittest.TestCase):
    """T45c: two keys - authored layer, then world depth inside it."""

    def test_foreground_draws_after_the_cast(self) -> None:
        queue = DrawQueue()
        queue.add(Layer.FOREGROUND, 0.0, lambda cr: None, name="bush")
        queue.add_actor(800.0, lambda cr: None, name="chiku")
        self.assertEqual([name for name, _, _ in queue.plan()], ["chiku", "bush"])

    def test_scenery_nearer_than_the_cast_draws_in_front_of_it(self) -> None:
        queue = DrawQueue()
        queue.add(Layer.ACTOR, 900.0, lambda cr: None, name="trunk_near")
        queue.add_actor(800.0, lambda cr: None, name="chiku")
        queue.add(Layer.ACTOR, 700.0, lambda cr: None, name="trunk_far")
        order = [name for name, _, _ in queue.plan()]
        self.assertLess(order.index("trunk_far"), order.index("chiku"))
        self.assertGreater(order.index("trunk_near"), order.index("chiku"))

    def test_a_held_prop_outranks_a_nearer_ground_prop(self) -> None:
        queue = DrawQueue()
        queue.add_prop(1200.0, lambda cr: None, held=False, name="cup_on_floor")
        queue.add_prop(100.0, lambda cr: None, held=True, name="key_in_hand")
        order = [name for name, _, _ in queue.plan()]
        self.assertLess(order.index("cup_on_floor"), order.index("key_in_hand"))

    def test_the_world_plane_is_the_actor_plane(self) -> None:
        self.assertEqual(int(Layer.WORLD), int(Layer.ACTOR))


if __name__ == "__main__":
    unittest.main()
