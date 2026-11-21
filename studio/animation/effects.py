"""Cartoon Visual Effects: Dust Puffs, Twinkle Sparkles, Emotion Pops.
"""

import math
from typing import List, Tuple
import cairo
from studio.characters.rig_base import draw_ellipse

def draw_sparkle(cr: cairo.Context, cx: float, cy: float, radius: float, angle: float,
                 color: Tuple[float, float, float, float] = (1.0, 0.95, 0.2, 0.95)):
    """Draws a 4-point cartoon twinkle star."""
    cr.save()
    cr.translate(cx, cy)
    cr.rotate(angle)
    cr.set_source_rgba(*color)
    cr.move_to(0, -radius)
    cr.curve_to(radius * 0.1, -radius * 0.1, radius * 0.1, -radius * 0.1, radius, 0)
    cr.curve_to(radius * 0.1, radius * 0.1, radius * 0.1, radius * 0.1, 0, radius)
    cr.curve_to(-radius * 0.1, radius * 0.1, -radius * 0.1, radius * 0.1, -radius, 0)
    cr.curve_to(-radius * 0.1, -radius * 0.1, -radius * 0.1, -radius * 0.1, 0, -radius)
    cr.fill()
    # Center bright dot
    draw_ellipse(cr, 0, 0, radius * 0.2, radius * 0.2, fill_color=(1.0, 1.0, 1.0, 1.0))
    cr.restore()

def draw_dust_puff(cr: cairo.Context, cx: float, cy: float, progress: float, scale: float = 1.0):
    """Draws an expanding, dissipating cartoon dust puff."""
    if progress <= 0.0 or progress >= 1.0:
        return
    alpha = (1.0 - progress) * 0.7
    cr.save()
    cr.translate(cx, cy)
    cr.scale(scale * (0.6 + progress * 0.8), scale * (0.6 + progress * 0.8))

    dust_color = (0.92, 0.88, 0.80, alpha)
    outline_color = (0.65, 0.60, 0.52, alpha)

    # 3 expanding cloud bubbles
    draw_ellipse(cr, -30 * progress, -10 * progress, 22, 18, fill_color=dust_color, stroke_color=outline_color, stroke_width=2.5)
    draw_ellipse(cr, 30 * progress, -10 * progress, 22, 18, fill_color=dust_color, stroke_color=outline_color, stroke_width=2.5)
    draw_ellipse(cr, 0, -22 * progress, 28, 22, fill_color=dust_color, stroke_color=outline_color, stroke_width=2.5)

    cr.restore()

def draw_exclamation_pop(cr: cairo.Context, cx: float, cy: float, progress: float):
    """Draws a cartoon '!' shock pop above head."""
    if progress <= 0.0 or progress >= 1.0:
        return
    pop_scale = math.sin(progress * math.pi) * 1.3
    cr.save()
    cr.translate(cx, cy - 30 * progress)
    cr.scale(pop_scale, pop_scale)
    # Yellow exclamation mark with dark border
    cr.set_source_rgba(1.0, 0.85, 0.1, 1.0)
    draw_ellipse(cr, 0, -25, 8, 22, fill_color=(1.0, 0.85, 0.1, 1.0), stroke_color=(0.1, 0.1, 0.1, 1.0), stroke_width=3.5)
    draw_ellipse(cr, 0, 8, 7, 7, fill_color=(1.0, 0.85, 0.1, 1.0), stroke_color=(0.1, 0.1, 0.1, 1.0), stroke_width=3.5)
    cr.restore()


def draw_vignette(cr: cairo.Context, width: float, height: float,
                  strength: float = 0.30) -> None:
    """Soft radial darkening toward the frame edges.

    A flat frame is one of the cues that reads as "not really filmed": real lenses lose light
    at the corners. This is one gradient fill per frame, so it costs almost nothing, and it
    also softens a character cropped by the edge of a close-up.
    """

    radius = math.hypot(width, height) / 2.0
    gradient = cairo.RadialGradient(width / 2.0, height / 2.0, radius * 0.45,
                                    width / 2.0, height / 2.0, radius)
    gradient.add_color_stop_rgba(0.0, 0.0, 0.0, 0.0, 0.0)
    gradient.add_color_stop_rgba(0.72, 0.0, 0.0, 0.0, strength * 0.45)
    gradient.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, strength)
    cr.save()
    cr.set_source(gradient)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    cr.restore()
