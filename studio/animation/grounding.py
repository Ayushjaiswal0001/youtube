"""Placing a rig so its feet land exactly on the ground plane (T45).

Measured, not assumed: a rig's anchor is *not* its feet. Rendering Chiku at ``y = 788`` puts the
bottom of his boots at 820, thirty-two pixels through the floor, and Gappu at 810. Every landscape
scene made with the raw stage anchor therefore has the cast slightly buried.

This module measures the drawn silhouette once per rig and derives the offset, so a change to the
boot art moves the offset with it instead of silently reintroducing the bug.
"""

from __future__ import annotations

import cairo

# Measurement scratch space: big enough for both rigs at stage scale, small enough to scan quickly.
_PROBE_W, _PROBE_H = 900, 1200
_ANCHOR_X, _ANCHOR_Y = 450, 200

_cache: dict[tuple[str, float], float] = {}


def measure_foot_offset(rig) -> float:
    """How far below the rig's anchor the drawn silhouette reaches, in world pixels.

    Positive means the feet extend *below* the anchor, so the anchor must be raised by that amount to
    stand the character on the ground.
    """

    name = str(getattr(getattr(rig, "schema", None), "id", type(rig).__name__))
    key = (name, round(float(rig.scale), 4))
    if key in _cache:
        return _cache[key]

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _PROBE_W, _PROBE_H)
    cr = cairo.Context(surface)
    # Map the rig anchor onto a known point so the scan does not depend on where the rig is standing.
    cr.translate(_ANCHOR_X - rig.x, _ANCHOR_Y - rig.y)
    rig.draw(cr)
    surface.flush()
    data = bytes(surface.get_data())
    stride = surface.get_stride()

    bottom = _ANCHOR_Y
    for y in range(_PROBE_H - 1, -1, -1):
        row = y * stride
        if any(data[row + x * 4 + 3] for x in range(0, _PROBE_W, 2)):
            bottom = y
            break
    offset = float(bottom - _ANCHOR_Y)
    _cache[key] = offset
    return offset


def place_on_ground(rig, ground_y: float) -> float:
    """Stand a rig on ``ground_y`` and return the offset that was applied."""

    offset = measure_foot_offset(rig)
    rig.y = float(ground_y) - offset
    return offset


def ground_error(rig, ground_y: float) -> float:
    """Signed distance from the drawn feet to the ground plane. 0 means planted."""

    return float(ground_y) - (float(rig.y) + measure_foot_offset(rig))


def clear_cache() -> None:
    _cache.clear()
