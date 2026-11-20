"""Shared mouth geometry so both rigs speak the same visual language.

Every shape keeps the same anchor (the middle of the muzzle) and is drawn from a small
table, so adding a viseme means adding one branch here instead of editing two rigs.
"""

from __future__ import annotations

import cairo

from .rig_base import Viseme, draw_ellipse, draw_capsule

MOUTH_INTERIOR = (0.55, 0.05, 0.05, 1.0)
TONGUE = (0.95, 0.45, 0.45, 1.0)
TEETH = (0.98, 0.97, 0.94, 1.0)
OUTLINE = (0.20, 0.11, 0.07, 1.0)


def draw_mouth(
    cr: cairo.Context,
    viseme: str,
    openness: float,
    *,
    anchor_y: float,
    size: float = 1.0,
    stroke_width: float = 3.5,
) -> None:
    """Draw ``viseme`` at ``anchor_y`` in the current local coordinate system."""

    openness = max(0.0, min(1.0, openness))
    cr.save()
    cr.translate(0, anchor_y)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_width(stroke_width)

    if viseme in (Viseme.OPEN_WIDE, Viseme.SURPRISED):
        height = (16 + openness * 14) * size
        width = (18 + openness * 4) * size
        draw_ellipse(cr, 0, 12 * size, width, max(4.0, height),
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width)
        draw_ellipse(cr, 0, (18 + openness * 6) * size, width * 0.62, max(2.5, height * 0.45),
                     fill_color=TONGUE)

    elif viseme == Viseme.ROUND:
        width = (10 + openness * 2) * size
        height = (12 + openness * 8) * size
        draw_ellipse(cr, 0, 10 * size, width, max(4.0, height),
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width)

    elif viseme == Viseme.WIDE:
        height = (5 + openness * 8) * size
        draw_ellipse(cr, 0, 9 * size, (21 + openness * 3) * size, max(3.0, height),
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width)
        # upper teeth strip keeps E/I readable at small scale
        cr.save()
        cr.rectangle((-19 * size), (8 * size), 38 * size, max(2.0, 4 * size))
        cr.set_source_rgba(*TEETH)
        cr.fill()
        cr.restore()

    elif viseme == Viseme.TEETH:
        # F / V: lower lip tucked under the upper teeth, mouth barely open
        cr.save()
        cr.rectangle((-16 * size), (6 * size), 32 * size, max(2.5, 5 * size))
        cr.set_source_rgba(*TEETH)
        cr.fill()
        cr.set_source_rgba(*OUTLINE)
        cr.set_line_width(stroke_width * 0.8)
        cr.move_to(-16 * size, (6 * size))
        cr.curve_to(-8 * size, (12 + openness * 5) * size, 8 * size, (12 + openness * 5) * size, 16 * size, (6 * size))
        cr.stroke()
        cr.restore()

    elif viseme == Viseme.TONGUE:
        height = (7 + openness * 9) * size
        draw_ellipse(cr, 0, 10 * size, (14 + openness * 2) * size, max(3.5, height),
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width)
        # tongue tip resting on the lower lip
        draw_ellipse(cr, 0, (13 + openness * 3) * size, 7 * size, max(2.5, height * 0.45),
                     fill_color=TONGUE)

    elif viseme == Viseme.OPEN_SMALL:
        height = (9 + openness * 8) * size
        draw_ellipse(cr, 0, 10 * size, 14 * size, max(3.5, height),
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width)

    elif viseme == Viseme.NEUTRAL:
        draw_capsule(cr, -9 * size, 10 * size, 9 * size, 10 * size, 2.2 * size,
                     fill_color=MOUTH_INTERIOR, stroke_color=OUTLINE, stroke_width=stroke_width * 0.8)

    elif viseme == Viseme.CLOSED:
        cr.set_source_rgba(*OUTLINE)
        cr.move_to(-14 * size, 9 * size)
        cr.curve_to(-6 * size, 12 * size, 6 * size, 12 * size, 14 * size, 9 * size)
        cr.stroke()

    else:  # SMILE and anything unknown
        cr.set_source_rgba(*OUTLINE)
        cr.move_to(-18 * size, 6 * size)
        cr.curve_to(-8 * size, 18 * size, 8 * size, 18 * size, 18 * size, 6 * size)
        cr.stroke()
        cr.move_to(17 * size, 3 * size)
        cr.line_to(20 * size, 7 * size)
        cr.stroke()

    cr.restore()
