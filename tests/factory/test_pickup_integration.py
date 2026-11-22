"""Tests for the pickup-in-production wiring (T43 integration).

The interrupted milestone left the renderer able to *construct* a pickup but not able to keep it: the
plan normaliser dropped the ``pickup`` key, the object was missing from the planned framing, its
report never reached episode QC, and the released object teleported back to where it was found. These
tests pin all four, because each failure was silent - the render succeeded and looked plausible.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from factory.media.landscape_stage import plan_scenes, scene_signature
from factory.qa.validator import _check_pickup
from studio.animation.pickup_scene import PickupScene
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.pickup import PickupState

STAGE = stage_for(1920, 1080)
PICKUP = {"object": "brass_key", "grip": "small_object", "holder": "chiku", "offset": 46,
          "surface": "ground"}


def _plan(**scene_extra):
    scene = {"n": 1, "speaker": "chiku", "line": "यह टूटी खिड़की की सीटी है।", "camera": "auto"}
    scene.update(scene_extra)
    return {"id": "pickup-plan", "title": "परीक्षण", "scenes": [scene]}


class PlanNormalisationTests(unittest.TestCase):
    def test_a_pickup_survives_plan_normalisation(self) -> None:
        scene = plan_scenes(_plan(pickup=PICKUP))[0]
        self.assertEqual(scene["pickup"], PICKUP)

    def test_lighting_survives_plan_normalisation(self) -> None:
        self.assertEqual(plan_scenes(_plan(lighting="sunset"))[0]["lighting"], "sunset")

    def test_a_pickup_changes_the_scene_signature(self) -> None:
        scene = plan_scenes(_plan())[0]
        plain = scene_signature(scene, 0.0, 0.0, stage_signature="s", audio_digest="a")
        with_pickup = scene_signature(dict(scene, pickup=PICKUP), 0.0, 0.0,
                                      stage_signature="s", audio_digest="a")
        self.assertNotEqual(plain, with_pickup,
                            "a cached scene would be reused after a pickup was authored")

    def test_lighting_changes_the_scene_signature(self) -> None:
        scene = plan_scenes(_plan())[0]
        plain = scene_signature(scene, 0.0, 0.0, stage_signature="s", audio_digest="a")
        lit = scene_signature(dict(scene, lighting="sunset"), 0.0, 0.0,
                              stage_signature="s", audio_digest="a")
        self.assertNotEqual(plain, lit)


class PickupSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rig = ChikuRig(**STAGE.anchor("chiku"))
        self.rigs = {"chiku": self.rig, "gappu": GappuRig(**STAGE.anchor("gappu"))}

    def _scene(self, **overrides):
        spec = dict(PICKUP, **overrides)
        return PickupScene(spec, self.rigs, 4.0, STAGE.ground_y)

    def test_ground_pickup_reaches_contact(self) -> None:
        scene = self._scene()
        errors = []
        for i in range(int(4.0 * 30)):
            frame = scene.update(i / 30.0)
            errors.append(frame["error"])
        self.assertLess(min(errors), 0.0, "the wrist never entered the object")
        self.assertIn(PickupState.COMPLETE.value, scene.report.states)

    def test_a_released_object_stays_where_it_was_put_down(self) -> None:
        scene = self._scene()
        frames = [scene.update(i / 30.0) for i in range(int(4.0 * 30))]
        placed = [frame["point"] for frame in frames
                  if frame["state"] == PickupState.COMPLETE.value]
        self.assertTrue(placed, "the pickup never completed")
        # The bug this pins: at COMPLETE the point used to snap back to the object's original
        # centre, which is a visible teleport and contradicts the story beat.
        self.assertGreater(
            abs(placed[-1][1] - scene.obj.centre[1]), 1.0,
            "released object returned to its original position")

    def test_contact_is_measured_not_assumed(self) -> None:
        scene = self._scene()
        for i in range(int(4.0 * 30)):
            scene.update(i / 30.0)
        # The report must never claim a grip while the drawn wrist was outside the object.
        self.assertEqual(scene.report.claimed_contact_without_touch, 0)
        self.assertIsNotNone(scene.report.as_dict()["min_contact_error"])

    def test_finishing_restores_the_rig_for_the_next_scene(self) -> None:
        scene = self._scene()
        for i in range(int(4.0 * 30)):
            scene.update(i / 30.0)
        self.assertAlmostEqual(self.rig.torso.local_rot, scene.entry_pose.bend, places=6)
        self.assertAlmostEqual(self.rig.squash, scene.entry_pose.squash, places=6)
        self.assertIsNone(self.rig.arm_r_ik, "IK stayed attached to the rig")

    def test_an_unknown_surface_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._scene(surface="ceiling")

    def test_a_fractional_table_height_is_rejected(self) -> None:
        """Authored as a fraction instead of a world y - caught by the physical range check."""

        with self.assertRaises(ValueError) as ctx:
            PickupScene({"object": "brass_key", "surface": "table"}, self.rigs, 4.0,
                        STAGE.ground_y, table_height=0.62)
        self.assertIn("absolute world y", str(ctx.exception))

    def test_a_table_above_the_shoulder_is_rejected(self) -> None:
        """Reaching up is a different action from picking up; this rig cannot do it."""

        with self.assertRaises(ValueError):
            PickupScene({"object": "brass_key", "surface": "table"}, self.rigs, 4.0,
                        STAGE.ground_y, table_height=STAGE.ground_y - 400.0)

    def test_a_table_at_a_real_height_is_reachable(self) -> None:
        shoulder = self.rigs["chiku"].y
        scene = PickupScene({"object": "brass_key", "surface": "table"}, self.rigs, 4.0,
                            STAGE.ground_y, table_height=STAGE.ground_y - 180.0)
        self.assertEqual(scene.surface, "table")
        self.assertLess(scene.obj.centre[1], shoulder)

    def test_the_report_is_json_safe(self) -> None:
        scene = self._scene()
        for i in range(60):
            scene.update(i / 30.0)
        json.dumps(scene.as_dict())


class PickupQcTests(unittest.TestCase):
    def _episode(self, tmp: Path, scenes: list) -> Path:
        (tmp / "framing.json").write_text(json.dumps({"scenes": scenes}), encoding="utf-8")
        video = tmp / "video.mp4"
        video.write_bytes(b"x")
        return video

    def test_no_pickup_means_no_check(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), [{"scene": 1}])
            self.assertIsNone(_check_pickup(video))

    def test_a_clean_pickup_passes(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), [{"scene": 1, "pickup": {"report": {
                "claimed_contact_without_touch": 0, "min_contact_error": -12.0,
                "reachable": True}}}])
            check = _check_pickup(video)
            self.assertTrue(check["ok"], check)

    def test_contact_claimed_without_touching_fails_the_gate(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), [{"scene": 1, "pickup": {"report": {
                "claimed_contact_without_touch": 9, "min_contact_error": 40.0,
                "reachable": True}}}])
            check = _check_pickup(video)
            self.assertFalse(check["ok"])
            self.assertEqual(check["severity"], "error")

    def test_an_out_of_reach_pickup_fails_the_gate(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), [{"scene": 1, "pickup": {"report": {
                "claimed_contact_without_touch": 0, "min_contact_error": 120.0,
                "reachable": False}}}])
            self.assertFalse(_check_pickup(video)["ok"])


if __name__ == "__main__":
    unittest.main()
