"""Text-to-viseme tests: shapes, timing, anti-flicker, and script coverage."""

from __future__ import annotations

import math
import unittest

import cairo

from studio.characters.lipsync import SILENCE_FLOOR, VisemeTrack
from studio.characters.mouth import draw_mouth
from studio.characters.rig_base import Viseme
from studio.characters.visemes import (
    DEFAULT_OPEN,
    MIN_HOLD_MS,
    VisemeTimeline,
    parse_units,
)

SHAPE_CHARS = {
    Viseme.CLOSED: "M",
    Viseme.NEUTRAL: "_",
    Viseme.SMILE: "u",
    Viseme.WIDE: "E",
    Viseme.TEETH: "F",
    Viseme.TONGUE: "L",
    Viseme.OPEN_SMALL: "e",
    Viseme.OPEN_WIDE: "A",
    Viseme.ROUND: "O",
    Viseme.SURPRISED: "!",
}


def shapes_of(text: str) -> list[str]:
    return [unit.shape for unit in parse_units(text)]


def chars_of(text: str) -> str:
    return "".join(SHAPE_CHARS.get(unit.shape, "?") for unit in parse_units(text))


class HindiMappingTests(unittest.TestCase):
    def test_bilabials_close_the_lips(self) -> None:
        for word in ("मम्मी", "पापा", "बाबा", "भाई"):
            units = parse_units(word)
            self.assertIn(Viseme.CLOSED, [unit.shape for unit in units], word)

    def test_open_vowels(self) -> None:
        self.assertIn(Viseme.OPEN_WIDE, shapes_of("आम"))
        self.assertIn(Viseme.OPEN_WIDE, shapes_of("राजा"))

    def test_wide_and_round_vowels(self) -> None:
        self.assertIn(Viseme.WIDE, shapes_of("ईख"))
        self.assertIn(Viseme.WIDE, shapes_of("बिल्ली"))
        self.assertIn(Viseme.ROUND, shapes_of("ऊन"))
        self.assertIn(Viseme.ROUND, shapes_of("मोर"))
        self.assertIn(Viseme.ROUND, shapes_of("चूहा"))

    def test_teeth_and_tongue(self) -> None:
        self.assertIn(Viseme.TEETH, shapes_of("फ़ल"))    # /f/ (nukta form)
        self.assertIn(Viseme.CLOSED, shapes_of("फल"))    # /pʰ/ is a bilabial — lips close
        self.assertIn(Viseme.TEETH, shapes_of("फ़ल"))  # decomposed nukta must behave the same
        self.assertIn(Viseme.TEETH, shapes_of("साबुन"))   # sibilant
        self.assertIn(Viseme.TONGUE, shapes_of("लड्डू"))  # lateral + retroflex
        self.assertIn(Viseme.TONGUE, shapes_of("तरबूज"))

    def test_shape_string_helper(self) -> None:
        self.assertEqual(chars_of("पापा"), "MAMA")

    def test_conjunct_and_word_final_schwa(self) -> None:
        # क् + ष is one unreleased cluster; final consonant loses its inherent 'a'
        units = parse_units("राक्षस")
        self.assertGreaterEqual(len(units), 4)
        self.assertNotEqual(units[-1].shape, Viseme.OPEN_SMALL)

    def test_punctuation_creates_a_pause(self) -> None:
        units = parse_units("रुको! फिर चलो।")
        pauses = [unit for unit in units if unit.kind == "pause"]
        self.assertEqual(len(pauses), 2)

    def test_difficult_hindi_word_does_not_crash(self) -> None:
        for word in ("क्षत्रिय", "श्रृंगार", "विद्यालय", "उत्तरप्रदेश", "अंतर्राष्ट्रीय", "ज़िम्मेदारी"):
            units = parse_units(word)
            self.assertTrue(units, word)
            self.assertTrue(all(unit.shape in DEFAULT_OPEN for unit in units), word)


class EnglishMappingTests(unittest.TestCase):
    def test_bilabials(self) -> None:
        for word in ("mama", "papa", "bomb", "baby"):
            self.assertIn(Viseme.CLOSED, [unit.shape for unit in parse_units(word)], word)

    def test_vowels(self) -> None:
        self.assertIn(Viseme.OPEN_WIDE, shapes_of("father"))
        self.assertIn(Viseme.WIDE, shapes_of("beep"))
        self.assertIn(Viseme.ROUND, shapes_of("food"))

    def test_digraphs(self) -> None:
        self.assertIn(Viseme.TEETH, shapes_of("phone"))
        self.assertIn(Viseme.TONGUE, shapes_of("think"))
        self.assertIn(Viseme.WIDE, shapes_of("shop"))

    def test_silent_final_e(self) -> None:
        long_units = parse_units("make")
        short_units = parse_units("mak")
        self.assertLessEqual(len(long_units), len(short_units) + 1)

    def test_mixed_hindi_english(self) -> None:
        text = "यह video बहुत अच्छा है, subscribe करो!"
        units = parse_units(text)
        shapes = {unit.shape for unit in units}
        self.assertTrue({Viseme.TEETH, Viseme.CLOSED} & shapes)   # Hindi + English consonants
        self.assertIn(Viseme.ROUND, shapes)                        # 'o' in video/subscribe
        self.assertTrue(any(unit.kind == "pause" for unit in units))


class TimingTests(unittest.TestCase):
    def test_covers_the_line_and_ends_near_duration(self) -> None:
        timeline = VisemeTimeline.from_text("आज हम एक नई कहानी सुनेंगे।", duration=4.0, fps=30)
        self.assertEqual(len(timeline), 120)
        self.assertNotEqual(timeline.shapes[-1], Viseme.CLOSED)

    def test_minimum_hold_time_is_respected(self) -> None:
        # rapid alternation forces sub-frame runs that must be merged
        timeline = VisemeTimeline.from_text("ma ma ma ma ma pa pa pa", duration=1.2, fps=30)
        min_frames = max(1, int(round(MIN_HOLD_MS / 1000 * 30)))
        runs = []
        index = 0
        while index < len(timeline.shapes):
            start = index
            while index < len(timeline.shapes) and timeline.shapes[index] == timeline.shapes[start]:
                index += 1
            runs.append(index - start)
        self.assertGreaterEqual(min(runs), min_frames, f"runs={runs}")

    def test_short_speech_runs_are_merged_even_next_to_silence(self) -> None:
        fps = 30
        openness = [0.9] * 10 + [0.0] * 5 + [0.9] * 3 + [0.0] * 12 + [0.9] * 30
        envelope = VisemeTrack(fps=fps, openness=openness)
        timeline = VisemeTimeline.from_text("मम मम मम आ आ आ", duration=2.0, fps=fps, envelope=envelope)
        runs: list[int] = []
        index = 0
        while index < len(timeline.shapes):
            start = index
            while index < len(timeline.shapes) and timeline.shapes[index] == timeline.shapes[start]:
                index += 1
            if timeline.shapes[start] != Viseme.CLOSED:
                runs.append(index - start)
        self.assertTrue(runs)
        self.assertGreaterEqual(min(runs), 2, f"speech runs={runs}")

    def test_change_rate_is_speech_like(self) -> None:
        for text, duration in (
            ("नमस्ते दोस्तों आज हम बहुत मज़ेदार कहानी देखेंगे", 6.0),
            ("Hello friends, today we learn something surprising", 6.0),
            ("यह video बहुत अच्छा है और मज़ेदार भी है", 5.0),
        ):
            rate = VisemeTimeline.from_text(text, duration=duration, fps=30).change_rate()
            self.assertGreater(rate, 1.5, text)
            self.assertLess(rate, 12.0, f"{text} flickering at {rate:.1f}/s")

    def test_silence_overrides_text(self) -> None:
        fps = 30
        openness = [0.0] * (fps * 2) + [0.8] * (fps * 2)
        envelope = VisemeTrack(fps=fps, openness=openness)
        timeline = VisemeTimeline.from_text("आ आ आ आ", duration=4.0, fps=fps, envelope=envelope)
        self.assertTrue(all(shape == Viseme.CLOSED for shape in timeline.shapes[: fps * 2]))
        self.assertTrue(any(timeline.scale_at(index / fps) > 0 for index in range(fps * 2, fps * 4)))

    def test_boundaries_are_used_when_plausible(self) -> None:
        boundaries = [
            {"text": "आज हम", "start": 0.0, "end": 1.0},
            {"text": "नई कहानी सुनेंगे", "start": 2.0, "end": 4.0},
        ]
        timeline = VisemeTimeline.from_text(
            "आज हम नई कहानी सुनेंगे", duration=4.2, fps=30, boundaries=boundaries
        )
        # the zero-weight gap between 1.0 s and 2.0 s must stay neutral, not smear a shape
        middle = [timeline.shape_at(t / 30) for t in range(int(1.1 * 30), int(1.9 * 30))]
        self.assertTrue(all(shape == Viseme.NEUTRAL for shape in middle), middle)

    def test_stale_boundaries_are_ignored(self) -> None:
        timeline = VisemeTimeline.from_text(
            "आज हम नई कहानी सुनेंगे", duration=4.0, fps=30,
            boundaries=[{"text": "unrelated cached line", "start": 0.0, "end": 3.9}],
        )
        self.assertGreater(timeline.change_rate(), 1.0)

    def test_empty_and_zero_duration(self) -> None:
        self.assertEqual(len(VisemeTimeline.from_text("", duration=3.0)), 0)
        self.assertEqual(len(VisemeTimeline.from_text("hello", duration=0.0)), 0)

    def test_deterministic(self) -> None:
        first = VisemeTimeline.from_text("मिश्रित text के साथ 123", duration=3.5, fps=30)
        second = VisemeTimeline.from_text("मिश्रित text के साथ 123", duration=3.5, fps=30)
        self.assertEqual(first.shapes, second.shapes)
        self.assertEqual(first.scales, second.scales)


class DrawingTests(unittest.TestCase):
    def test_every_shape_renders(self) -> None:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
        context = cairo.Context(surface)
        for shape in DEFAULT_OPEN:
            for openness in (0.0, 0.5, 1.0):
                draw_mouth(context, shape, openness, anchor_y=100, size=1.5)
        surface.write_to_png("/dev/null") if False else surface.flush()

    def test_shapes_are_visually_distinct(self) -> None:
        footprints = {}
        for shape in DEFAULT_OPEN:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 120)
            context = cairo.Context(surface)
            draw_mouth(context, shape, 0.6, anchor_y=60, size=1.4)
            surface.flush()
            data = surface.get_data()
            footprints[shape] = sum(1 for byte in data if byte)
        # closed lips and wide open vowels must not have the same ink footprint
        self.assertGreater(footprints[Viseme.OPEN_WIDE], footprints[Viseme.CLOSED])
        self.assertGreater(footprints[Viseme.WIDE], footprints[Viseme.CLOSED])
        self.assertNotEqual(footprints[Viseme.ROUND], footprints[Viseme.OPEN_WIDE])


class RigTimelineTests(unittest.TestCase):
    def test_rig_follows_timeline_shapes(self) -> None:
        from studio.characters.chiku import ChikuRig
        from studio.characters.gappu import GappuRig

        timeline = VisemeTimeline(fps=30, shapes=[Viseme.OPEN_WIDE] * 15 + [Viseme.ROUND] * 15,
                                  scales=[DEFAULT_OPEN[Viseme.OPEN_WIDE]] * 15 + [DEFAULT_OPEN[Viseme.ROUND]] * 15)
        envelope = VisemeTrack(fps=30, openness=[0.9] * 30)
        for rig in (ChikuRig(x=0, y=0), GappuRig(x=0, y=0)):
            rig.update_pose("idle", 0.1, is_talking=True, phoneme_intensity=1.0,
                            lipsync=envelope, timeline=timeline)
            self.assertEqual(rig.viseme, Viseme.OPEN_WIDE)
            self.assertGreater(rig.mouth_open, 0.5)
            rig.update_pose("idle", 0.8, is_talking=True, phoneme_intensity=1.0,
                            lipsync=envelope, timeline=timeline)
            self.assertEqual(rig.viseme, Viseme.ROUND)
            rig.update_pose("idle", 0.1, is_talking=False, lipsync=envelope, timeline=timeline)
            self.assertNotEqual(rig.viseme, Viseme.OPEN_WIDE)

    def test_silence_still_closes_the_mouth(self) -> None:
        from studio.characters.chiku import ChikuRig

        timeline = VisemeTimeline(fps=30, shapes=[Viseme.OPEN_WIDE] * 30,
                                  scales=[DEFAULT_OPEN[Viseme.OPEN_WIDE]] * 30)
        envelope = VisemeTrack(fps=30, openness=[0.0] * 30)
        rig = ChikuRig(x=0, y=0)
        rig.update_pose("idle", 0.5, is_talking=True, lipsync=envelope, timeline=timeline)
        self.assertEqual(rig.viseme, Viseme.CLOSED)
        self.assertEqual(rig.mouth_open, 0.0)


class BoundarySidecarTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        from studio.audio.tts_engine import TTSEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = TTSEngine(output_dir=_Path(tmp))
            audio = _Path(tmp) / "line_narrator.mp3"
            audio.write_bytes(b"x" * 2048)
            boundaries = [
                {"text": "पहला वाक्य", "start": 0.0, "end": 1.4},
                {"text": "दूसरा वाक्य", "start": 1.5, "end": 3.0},
            ]
            engine._save_boundaries(audio, "पहला वाक्य। दूसरा वाक्य।", 3.1, boundaries)
            self.assertTrue(engine._boundaries_path(audio).is_file())
            loaded = engine._load_boundaries(audio)
            self.assertEqual(loaded, boundaries)

    def test_corrupt_sidecar_is_ignored(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        from studio.audio.tts_engine import TTSEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = TTSEngine(output_dir=_Path(tmp))
            audio = _Path(tmp) / "line_narrator.mp3"
            audio.write_bytes(b"x" * 2048)
            engine._boundaries_path(audio).write_text("{not json", encoding="utf-8")
            self.assertIsNone(engine._load_boundaries(audio))


class LipSyncTrackRegressionTests(unittest.TestCase):
    """T31a behaviour must survive: envelope-only path still works."""

    def test_envelope_only_path(self) -> None:
        from studio.characters.chiku import ChikuRig

        envelope = VisemeTrack(fps=30, openness=[0.0] * 15 + [0.9] * 15)
        rig = ChikuRig(x=0, y=0)
        rig.update_pose("idle", 0.1, is_talking=True, lipsync=envelope)
        self.assertEqual(rig.mouth_open, 0.0)
        rig.update_pose("idle", 0.9, is_talking=True, lipsync=envelope)
        self.assertGreater(rig.mouth_open, 0.0)

    def test_deviation_never_nan(self) -> None:
        timeline = VisemeTimeline.from_text("क्ष त्र ज्ञ श्र", duration=2.0, fps=30)
        for index in range(len(timeline)):
            value = timeline.scale_at(index / 30)
            self.assertFalse(math.isnan(value))


if __name__ == "__main__":
    unittest.main()
