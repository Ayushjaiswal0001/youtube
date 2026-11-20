"""Gaze, saccade, blink and eye-expression tests (T32).

The point of these tests is behaviour, not coverage: blinks must not be a metronome, eyes
must actually look at things, distinctive emotions must produce distinctive eye poses, and
the renderer must draw every expression without falling over.
"""

from __future__ import annotations

import json
import math
import statistics
import unittest
from pathlib import Path
from dataclasses import replace

import cairo
import numpy as np

from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.gaze import (
    ANCHOR_CAMERA,
    EXPRESSIONS,
    POSE_EXPRESSIONS,
    BlinkPattern,
    EyeState,
    FaceController,
    SaccadeSchedule,
    expression_for_pose,
    gaze_toward,
)
from studio.characters.schema import CharacterSchema, load_schema


def rig_for(name: str, state: EyeState | None = None):
    rig = ChikuRig(x=200, y=520, scale=1.4) if name == "chiku" else GappuRig(x=200, y=520, scale=1.4)
    rig.eye_state = state
    return rig


def frame(rig, size: int = 420) -> np.ndarray:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    cr.set_source_rgb(1.0, 0.0, 1.0)  # magenta: cannot collide with any character colour
    cr.paint()
    rig.draw(cr)
    surface.flush()
    data = np.frombuffer(bytes(surface.get_data()), dtype=np.uint8).reshape(size, -1, 4)
    # cairo ARGB32 is BGRA in memory on little-endian machines
    return data[:, :, :3][:, :, ::-1].copy()


def color_mask(image: np.ndarray, rgb: tuple, tolerance: int = 6) -> np.ndarray:
    target = np.array([int(round(c * 255)) for c in rgb[:3]])
    return np.all(np.abs(image.astype(int) - target) <= tolerance, axis=2)


def centroid(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


class BlinkTests(unittest.TestCase):
    def test_same_seed_is_reproducible(self) -> None:
        a = BlinkPattern(3.2, 0.14, seed=11, span=30)
        b = BlinkPattern(3.2, 0.14, seed=11, span=30)
        self.assertEqual([(bl.start, bl.duration) for bl in a._blinks],
                         [(bl.start, bl.duration) for bl in b._blinks])

    def test_different_seed_moves_the_blinks(self) -> None:
        a = BlinkPattern(3.2, 0.14, seed=11, span=30)
        b = BlinkPattern(3.2, 0.14, seed=12, span=30)
        self.assertNotEqual([bl.start for bl in a._blinks], [bl.start for bl in b._blinks])

    def test_rhythm_is_not_a_metronome(self) -> None:
        pattern = BlinkPattern(3.2, 0.14, seed=5, span=60)
        intervals = pattern.intervals()
        self.assertGreater(len(intervals), 5)
        self.assertGreater(statistics.pstdev(intervals), 0.35)
        self.assertLess(min(intervals), 2.4)
        self.assertGreater(max(intervals), 4.0)

    def test_plausible_blink_rate(self) -> None:
        pattern = BlinkPattern(3.2, 0.14, seed=7, span=60)
        count = pattern.count(0.0, 60.0)
        self.assertGreater(count, 10)
        self.assertLess(count, 40)

    def test_close_is_faster_than_open(self) -> None:
        pattern = BlinkPattern(3.2, 0.14, seed=3, span=30)
        blink = next(b for b in pattern._blinks if b.amplitude >= 1.0)
        closing = [t for t in _steps(blink.start, blink.start + blink.duration)
                   if pattern.lid_at(t) >= 0.95]
        opening = [t for t in _steps(blink.start, blink.start + blink.duration)
                   if pattern.lid_at(t) <= 0.05]
        self.assertTrue(closing, "blink never fully closes")
        self.assertLess(closing[0] - blink.start, 0.5 * blink.duration)
        # eyelid is still partly shut halfway through the opening phase
        self.assertGreater(pattern.lid_at(blink.start + blink.duration * 0.75), 0.2)

    def test_lid_is_zero_between_blinks_and_bounded(self) -> None:
        pattern = BlinkPattern(3.2, 0.14, seed=9, span=40)
        values = [pattern.lid_at(t) for t in _steps(0.0, 40.0, 1 / 60)]
        self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
        self.assertGreater(sum(1 for v in values if v == 0.0), len(values) * 0.85)

    def test_partial_and_double_blinks_exist(self) -> None:
        amplitudes = set()
        has_double = False
        for seed in range(40):
            pattern = BlinkPattern(3.2, 0.14, seed=seed, span=40)
            amplitudes.update(round(bl.amplitude, 2) for bl in pattern._blinks)
            gaps = [b.start - a.start for a, b in zip(pattern._blinks, pattern._blinks[1:])]
            if any(gap < 0.35 for gap in gaps):
                has_double = True
        self.assertGreater(len(amplitudes), 1, "every blink has the same amplitude")
        self.assertTrue(has_double, "no double blink across 40 seeds")

    def test_scale_shrinks_the_blink(self) -> None:
        pattern = BlinkPattern(3.2, 0.14, seed=3, span=30)
        peak = max(pattern.lid_at(t) for t in _steps(0.0, 30.0, 1 / 60))
        shrunk = max(pattern.lid_at(t, 0.5) for t in _steps(0.0, 30.0, 1 / 60))
        self.assertAlmostEqual(shrunk, peak * 0.5, places=5)


def _steps(start: float, end: float, step: float = 1 / 120) -> list[float]:
    out = []
    t = start
    while t <= end:
        out.append(t)
        t += step
    return out


class SaccadeTests(unittest.TestCase):
    def test_gaze_is_bounded_and_finite(self) -> None:
        schedule = SaccadeSchedule(seed=4, span=30)
        for t in _steps(0.0, 30.0, 1 / 30):
            gx, gy = schedule.base_gaze_at(t)
            self.assertTrue(-1.0 <= gx <= 1.0 and -1.0 <= gy <= 1.0)
            self.assertFalse(math.isnan(gx) or math.isnan(gy))

    def test_eyes_look_around(self) -> None:
        schedule = SaccadeSchedule(seed=4, span=30)
        targets = {(round(gy, 1), round(gx, 1)) for gx, gy in schedule._events and
                   [(e.to[0], e.to[1]) for e in schedule._events]}
        self.assertGreaterEqual(len(targets), 3)
        self.assertGreater(schedule.moves, 4)

    def test_movements_are_fast(self) -> None:
        schedule = SaccadeSchedule(seed=6, span=30)
        self.assertTrue(schedule._events)
        for event in schedule._events:
            self.assertLessEqual(event.duration, 0.2)
            self.assertGreaterEqual(event.duration, 0.04)

    def test_scripted_target_is_honoured(self) -> None:
        schedule = SaccadeSchedule(seed=2, span=20,
                                   scripted=[(5.0, (0.9, -0.9))])
        gx, gy = schedule.base_gaze_at(5.25)
        self.assertAlmostEqual(gx, 0.9, places=3)
        self.assertAlmostEqual(gy, -0.9, places=3)

    def test_tremor_is_small(self) -> None:
        schedule = SaccadeSchedule(seed=2, span=20, micro=0.04)
        for t in _steps(0.0, 20.0, 1 / 24):
            dx, dy = schedule.tremor(t)
            self.assertLessEqual(math.hypot(dx, dy), 0.08)
            self.assertGreater(math.hypot(dx, dy), 0.0)

    def test_no_repeated_target(self) -> None:
        schedule = SaccadeSchedule(seed=8, span=40)
        for event in schedule._events:
            self.assertTrue(abs(event.to[0] - event.frm[0]) > 1e-3
                            or abs(event.to[1] - event.frm[1]) > 1e-3)

    def test_determinism(self) -> None:
        a = SaccadeSchedule(seed=13, span=20)
        b = SaccadeSchedule(seed=13, span=20)
        self.assertEqual([(e.start, e.to) for e in a._events],
                         [(e.start, e.to) for e in b._events])

    def test_gaze_toward_partner(self) -> None:
        right = gaze_toward(own_x=380, other_x=780, other_y=1200, eye_y=1250)
        self.assertGreater(right[0], 0.5)
        left = gaze_toward(own_x=780, other_x=380, other_y=1200, eye_y=1250)
        self.assertLess(left[0], -0.5)
        same = gaze_toward(own_x=500, other_x=503, other_y=1250, eye_y=1250)
        self.assertEqual(same[0], 0.0)


class ExpressionTests(unittest.TestCase):
    def test_every_expression_is_finite(self) -> None:
        for name, profile in EXPRESSIONS.items():
            for field_name in ("lid_closed", "lower_lid", "brow_y", "brow_tilt",
                               "brow_asymmetry", "pupil_scale", "gaze_x", "gaze_y",
                               "saccade_scale", "blink_scale"):
                value = getattr(profile, field_name)
                self.assertTrue(math.isfinite(value), f"{name}.{field_name}")

    def test_expressions_are_distinguishable(self) -> None:
        fingerprints = {
            (round(p.lid_closed, 2), round(p.lower_lid, 2), round(p.brow_y, 1),
             round(p.brow_tilt, 2), round(p.gaze_x, 2), round(p.gaze_y, 2),
             round(p.pupil_scale, 2))
            for name, p in EXPRESSIONS.items() if name != "neutral"
        }
        self.assertGreaterEqual(len(fingerprints), 10)

    def test_shock_opens_eyes_suspicion_narrows_them(self) -> None:
        neutral = EXPRESSIONS["neutral"]
        self.assertLess(EXPRESSIONS["surprised"].lower_lid, 0.0)
        self.assertGreater(EXPRESSIONS["suspicious"].lid_closed, neutral.lid_closed)
        self.assertGreater(EXPRESSIONS["angry"].lower_lid, neutral.lower_lid)
        self.assertGreater(EXPRESSIONS["confused"].brow_asymmetry, 0.0)
        self.assertGreater(EXPRESSIONS["sad"].gaze_y, 0.0)
        self.assertLess(EXPRESSIONS["thinking"].gaze_y, 0.0)
        self.assertLess(EXPRESSIONS["surprised"].pupil_scale, 1.0)

    def test_blend_interpolates(self) -> None:
        mid = EXPRESSIONS["happy"].blended(EXPRESSIONS["surprised"], 0.5)
        self.assertAlmostEqual(mid.lid_closed,
                               (EXPRESSIONS["happy"].lid_closed + EXPRESSIONS["surprised"].lid_closed) / 2)
        self.assertEqual(EXPRESSIONS["happy"].blended(EXPRESSIONS["sad"], 0.0), EXPRESSIONS["happy"])
        self.assertEqual(EXPRESSIONS["happy"].blended(EXPRESSIONS["sad"], 1.0), EXPRESSIONS["sad"])

    def test_pose_mapping_covers_story_poses(self) -> None:
        for pose in ("idle", "excited_jump", "shocked_freeze", "skeptical_eyebrow",
                     "observing", "boast_proud"):
            self.assertIn(expression_for_pose(pose), EXPRESSIONS)
        self.assertEqual(expression_for_pose("never-heard-of-it"), "neutral")


class ControllerTests(unittest.TestCase):
    def test_state_is_finite_for_a_whole_minute(self) -> None:
        for character in ("chiku", "gappu"):
            controller = FaceController(load_schema(character), seed=17, span=60,
                                        schedule=[(0.0, "neutral"), (10.0, "surprised"),
                                                  (20.0, "sad"), (30.0, "angry"),
                                                  (40.0, "happy")])
            for t in _steps(0.0, 60.0, 1 / 12):
                state = controller.state_at(t)
                for value in (state.lid_left, state.lid_right, state.pupil_left[0],
                              state.pupil_left[1], state.pupil_scale, state.brow_y):
                    self.assertTrue(math.isfinite(value))
                self.assertTrue(0.0 <= state.lid_left <= 1.0)

    def test_transition_is_gradual(self) -> None:
        controller = FaceController(load_schema("chiku"), seed=1, span=20,
                                    schedule=[(0.0, "happy"), (5.0, "angry")],
                                    transition=0.4)
        before = controller.state_at(4.9).lid_left
        early = controller.state_at(5.1).lid_left
        late = controller.state_at(5.5).lid_left
        self.assertLess(before, early)
        self.assertLess(early, late)
        self.assertAlmostEqual(late, EXPRESSIONS["angry"].lid_closed, places=3)

    def test_shock_suppresses_blinking(self) -> None:
        schema = load_schema("chiku")
        controller = FaceController(schema, seed=5, span=30,
                                    schedule=[(0.0, "neutral"), (5.0, "surprised")])
        lids = [controller.state_at(t).lid_right for t in _steps(5.0, 5.9, 1 / 30)]
        self.assertEqual(max(lids), 0.0)
        window = [controller.state_at(t).lid_right for t in _steps(0.0, 5.0, 1 / 30)]
        self.assertGreater(max(window), 0.8, "normal blinking should happen before the shock")

    def test_character_overrides_are_applied(self) -> None:
        base = load_schema("chiku")
        data = {
            "schema_version": 1, "id": "chiku", "display_name": "C", "archetype": "monkey",
            "voice": "chiku", "anchor": dict(base.anchor),
            "palette": {k: list(v) for k, v in base.palette.items()},
            "proportions": dict(base.proportions.values),
            "timing": {name: getattr(base.timing, name) for name in
                       ("blink_period", "blink_duration", "blink_phase", "breath_rate",
                        "breath_phase", "breath_amplitude", "sway_rate", "sway_amplitude",
                        "tail_rate", "tail_amplitude", "idle_arm_rate")},
            "shapes": json.loads(
                (Path("content/characters/chiku.json")).read_text(encoding="utf-8")
            )["shapes"],
            "expressions": {"happy": {"lid_closed": 0.9, "gaze_x": -0.5}},
        }
        schema = CharacterSchema.from_dict(data)
        controller = FaceController(schema, seed=1, span=10, expression="happy")
        self.assertAlmostEqual(controller._merged["happy"].lid_closed, 0.9)
        state = controller.state_at(3.0)
        self.assertLess(state.pupil_left[0], 0.0)

    def test_wink_override(self) -> None:
        controller = FaceController(load_schema("gappu"), seed=2, span=10)
        state = controller.with_lids(1.0, 1.0, 0.0)
        self.assertEqual(state.lid_left, 1.0)
        self.assertEqual(state.lid_right, 0.0)


class RenderTests(unittest.TestCase):
    def test_expressive_render_differs_from_legacy(self) -> None:
        for name in ("chiku", "gappu"):
            legacy = frame(rig_for(name))
            expressive = frame(rig_for(name, FaceController(load_schema(name), seed=1,
                                                            span=10).state_at(2.0)))
            self.assertFalse(np.array_equal(legacy, expressive), name)

    def test_closed_eye_draws_less_ink(self) -> None:
        schema = load_schema("chiku")
        controller = FaceController(schema, seed=3, span=10)
        white = schema.color("eye_white")
        open_img = frame(rig_for("chiku", controller.with_lids(2.0, 0.0, 0.0)))
        closed_img = frame(rig_for("chiku", controller.with_lids(2.0, 1.0, 1.0)))
        self.assertGreater(color_mask(open_img, white).sum(),
                           color_mask(closed_img, white).sum() * 3)

    def test_pupils_follow_gaze(self) -> None:
        schema = load_schema("chiku")
        controller = FaceController(schema, seed=3, span=10)
        pupil = schema.color("pupil")
        right = controller.with_lids(2.0, 0.0, 0.0)
        right = replace(right, pupil_left=(0.85, 0.0), pupil_right=(0.85, 0.0))
        left = replace(right, pupil_left=(-0.85, 0.0), pupil_right=(-0.85, 0.0))
        right_c = centroid(color_mask(frame(rig_for("chiku", right)), pupil))
        left_c = centroid(color_mask(frame(rig_for("chiku", left)), pupil))
        self.assertIsNotNone(right_c)
        self.assertIsNotNone(left_c)
        self.assertGreater(right_c[0] - left_c[0], 8.0)

    def test_wide_expression_opens_taller_than_suspicion(self) -> None:
        schema = load_schema("chiku")
        controller = FaceController(schema, seed=3, span=10)
        outline = schema.color("outline")

        def eye_height(name: str) -> int:
            state = replace(controller.state_at(2.0), lid_left=0.0, lid_right=0.0,
                            expression=name,
                            lower_lid=EXPRESSIONS[name].lower_lid)
            img = frame(rig_for("chiku", state))
            mask = color_mask(img, schema.color("eye_white"))
            ys, _ = np.nonzero(mask)
            return int(ys.max() - ys.min()) if len(ys) else 0

        self.assertGreaterEqual(eye_height("surprised"), eye_height("suspicious") + 6)
        self.assertGreaterEqual(eye_height("suspicious"), eye_height("angry"))

    def test_all_expressions_render(self) -> None:
        for character in ("chiku", "gappu"):
            controller = FaceController(load_schema(character), seed=9, span=30)
            for name in EXPRESSIONS:
                state = replace(controller.state_at(2.0),
                                lid_left=0.0, lid_right=0.0, expression=name,
                                lower_lid=EXPRESSIONS[name].lower_lid)
                image = frame(rig_for(character, state), size=260)
                self.assertEqual(image.shape[0], 260)
                self.assertGreater(int(image.min()), -1)

    def test_rids_accept_controllers(self) -> None:
        for name in ("chiku", "gappu"):
            rig = rig_for(name)
            rig.attach_face(FaceController(load_schema(name), seed=4, span=10))
            rig.face_state_at(1.5)
            self.assertIsNotNone(rig.eye_state)
            frame(rig, size=200)


if __name__ == "__main__":
    unittest.main()
