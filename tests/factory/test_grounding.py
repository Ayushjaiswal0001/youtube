"""Tests for measured ground placement (T45)."""

from __future__ import annotations

import unittest

from studio.animation.grounding import (clear_cache, ground_error, measure_foot_offset,
                                        place_on_ground)
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

STAGE = stage_for(1920, 1080)


class GroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def test_the_anchor_is_not_the_feet(self) -> None:
        """This is the defect the module exists for: anchors sit above the drawn boots."""

        for name, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
            rig = cls(**STAGE.anchor(name))
            self.assertGreater(measure_foot_offset(rig), 0.0, name)

    def test_place_on_ground_lands_the_feet_exactly(self) -> None:
        for name, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
            for ground in (788.0, 500.0, 1028.0):
                rig = cls(**STAGE.anchor(name))
                place_on_ground(rig, ground)
                self.assertAlmostEqual(ground_error(rig, ground), 0.0, places=6,
                                       msg=f"{name} at {ground}")

    def test_offset_is_cached_but_still_correct(self) -> None:
        rig = ChikuRig(**STAGE.anchor("chiku"))
        first = measure_foot_offset(rig)
        second = measure_foot_offset(rig)
        self.assertEqual(first, second)

    def test_offset_is_independent_of_starting_position(self) -> None:
        rig = ChikuRig(**STAGE.anchor("chiku"))
        before = measure_foot_offset(rig)
        rig.y = 123.0
        self.assertEqual(measure_foot_offset(rig), before)

    def test_rigs_have_distinct_offsets(self) -> None:
        chiku = ChikuRig(**STAGE.anchor("chiku"))
        gappu = GappuRig(**STAGE.anchor("gappu"))
        self.assertNotAlmostEqual(measure_foot_offset(chiku), measure_foot_offset(gappu))


if __name__ == "__main__":
    unittest.main()
