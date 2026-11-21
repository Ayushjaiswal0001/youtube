"""What a rig actually draws, measured (T41).

T39 gave every shot a subject box so the camera could know what it was framing. The box was
computed from the character schema's proportions, and it was wrong by a wide margin: on the
portrait stage it claimed Chiku was 278 world units tall when his drawn silhouette is 335, and it
claimed Gappu was 101 units tall against 265 drawn. Every framing measurement since - including
the "0 required subjects cropped" claim - was therefore measured against a box rather than against
the character, and a landscape render put the cast's heads through the top of the frame.

Rather than reverse-engineer the rig's internal offsets into a second formula (which is how the
two drifted apart in the first place), this module *renders* a rig and measures its alpha bounds.
The measurement is cached per (rig class, pose, facing), because the drawn art only depends on
those; body motion is applied afterwards as a translation and a bounded inflation.

Honest limits, stated rather than hidden:

* the box is measured with the body at rest, then inflated by ``PAD`` so a squash, a jump or a
  tail swing stays inside it;
* poses not seen before are measured once and cached, so the first frame of a new pose pays for it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cairo

from studio.animation.framing import GESTURE_REACH, Subject

# A rest-pose silhouette does not cover a squash, a jump arc or a tail swing. This inflation is
# asserted against drawn frames in tests/factory/test_silhouette.py rather than assumed.
PAD = 0.14

# Canvas and origin used for measurement: comfortably larger than any pose, with the anchor at a
# known point so screen bounds convert straight back to anchor-relative world units.
_CANVAS_W, _CANVAS_H = 1600, 1800
_ANCHOR_X, _ANCHOR_Y = 800.0, 1400.0

# class name -> (pose, facing) -> (left, top, right, bottom) relative to the anchor, at scale 1.0
_CACHE: Dict[Tuple[str, str, float], Tuple[float, float, float, float]] = {}


@dataclass(frozen=True)
class Silhouette:
    """A rig's drawn extent, relative to its anchor, at scale 1.0."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def inflated(self, pad: float = PAD) -> "Silhouette":
        width = self.right - self.left
        height = self.height
        return Silhouette(self.left - width * pad, self.top - height * pad,
                          self.right + width * pad, self.bottom + height * pad)


def measure(rig, pose: Optional[str] = None, facing: Optional[float] = None) -> Silhouette:
    """Render ``rig`` once and return its drawn bounds relative to its anchor.

    The rig is drawn through its own ``draw`` method, so this cannot disagree with the render: it
    *is* the render, measured.
    """

    rig_class = type(rig).__name__
    pose = pose or getattr(rig, "_last_pose", "idle")
    facing_key = 1.0 if (facing if facing is not None else rig.facing) >= 0 else -1.0
    key = (rig_class, str(pose), facing_key)
    cached = _CACHE.get(key)
    if cached is not None:
        return Silhouette(*cached)

    # A throwaway copy at a known place and scale, so the measurement does not disturb the rig that
    # is about to be drawn and so screen units are world units.
    probe = type(rig)(x=_ANCHOR_X, y=_ANCHOR_Y, scale=1.0)
    probe.facing = facing_key
    probe.update_pose(str(pose), 1.0)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, _CANVAS_W, _CANVAS_H)
    context = cairo.Context(surface)
    probe.draw(context)
    surface.flush()
    bounds = _alpha_bounds(surface, _CANVAS_W, _CANVAS_H)
    if bounds is None:
        silhouette = Silhouette(-10.0, -10.0, 10.0, 10.0)
    else:
        x0, y0, x1, y1 = bounds
        silhouette = Silhouette(x0 - _ANCHOR_X, y0 - _ANCHOR_Y,
                                x1 - _ANCHOR_X, y1 - _ANCHOR_Y)
    _CACHE[key] = (silhouette.left, silhouette.top, silhouette.right, silhouette.bottom)
    return silhouette


def _alpha_bounds(surface, width: int, height: int):
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    span = stride // 4
    top = bottom = left = right = -1
    for y in range(height):
        row = data[y * stride: y * stride + width * 4]
        alphas = row[3::4]
        if max(alphas) <= 8:
            continue
        if top < 0:
            top = y
        bottom = y
        first = next(x for x in range(width) if alphas[x] > 8)
        # The index of the last painted column, not its distance from the right edge: the first
        # version of this line returned a distance and halved every measured width.
        last = next(x for x in range(width - 1, -1, -1) if alphas[x] > 8)
        left = first if left < 0 else min(left, first)
        right = last if right < 0 else max(right, last)
    if top < 0:
        return None
    return (float(left), float(top), float(right + 1), float(bottom + 1))


def subject_from_rig(rig, pose: Optional[str] = None, body=None,
                     reach: Optional[float] = None, pad: float = PAD) -> Subject:
    """A framing subject for this rig, positioned on the stage it is actually standing on.

    ``subject_from_schema`` reads the anchor out of the character file, which is the *authored*
    position. A staged character is placed by the stage, so the framing has to read the rig.
    """

    silhouette = measure(rig, pose).inflated(pad)
    scale = float(rig.scale)
    offset_x = float(rig.x)
    y = float(rig.y)
    if body is not None:
        offset_x += float(getattr(body, "hip_x", 0.0))
        y += float(getattr(body, "jump_y", 0.0))
    top = y + silhouette.top * scale
    bottom = y + silhouette.bottom * scale
    # The anchor is not the body's centre: Chiku's silhouette runs from -126 to -13 around it, so
    # a box centred on the anchor frames about 90 px to the right of the character. The box is
    # placed on the drawing's centre and widened to hold both edges.
    centre_x = offset_x + (silhouette.left + silhouette.right) / 2.0 * scale
    half_w = (silhouette.right - silhouette.left) / 2.0 * scale
    reach_width = reach
    if reach_width is None and reach != 0.0:
        # Reserve the widest pose the rig can strike, measured from the art.
        reach_width = max(half_w, max_extent(rig) * scale) * GESTURE_REACH
    return Subject(name=getattr(rig, "name", type(rig).__name__.replace("Rig", "").lower()),
                   x=centre_x, y=y, half_w=half_w, top=top, bottom=bottom, reach=reach_width)


# Poses that put an arm out. The widest of these is what a shot has to reserve for a gesture, so
# that a swing cannot trail out of a frame that was planned for a hanging arm. Measured, not
# estimated: T41's first attempt reserved 55% of body height and pushed every shot to the zoom
# floor, which turned a close-up into a medium shot.
_EXTENDED_POSES = ("laughing_point", "hands_on_hips", "boast_proud", "embarrassed_smile",
                   "excited_jump", "idle")

_REACH: Dict[str, float] = {}


def max_extent(rig) -> float:
    """Half-width, at scale 1.0, of the widest pose this rig has.

    Cached per rig class. Each pose is drawn once, on first use of that character.
    """

    rig_class = type(rig).__name__
    cached = _REACH.get(rig_class)
    if cached is not None:
        return cached
    widest = 0.0
    for pose in _EXTENDED_POSES:
        try:
            silhouette = measure(rig, pose)
        except Exception:
            continue
        widest = max(widest, abs(silhouette.left), abs(silhouette.right))
    widest = widest or 140.0
    _REACH[rig_class] = widest
    return widest


def clear_cache() -> None:
    _CACHE.clear()
    _REACH.clear()
