"""Shared eye and eyebrow renderer for every character rig.

Two rendering paths live here, on purpose:

``draw_eyes(..., state=None)``
    The original expression: a white ellipse scaled vertically by ``blink_t`` with a
    single closed-eye arc. Kept bit-for-bit so golden frames stay valid and so the rigs
    did not silently change look when this module was introduced.

``draw_eyes(..., state=EyeState)``
    The expressive path: real eyelids (upper and lower, independently animated),
    expression-driven aperture, dilation, gaze offsets per eye and three closed-eye
    shapes.

Both rigs call the same functions, so a change here is a change for both characters and
per-character differences belong in ``content/characters/*.json`` (``eyes`` block).
"""

from __future__ import annotations

import math
from typing import Dict, Sequence, Tuple

import cairo

from studio.characters.schema import EyeConfig
from studio.characters.gaze import clamp

Color = Tuple[float, ...]

LEGACY_CLOSED_THRESHOLD = 0.8
# Below this the eye is drawn as a closed curve rather than as a slit.
CLOSED_EPSILON = 0.02


def _lid_edge(cr: cairo.Context, x0: float, x1: float, y: float, curvature: float) -> None:
    """One eyelid edge, bowed by ``curvature`` (positive bows toward +y)."""
    span = x1 - x0
    cr.move_to(x0, y)
    cr.curve_to(x0 + span * 0.28, y + curvature,
                x0 + span * 0.72, y + curvature,
                x1, y)


def _lash(cr: cairo.Context, color: Color, width: float) -> None:
    cr.set_source_rgba(*color)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.stroke()


def _closed_eye(cr: cairo.Context, points: Sequence[Sequence[float]],
                color: Color, width: float, style: str) -> None:
    """Draw a closed eye.

    ``curve``  the original downward curve used by the legacy path
    ``happy``  an upward arc (``^``): the eye smiles
    ``flat``   a straight lid line, used for suspicion and exhaustion
    """

    cr.set_source_rgba(*color)
    cr.set_line_width(width)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)

    if style == "happy":
        cr.move_to(-points[-1][0], 0.0)
        cr.curve_to(-points[-1][0] * 0.45, -points[-1][1] * 1.15,
                    points[-1][0] * 0.45, -points[-1][1] * 1.15,
                    points[-1][0], 0.0)
        cr.stroke()
        return
    if style == "flat":
        cr.move_to(-points[-1][0], -2.0)
        cr.curve_to(-points[-1][0] * 0.4, 1.0, points[-1][0] * 0.4, 1.0,
                    points[-1][0], -2.0)
        cr.stroke()
        return

    cr.move_to(points[0][0], points[0][1])
    cr.curve_to(points[1][0], points[1][1], points[2][0], points[2][1],
                points[3][0], points[3][1])
    cr.stroke()


def draw_eyes(cr: cairo.Context, prop, eye_cfg: EyeConfig, *,
              colors: Dict[str, Color],
              state=None,
              blink_t: float = 0.0,
              look_x: float = 0.0,
              look_y: float = 0.0,
              pupil_range: Tuple[float, float] = (5.0, 4.0)) -> None:
    """Draw both eyes.

    ``state`` present -> expressive path; ``state`` absent -> the legacy path that the
    golden frames were captured from.
    """

    if state is None:
        _draw_eyes_legacy(cr, prop, eye_cfg, colors=colors, blink_t=blink_t,
                          look_x=look_x, look_y=look_y, pupil_range=pupil_range)
    else:
        _draw_eyes_expressive(cr, prop, eye_cfg, colors=colors, state=state,
                             pupil_range=pupil_range)


def _draw_eyes_legacy(cr: cairo.Context, prop, eye_cfg: EyeConfig, *,
                      colors: Dict[str, Color], blink_t: float,
                      look_x: float, look_y: float,
                      pupil_range: Tuple[float, float]) -> None:
    outline = colors["outline"]
    for eye_x in (-prop.eye_x, prop.eye_x):
        cr.save()
        cr.translate(eye_x, prop.eye_y)

        if blink_t > LEGACY_CLOSED_THRESHOLD:
            _closed_eye(cr, eye_cfg.closed_curve, outline, eye_cfg.lash_width, "curve")
        else:
            eye_h = prop.eye_ry * (1.0 - blink_t)
            _ellipse(cr, 0, 0, prop.eye_rx, eye_h,
                     fill=colors["eye_white"], stroke=outline,
                     stroke_width=eye_cfg.lash_width)
            pupil_px = look_x * pupil_range[0]
            pupil_py = look_y * pupil_range[1]
            _ellipse(cr, pupil_px, pupil_py, prop.pupil_rx,
                     prop.pupil_ry * (1.0 - blink_t), fill=colors["pupil"])
            _ellipse(cr, pupil_px + eye_cfg.catchlight_offset[0] + look_x * eye_cfg.catchlight_follow[0],
                     pupil_py + eye_cfg.catchlight_offset[1] + look_y * eye_cfg.catchlight_follow[1],
                     eye_cfg.catchlight_r, eye_cfg.catchlight_r,
                     fill=(1.0, 1.0, 1.0, eye_cfg.catchlight_alpha))

        cr.restore()


def _aperture_path(cr: cairo.Context, rx: float, ry_top: float, ry_bot: float,
                   curvature: float) -> None:
    """Asymmetric eye opening: a half ellipse up and a half ellipse down."""

    k = 0.5522847498 * max(0.2, curvature)
    cr.move_to(-rx, 0.0)
    cr.curve_to(-rx, -ry_top * k, -rx * k, -ry_top, 0.0, -ry_top)
    cr.curve_to(rx * k, -ry_top, rx, -ry_top * k, rx, 0.0)
    cr.curve_to(rx, ry_bot * k, rx * k, ry_bot, 0.0, ry_bot)
    cr.curve_to(-rx * k, ry_bot, -rx, ry_bot * k, -rx, 0.0)
    cr.close_path()


def _draw_eyes_expressive(cr: cairo.Context, prop, eye_cfg: EyeConfig, *,
                          colors: Dict[str, Color], state,
                          pupil_range: Tuple[float, float]) -> None:
    outline = colors["outline"]
    white = colors["eye_white"]
    pupil_color = colors["pupil"]
    sides = (
        (-prop.eye_x, state.lid_left, state.pupil_left),
        (prop.eye_x, state.lid_right, state.pupil_right),
    )
    for eye_x, lid, pupil in sides:
        cr.save()
        cr.translate(eye_x, prop.eye_y)

        if lid >= 1.0 - CLOSED_EPSILON:
            _closed_eye(cr, eye_cfg.closed_curve, outline, eye_cfg.lash_width,
                        state.closed_style)
            cr.restore()
            continue

        lid = clamp(lid, 0.0, 1.0)
        open_top = min(eye_cfg.lid_open_max, max(0.05, 1.0 - lid))
        low = clamp(state.lower_lid, -0.6, eye_cfg.lower_lid_max)
        ry_top = prop.eye_ry * open_top
        ry_bot = prop.eye_ry * (1.0 - 0.55 * low)

        _aperture_path(cr, prop.eye_rx, ry_top, ry_bot, eye_cfg.lid_curvature)
        cr.set_source_rgba(*white)
        cr.fill_preserve()
        cr.set_source_rgba(*outline)
        cr.set_line_width(eye_cfg.lash_width)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

        # Everything below is clipped to the aperture, so the pupil can never escape.
        _aperture_path(cr, prop.eye_rx, ry_top, ry_bot, eye_cfg.lid_curvature)
        cr.save()
        cr.clip()

        pupil_scale = clamp(state.pupil_scale, eye_cfg.pupil_min, eye_cfg.pupil_max)
        prx = prop.pupil_rx * pupil_scale
        pry = prop.pupil_ry * pupil_scale
        # Expressive eyes travel across the whole aperture: a 4 px range reads as a stare.
        # Travel is capped well inside the aperture: pinning the pupil to the very edge
        # reads as a cartoon "crazy eye", not as looking at someone.
        px_limit = max(0.5, min(prop.eye_rx - prx - 1.0, prop.eye_rx * 0.5))
        py_limit = max(0.5, min(min(ry_top, ry_bot) - pry * 0.75,
                                min(ry_top, ry_bot) * 0.45))
        px = clamp(pupil[0], -1.0, 1.0) * px_limit
        py = clamp(pupil[1], -1.0, 1.0) * py_limit
        _ellipse(cr, px, py, prx, pry, fill=pupil_color)
        _ellipse(cr, px + eye_cfg.catchlight_offset[0] + pupil[0] * eye_cfg.catchlight_follow[0],
                 py + eye_cfg.catchlight_offset[1] + pupil[1] * eye_cfg.catchlight_follow[1],
                 eye_cfg.catchlight_r * max(0.8, pupil_scale),
                 eye_cfg.catchlight_r * max(0.8, pupil_scale),
                 fill=(1.0, 1.0, 1.0, eye_cfg.catchlight_alpha))
        cr.restore()

        cr.restore()


def draw_brows(cr: cairo.Context, prop, eye_cfg: EyeConfig, *,
               colors: Dict[str, Color],
               y_offset: float = 0.0, tilt_left: float = 0.0,
               tilt_right: float = 0.0) -> None:
    """Draw both brows.

    ``tilt_left`` / ``tilt_right`` are supplied separately so an expression can raise one
    brow (suspicion, confusion) instead of moving both symmetrically.
    """

    outline = colors["outline"]
    for is_right, eb_x, tilt in (
        (False, -prop.brow_anchor_x, tilt_left),
        (True, prop.brow_anchor_x, tilt_right),
    ):
        # A pose and an expression can both raise the brow; clamp the sum so it cannot
        # climb into the hairline.
        y_offset = max(-18.0, min(10.0, y_offset))
        tilt = max(-0.6, min(0.6, tilt))
        cr.save()
        cr.translate(eb_x, prop.brow_y + y_offset)
        cr.rotate(tilt if not is_right else -tilt)
        cr.set_source_rgba(*outline)
        cr.set_line_width(eye_cfg.brow_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(-prop.brow_rx, 0)
        cr.curve_to(-prop.brow_ctrl_x, -prop.brow_ctrl_y,
                    prop.brow_ctrl_x, -prop.brow_ctrl_y,
                    prop.brow_rx, 0)
        cr.stroke()
        cr.restore()


def _ellipse(cr: cairo.Context, cx: float, cy: float, rx: float, ry: float, *,
             fill: Color | None = None, stroke: Color | None = None,
             stroke_width: float = 3.0) -> None:
    """Ellipse with round joins, matching the rig helper's rendering exactly."""

    cr.save()
    cr.translate(cx, cy)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1.0, 0, 2 * math.pi)
    cr.restore()
    if fill:
        cr.set_source_rgba(*fill)
        if stroke:
            cr.fill_preserve()
        else:
            cr.fill()
    if stroke:
        cr.set_source_rgba(*stroke)
        cr.set_line_width(stroke_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()
