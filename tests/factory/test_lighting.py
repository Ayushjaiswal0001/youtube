"""Tests for lighting presets and directional shadows (T44)."""

from __future__ import annotations

import math
import unittest

from studio.animation.lighting import (DEFAULT_PRESET, PRESETS, LightingPreset, apply_grade,
                                      describe, draw_shadow, preset_for)

REQUIRED = ("daylight", "warm_afternoon", "sunset", "cool_evening", "indoor_warm")


class PresetTests(unittest.TestCase):
    def test_required_presets_exist(self) -> None:
        for name in REQUIRED:
            self.assertIn(name, PRESETS)

    def test_preset_values_are_sane(self) -> None:
        for name, preset in PRESETS.items():
            self.assertGreater(preset.elevation_deg, 0.0, name)
            self.assertLessEqual(preset.elevation_deg, 90.0, name)
            self.assertGreaterEqual(preset.ambient, 0.0, name)
            self.assertLessEqual(preset.ambient, 1.0, name)
            self.assertGreater(preset.shadow_opacity, 0.0, name)
            self.assertLessEqual(preset.shadow_opacity, 0.65, name)
            self.assertIn(preset.light_x, (-1.0, 1.0), name)

    def test_unknown_preset_falls_back_instead_of_failing(self) -> None:
        self.assertIs(preset_for("nonesuch"), DEFAULT_PRESET)
        self.assertIs(preset_for(None), DEFAULT_PRESET)

    def test_describe_is_machine_readable(self) -> None:
        info = describe(PRESETS["sunset"])
        self.assertEqual(info["name"], "sunset")
        self.assertIsInstance(info["elevation_deg"], float)


class ShadowGeometryTests(unittest.TestCase):
    def test_shadow_follows_the_light_direction(self) -> None:
        for name, preset in PRESETS.items():
            geom = preset.shadow_for(120.0, 80.0, 788.0)
            self.assertEqual(math.copysign(1.0, geom.offset_x), preset.light_x,
                             f"{name} shadow fell against the light")

    def test_a_standing_body_still_shows_contact(self) -> None:
        geom = PRESETS["daylight"].shadow_for(0.0, 80.0, 788.0)
        self.assertGreater(abs(geom.offset_x), 0.0)
        self.assertGreater(geom.opacity, 0.0)

    def test_jumping_lengthens_offsets_softens_and_fades_the_shadow(self) -> None:
        preset = PRESETS["warm_afternoon"]
        ground = preset.shadow_for(0.0, 80.0, 788.0)
        air = preset.shadow_for(180.0, 80.0, 788.0)
        self.assertGreater(abs(air.offset_x), abs(ground.offset_x))
        self.assertGreater(air.length, ground.length)
        self.assertGreater(air.softness, ground.softness)
        self.assertLess(air.opacity, ground.opacity)

    def test_a_lower_sun_casts_further(self) -> None:
        high = PRESETS["daylight"].shadow_for(150.0, 80.0, 788.0)
        low = PRESETS["sunset"].shadow_for(150.0, 80.0, 788.0)
        self.assertGreater(abs(low.offset_x), abs(high.offset_x))

    def test_opacity_is_always_clamped(self) -> None:
        """No preset may make a shadow so dark it reads as a hole in the floor."""

        for name, preset in PRESETS.items():
            for height in (0.0, 50.0, 500.0):
                self.assertLessEqual(preset.shadow_for(height, 80.0, 788.0).opacity, 0.65, name)

    def test_crouching_keeps_the_shadow_attached(self) -> None:
        preset = PRESETS["sunset"]
        geom = preset.shadow_for(0.0, 60.0, 788.0)
        self.assertLess(abs(geom.offset_x), 20.0)


class DrawTests(unittest.TestCase):
    def test_draw_shadow_returns_the_geometry_it_drew(self) -> None:
        import cairo
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        cr = cairo.Context(surface)
        preset = PRESETS["sunset"]
        geom = draw_shadow(cr, preset, x=100.0, ground_y=180.0, body_half_width=30.0,
                           height_above_ground=90.0)
        expected = preset.shadow_for(90.0, 30.0, 180.0)
        self.assertAlmostEqual(geom.offset_x, expected.offset_x, places=6)

    def test_grade_is_a_no_op_for_neutral_daylight(self) -> None:
        import cairo
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
        cr = cairo.Context(surface)
        cr.set_source_rgb(0.4, 0.5, 0.6)
        cr.paint()
        apply_grade(cr, PRESETS["daylight"], 8, 8)
        surface.flush()
        data = bytes(surface.get_data())
        # Compare whole pixels (BGRA), not byte values: within one pixel the channels differ.
        first = data[:4]
        self.assertTrue(all(data[i:i + 4] == first for i in range(0, 32, 4)))


if __name__ == "__main__":
    unittest.main()
