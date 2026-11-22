"""Picking something up and giving it to someone, inside one scene.

The pickup worked and the hand-off worked, but only as separate beats. That left a hole: an episode
could lift a key and then cut to the other character already holding it, which is not a hand-off, it is
a continuity error with a pleasant name. This file tests the joined version - one scene, two characters,
one object, and a transfer that only happens when the two *drawn* hands are measurably together.
"""

from __future__ import annotations

import math

import pytest

from studio.animation.pickup_scene import PickupScene
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

STAGE = stage_for(1920, 1080)
GROUND = STAGE.ground_y


def rigs() -> dict:
    return {"chiku": ChikuRig(**STAGE.anchor("chiku")),
            "gappu": GappuRig(**STAGE.anchor("gappu"))}


def spec(**overrides) -> dict:
    base = {"object": "brass_key", "holder": "chiku", "offset": 46, "surface": "ground",
            "keep": True, "handoff_to": "gappu"}
    base.update(overrides)
    return base


def make(duration: float = 8.0, **overrides) -> PickupScene:
    return PickupScene(spec(**overrides), rigs(), duration, GROUND)


def run(scene: PickupScene, duration: float, step: float = 1 / 30) -> list[dict]:
    frames = []
    t = 0.0
    while t <= duration + 1e-9:
        frames.append(scene.update(t))
        t += step
    return frames


# ------------------------------------------------------------------ authoring mistakes fail loudly

def test_a_handoff_without_keep_is_rejected() -> None:
    with pytest.raises(ValueError) as caught:
        make(keep=False)
    assert "keep=true" in str(caught.value)


def test_a_handoff_to_self_is_rejected() -> None:
    with pytest.raises(ValueError):
        make(handoff_to="chiku")


def test_a_handoff_to_someone_not_in_the_scene_is_rejected() -> None:
    with pytest.raises(ValueError) as caught:
        make(handoff_to="ghost")
    assert "different character present" in str(caught.value)


# ------------------------------------------------------------------ the transfer is measured

def test_the_receiver_can_reach_the_meeting_point() -> None:
    scene = make()
    assert scene.report.handoff_reachable is True
    assert scene.transfer_point is not None
    assert scene.handoff_end > scene.handoff_start


def test_the_object_changes_hands_and_the_ledger_says_so() -> None:
    scene = make(duration=8.0)
    run(scene, 8.0)
    assert scene.report.transferred is True
    assert scene.ownership.holder_of("brass_key") == "gappu"
    actions = [change.action for change in scene.ownership.history]
    assert actions.count("transfer") == 1
    assert "claim" in actions


def test_the_two_hands_are_measurably_together_at_the_transfer() -> None:
    scene = make(duration=8.0)
    frames = run(scene, 8.0)
    handoff = [f for f in frames if f.get("handoff")]
    assert handoff, "the hand-off window produced no frames"
    smallest = min(f["handoff_gap"] for f in handoff)
    # Both hands are solved toward the same point, so the gap must be small - if this grows, the two
    # IK chains are being solved in different spaces and the 'transfer' is two mimes in a field.
    assert smallest < 18.0, smallest
    assert scene.report.handoff_contact_error == pytest.approx(smallest, abs=0.01)


def test_no_transfer_happens_before_the_window_opens() -> None:
    scene = make(duration=8.0)
    before = scene.handoff_start
    frames = run(scene, before - 0.1)
    assert scene.report.transferred is False
    assert scene.ownership.holder_of("brass_key") == "chiku"
    assert not any(f.get("handoff") for f in frames)


def test_the_giver_holds_the_object_through_the_whole_pickup() -> None:
    scene = make(duration=8.0)
    seen_grip = False
    t = 0.0
    while t <= 8.0:
        frame = scene.update(t)
        if frame.get("state") in {"GRIPPING", "HOLDING"}:
            seen_grip = True
        t += 1 / 30
    assert seen_grip
    assert scene.ownership.holder_of("brass_key") == "gappu"


def test_a_partner_who_cannot_reach_is_reported_not_hidden() -> None:
    """Move the partner far away: the meeting point stays geometrically valid but unreachable."""

    scene = make(duration=8.0)
    scene.partner.x = scene.rig.x + 9000
    scene._plan_handoff()
    assert scene.report.handoff_reachable is False
    assert scene.handoff_surface_gap > 100


def test_the_report_is_json_safe() -> None:
    import json

    scene = make(duration=8.0)
    run(scene, 8.0)
    payload = json.dumps(scene.as_dict())
    data = json.loads(payload)
    assert data["report"]["handoff_to"] == "gappu"
    assert data["report"]["transferred"] is True
    assert data["handoff"]["to"] == "gappu"
    assert data["ownership"]["objects"]["brass_key"]["holder"] == "gappu"


def test_release_restores_both_rigs() -> None:
    scene = make(duration=8.0)
    gappu = scene.partner
    original = gappu.torso.local_rot
    run(scene, 8.0)
    scene.release()
    assert getattr(gappu, "arm_l_ik", None) in (None, {})
    assert gappu.torso.local_rot == pytest.approx(original, abs=1e-6)


def test_the_handoff_window_fits_inside_the_scene() -> None:
    for duration in (4.0, 6.0, 8.0, 12.0):
        scene = make(duration=duration)
        assert 0.0 < scene.handoff_start < scene.handoff_end <= duration + 1e-9
        assert scene.handoff_start >= scene.stand_end


def test_a_short_scene_still_hands_off() -> None:
    """A three-second beat cannot afford the full window, but it must not silently drop the transfer."""

    scene = make(duration=3.0)
    run(scene, 3.0)
    assert scene.report.transferred is True


def test_the_giver_does_not_teleport_the_object_to_the_partner() -> None:
    scene = make(duration=8.0)
    frames = run(scene, 8.0)
    points = [f["point"] for f in frames if f.get("handoff")]
    assert len(points) > 1
    steps = [math.dist(a, b) for a, b in zip(points, points[1:])]
    assert max(steps) < 40.0, max(steps)


# ------------------------------------------------------------------ deliberately broken episodes

def _episode(*scenes: dict) -> list[dict]:
    base = {"speaker": "chiku", "line": "लाइन", "camera": "auto"}
    return [dict(base, **scene) for scene in scenes]


def test_a_handoff_to_an_unknown_character_is_an_error() -> None:
    """An interaction naming someone the episode does not have is an authoring error, not a warning."""

    from studio.animation.continuity import validate_episode

    report = validate_episode(_episode(
        {"n": 1, "pickup": {"object": "brass_key", "holder": "chiku", "keep": True}},
        # The supported authoring form for a cross-scene hand-off.
        {"n": 2, "prop": "brass_key", "prop_holder": "chiku", "prop_handoff_to": "ghost"},
    ))
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "unknown_character" in codes, codes


def test_two_scenes_cannot_both_pick_up_the_same_object() -> None:
    """A second claim on an object that is already held is a conflict, whether or not anyone noticed."""

    from studio.animation.continuity import validate_episode

    report = validate_episode(_episode(
        {"n": 1, "pickup": {"object": "brass_key", "holder": "chiku", "keep": True}},
        {"n": 2, "pickup": {"object": "brass_key", "holder": "gappu", "keep": True}},
    ))
    assert not report.ok, [i.as_dict() for i in report.issues]
    assert report.errors


def test_an_empty_episode_produces_no_false_alarms() -> None:
    from studio.animation.continuity import validate_episode

    report = validate_episode(_episode({"n": 1}, {"n": 2, "speaker": "gappu"}))
    assert report.ok, [i.as_dict() for i in report.errors]
