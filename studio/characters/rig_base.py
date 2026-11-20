"""Hierarchical 2D Vector Rigging Engine.
Provides joint transforms, bone hierarchies, procedural motion, easing,
and vector rendering via PyCairo.
"""

import math
from typing import Dict, List, Optional, Tuple, Any
import cairo


# --- Easing Functions for Natural Cartoon Physics ---

def linear(t: float) -> float:
    return max(0.0, min(1.0, t))

def ease_in_quad(t: float) -> float:
    t = linear(t)
    return t * t

def ease_out_quad(t: float) -> float:
    t = linear(t)
    return t * (2.0 - t)

def ease_in_out_quad(t: float) -> float:
    t = linear(t)
    if t < 0.5:
        return 2.0 * t * t
    return -1.0 + (4.0 - 2.0 * t) * t

def ease_out_bounce(t: float) -> float:
    t = linear(t)
    if t < (1 / 2.75):
        return 7.5625 * t * t
    elif t < (2 / 2.75):
        t -= (1.5 / 2.75)
        return 7.5625 * t * t + 0.75
    elif t < (2.5 / 2.75):
        t -= (2.25 / 2.75)
        return 7.5625 * t * t + 0.9375
    else:
        t -= (2.625 / 2.75)
        return 7.5625 * t * t + 0.984375

def spring_overshoot(t: float, overshoot: float = 1.25) -> float:
    """Cartoon overshoot pop for energetic character reactions."""
    t = linear(t)
    return (overshoot * t - (overshoot - 1.0)) * math.sin(t * math.pi * 0.5) if t < 1.0 else 1.0


# --- Viseme Mouth States for Lip-Sync ---

class Viseme:
    CLOSED = "closed"
    SMILE = "smile"
    OPEN_SMALL = "open_small"
    OPEN_WIDE = "open_wide"
    ROUND = "round"
    SURPRISED = "surprised"


# --- Transform Node Hierarchy ---

class JointNode:
    """A transform node in a 2D skeletal hierarchy."""

    def __init__(self, name: str, parent: Optional["JointNode"] = None,
                 local_x: float = 0.0, local_y: float = 0.0,
                 local_rot: float = 0.0, local_sx: float = 1.0, local_sy: float = 1.0):
        self.name = name
        self.parent = parent
        self.local_x = local_x
        self.local_y = local_y
        self.local_rot = local_rot  # in radians
        self.local_sx = local_sx
        self.local_sy = local_sy
        self.children: List["JointNode"] = []
        if parent:
            parent.children.append(self)

    def get_world_matrix(self) -> cairo.Matrix:
        """Computes the global world transformation matrix for this joint."""
        local = cairo.Matrix()
        local.translate(self.local_x, self.local_y)
        local.rotate(self.local_rot)
        local.scale(self.local_sx, self.local_sy)
        if self.parent:
            parent_mat = self.parent.get_world_matrix()
            return local.multiply(parent_mat)
        return local


# --- Helper drawing functions for PyCairo ---

def draw_ellipse(cr: cairo.Context, cx: float, cy: float, rx: float, ry: float,
                 fill_color: Optional[Tuple[float, float, float, float]] = None,
                 stroke_color: Optional[Tuple[float, float, float, float]] = None,
                 stroke_width: float = 3.0):
    cr.save()
    cr.translate(cx, cy)
    cr.scale(rx, ry)
    cr.arc(0, 0, 1.0, 0, 2 * math.pi)
    cr.restore()
    if fill_color:
        cr.set_source_rgba(*fill_color)
        if stroke_color:
            cr.fill_preserve()
        else:
            cr.fill()
    if stroke_color:
        cr.set_source_rgba(*stroke_color)
        cr.set_line_width(stroke_width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.stroke()

def draw_capsule(cr: cairo.Context, x1: float, y1: float, x2: float, y2: float, radius: float,
                 fill_color: Optional[Tuple[float, float, float, float]] = None,
                 stroke_color: Optional[Tuple[float, float, float, float]] = None,
                 stroke_width: float = 3.0):
    """Draws a rounded capsule bone between two points."""
    dx = x2 - x1
    dy = y2 - y1
    dist = math.hypot(dx, dy)
    angle = math.atan2(dy, dx)
    cr.save()
    cr.translate(x1, y1)
    cr.rotate(angle)
    cr.arc(dist, 0, radius, -math.pi / 2, math.pi / 2)
    cr.arc(0, 0, radius, math.pi / 2, 3 * math.pi / 2)
    cr.close_path()
    cr.restore()
    if fill_color:
        cr.set_source_rgba(*fill_color)
        if stroke_color:
            cr.fill_preserve()
        else:
            cr.fill()
    if stroke_color:
        cr.set_source_rgba(*stroke_color)
        cr.set_line_width(stroke_width)
        cr.stroke()
