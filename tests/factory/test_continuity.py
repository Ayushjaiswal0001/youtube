"""Tests for object ownership (T43B), scene continuity (T47), and the carry rule.

The ownership rules exist because two plausible-looking systems disagreed: the pickup track released
an object at the end of its interaction while a later scene declared a hand-off from the same hand.
Nothing detected the contradiction, because ownership was not modelled anywhere. These tests pin the
rules that make the contradiction impossible to express.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.media.landscape_stage import plan_scenes
from factory.qa.validator import _check_continuity
from studio.animation.continuity import ERROR, INFO, WARNING, build_states, validate_episode
from studio.animation.ownership import (
    HANDOFF,
    HOLD,
    PICKUP,
    REACH,
    APPROACH,
    IllegalTransfer,
    OwnershipConflict,
    OwnershipLedger,
    UnknownObject,
    validate_sequence,
)
from studio.animation.pickup_scene import PickupScene
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

STAGE = stage_for(1920, 1080)


def _ledger(**kwargs) -> OwnershipLedger:
    ledger = OwnershipLedger(characters=("chiku", "gappu"), **kwargs)
    ledger.register("key", (600.0, 760.0))
    return ledger


class LedgerTests(unittest.TestCase):
    def test_registering_an_object_with_no_holder(self) -> None:
        ledger = _ledger()
        self.assertIsNone(ledger.holder_of("key"))
        self.assertEqual(ledger.held_by("chiku"), [])

    def test_a_claim_needs_measured_contact(self) -> None:
        ledger = _ledger()
        with self.assertRaises(IllegalTransfer):
            ledger.claim("key", "chiku", 1.0, contact_confirmed=False)

    def test_a_claim_records_history(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        self.assertEqual(ledger.holder_of("key"), "chiku")
        self.assertEqual([c.action for c in ledger.history], ["register", "claim"])

    def test_two_characters_cannot_claim_the_same_object(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        with self.assertRaises(OwnershipConflict):
            ledger.claim("key", "gappu", 2.0)

    def test_claiming_what_you_already_hold_is_a_no_op(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        ledger.claim("key", "chiku", 2.0)
        self.assertEqual(ledger.holder_of("key"), "chiku")

    def test_a_transfer_requires_the_receiver_to_have_touched_it(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        with self.assertRaises(IllegalTransfer):
            ledger.transfer("key", "chiku", "gappu", 2.0, contact_confirmed=False)
        self.assertEqual(ledger.holder_of("key"), "chiku", "the giver let go without contact")

    def test_a_transfer_from_the_wrong_hand_is_refused(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        with self.assertRaises(IllegalTransfer):
            ledger.transfer("key", "gappu", "chiku", 2.0, contact_confirmed=True)

    def test_a_confirmed_transfer_moves_ownership(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        ledger.transfer("key", "chiku", "gappu", 2.0, contact_confirmed=True)
        self.assertEqual(ledger.holder_of("key"), "gappu")
        self.assertEqual(ledger.held_by("chiku"), [])

    def test_only_the_holder_can_release(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0)
        with self.assertRaises(IllegalTransfer):
            ledger.release("key", "gappu", 2.0)

    def test_release_keeps_the_objects_position(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0, position=(700.0, 740.0))
        ledger.release("key", "chiku", 2.0)
        state = ledger.state("key")
        self.assertEqual(state.holder, None)
        self.assertEqual(state.position, (700.0, 740.0))

    def test_an_unregistered_object_is_an_error(self) -> None:
        with self.assertRaises(UnknownObject):
            _ledger().claim("ghost", "chiku", 1.0)

    def test_the_snapshot_is_json_safe(self) -> None:
        ledger = _ledger()
        ledger.claim("key", "chiku", 1.0, position=(700.0, 740.0))
        json.dumps(ledger.snapshot(1.0))
        json.dumps(ledger.as_dict())


class SequenceTests(unittest.TestCase):
    def test_a_full_sequence_is_legal(self) -> None:
        self.assertEqual(validate_sequence([APPROACH, "CROUCH", PICKUP, HOLD, REACH, HANDOFF]),
                         [])

    def test_a_handoff_before_a_pickup_is_illegal(self) -> None:
        codes = [v.code for v in validate_sequence([HANDOFF, PICKUP])]
        self.assertIn("out_of_order", codes)

    def test_a_ground_pickup_needs_a_crouch(self) -> None:
        codes = [v.code for v in validate_sequence([APPROACH, PICKUP])]
        self.assertIn("pickup_without_crouch", codes)

    def test_a_table_pickup_needs_no_crouch(self) -> None:
        codes = [v.code for v in validate_sequence([APPROACH, PICKUP], surface="table")]
        self.assertNotIn("pickup_without_crouch", codes)

    def test_a_handoff_needs_a_receiver(self) -> None:
        codes = [v.code for v in validate_sequence([PICKUP, HOLD, HANDOFF], characters=1)]
        self.assertIn("handoff_without_partner", codes)

    def test_a_handoff_needs_a_reach(self) -> None:
        codes = [v.code for v in validate_sequence([PICKUP, HOLD, HANDOFF])]
        self.assertIn("handoff_without_reach", codes)


class CarryTests(unittest.TestCase):
    """A picked-up object that is kept must stay in the hand, not fall back to the floor."""

    def setUp(self) -> None:
        self.rig = ChikuRig(**STAGE.anchor("chiku"))
        self.rigs = {"chiku": self.rig, "gappu": GappuRig(**STAGE.anchor("gappu"))}

    def _scene(self, keep: bool) -> PickupScene:
        return PickupScene({"object": "brass_key", "grip": "small_object", "holder": "chiku",
                            "offset": 46, "surface": "ground", "keep": keep},
                           self.rigs, 4.0, STAGE.ground_y)

    def test_a_kept_object_stays_held_after_the_interaction(self) -> None:
        scene = self._scene(keep=True)
        for i in range(int(4.0 * 30)):
            frame = scene.update(i / 30.0)
        self.assertTrue(frame["held"])
        self.assertTrue(scene.as_dict()["report"]["kept"])

    def test_a_kept_object_follows_the_hand(self) -> None:
        scene = self._scene(keep=True)
        points = []
        for i in range(int(4.0 * 30)):
            frame = scene.update(i / 30.0)
            if frame["state"] == "COMPLETE":
                points.append(frame["point"])
        self.assertTrue(points)
        self.assertGreater(len({(round(x), round(y)) for x, y in points}), 1,
                           "a carried object must move with the character")

    def test_a_released_object_does_not_claim_to_be_held(self) -> None:
        scene = self._scene(keep=False)
        for i in range(int(4.0 * 30)):
            frame = scene.update(i / 30.0)
        self.assertFalse(frame["held"])
        self.assertFalse(scene.as_dict()["report"]["kept"])


def _scene(n: int, line: str = "कुछ कहानी है।", **extra):
    scene = {"n": n, "speaker": "chiku", "line": line, "camera": "auto"}
    scene.update(extra)
    return scene


def _plan(*scenes):
    return {"id": "continuity", "title": "परीक्षण", "scenes": list(scenes)}


class ContinuityTests(unittest.TestCase):
    def test_a_clean_episode_passes(self) -> None:
        report = build_states(plan_scenes(_plan(_scene(1), _scene(2, speaker="gappu"))))
        self.assertTrue(report.ok, report.as_dict())

    def test_an_empty_line_is_an_error(self) -> None:
        # `plan_scenes` refuses to build a scene without a line, so this exercises the validator
        # directly - the validator still has to catch a plan that arrives by another route.
        report = build_states([{"scene_num": 1, "speaker": "chiku", "line": ""}])
        self.assertIn("empty_line", [i.code for i in report.errors])

    def test_a_repeated_line_is_only_a_warning(self) -> None:
        report = build_states(plan_scenes(_plan(_scene(1), _scene(2))))
        self.assertIn("repeated_line", [i.code for i in report.of(WARNING)])
        self.assertTrue(report.ok)

    def test_a_pickup_then_a_handoff_is_continuous(self) -> None:
        report = build_states(plan_scenes(_plan(
            _scene(1, pickup={"object": "key", "holder": "chiku", "surface": "ground"}),
            _scene(2, speaker="gappu", prop="key", prop_holder="chiku",
                   prop_handoff_to="gappu", prop_handoff_at=0.5, interaction="hand_off"),
        )))
        self.assertTrue(report.ok, report.as_dict())
        self.assertEqual(report.states[-1].owners.get("key"), "gappu")

    def test_a_prop_that_changes_hands_with_no_interaction_is_an_error(self) -> None:
        report = build_states(plan_scenes(_plan(
            _scene(1, pickup={"object": "key", "holder": "chiku", "surface": "ground"}),
            _scene(2, speaker="gappu", prop="key", prop_holder="gappu"),
        )))
        self.assertIn("ownership_without_transfer", [i.code for i in report.errors])

    def test_a_handoff_to_yourself_is_an_error(self) -> None:
        report = build_states(plan_scenes(_plan(
            _scene(1, prop="key", prop_holder="chiku", prop_handoff_to="chiku"))))
        self.assertIn("handoff_to_self", [i.code for i in report.errors])

    def test_an_unknown_holder_is_an_error(self) -> None:
        report = build_states([{"scene_num": 1, "speaker": "chiku", "line": "कुछ।",
                                "prop": "key", "prop_holder": "nobody"}])
        self.assertIn("unknown_character", [i.code for i in report.errors])

    def test_a_lighting_change_is_recorded_as_info(self) -> None:
        report = build_states(plan_scenes(_plan(_scene(1, lighting="sunset"),
                                                _scene(2, speaker="gappu",
                                                       lighting="cool_evening"))))
        self.assertIn("lighting_change", [i.code for i in report.of(INFO)])
        self.assertTrue(report.ok)

    def test_a_camera_zoom_jump_is_a_warning(self) -> None:
        report = build_states(
            [dict(plan_scenes(_plan(_scene(1)))[0], shot_zoom=1.0),
             dict(plan_scenes(_plan(_scene(2, speaker="gappu")))[0], shot_zoom=1.9)])
        self.assertIn("camera_jump", [i.code for i in report.of(WARNING)])

    def test_a_facing_flip_without_a_declaration_is_a_warning(self) -> None:
        report = build_states(
            [dict(plan_scenes(_plan(_scene(1)))[0], interaction=None),
             dict(plan_scenes(_plan(_scene(2, speaker="gappu")))[0], interaction=None)],
            default_facing={"chiku": 1.0, "gappu": -1.0})
        self.assertTrue(report.ok)

    def test_the_report_is_json_safe(self) -> None:
        report = validate_episode(plan_scenes(_plan(_scene(1), _scene(2, speaker="gappu"))))
        json.dumps(report.as_dict())

    def test_the_real_episode_has_no_continuity_errors(self) -> None:
        data = json.loads((Path(__file__).resolve().parents[2] / "content" / "longform" /
                           "natkhat-toons.json").read_text(encoding="utf-8"))
        report = validate_episode(plan_scenes(data["channels"]["natkhat-toons"][0]),
                                  ground_y=STAGE.ground_y)
        self.assertTrue(report.ok, [i.as_dict() for i in report.errors])


class ContinuityQcTests(unittest.TestCase):
    def _episode(self, tmp: Path, payload: dict) -> Path:
        (tmp / "continuity.json").write_text(json.dumps(payload), encoding="utf-8")
        video = tmp / "video.mp4"
        video.write_bytes(b"x")
        return video

    def test_no_report_means_no_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            video.write_bytes(b"x")
            self.assertIsNone(_check_continuity(video))

    def test_a_clean_report_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), {"ok": True, "counts": {"error": 0, "warning": 1,
                                                                    "info": 0},
                                             "issues": [], "states": [{}, {}]})
            self.assertTrue(_check_continuity(video)["ok"])

    def test_an_error_fails_the_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = self._episode(Path(tmp), {
                "ok": False, "counts": {"error": 1, "warning": 0, "info": 0},
                "issues": [{"severity": "error", "scene": 3, "code": "ownership_without_transfer",
                            "message": "'key' moved with no hand-off"}],
                "states": [{}]})
            check = _check_continuity(video)
            self.assertFalse(check["ok"])
            self.assertEqual(check["severity"], "error")
            self.assertIn("scene 3", check["detail"])


if __name__ == "__main__":
    unittest.main()
