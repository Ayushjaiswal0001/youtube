"""Native 16:9 long-form renderer tests.

These exercise the composition profile without ffmpeg: frame drawing, chapter
resolution, caption chunking and the long-form script contract.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from factory.config import load_channel_specs
from factory.content.models import ScriptLine, WordTiming
from factory.content.script import build_english_script, load_plans_for
from factory.media.landscape_renderer import (
    CAPTION_TOP,
    HEIGHT,
    PANEL_BOTTOM,
    WIDTH,
    _active_chunk,
    _base,
    _chapter_map,
    _chunks,
    _draw_frame,
    get_profile,
)


def _long_plan():
    spec = replace(load_channel_specs()["nexus-node"], format="long")
    plans = [plan for plan in load_plans_for(spec) if plan.get("format") == "long"]
    if not plans:
        raise unittest.SkipTest("no long-form plan in content/longform")
    return spec, plans[0]


class GeometryTests(unittest.TestCase):
    def test_profile_is_1080p_landscape(self) -> None:
        spec, _ = _long_plan()
        profile = get_profile(spec)
        self.assertEqual((profile.width, profile.height), (1920, 1080))
        self.assertEqual((WIDTH, HEIGHT), (1920, 1080))

    def test_caption_band_sits_below_the_text_panel(self) -> None:
        self.assertGreater(CAPTION_TOP, PANEL_BOTTOM)
        self.assertLess(CAPTION_TOP, HEIGHT)

    def test_base_canvas_matches_profile(self) -> None:
        spec, _ = _long_plan()
        profile = get_profile(spec)
        base = _base(profile, spec)
        self.assertEqual(base.size, (profile.width, profile.height))


class ChapterTests(unittest.TestCase):
    def _script(self):
        spec, plan = _long_plan()
        return spec, build_english_script(spec, plan)

    def test_every_line_resolves_to_a_chapter(self) -> None:
        spec, script = self._script()
        mapping, marks, starts = _chapter_map(script, script.lines)
        self.assertTrue(starts, "plan chapters should produce start markers")
        first_start = min(starts)
        for index in range(first_start, len(script.lines)):
            self.assertIn(index, mapping, f"line {index} has no chapter")
        # the hook precedes chapter one and is intentionally unmapped
        self.assertNotIn(min(range(len(script.lines))), mapping) if first_start > 0 else None
        self.assertEqual(len(marks), len(starts))
        self.assertEqual(sorted(starts), sorted({int(ch["line"]) for ch in script.metadata["chapters"]}))

    def test_chapter_is_forward_filled_not_only_at_its_start(self) -> None:
        spec, script = self._script()
        mapping, _marks, starts = _chapter_map(script, script.lines)
        first_start = min(starts)
        numbers = [mapping[index][0] for index in range(first_start, len(script.lines))]
        self.assertEqual(numbers, sorted(numbers), "chapter numbers must not go backwards")
        self.assertGreaterEqual(len(set(numbers)), 2)

    def test_script_without_chapters_yields_no_starts(self) -> None:
        spec = replace(load_channel_specs()["nexus-node"], format="long")
        script = ScriptLine.__new__(ScriptLine)  # placeholder to keep import used
        self.assertIsNotNone(script)
        mapping, marks, starts = _chapter_map(_ShamScript(), [_line("x", 0.0, 1.0)])
        self.assertEqual((mapping, marks, starts), ({}, [], set()))


class _ShamScript:
    metadata: dict = {}


def _line(text: str, start: float, end: float, words: list[tuple[str, float, float]] | None = None) -> ScriptLine:
    timings = [WordTiming(word, s, e) for word, s, e in (words or [])]
    return ScriptLine(text=text, headline="H", start=start, end=end, words=timings)


class CaptionChunkTests(unittest.TestCase):
    def test_chunks_group_words_into_fours(self) -> None:
        words = [(f"w{i}", i * 0.2, (i + 1) * 0.2) for i in range(9)]
        chunks = _chunks(_line(" ".join(word for word, _, _ in words), 0.0, 1.8, words))
        self.assertEqual([len(chunk["words"]) for chunk in chunks], [4, 4, 1])
        self.assertEqual(chunks[0]["start"], 0.0)
        self.assertAlmostEqual(chunks[-1]["end"], 1.8)

    def test_chunks_fall_back_to_even_spacing_without_word_timings(self) -> None:
        chunks = _chunks(_line("one two three four five", 2.0, 3.0))
        self.assertGreaterEqual(chunks[0]["start"], 2.0)
        self.assertLessEqual(chunks[-1]["end"], 3.5)

    def test_active_chunk_tracks_time(self) -> None:
        words = [("alpha", 0.0, 0.4), ("beta", 0.4, 0.8)]
        chunks = _chunks(_line("alpha beta", 0.0, 0.8, words))
        self.assertIsNotNone(_active_chunk(chunks, 0.1))
        self.assertIsNone(_active_chunk(chunks, 5.0))


class LongFormScriptTests(unittest.TestCase):
    def test_long_plan_satisfies_long_form_budget(self) -> None:
        spec, plan = _long_plan()
        script = build_english_script(spec, plan)
        self.assertGreaterEqual(script.metadata["word_count"], 300)
        self.assertGreaterEqual(len(script.metadata["chapters"]), 3)
        self.assertEqual(script.format, "long")

    def test_short_form_limits_still_apply_to_vertical_spec(self) -> None:
        shorts = load_channel_specs()["nexus-node"]
        plan = load_plans_for(shorts)[0]
        script = build_english_script(shorts, plan)
        self.assertLessEqual(script.metadata["word_count"], 140)
        self.assertEqual(script.metadata["chapters"], [])

    def test_plan_too_short_for_long_form_is_rejected(self) -> None:
        spec, plan = _long_plan()
        trimmed = {**plan, "beats": plan["beats"][:1]}
        with self.assertRaises(ValueError):
            build_english_script(spec, trimmed)


class FrameRenderTests(unittest.TestCase):
    def test_frame_draws_at_1080p_with_chapter_card(self) -> None:
        spec, plan = _long_plan()
        script = build_english_script(spec, plan)
        t = 0.0
        for line in script.lines:
            words = [word for word in line.text.split() if word]
            step = 0.2
            line.words = [WordTiming(word, t + i * step, t + (i + 1) * step) for i, word in enumerate(words)]
            line.start, line.end = t, t + len(words) * step
            t = line.end + 0.2

        profile = get_profile(spec)
        base = _base(profile, spec)
        mapping, marks, starts = _chapter_map(script, script.lines)
        brand = ("NEXUS NODE", "SYSTEM BRIEF", "@nexusnode012")

        card = _draw_frame(base, script.lines[1], script.lines[1].start, t, 1, len(script.lines), spec, brand, marks, mapping, starts)
        self.assertEqual(card.size, (1920, 1080))
        self.assertIn(card.mode, {"RGB", "RGBA"})

        content = _draw_frame(
            base, script.lines[1], script.lines[1].start + 2.0, t, 1, len(script.lines), spec, brand, marks, mapping, starts
        )
        self.assertEqual(content.size, (1920, 1080))
        self.assertNotEqual(
            card.convert("RGB").getpixel((card.width // 2, card.height // 3)),
            content.convert("RGB").getpixel((content.width // 2, content.height // 3)),
        )


if __name__ == "__main__":
    unittest.main()
