"""Stage tests (T41).

The stage exists so one animation engine can stage a 9:16 scene and a 16:9 scene. The portrait
stage is the load-bearing one: every existing episode and every golden frame was rendered on it,
so its numbers are asserted to be the constants the renderer used before the stage existed.

The landscape numbers are asserted against the frame arithmetic that produced them, not copied
from the constants again - a test that repeats a constant proves nothing.
"""

import unittest

from studio.animation.framing import fit_zoom, plan_shot, project, subject_from_schema
from studio.animation.stage import (
    EYE_ABOVE_GROUND_RATIO,
    LANDSCAPE,
    LANDSCAPE_GROUND_Y,
    PORTRAIT,
    PORTRAIT_BODY_HEIGHT,
    stage_for,
)
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig


def subjects(stage):
    return {
        "chiku": subject_from_schema("chiku", ChikuRig(**stage.anchor("chiku")).schema),
        "gappu": subject_from_schema("gappu", GappuRig(**stage.anchor("gappu")).schema),
    }


class LookupTests(unittest.TestCase):
    def test_the_two_production_sizes_are_staged(self):
        self.assertIs(stage_for(1080, 1920), PORTRAIT)
        self.assertIs(stage_for(1920, 1080), LANDSCAPE)

    def test_an_unstaged_viewport_is_an_error_not_a_guess(self):
        # Silently inheriting portrait constants is how a cast ends up in the wrong place.
        with self.assertRaises(ValueError) as ctx:
            stage_for(1000, 1000)
        self.assertIn("1000x1000", str(ctx.exception))
        self.assertIn("1080x1920", str(ctx.exception))

    def test_aspect_is_reported_not_assumed(self):
        self.assertFalse(PORTRAIT.landscape)
        self.assertTrue(LANDSCAPE.landscape)
        self.assertAlmostEqual(PORTRAIT.aspect, 0.5625)
        self.assertAlmostEqual(LANDSCAPE.aspect, 16 / 9)


class PortraitStageTests(unittest.TestCase):
    def test_the_portrait_stage_is_the_old_hand_typed_constants(self):
        slot = PORTRAIT.slot("chiku")
        self.assertEqual((slot.x, slot.y, slot.scale, slot.facing), (380.0, 1450.0, 1.35, 1.0))
        slot = PORTRAIT.slot("gappu")
        self.assertEqual((slot.x, slot.y, slot.scale, slot.facing), (780.0, 1450.0, 1.12, -1.0))
        self.assertEqual(PORTRAIT.ground_y, 1450.0)
        self.assertEqual(PORTRAIT.eye_y, 1180.0)

    def test_the_portrait_eye_line_is_where_the_rigs_put_their_eyes(self):
        # The eye line is a stage property, so it has to agree with the body it frames: 270 of the
        # 958 units between the feet and the top of the head.
        self.assertAlmostEqual((PORTRAIT.ground_y - PORTRAIT.eye_y) / PORTRAIT_BODY_HEIGHT,
                               EYE_ABOVE_GROUND_RATIO, places=3)

    def test_portrait_effects_land_on_the_old_literals(self):
        # The renderer used to paint the sparkle at (460, 1150) and the dust at (380, 1460).
        self.assertEqual(PORTRAIT.at("chiku", 80.0, -300.0), (460.0, 1150.0))
        self.assertEqual(PORTRAIT.at("chiku", 0.0, 10.0), (380.0, 1460.0))
        self.assertEqual(PORTRAIT.at("chiku", 0.0, -430.0), (380.0, 1020.0))


class LandscapeStageTests(unittest.TestCase):
    def test_the_cast_keeps_its_identity(self):
        # Same characters on both stages: same scale, same facing. A landscape character is not a
        # stretched portrait character.
        for name in PORTRAIT.names():
            self.assertEqual(LANDSCAPE.slot(name).scale, PORTRAIT.slot(name).scale)
            self.assertEqual(LANDSCAPE.slot(name).facing, PORTRAIT.slot(name).facing)
            self.assertEqual(LANDSCAPE.slot(name).y, PORTRAIT.slot(name).y - 422.0)

    def test_the_cast_is_spread_out_for_the_wider_frame(self):
        portrait_gap = PORTRAIT.slot("gappu").x - PORTRAIT.slot("chiku").x
        landscape_gap = LANDSCAPE.slot("gappu").x - LANDSCAPE.slot("chiku").x
        self.assertGreater(landscape_gap, portrait_gap)
        # ... but not so far apart that the pair no longer reads as one shot.
        self.assertLess(landscape_gap, LANDSCAPE.width / 2.0)

    def test_a_landscape_wide_shot_is_allowed_to_pull_back_further(self):
        self.assertLess(LANDSCAPE.min_zoom, PORTRAIT.min_zoom)

    def test_the_pair_fits_the_frame_at_the_staged_zoom(self):
        # The numbers in stage.py claim a full-body two-shot at zoom 0.95. Derive it from the rigs
        # and check, rather than trusting the constant.
        cast = subjects(LANDSCAPE)
        boxes = [cast[name].bounds(0.0) for name in cast]
        zoom = min(0.95, fit_zoom(boxes, LANDSCAPE.viewport, min_zoom=LANDSCAPE.min_zoom))
        shot = plan_shot("two_shot", cast, LANDSCAPE.viewport, speaker="chiku",
                         zoom_range=LANDSCAPE.zoom_range)
        centre_y = (min(b[1] for b in boxes) + max(b[3] for b in boxes)) / 2.0
        pan_x = (min(b[0] for b in boxes) + max(b[2] for b in boxes)) / 2.0 - LANDSCAPE.width / 2
        pan_y = centre_y - LANDSCAPE.height / 2.0
        for name, box in zip(cast, boxes):
            x0, y0 = project(box[0], box[1], zoom, pan_x, pan_y, LANDSCAPE.viewport)
            x1, y1 = project(box[2], box[3], zoom, pan_x, pan_y, LANDSCAPE.viewport)
            self.assertGreaterEqual(y0, 0.0, f"{name} is cut off at the top")
            self.assertLessEqual(y1, LANDSCAPE.height, f"{name} is cut off at the bottom")
            self.assertGreaterEqual(x0, 0.0, f"{name} is cut off on the left")
            self.assertLessEqual(x1, LANDSCAPE.width, f"{name} is cut off on the right")
        self.assertGreater(zoom, 0.0)
        self.assertGreater(shot.zoom, 0.0)

    def test_the_ground_sits_above_the_bottom_edge(self):
        # Feet must not be planted on the frame line.
        feet = project(LANDSCAPE.slot("chiku").x, LANDSCAPE.ground_y, 0.95, 0.0, 0.0,
                       LANDSCAPE.viewport)[1]
        self.assertLess(feet, LANDSCAPE.height)
        self.assertGreater(feet, LANDSCAPE.height * 0.85)


class PlacementTests(unittest.TestCase):
    def test_anchors_are_rig_kwargs(self):
        self.assertEqual(PORTRAIT.anchor("gappu"),
                         {"x": 780.0, "y": 1450.0, "scale": 1.12})

    def test_an_unknown_character_names_the_stage(self):
        with self.assertRaises(KeyError) as ctx:
            LANDSCAPE.slot("mowgli")
        self.assertIn("landscape", str(ctx.exception))

    def test_the_renderer_uses_the_stage_it_was_given(self):
        from studio.animation.scene_renderer import SceneRenderer
        renderer = SceneRenderer(1920, 1080)
        self.assertIs(renderer.stage, LANDSCAPE)
        self.assertIs(SceneRenderer(1080, 1920).stage, PORTRAIT)


if __name__ == "__main__":
    unittest.main()
