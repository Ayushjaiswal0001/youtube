"""T42b: cuts inside a dialogue line, and the camera support they need."""

from __future__ import annotations

import unittest

from studio.animation.camera import CameraDirector
from studio.animation.shot_plan import (
    MAX_CUTS_PER_LINE,
    MIN_CUT_GAP,
    line_cuts,
)

LONG_TURN = ("दरवाज़ा धीरे से खुला, और अंदर ठंडी हवा निकली।")
TURNING = "और या कि और या, और या कि और।"


class CameraCutTests(unittest.TestCase):
    def _director(self) -> CameraDirector:
        return CameraDirector("medium_pan", 6.0, (1920, 1080))

    def test_a_cut_changes_the_style(self) -> None:
        director = self._director()
        director.cut_to("two_shot_hold", 3.0)
        self.assertEqual(director.style, "two_shot_hold")
        self.assertEqual(director.cuts, [(3.0, "two_shot_hold")])

    def test_a_cut_restarts_the_move(self) -> None:
        director = self._director()
        before = director.state_at(3.0)
        director.cut_to("two_shot_hold", 3.0)
        after = director.state_at(3.0)
        self.assertNotEqual(round(before.zoom, 3), round(after.zoom, 3),
                            "the new shot opened at the old shot's zoom")

    def test_cutting_to_the_same_style_at_the_same_time_is_idempotent(self) -> None:
        director = self._director()
        director.cut_to("two_shot_hold", 3.0)
        director.cut_to("two_shot_hold", 3.0)
        self.assertEqual(len(director.cuts), 1)

    def test_an_unknown_style_does_not_change_the_shot(self) -> None:
        director = self._director()
        director.cut_to("not_a_style", 2.0)
        self.assertEqual(director.style, "medium_pan")

    def test_time_before_the_cut_is_clamped(self) -> None:
        director = self._director()
        director.cut_to("two_shot_hold", 3.0)
        self.assertGreaterEqual(director.state_at(3.0).zoom, 1.0)

    def test_the_move_before_a_cut_is_unchanged(self) -> None:
        director = self._director()
        plain = CameraDirector("medium_pan", 6.0, (1920, 1080))
        director.cut_to("two_shot_hold", 4.0)
        self.assertEqual(round(director.state_at(1.0).zoom, 6),
                         round(plain.state_at(1.0).zoom, 6))


class LineCutTests(unittest.TestCase):
    def test_a_short_line_gets_no_cut(self) -> None:
        self.assertEqual(line_cuts("हाँ।", 2.0, speaker="chiku"), [])

    def test_a_blank_line_gets_no_cut(self) -> None:
        self.assertEqual(line_cuts("", 8.0, speaker="chiku"), [])

    def test_a_long_line_with_a_turn_gets_a_cut(self) -> None:
        cuts = line_cuts(LONG_TURN, 6.0, speaker="chiku", listener="gappu")
        self.assertTrue(cuts)
        self.assertLess(cuts[0]["at"], 6.0)

    def test_cuts_are_never_closer_than_the_minimum_gap(self) -> None:
        cuts = line_cuts(TURNING, 8.0, speaker="chiku", listener="gappu")
        times = [cut["at"] for cut in cuts]
        for earlier, later in zip(times, times[1:]):
            self.assertGreaterEqual(later - earlier, MIN_CUT_GAP - 1e-9)

    def test_no_line_is_cut_into_a_montage(self) -> None:
        self.assertLessEqual(len(line_cuts(TURNING, 9.0, speaker="chiku", listener="gappu")),
                             MAX_CUTS_PER_LINE)

    def test_a_cut_targets_a_different_shot(self) -> None:
        cuts = line_cuts(LONG_TURN, 6.0, speaker="chiku", listener="gappu",
                         style="medium_pan")
        self.assertTrue(cuts)
        self.assertNotEqual(cuts[0]["camera"], "medium_pan",
                            "a cut that keeps the same style is invisible")

    def test_a_reaction_shot_is_used_for_a_question(self) -> None:
        line = "क्या तुमने वह आवाज़ सुनी है? और क्या तुम डर गए थे?"
        cuts = line_cuts(line, 7.0, speaker="chiku", listener="gappu")
        self.assertTrue(cuts)
        self.assertTrue(any(cut["camera"] == "close_up_gappu" for cut in cuts), cuts)

    def test_a_danda_alone_is_not_a_cut_signal(self) -> None:
        # Two sentences, no conjunction and no comma turn: this is a line, not a shot list.
        self.assertEqual(line_cuts("गप्पू यहाँ आओ। बहुत अंधेरा है।", 6.5, speaker="chiku",
                                   listener="gappu"), [])

    def test_cuts_stay_inside_the_line(self) -> None:
        for cut in line_cuts(LONG_TURN, 6.0, speaker="chiku", listener="gappu"):
            self.assertGreater(cut["at"], 0.0)
            self.assertLess(cut["at"], 6.0)


if __name__ == "__main__":
    unittest.main()
