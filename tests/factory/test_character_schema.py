"""Character schema tests: validation, data-driven construction, render parity.

The render-parity tests are the important ones: `tests/factory/goldens/manifest.json`
holds SHA-256 hashes of frames produced by the *pre-schema* rigs. Any refactor that
changes a pixel of either character fails here.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cairo

from studio.characters.chiku import CHIKU_SCHEMA, ChikuRig
from studio.characters.gappu import GAPPU_SCHEMA, GappuRig
from studio.characters.lipsync import VisemeTrack
from studio.characters.rig_base import Viseme
from studio.characters.schema import (
    ARCHETYPES,
    REQUIRED_PALETTE,
    REQUIRED_PROPORTIONS,
    REQUIRED_TIMING,
    CharacterSchema,
    Proportions,
    SchemaError,
    load_schema,
)
from studio.characters.visemes import VisemeTimeline

GOLDENS = Path(__file__).resolve().parent / "goldens"

RENDER_CASES = [
    ("chiku", "idle", Viseme.SMILE, 0.0, 0.7),
    ("chiku", "excited_jump", Viseme.OPEN_WIDE, 0.42, 0.0),
    ("chiku", "shocked_freeze", Viseme.SURPRISED, 1.11, 0.3),
    ("chiku", "talking", Viseme.ROUND, 0.9, 1.0),
    ("gappu", "idle", Viseme.SMILE, 0.0, 0.7),
    ("gappu", "excited_jump", Viseme.OPEN_WIDE, 0.42, 0.0),
    ("gappu", "embarrassed_smile", Viseme.SMILE, 0.73, 0.5),
    ("gappu", "talking", Viseme.WIDE, 1.2, 1.0),
]


def render(name: str, pose: str, viseme: str, t: float, talking: float,
           schema: CharacterSchema | None = None) -> bytes:
    """Render one frame exactly the way the goldens were produced."""

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 700)
    context = cairo.Context(surface)
    context.set_source_rgb(0.12, 0.12, 0.16)
    context.paint()
    rig_class = ChikuRig if name == "chiku" else GappuRig
    rig = rig_class(x=350, y=620, scale=1.0, schema=schema)
    is_talking = talking > 0.5
    envelope = VisemeTrack(fps=30, openness=[0.8] * 120)
    timeline = VisemeTimeline(
        fps=30,
        shapes=[Viseme.WIDE] * 60 + [Viseme.OPEN_WIDE] * 60,
        scales=[0.4] * 60 + [0.9] * 60,
    )
    rig.update_pose(pose, t, is_talking=is_talking, phoneme_intensity=talking,
                    lipsync=envelope if is_talking else None,
                    timeline=timeline if is_talking else None)
    if not is_talking:
        rig.viseme = viseme
    rig.draw(context)
    surface.flush()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        path = Path(handle.name)
    surface.write_to_png(str(path))
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def base_dict(character_id: str = "chiku") -> dict:
    schema = load_schema(character_id)
    return {
        "schema_version": 1,
        "id": character_id,
        "display_name": "Test",
        "archetype": schema.archetype,
        "voice": "chiku",
        "anchor": dict(schema.anchor),
        "features": list(schema.features),
        "palette": {k: list(v) for k, v in schema.palette.items()},
        "proportions": dict(schema.proportions.values),
        "timing": {name: getattr(schema.timing, name) for name in REQUIRED_TIMING},
        "mouth": {
            "anchor_y": schema.mouth.anchor_y,
            "size": schema.mouth.size,
            "stroke_width": schema.mouth.stroke_width,
            "eye_pupil_range": [schema.mouth.pupil_x_range, schema.mouth.pupil_y_range],
        },
    }


class BundledSchemaTests(unittest.TestCase):
    def test_both_characters_load(self) -> None:
        for character_id in ("chiku", "gappu"):
            schema = load_schema(character_id)
            self.assertEqual(schema.character_id, character_id)
            self.assertIn(schema.archetype, ARCHETYPES)
            self.assertTrue(schema.display_name)
            self.assertTrue(schema.voice)

    def test_module_constants_come_from_the_schema(self) -> None:
        self.assertIs(ChikuRig().schema, CHIKU_SCHEMA)
        self.assertIs(GappuRig().schema, GAPPU_SCHEMA)

    def test_characters_actually_differ_in_data(self) -> None:
        chiku, gappu = load_schema("chiku"), load_schema("gappu")
        self.assertNotEqual(chiku.palette["fur"], gappu.palette["fur"])
        self.assertNotEqual(chiku.timing.blink_period, gappu.timing.blink_period)
        self.assertNotEqual(chiku.proportions.head_rx, gappu.proportions.head_rx)
        self.assertIn("vest", chiku.features)
        self.assertIn("spectacles", gappu.features)
        self.assertNotIn("spectacles", chiku.features)

    def test_timing_profile_drives_motion(self) -> None:
        chiku, gappu = load_schema("chiku"), load_schema("gappu")
        self.assertAlmostEqual(chiku.timing.blink(0.05), gappu.timing.blink(0.05) * 0 + chiku.timing.blink(0.05))
        # Chiku blinks on a 3.2 s cycle, Gappu on 4.0 s with a 1.2 s phase offset
        self.assertGreater(chiku.timing.blink(0.05), 0.5)
        self.assertEqual(gappu.timing.blink(0.05), 0.0)
        self.assertAlmostEqual(chiku.timing.breath(0.0), 0.0)
        self.assertAlmostEqual(gappu.timing.breath(0.0), 3.0 * 0.8414709848, places=5)

    def test_anchor_defaults(self) -> None:
        rig = ChikuRig()
        self.assertAlmostEqual(rig.x, CHIKU_SCHEMA.anchor["x"])
        self.assertAlmostEqual(rig.scale, CHIKU_SCHEMA.anchor["scale"])

    def test_explicit_arguments_still_win(self) -> None:
        rig = ChikuRig(x=380, y=1450, scale=1.35)
        self.assertEqual((rig.x, rig.y, rig.scale), (380, 1450, 1.35))
        self.assertEqual(rig.facing, 1.0)
        self.assertEqual(GappuRig().facing, -1.0)

    def test_scaled_proportions_do_not_mutate_source(self) -> None:
        props = CHIKU_SCHEMA.proportions
        bigger = props.scaled(2.0)
        self.assertAlmostEqual(bigger.head_rx, props.head_rx * 2)
        self.assertAlmostEqual(props.head_rx, 72.0)


class ValidationTests(unittest.TestCase):
    def assert_rejected(self, mutate, message: str) -> None:
        data = base_dict()
        mutate(data)
        with self.assertRaises(SchemaError) as context:
            CharacterSchema.from_dict(data, source="test")
        self.assertIn(message, str(context.exception))

    def test_missing_field(self) -> None:
        self.assert_rejected(lambda d: d.pop("palette"), "missing required field")

    def test_unknown_archetype(self) -> None:
        self.assert_rejected(lambda d: d.update(archetype="dragon"), "unknown archetype")

    def test_unsupported_version(self) -> None:
        self.assert_rejected(lambda d: d.update(schema_version=99), "unsupported schema_version")

    def test_missing_palette_colour(self) -> None:
        self.assert_rejected(lambda d: d["palette"].pop("outline"), "palette is missing 'outline'")

    def test_bad_colour_length(self) -> None:
        self.assert_rejected(lambda d: d["palette"].update(fur=[1.0, 0.5]), "must be [r, g, b]")

    def test_colour_out_of_range(self) -> None:
        self.assert_rejected(lambda d: d["palette"].update(fur=[1.4, 0.5, 0.2, 1.0]), "outside 0..1")

    def test_missing_proportion(self) -> None:
        self.assert_rejected(lambda d: d["proportions"].pop("head_rx"), "missing proportion")

    def test_non_numeric_proportion(self) -> None:
        self.assert_rejected(lambda d: d["proportions"].update(head_rx="big"), "must be a number")

    def test_missing_timing(self) -> None:
        self.assert_rejected(lambda d: d["timing"].pop("blink_period"), "missing timing field")

    def test_zero_blink_period(self) -> None:
        self.assert_rejected(lambda d: d["timing"].update(blink_period=0.0), "must be positive")

    def test_unknown_feature(self) -> None:
        self.assert_rejected(lambda d: d.update(features=["jetpack"]), "unknown feature")

    def test_bad_anchor(self) -> None:
        self.assert_rejected(lambda d: d["anchor"].pop("facing"), "anchor is missing 'facing'")
        self.assert_rejected(lambda d: d["anchor"].update(scale=0.0), "anchor.scale must be positive")

    def test_missing_file(self) -> None:
        with self.assertRaises(SchemaError):
            CharacterSchema.load("nobody", directory=Path(tempfile.gettempdir()))

    def test_unknown_character_lists_available(self) -> None:
        with self.assertRaises(SchemaError) as context:
            load_schema("does-not-exist")
        self.assertIn("available:", str(context.exception))

    def test_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{oops", encoding="utf-8")
            with self.assertRaises(SchemaError):
                CharacterSchema.from_file(path)

    def test_required_lists_are_covered_by_both_characters(self) -> None:
        for character_id in ("chiku", "gappu"):
            schema = load_schema(character_id)
            for name in REQUIRED_PALETTE:
                self.assertIn(name, schema.palette, character_id)
            for name in REQUIRED_PROPORTIONS:
                self.assertIn(name, schema.proportions.values, character_id)
            for name in REQUIRED_TIMING:
                self.assertIsInstance(getattr(schema.timing, name), float)


class RenderParityTests(unittest.TestCase):
    """The schema refactor must not move a single pixel."""

    @classmethod
    def setUpClass(cls) -> None:
        manifest_path = GOLDENS / "manifest.json"
        if not manifest_path.is_file():
            raise unittest.SkipTest("golden manifest missing")
        cls.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_golden_frames_are_reproduced(self) -> None:
        for name, pose, viseme, t, talking in RENDER_CASES:
            key = f"{name}_{pose}_{viseme}.png"
            data = render(name, pose, viseme, t, talking)
            digest = hashlib.sha256(data).hexdigest()[:16]
            self.assertEqual(digest, self.manifest[key], f"{key} changed")

    def test_rendered_frames_are_deterministic(self) -> None:
        first = render("chiku", "idle", Viseme.SMILE, 0.4, 0.7)
        second = render("chiku", "idle", Viseme.SMILE, 0.4, 0.7)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())


class DataDrivenCharacterTests(unittest.TestCase):
    """A new character must be creatable from data alone."""

    def test_recoloured_character_renders_and_differs(self) -> None:
        data = base_dict()
        data["id"] = "chiku-blue"
        data["palette"]["fur"] = [0.25, 0.35, 0.85, 1.0]
        data["palette"]["vest"] = [0.10, 0.55, 0.35, 1.0]
        data["proportions"]["head_rx"] = 88.0
        data["proportions"]["eye_rx"] = 20.0
        variant = CharacterSchema.from_dict(data, source="variant")

        original = render("chiku", "idle", Viseme.SMILE, 0.0, 0.7)
        recoloured = render("chiku", "idle", Viseme.SMILE, 0.0, 0.7, schema=variant)
        self.assertNotEqual(hashlib.sha256(original).hexdigest(),
                            hashlib.sha256(recoloured).hexdigest())

    def test_proportion_change_changes_geometry(self) -> None:
        data = base_dict()
        data["id"] = "chiku-tiny-head"
        data["proportions"]["head_rx"] = 40.0
        data["proportions"]["head_ry"] = 40.0
        small = CharacterSchema.from_dict(data, source="variant")
        self.assertNotEqual(hashlib.sha256(render("chiku", "idle", Viseme.SMILE, 0.0, 0.7)).hexdigest(),
                            hashlib.sha256(render("chiku", "idle", Viseme.SMILE, 0.0, 0.7, schema=small)).hexdigest())

    def test_mouth_config_is_honoured(self) -> None:
        data = base_dict()
        data["id"] = "chiku-big-mouth"
        data["mouth"]["anchor_y"] = 18.0
        data["mouth"]["size"] = 1.4
        big_mouth = CharacterSchema.from_dict(data, source="variant")
        self.assertNotEqual(hashlib.sha256(render("chiku", "talking", Viseme.OPEN_WIDE, 0.9, 1.0)).hexdigest(),
                            hashlib.sha256(render("chiku", "talking", Viseme.OPEN_WIDE, 0.9, 1.0, schema=big_mouth)).hexdigest())

    def test_schema_from_disk_roundtrip(self) -> None:
        data = base_dict("gappu")
        data["id"] = "temp-gappu"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "temp-gappu.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = CharacterSchema.from_file(path)
        self.assertEqual(loaded.character_id, "temp-gappu")
        self.assertEqual(loaded.archetype, "mouse")
        self.assertEqual(loaded.features, load_schema("gappu").features)


class LipSyncIntegrationTests(unittest.TestCase):
    """T31a/T31b must keep working through the schema-driven rigs."""

    def test_viseme_timeline_still_drives_the_mouth(self) -> None:
        timeline = VisemeTimeline(fps=30, shapes=[Viseme.ROUND] * 30,
                                  scales=[0.7] * 30)
        envelope = VisemeTrack(fps=30, openness=[0.9] * 30)
        for rig in (ChikuRig(), GappuRig()):
            rig.update_pose("idle", 0.5, is_talking=True, lipsync=envelope, timeline=timeline)
            self.assertEqual(rig.viseme, Viseme.ROUND)
            self.assertGreater(rig.mouth_open, 0.0)

    def test_silence_closes_the_mouth(self) -> None:
        timeline = VisemeTimeline(fps=30, shapes=[Viseme.OPEN_WIDE] * 30, scales=[0.9] * 30)
        envelope = VisemeTrack(fps=30, openness=[0.0] * 30)
        for rig in (ChikuRig(), GappuRig()):
            rig.update_pose("idle", 0.5, is_talking=True, lipsync=envelope, timeline=timeline)
            self.assertEqual(rig.viseme, Viseme.CLOSED)
            self.assertEqual(rig.mouth_open, 0.0)


if __name__ == "__main__":
    unittest.main()
