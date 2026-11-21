"""Landscape character pipeline tests (T41).

The parts that can be tested without rendering a whole episode: plan validation, the story packet,
overlay geometry, environment coverage, and the concat step that has to deliver a constant frame
rate. The last one is a regression test for a real defect - two scenes concatenated with a stream
copy delivered 29.93 fps because each scene's AAC tail pushed the next scene's video late.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import cairo
import numpy as np

from factory.config import load_channel_specs
from factory.media.landscape_stage import (
    BAND_BOTTOM,
    BAND_TOP,
    HEIGHT,
    WIDTH,
    _concat,
    build_script,
    build_story,
    caption_overlay,
    plan_scenes,
    title_overlay,
)
from studio.animation.environment import (
    HORIZON_Y,
    ForegroundLayer,
    LandscapeEnvironment,
)

SPEC = load_channel_specs()["natkhat-toons"]


def _plan(**overrides):
    plan = {
        "id": "test-stage",
        "title": "परीक्षण एपिसोड",
        "hook": "एक परीक्षण",
        "scenes": [
            {"n": 1, "speaker": "narrator", "line": "पहला दृश्य", "camera": "wide_establishing"},
            {"n": 2, "speaker": "chiku", "line": "दूसरा दृश्य", "prop": "brass_key"},
        ],
    }
    plan.update(overrides)
    return plan


def alpha(surface):
    width, height = surface.get_width(), surface.get_height()
    return np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(
        height, surface.get_stride() // 4, 4)[:, :width, 3]


class PlanTests(unittest.TestCase):
    def test_a_scene_without_a_line_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            plan_scenes(_plan(scenes=[{"n": 1, "line": "  "}]))
        self.assertIn("no line", str(ctx.exception))

    def test_a_plan_without_scenes_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_scenes(_plan(scenes=[]))

    def test_defaults_fill_in_so_a_plan_can_be_terse(self):
        scenes = plan_scenes(_plan())
        self.assertEqual(scenes[1]["speaker"], "chiku")
        self.assertEqual(scenes[1]["chiku_pose"], "idle")
        self.assertEqual(scenes[1]["camera"], "two_shot")
        self.assertEqual(scenes[1]["bg"], "haunted_haveli")

    def test_prop_and_interaction_keys_survive(self):
        scene = plan_scenes(_plan())[1]
        self.assertEqual(scene["prop"], "brass_key")

    def test_script_and_story_agree_with_the_plan(self):
        plan = _plan()
        script = build_script(SPEC, plan)
        story = build_story(SPEC, plan, script)
        self.assertEqual([line.text for line in script.lines],
                         [scene["dialogue"] for scene in story["scenes"]])
        self.assertEqual(script.format, "long")
        self.assertIn("render-stage", story["story_id"])
        self.assertEqual(story["total_scenes"], 2)


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stage-overlay-"))

    def tearDown(self):
        for path in self.tmp.glob("*"):
            path.unlink()
        self.tmp.rmdir()

    def test_the_caption_band_stays_in_the_caption_zone(self):
        from PIL import Image
        path = caption_overlay("एक छोटी सी पंक्ति", self.tmp / "sub.png")
        pixels = np.array(Image.open(path))
        opaque = pixels[:, :, 3] > 16
        ys = np.nonzero(opaque.any(axis=1))[0]
        self.assertLessEqual(ys.max(), int(HEIGHT * BAND_BOTTOM) + 1)
        self.assertGreaterEqual(ys.min(), int(HEIGHT * 0.70))

    def test_a_long_line_wraps_instead_of_overflowing(self):
        long_line = " ".join(["बहुत लंबी पंक्ति"] * 8)
        path = caption_overlay(long_line, self.tmp / "long.png")
        from PIL import Image
        pixels = np.array(Image.open(path))
        opaque = pixels[:, :, 3] > 16
        ys = np.nonzero(opaque.any(axis=1))[0]
        # Wrapping is what makes the band taller, not the text running off the right edge.
        self.assertLess(ys.min(), int(HEIGHT * BAND_TOP - 10))

    def test_the_title_card_clears_the_characters_heads(self):
        # Characters' heads sit around 0.28 of frame height on the landscape stage; a title card
        # that reaches 0.40 covered them (first stage render).
        path = title_overlay("हवेली की चाबी", self.tmp / "title.png")
        from PIL import Image
        pixels = np.array(Image.open(path))
        ys = np.nonzero((pixels[:, :, 3] > 16).any(axis=1))[0]
        self.assertLess(ys.max(), int(HEIGHT * 0.28))

    def test_overlays_are_frame_sized(self):
        from PIL import Image
        path = caption_overlay("पाठ", self.tmp / "sub.png")
        self.assertEqual(Image.open(path).size, (WIDTH, HEIGHT))


class EnvironmentTests(unittest.TestCase):
    def render(self, zoom, layer=None):
        target = layer or LandscapeEnvironment(WIDTH, HEIGHT, ground_y=788.0)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
        target.render_by_name("haunted_haveli", cairo.Context(surface), 1.0, 40.0, 20.0,
                              zoom=zoom)
        surface.flush()
        return surface

    def test_the_environment_covers_the_frame_at_every_zoom_the_stage_allows(self):
        for zoom in (0.62, 0.85, 1.0, 1.7, 2.2):
            coverage = alpha(self.render(zoom))
            self.assertEqual(int((coverage == 0).sum()), 0,
                             f"unpainted pixels at zoom {zoom}")

    def test_the_horizon_sits_where_the_stage_expects(self):
        # The floor has to be in shot: a horizon above the frame leaves no ground under the cast.
        self.assertGreater(HORIZON_Y, 0.0)
        self.assertLess(HORIZON_Y, HEIGHT * 0.6)

    def test_the_foreground_does_not_grow_into_the_caption_band(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
        layer = ForegroundLayer(WIDTH, HEIGHT, ground_y=788.0)
        layer.render_by_name("haunted_haveli", cairo.Context(surface), 1.0, 0.0, 0.0, zoom=1.0)
        surface.flush()
        coverage = alpha(surface)
        # The band is a centred rectangle, not a full-width row: foliage at the frame edges may
        # share its rows, but nothing may sit under the text itself.
        band = coverage[int(HEIGHT * BAND_TOP):int(HEIGHT * BAND_BOTTOM),
                        int(WIDTH * 0.12):int(WIDTH * 0.88)]
        self.assertEqual(int((band > 8).sum()), 0,
                         "foreground foliage is drawn behind the caption text")

    def test_shadows_are_offered_only_by_an_environment_with_a_floor(self):
        self.assertTrue(LandscapeEnvironment.casts_shadows)
        self.assertFalse(ForegroundLayer.casts_shadows)


class ConcatTests(unittest.TestCase):
    """A stream copy of two scenes delivered 29.93 fps. This is that defect, reproduced."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stage-concat-"))

    def tearDown(self):
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        self.tmp.rmdir()

    def scene(self, name: str, video: float, audio: float) -> Path:
        path = self.tmp / name
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=30:duration={video}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={audio}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-r", "30", "-fps_mode", "cfr", str(path),
        ], check=True)
        return path

    def probe(self, path: Path) -> dict:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate,start_time", "-of", "json", str(path)],
            capture_output=True, text=True, check=True)
        return json.loads(result.stdout)["streams"][0]

    def test_the_joined_episode_runs_at_a_constant_frame_rate(self):
        # Audio slightly longer than video: this is what a real scene looks like, and what made the
        # next scene start late.
        scenes = [self.scene("a.mp4", 1.0, 1.02), self.scene("b.mp4", 1.0, 1.02)]
        target = _concat(scenes, self.tmp / "joined.mp4")
        stream = self.probe(target)
        self.assertEqual(stream["avg_frame_rate"], "30/1")
        self.assertLess(abs(float(stream["start_time"])), 0.02)


if __name__ == "__main__":
    unittest.main()
