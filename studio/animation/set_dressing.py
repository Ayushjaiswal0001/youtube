"""Near-camera set dressing that can actually get in the way.

The six locations had backgrounds and a bottom strip of grass, and the measured occlusion of the cast
by foreground scenery was **0.0 in all six**. Nothing was wrong with the drawing code: the foliage was
deliberately confined to the outer 12% of the frame so it could never cover anything. A location that
cannot occlude the cast is a backdrop, not an environment - a character can never be behind anything,
which is what makes a 2D scene read as flat.

This module draws *objects* instead of decoration: trunk sections, bushes, rocks, pillars, fences,
each with a real world position, a real depth and a real alpha silhouette. They are placed so that
some of them stand in front of the cast and some behind, and the renderer composites them through
``compositor.DrawQueue`` with the same two keys as everything else (layer, then world depth).

The occlusion they cause is then *measured*, not asserted: :func:`measure_occlusion` intersects the
alpha of the drawn dressing with the alpha of the drawn character and reports the fraction of the
character that is actually covered.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cairo

from studio.animation.compositor import Layer

Box = Tuple[float, float, float, float]

#: Kinds of near-camera object. Each is drawn as a filled silhouette with an optional rim, because
#: that is what reads as "in front of" in a polished-2D frame.
TRUNK = "trunk"
BUSH = "bush"
ROCK = "rock"
PILLAR = "pillar"
FENCE = "fence"
GRASS = "grass"
SHRUB = "shrub"

#: Foliage colours, in the muted palette the locations already use.
_DARK = (0.030, 0.035, 0.028)
_RIM = (0.62, 0.66, 0.55)
_ROCK = (0.16, 0.16, 0.19)
_ROCK_RIM = (0.42, 0.43, 0.48)


@dataclass(frozen=True)
class Dressing:
    """One near-camera object: where it stands, how big it is, and which layer it belongs to."""

    kind: str
    x: float
    width: float
    height: float
    #: World depth, used inside a layer. Larger is nearer the camera.
    depth: float
    layer: Layer
    seed: int = 0
    mirror: float = 1.0
    #: Body colour, derived from the location palette so near scenery belongs to its scene instead
    #: of punching a black hole in it. The first version filled every silhouette with near-black and
    #: the result read as damage to the frame, not as foliage.
    tint: Tuple[float, float, float] = (0.06, 0.08, 0.06)
    #: Rim-light colour, also from the location, so the object has an edge against its background.
    rim: Tuple[float, float, float] = (0.55, 0.62, 0.50)

    @property
    def box(self) -> Box:
        """Screen-space bounds of the object, for framing and occlusion measurement."""

        base = self.x
        return (base - self.width / 2.0, self.base_y - self.height, self.width, self.height)

    #: Filled in by :func:`dressing_for`: the ground line the object stands on.
    base_y: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return {"kind": self.kind, "x": round(self.x, 1), "width": round(self.width, 1),
                "height": round(self.height, 1), "depth": round(self.depth, 2),
                "layer": self.layer.name, "base_y": round(self.base_y, 1)}


def _mul(colour, amount: float) -> Tuple[float, float, float]:
    return (colour[0] * amount, colour[1] * amount, colour[2] * amount)


def _lighten(colour, amount: float) -> Tuple[float, float, float]:
    return (min(1.0, colour[0] + amount), min(1.0, colour[1] + amount),
            min(1.0, colour[2] + amount))


def _rng(name: str) -> random.Random:
    return random.Random(sum(ord(ch) * (i + 7) for i, ch in enumerate(name)))


def dressing_for(name: str, width: int, height: int, ground_y: float, *,
                 cast_boxes: Sequence[Box] = ()) -> List[Dressing]:
    """Place the near-camera set for one location.

    Three bands, chosen so the result is legible rather than busy:

    * **foreground** - two or three large objects near the lens, one of which deliberately overlaps
      the cast's lower body. Kept below ``0.72 * height`` so a face is never covered.
    * **mid** - a trunk or pillar standing *between* the two characters, which is what lets one of
      them be partially hidden without hiding the other.
    * **near ground** - small rocks and grass tufts that sit with the cast and give the floor a scale.

    ``cast_boxes`` is used only to avoid burying a whole character: an object that would cover more
    than half of an actor is moved aside. The occluder is intentional; an accident is not.
    """

    from studio.animation.environment import LOCATIONS
    location = LOCATIONS.get(name)
    # Near scenery is the location's own `near` colour, lifted until it is readable and then
    # darkened: a silhouette that is pure black stops being an object and starts being a hole.
    base = getattr(location, "near", (0.16, 0.32, 0.20))
    haze = getattr(location, "haze", (0.86, 0.93, 0.96))
    foliage = _mul(_lighten(base, 0.10), 0.72)
    rim = _lighten(haze, 0.0)
    stone = _mul(_lighten(getattr(location, "ground_top", (0.4, 0.4, 0.4)), 0.06), 0.80)
    # Trunks and pillars are built from the *mid* colour, not the near one: a silhouette mixed from
    # the darkest value in the palette came out as a black bar across the frame, which reads as
    # damage rather than as an object standing in front of the camera.
    bark = _mul(_lighten(getattr(location, "mid", (0.2, 0.3, 0.2)), 0.04), 0.94)
    stone_rim = _lighten(getattr(location, "ground_top", (0.4, 0.4, 0.4)), 0.18)

    rng = _rng(name)
    items: List[Dressing] = []

    # --- foreground ---------------------------------------------------------------------------
    # Deliberately restrained. The point is that near objects *can* cross the cast, not that they
    # bury them: grass and a low bush reach the knees and the frame edge, nothing reaches a face, and
    # the measured coverage lands in the low tens of percent rather than half the character.
    # One clump in front of each character's feet. The former single clump sat between the two
    # slots and covered neither, which is how a placement can look reasonable and occlude nothing.
    items.append(Dressing(GRASS, width * 0.3125, width * 0.155, height * 0.175, 3.0,
                          Layer.FOREGROUND, seed=rng.randrange(1000),
                          base_y=ground_y + height * 0.006, tint=foliage, rim=rim))
    # Narrower than the first character's clump on purpose: Gappu is a smaller rig, so the same
    # grass would cover most of him and the "do not bury a character" guard would delete it. This is
    # the size that clips his legs and leaves him readable.
    items.append(Dressing(GRASS, width * 0.6875, width * 0.095, height * 0.105, 3.1,
                          Layer.FOREGROUND, seed=rng.randrange(1000),
                          base_y=ground_y + height * 0.008, tint=foliage, rim=rim))
    # A low shrub at the outer edge of each character's feet: grass alone is a sliver, and a
    # silhouette that only ever clips an ankle is not something a character can walk behind.
    items.append(Dressing(SHRUB, width * 0.362, width * 0.13, height * 0.085, 2.6,
                          Layer.FOREGROUND, seed=rng.randrange(1000),
                          base_y=ground_y + height * 0.012, tint=_mul(foliage, 0.92), rim=rim))
    items.append(Dressing(BUSH, width * 0.035, width * 0.17, height * 0.145, 3.2,
                          Layer.FOREGROUND, seed=rng.randrange(1000),
                          base_y=ground_y + height * 0.035, tint=foliage, rim=rim))
    items.append(Dressing(BUSH, width * 0.985, width * 0.22, height * 0.17, 3.6,
                          Layer.FOREGROUND, seed=rng.randrange(1000),
                          base_y=ground_y + height * 0.05, mirror=-1.0,
                          tint=foliage, rim=rim))

    # --- mid: something to stand behind -------------------------------------------------------
    mid_kind = TRUNK if name not in ("haunted_haveli", "market_square") else PILLAR
    items.append(Dressing(mid_kind, width * 0.655, width * 0.052, height * 0.46,
                          ground_y + 6.0, Layer.ACTOR, seed=rng.randrange(1000),
                          base_y=ground_y + 6.0, tint=bark, rim=rim))
    items.append(Dressing(ROCK, width * 0.175, width * 0.10, height * 0.062, ground_y + 4.0,
                          Layer.ACTOR, seed=rng.randrange(1000), base_y=ground_y + 4.0,
                          tint=stone, rim=stone_rim))

    # Not every place grows the same thing. A cave mouth gets boulders, a riverbank gets reeds, and
    # the rest get bushes - so the six locations read as six places rather than one place in six
    # palettes, which is what an identical set in every location produced.
    if name in ("cave_entrance", "haunted_haveli"):
        items = [Dressing(ROCK, item.x, item.width * 0.92, item.height * 0.62, item.depth,
                          item.layer, seed=item.seed, mirror=item.mirror, base_y=item.base_y,
                          tint=stone, rim=stone_rim) if item.kind is BUSH else item
                 for item in items]
    elif name == "riverbank":
        items = [Dressing(GRASS, item.x, item.width * 0.86, item.height * 1.35, item.depth,
                          item.layer, seed=item.seed, mirror=item.mirror, base_y=item.base_y,
                          tint=foliage, rim=rim) if item.kind is BUSH else item
                 for item in items]

    # --- near ground: small things that share the floor with the cast ------------------------
    for index in range(4):
        items.append(Dressing(SHRUB, width * (0.10 + index * 0.25), width * 0.045,
                              height * (0.045 + 0.010 * (index % 3)), 0.7,
                              Layer.GROUND_PROP, seed=rng.randrange(1000),
                              base_y=ground_y + 2.0, tint=foliage, rim=rim))

    if cast_boxes:
        items = [item for item in items if _acceptable(item, cast_boxes)]
    return items


def _acceptable(item: Dressing, cast_boxes: Sequence[Box]) -> bool:
    """Refuse a foreground object that would hide more than half of any character."""

    if item.layer is not Layer.FOREGROUND:
        return True
    ox, oy, ow, oh = item.box
    for bx, by, bw, bh in cast_boxes:
        overlap_w = max(0.0, min(ox + ow, bx + bw) - max(ox, bx))
        overlap_h = max(0.0, min(oy + oh, by + bh) - max(oy, by))
        if bw <= 0 or bh <= 0:
            continue
        if (overlap_w * overlap_h) / (bw * bh) > 0.5:
            return False
    return True


# -- drawing ---------------------------------------------------------------------------------


def draw(cr: cairo.Context, item: Dressing, t: float = 0.0) -> None:
    """Draw one object as a filled alpha silhouette with a rim light."""

    drawer = {
        TRUNK: _trunk, BUSH: _bush, ROCK: _rock, PILLAR: _pillar,
        FENCE: _fence, GRASS: _grass, SHRUB: _shrub,
    }.get(item.kind)
    if drawer is None:
        return
    cr.save()
    cr.translate(item.x, item.base_y)
    cr.scale(item.mirror, 1.0)
    drawer(cr, item, t)
    cr.restore()


def draw_layer(cr: cairo.Context, items: Sequence[Dressing], layer: Layer, t: float = 0.0) -> int:
    """Draw every item in one layer, back to front, and report how many were drawn."""

    drawn = 0
    for item in sorted((i for i in items if i.layer is layer), key=lambda i: i.depth):
        draw(cr, item, t)
        drawn += 1
    return drawn


def _rim(cr: cairo.Context, width: float, item: Dressing) -> None:
    cr.set_source_rgba(*item.rim, 0.45)
    cr.set_line_width(width)
    cr.stroke_preserve()
    cr.set_source_rgba(*item.tint, 0.96)
    cr.fill()


def _bush(cr: cairo.Context, item: Dressing, t: float) -> None:
    rng = random.Random(item.seed)
    lobes = 5
    for index in range(lobes):
        cx = (index - (lobes - 1) / 2.0) * item.width * 0.17
        cy = -item.height * (0.42 + 0.22 * (0.5 + 0.5 * math.sin(item.seed + index)))
        radius = item.width * (0.17 + 0.05 * (index % 3))
        sway = math.sin(t * 0.9 + index) * 1.8
        cr.new_path()
        cr.arc(cx + sway, cy, radius, 0, math.tau)
        _rim(cr, 3.0, item)
    cr.new_path()
    cr.rectangle(-item.width * 0.44, -item.height * 0.30, item.width * 0.88, item.height * 0.30)
    cr.close_path()
    cr.set_source_rgba(*item.tint, 0.96)
    cr.fill()


def _shrub(cr: cairo.Context, item: Dressing, t: float) -> None:
    for index in range(3):
        cx = (index - 1) * item.width * 0.26
        radius = item.width * (0.26 - 0.03 * index)
        cr.new_path()
        cr.arc(cx, -radius * 0.85, radius, 0, math.tau)
        _rim(cr, 2.0, item)


def _grass(cr: cairo.Context, item: Dressing, t: float) -> None:
    rng = random.Random(item.seed)
    for index in range(13):
        spread = index - 6
        height = item.height * (0.55 + 0.45 * rng.random())
        sway = math.sin(t * 1.2 + index * 0.6) * 2.6
        cr.new_path()
        cr.move_to(spread * item.width * 0.085 - 3.2, 0.0)
        cr.curve_to(spread * item.width * 0.11 + sway * 0.4, -height * 0.6,
                    spread * item.width * 0.11 + sway, -height * 0.9,
                    spread * item.width * 0.11 + sway, -height)
        cr.line_to(spread * item.width * 0.085 + 3.2, 0.0)
        cr.close_path()
        cr.set_source_rgba(*item.tint, 0.95)
        cr.fill()


def _trunk(cr: cairo.Context, item: Dressing, t: float) -> None:
    half = item.width * 0.5
    cr.new_path()
    cr.move_to(-half, 0.0)
    cr.curve_to(-half * 0.82, -item.height * 0.55, -half * 0.9, -item.height * 0.82,
                -half * 0.58, -item.height)
    cr.line_to(half * 0.6, -item.height)
    cr.curve_to(half * 0.9, -item.height * 0.7, half * 0.84, -item.height * 0.4, half, 0.0)
    cr.close_path()
    _rim(cr, 4.0, item)
    # A soft vertical highlight down one side: without it the trunk is a flat black rectangle and
    # the eye reads it as a hole in the frame rather than as a cylinder lit from one side.
    cr.save()
    cr.rectangle(-half * 0.55, -item.height, half * 0.5, item.height)
    gradient = cairo.LinearGradient(-half * 0.55, 0.0, half * 0.0, 0.0)
    gradient.add_color_stop_rgba(0.0, *item.rim, 0.0)
    gradient.add_color_stop_rgba(0.5, *item.rim, 0.22)
    gradient.add_color_stop_rgba(1.0, *item.rim, 0.0)
    cr.set_source(gradient)
    cr.fill()
    cr.restore()

    # Two bark grooves so the silhouette is not a flat slab.
    cr.set_source_rgba(*item.rim, 0.20)
    cr.set_line_width(max(2.0, item.width * 0.045))
    for offset in (-0.18, 0.12, 0.32):
        cr.new_path()
        cr.move_to(half * offset, -item.height * 0.92)
        cr.curve_to(half * (offset + 0.08), -item.height * 0.6,
                    half * (offset - 0.06), -item.height * 0.3, half * offset, -4.0)
        cr.stroke()


def _pillar(cr: cairo.Context, item: Dressing, t: float) -> None:
    half = item.width * 0.5
    cr.new_path()
    cr.rectangle(-half, -item.height, item.width, item.height)
    _rim(cr, 3.5, item)
    # Shaft highlight, so a pillar in a night scene is stone and not a void.
    cr.rectangle(-half * 0.5, -item.height, half * 0.44, item.height)
    gradient = cairo.LinearGradient(-half * 0.5, 0.0, 0.0, 0.0)
    gradient.add_color_stop_rgba(0.0, *item.rim, 0.0)
    gradient.add_color_stop_rgba(0.55, *item.rim, 0.20)
    gradient.add_color_stop_rgba(1.0, *item.rim, 0.0)
    cr.set_source(gradient)
    cr.fill()
    cr.new_path()
    cr.rectangle(-half * 1.3, -item.height - item.width * 0.22, item.width * 1.3,
                 item.width * 0.22)
    cr.set_source_rgba(*item.tint, 0.96)
    cr.fill()
    cr.new_path()
    cr.rectangle(-half * 1.25, -item.width * 0.16, item.width * 1.25, item.width * 0.16)
    cr.fill()


def _rock(cr: cairo.Context, item: Dressing, t: float) -> None:
    rng = random.Random(item.seed)
    cr.new_path()
    cr.move_to(-item.width * 0.5, 0.0)
    steps = 7
    for index in range(1, steps + 1):
        x = -item.width * 0.5 + item.width * index / steps
        y = -item.height * (0.55 + 0.45 * math.sin(index * 1.7 + rng.random()))
        cr.line_to(x, y)
    cr.line_to(item.width * 0.5, 0.0)
    cr.close_path()
    cr.set_source_rgba(*item.rim, 0.5)
    cr.set_line_width(3.0)
    cr.stroke_preserve()
    cr.set_source_rgba(*item.tint, 0.98)
    cr.fill()


def _fence(cr: cairo.Context, item: Dressing, t: float) -> None:
    cr.set_source_rgba(*item.tint, 0.97)
    for index in range(4):
        x = -item.width * 0.5 + index * item.width / 3.0
        width = max(4.0, item.width * 0.055)
        cr.rectangle(x - width / 2.0, -item.height, width, item.height)
        cr.fill()
    cr.rectangle(-item.width * 0.5, -item.height * 0.72, item.width, item.height * 0.07)
    cr.fill()
    cr.rectangle(-item.width * 0.5, -item.height * 0.42, item.width, item.height * 0.07)
    cr.fill()


# -- measurement ------------------------------------------------------------------------------


def measure_occlusion(width: int, height: int, items: Sequence[Dressing],
                      actor_surfaces: Sequence[cairo.ImageSurface],
                      *, threshold: int = 24, head_fraction: float = 0.38) -> Dict[str, float]:
    """How much of each drawn character the drawn foreground actually covers.

    Both sides are measured from pixels: the foreground layer is rendered to a surface of its own and
    the character is rendered to another, and the answer is the ratio of shared opaque pixels to
    opaque character pixels. Comparing bounding boxes instead would report occlusion for an object
    that merely shares a rectangle with the character.
    """

    if not items:
        return {}
    layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(layer)
    draw_layer(cr, items, Layer.FOREGROUND, 0.0)
    layer.flush()
    fg = layer.get_data()
    stride = layer.get_stride()

    fractions: Dict[str, float] = {}
    for index, surface in enumerate(actor_surfaces):
        actor = surface.get_data()
        a_stride = surface.get_stride()
        # The head band is derived from the drawn silhouette, not from the rig: a face that is
        # covered must be found where the character was actually drawn.
        top, bottom = _alpha_rows(surface, threshold)
        head_limit = top + max(1.0, (bottom - top) * head_fraction)
        covered = total = 0
        head_covered = head_total = 0
        for y in range(0, height, 2):
            row = y * stride
            a_row = y * a_stride
            in_head = y <= head_limit
            for x in range(0, width, 2):
                if actor[a_row + x * 4 + 3] > threshold:
                    total += 1
                    hit = fg[row + x * 4 + 3] > threshold
                    if hit:
                        covered += 1
                    if in_head:
                        head_total += 1
                        if hit:
                            head_covered += 1
        fractions[f"actor{index}"] = round(covered / total, 4) if total else 0.0
        fractions[f"actor{index}_head"] = (round(head_covered / head_total, 4)
                                          if head_total else 0.0)
    return fractions


def _alpha_rows(surface: cairo.ImageSurface, threshold: int) -> Tuple[int, int]:
    data = surface.get_data()
    stride = surface.get_stride()
    width, height = surface.get_width(), surface.get_height()
    top, bottom = height, -1
    for y in range(0, height, 3):
        row = y * stride
        for x in range(0, width, 3):
            if data[row + x * 4 + 3] > threshold:
                top = min(top, y)
                bottom = max(bottom, y)
                break
    if bottom < 0:
        return (0, 0)
    return (top, bottom)


def describe(items: Sequence[Dressing]) -> Dict[str, object]:
    by_layer: Dict[str, int] = {}
    for item in items:
        by_layer[item.layer.name] = by_layer.get(item.layer.name, 0) + 1
    return {"count": len(items), "by_layer": by_layer,
            "kinds": sorted({item.kind for item in items}),
            "items": [item.as_dict() for item in items]}
