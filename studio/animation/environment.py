"""Multi-layer 16:9 environments for landscape character scenes (T41).

The portrait backgrounds are vertical compositions: sky at the top, ground at the bottom, scenery
stacked up the frame. Drawing one of those into a 1920x1080 frame would show a narrow slice of it,
which is why the landscape renderer has so far drawn cards and diagrams instead of characters.

This module is a different composition, not a wider one:

    sky (parallax 0.15)  ->  far range (0.25)  ->  mid scenery (0.5)  ->  horizon haze (0.6)
    ->  ground and path (0.85)  ->  motes (0.9)  ->  [characters, parallax 1.0]  ->  foreground (1.15)

The last layer matters most: something drawn *in front of* the cast is what makes them stand inside
the picture rather than on top of it. Parallax factors are applied to the camera pan, so the far
layers slide less than the cast and the foreground slides more.

Every layer is authored to bleed past the frame edges, so the widest landscape shot the stage
allows (zoom 0.62) still shows painted world rather than blank canvas - the portrait stage cannot
do that, which is why its zoom floor is 0.85.

Costs are deliberately bounded: each layer is a handful of filled paths, and the atmospheric layer
is a fixed number of motes. No per-pixel work, no blur filters.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Tuple

import cairo

# Where the horizon sits, in the same world coordinates the characters stand in. The stage puts
# feet at 1028, so the floor occupies the bottom half of the frame and the sky the top.
HORIZON_Y = 470.0

# Layers are drawn this much wider/taller than the frame on every side. At the minimum landscape
# zoom the visible world is 1/0.62 = 1.61 frames wide, so 1.8 leaves margin for the parallax slide.
BLEED = 1.8

LIGHT_DIRECTION = -1.0   # shadows fall to the left


@dataclass(frozen=True)
class Location:
    """Palette and scenery selection for one environment."""

    sky_top: Tuple[float, float, float]
    sky_bottom: Tuple[float, float, float]
    far: Tuple[float, float, float]
    mid: Tuple[float, float, float]
    near: Tuple[float, float, float]
    ground_top: Tuple[float, float, float]
    ground_bottom: Tuple[float, float, float]
    path: Tuple[float, float, float]
    haze: Tuple[float, float, float]
    accent: Tuple[float, float, float]
    silhouette: str = "trees"
    moon: bool = False
    fireflies: bool = False
    mist: bool = True
    leaves: bool = True


LOCATIONS: Dict[str, Location] = {
    "haunted_haveli": Location(
        sky_top=(0.06, 0.07, 0.14), sky_bottom=(0.20, 0.17, 0.28),
        far=(0.11, 0.11, 0.19), mid=(0.16, 0.15, 0.24), near=(0.09, 0.09, 0.14),
        ground_top=(0.20, 0.19, 0.25), ground_bottom=(0.10, 0.10, 0.13),
        path=(0.26, 0.25, 0.30), haze=(0.30, 0.30, 0.42),
        accent=(0.85, 0.78, 0.45), silhouette="ruins", moon=True,
    ),
    "jungle_clearing": Location(
        sky_top=(0.36, 0.66, 0.88), sky_bottom=(0.76, 0.90, 0.96),
        far=(0.36, 0.55, 0.45), mid=(0.24, 0.45, 0.32), near=(0.16, 0.32, 0.20),
        ground_top=(0.46, 0.62, 0.33), ground_bottom=(0.30, 0.45, 0.24),
        path=(0.72, 0.65, 0.42), haze=(0.86, 0.93, 0.96),
        accent=(0.98, 0.85, 0.30), silhouette="trees", fireflies=True,
    ),
    "forest_path": Location(
        sky_top=(0.22, 0.36, 0.30), sky_bottom=(0.55, 0.70, 0.55),
        far=(0.22, 0.34, 0.26), mid=(0.15, 0.26, 0.19), near=(0.10, 0.18, 0.13),
        ground_top=(0.34, 0.44, 0.26), ground_bottom=(0.20, 0.28, 0.17),
        path=(0.55, 0.50, 0.36), haze=(0.72, 0.82, 0.72),
        accent=(0.90, 0.80, 0.40), silhouette="trees",
    ),
    "riverbank": Location(
        sky_top=(0.42, 0.68, 0.86), sky_bottom=(0.82, 0.92, 0.95),
        far=(0.40, 0.52, 0.55), mid=(0.30, 0.46, 0.38), near=(0.20, 0.34, 0.26),
        ground_top=(0.62, 0.70, 0.50), ground_bottom=(0.42, 0.50, 0.36),
        path=(0.50, 0.72, 0.82), haze=(0.88, 0.94, 0.96),
        accent=(0.98, 0.90, 0.55), silhouette="hills", mist=False,
    ),
    "cave_entrance": Location(
        sky_top=(0.10, 0.09, 0.12), sky_bottom=(0.22, 0.18, 0.20),
        far=(0.15, 0.13, 0.16), mid=(0.20, 0.17, 0.19), near=(0.11, 0.10, 0.12),
        ground_top=(0.26, 0.23, 0.24), ground_bottom=(0.14, 0.13, 0.14),
        path=(0.24, 0.21, 0.22), haze=(0.35, 0.32, 0.40),
        accent=(0.55, 0.75, 0.85), silhouette="hills", mist=False, leaves=False,
    ),
    "village_night": Location(
        sky_top=(0.05, 0.07, 0.16), sky_bottom=(0.13, 0.16, 0.30),
        far=(0.10, 0.12, 0.22), mid=(0.14, 0.16, 0.26), near=(0.08, 0.09, 0.15),
        ground_top=(0.22, 0.22, 0.28), ground_bottom=(0.12, 0.12, 0.17),
        path=(0.30, 0.29, 0.33), haze=(0.30, 0.34, 0.50),
        accent=(0.95, 0.80, 0.45), silhouette="ruins", moon=True, fireflies=True,
    ),
}

DEFAULT_LOCATION = LOCATIONS["jungle_clearing"]


class LandscapeEnvironment:
    """Draws a 16:9 environment that a staged cast can stand inside.

    The call signature mirrors ``BackgroundRenderer.render_by_name`` so the scene renderer can use
    either without knowing which one it has.
    """

    # A landscape environment paints a floor, so a cast standing on it can cast shadows. The
    # portrait backgrounds do not, and the scene renderer asks before drawing any.
    casts_shadows = True

    def __init__(self, width: int = 1920, height: int = 1080, ground_y: float = 1028.0):
        self.width = width
        self.height = height
        self.ground_y = ground_y

    # -- interface ----------------------------------------------------------

    def render_by_name(self, name: str, cr: cairo.Context, t: float,
                       camera_x: float = 0.0, camera_y: float = 0.0, zoom: float = 1.0):
        location = LOCATIONS.get(name, DEFAULT_LOCATION)
        cr.save()
        cr.translate(self.width / 2.0, self.height / 2.0)
        cr.scale(zoom, zoom)
        cr.translate(-self.width / 2.0, -self.height / 2.0)
        self._layers(cr, location, t, camera_x, camera_y, zoom, name)
        cr.restore()

    def draw_character_shadow(self, cr: cairo.Context, x: float, y: float, half_width: float,
                              height: float, alpha: float = 0.26,
                              lighting=None) -> None:
        """A soft contact shadow on the floor, offset away from the light.

        Drawn before the cast, in world coordinates under the camera, so it stays attached to the
        feet while the camera moves. When a ``LightingPreset`` is supplied (T44) the shadow's
        direction, length, softness and opacity come from the light and from how far the body is off
        the floor; without one the original behaviour is unchanged.
        """

        if lighting is not None:
            from studio.animation.lighting import draw_shadow
            draw_shadow(cr, lighting, x=x, ground_y=y, body_half_width=half_width,
                        height_above_ground=max(0.0, height))
            return

        radius_x = max(28.0, half_width * 1.15)
        radius_y = max(9.0, radius_x * 0.26)
        cr.save()
        cr.translate(x + LIGHT_DIRECTION * radius_x * 0.35, y)
        cr.scale(radius_x, radius_y)
        gradient = cairo.RadialGradient(0.0, 0.0, 0.05, 0.0, 0.0, 1.0)
        gradient.add_color_stop_rgba(0.0, 0.02, 0.02, 0.05, alpha)
        gradient.add_color_stop_rgba(1.0, 0.02, 0.02, 0.05, 0.0)
        cr.set_source(gradient)
        cr.arc(0.0, 0.0, 1.0, 0.0, math.tau)
        cr.fill()
        cr.restore()

    # -- layers -------------------------------------------------------------

    def _layers(self, cr, location: Location, t: float, camera_x: float, camera_y: float,
                zoom: float, name: str) -> None:
        w, h = self.width, self.height
        factor_scale = 1.0 / max(0.35, zoom)   # keeps parallax travel sensible when pulled back

        # 1. Sky. Drawn from well above the frame so the widest shot is still painted sky.
        gradient = cairo.LinearGradient(0.0, -h * 0.4, 0.0, HORIZON_Y + 40.0)
        gradient.add_color_stop_rgb(0.0, *location.sky_top)
        gradient.add_color_stop_rgb(1.0, *location.sky_bottom)
        cr.set_source(gradient)
        cr.rectangle(-w * BLEED, -h * BLEED, w * (1 + 2 * BLEED), (HORIZON_Y + 40.0) + h * BLEED)
        cr.fill()

        self._celestial(cr, location, t, camera_x * 0.12 * factor_scale, camera_y * 0.12)

        # 2. Far range: the picture's depth cue. Blended toward the sky so it reads as distance.
        self._parallax(cr, 0.25, camera_x, camera_y, factor_scale,
                       lambda: self._far_range(cr, location, w, h))
        # 3. Mid scenery.
        self._parallax(cr, 0.50, camera_x, camera_y, factor_scale,
                       lambda: self._mid_scenery(cr, location, w, h, t))
        # 4. Ground and the path across it.
        self._parallax(cr, 0.85, camera_x, camera_y, factor_scale,
                       lambda: self._ground(cr, location, w, h, name))
        # 5. Horizon haze, drawn after the ground so distance dissolves into it.
        if location.mist:
            self._parallax(cr, 0.60, camera_x, camera_y, factor_scale,
                           lambda: self._haze(cr, location, w, h, t))
        # 6. Atmosphere.
        if location.fireflies:
            self._parallax(cr, 0.90, camera_x, camera_y, factor_scale,
                           lambda: self._motes(cr, location, w, h, t))

    def _parallax(self, cr, factor: float, camera_x: float, camera_y: float,
                  factor_scale: float, draw) -> None:
        cr.save()
        cr.translate(-camera_x * factor * factor_scale, -camera_y * factor * factor_scale)
        draw()
        cr.restore()

    # -- individual layers --------------------------------------------------

    def _celestial(self, cr, location: Location, t: float, camera_x: float,
                   camera_y: float) -> None:
        """Sun, moon, or the glow that stands in for one, plus a couple of drifting clouds."""

        w = self.width
        x = w * 0.72 - camera_x
        y = HORIZON_Y - 150.0 - camera_y * 0.4
        if location.moon:
            stars = random.Random(31)
            for _ in range(70):
                sx = stars.uniform(-w * 0.3, w * 1.3) - camera_x * 0.06
                sy = stars.uniform(HORIZON_Y * 0.05, HORIZON_Y * 0.85)
                twinkle = 0.35 + 0.35 * math.sin(t * 1.7 + sx)
                cr.set_source_rgba(1.0, 1.0, 0.95, twinkle)
                cr.arc(sx, sy, stars.uniform(0.8, 2.0), 0.0, math.tau)
                cr.fill()
            glow = cairo.RadialGradient(x, y, 10.0, x, y, 190.0)
            glow.add_color_stop_rgba(0.0, *location.accent, 0.35)
            glow.add_color_stop_rgba(1.0, *location.accent, 0.0)
            cr.set_source(glow)
            cr.arc(x, y, 190.0, 0.0, math.tau)
            cr.fill()
            cr.set_source_rgb(*location.accent)
            cr.arc(x, y, 46.0, 0.0, math.tau)
            cr.fill()
            # A moon should have a face of shade, or it reads as a lamp.
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.10)
            cr.arc(x - 16.0, y - 10.0, 38.0, 0.0, math.tau)
            cr.fill()
        else:
            glow = cairo.RadialGradient(x, y, 20.0, x, y, 260.0)
            glow.add_color_stop_rgba(0.0, *location.accent, 0.30)
            glow.add_color_stop_rgba(1.0, *location.accent, 0.0)
            cr.set_source(glow)
            cr.arc(x, y, 260.0, 0.0, math.tau)
            cr.fill()

        for index, (offset, scale, speed) in enumerate(((0.18, 1.0, 0.010), (0.62, 0.7, 0.014))):
            drift = (t * speed * self.width) % (self.width * 1.6)
            cx = (self.width * offset + drift) % (self.width * 1.4) - self.width * 0.2
            self._cloud(cr, cx - camera_x * 0.5, HORIZON_Y - 210.0 - index * 70.0,
                        110.0 * scale, alpha=0.22 if index else 0.3)

    @staticmethod
    def _cloud(cr, x: float, y: float, size: float, alpha: float) -> None:
        cr.set_source_rgba(1.0, 1.0, 1.0, alpha)
        for dx, dy, s in ((0.0, 0.0, 1.0), (-0.7, 0.15, 0.7), (0.7, 0.12, 0.75)):
            cr.save()
            cr.translate(x + dx * size, y + dy * size)
            cr.scale(size * s, size * s * 0.55)
            cr.arc(0.0, 0.0, 1.0, 0.0, math.tau)
            cr.fill()
            cr.restore()

    @staticmethod
    def _mixed(colour, other, amount: float):
        return tuple(c * (1.0 - amount) + o * amount for c, o in zip(colour, other))

    def _far_range(self, cr, location: Location, w: int, h: int) -> None:
        # Two ridges, the farther one mixed further toward the sky. A single flat silhouette on a
        # dark sky reads as a jagged edge with no distance in it, which is what the first probe
        # render showed.
        self._ridge(cr, self._mixed(location.far, location.sky_bottom, 0.55), w, -60.0, 190.0, 11)
        self._ridge(cr, location.far, w, 0.0, 130.0, 17)

    def _ridge(self, cr, colour, w: int, offset_y: float, height: float, teeth: int) -> None:
        cr.set_source_rgb(*colour)
        cr.new_path()
        cr.move_to(-w * BLEED, HORIZON_Y + offset_y)
        step = w / float(teeth)
        seed = random.Random(7 + teeth)
        x = -w * BLEED
        while x < w * (1 + BLEED):
            peak = HORIZON_Y + offset_y - 40.0 - seed.random() * height
            cr.line_to(x + step * 0.5, peak)
            cr.line_to(x + step, HORIZON_Y + offset_y - seed.random() * 25.0)
            x += step
        cr.line_to(w * (1 + BLEED), HORIZON_Y + offset_y)
        cr.line_to(w * (1 + BLEED), HORIZON_Y + offset_y + 80.0)
        cr.line_to(-w * BLEED, HORIZON_Y + offset_y + 80.0)
        cr.close_path()
        cr.fill()

    def _mid_scenery(self, cr, location: Location, w: int, h: int, t: float) -> None:
        kind = location.silhouette
        seed = random.Random(23)
        count = 7 if kind != "ruins" else 4
        for index in range(count):
            x = -w * 0.4 + index * (w * 1.8 / count) + seed.uniform(-60.0, 60.0)
            if kind == "trees":
                self._tree(cr, location, x, HORIZON_Y + 26.0, 150.0 + seed.random() * 90.0,
                           sway=math.sin(t * 0.9 + index) * 3.0)
            elif kind == "hills":
                self._hill(cr, location, x, HORIZON_Y + 20.0, 260.0 + seed.random() * 120.0)
            else:
                self._ruin(cr, location, x, HORIZON_Y + 30.0, 190.0 + seed.random() * 70.0,
                           lit=(index % 2 == 0))

    @staticmethod
    def _tree(cr, location: Location, x: float, base_y: float, height: float,
              sway: float = 0.0) -> None:
        # A rim light on the side facing the moon separates the mid-ground from the far range. In
        # the first probe they were the same value and the scenery disappeared.
        cr.set_source_rgba(*location.haze, 0.35)
        cr.new_path()
        cr.move_to(x - height * 0.44 + sway, base_y - height * 0.44)
        cr.curve_to(x - height * 0.32 + sway, base_y - height * 1.04,
                    x + height * 0.32 + sway, base_y - height * 1.04,
                    x + height * 0.44 + sway, base_y - height * 0.44)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(*location.mid)
        cr.rectangle(x - height * 0.05, base_y - height * 0.55, height * 0.1, height * 0.55)
        cr.fill()
        cr.new_path()
        cr.move_to(x - height * 0.42 + sway, base_y - height * 0.45)
        cr.curve_to(x - height * 0.30 + sway, base_y - height * 1.02,
                    x + height * 0.30 + sway, base_y - height * 1.02,
                    x + height * 0.42 + sway, base_y - height * 0.45)
        cr.close_path()
        cr.fill()

    @staticmethod
    def _hill(cr, location: Location, x: float, base_y: float, width: float) -> None:
        cr.set_source_rgb(*location.mid)
        cr.new_path()
        cr.move_to(x - width / 2.0, base_y)
        cr.curve_to(x - width * 0.2, base_y - width * 0.55,
                    x + width * 0.2, base_y - width * 0.55,
                    x + width / 2.0, base_y)
        cr.close_path()
        cr.fill()

    @staticmethod
    def _ruin(cr, location: Location, x: float, base_y: float, height: float,
              lit: bool = False) -> None:
        """A broken haveli tower: a block with a crenellated top and one lit window."""

        width = height * 0.34
        cr.set_source_rgb(*location.mid)
        cr.rectangle(x - width / 2.0, base_y - height, width, height)
        cr.fill()
        for step in range(3):
            cr.rectangle(x - width / 2.0 + step * width / 3.0, base_y - height - height * 0.10,
                         width / 4.5, height * 0.10)
            cr.fill()
        if lit:
            cr.set_source_rgba(*location.accent, 0.75)
            cr.rectangle(x - width * 0.12, base_y - height * 0.72, width * 0.24, height * 0.14)
            cr.fill()

    def _ground(self, cr, location: Location, w: int, h: int, name: str) -> None:
        gradient = cairo.LinearGradient(0.0, HORIZON_Y, 0.0, h * (1 + BLEED))
        gradient.add_color_stop_rgb(0.0, *location.ground_top)
        gradient.add_color_stop_rgb(1.0, *location.ground_bottom)
        cr.set_source(gradient)
        cr.rectangle(-w * BLEED, HORIZON_Y, w * (1 + 2 * BLEED), h * (1 + BLEED) - HORIZON_Y)
        cr.fill()

        # Distance haze: the floor lightens toward the horizon, which is what stops the ground
        # reading as a flat wall.
        haze = cairo.LinearGradient(0.0, HORIZON_Y, 0.0, HORIZON_Y + 260.0)
        haze.add_color_stop_rgba(0.0, *location.haze, 0.30)
        haze.add_color_stop_rgba(1.0, *location.haze, 0.0)
        cr.set_source(haze)
        cr.rectangle(-w * BLEED, HORIZON_Y, w * (1 + 2 * BLEED), 260.0)
        cr.fill()

        if name != "riverbank":
            # A path converging on the horizon: the cheapest honest depth cue in 2D.
            cr.set_source_rgba(*location.path, 0.5)
            cr.new_path()
            cr.move_to(-w * 0.30, h * (1 + BLEED))
            cr.line_to(w * 0.12, HORIZON_Y + 6.0)
            cr.line_to(w * 0.52, HORIZON_Y + 6.0)
            cr.line_to(w * 0.92, h * (1 + BLEED))
            cr.close_path()
            cr.fill()

        # Perspective-spaced ground strokes: wide near the bottom, tight at the horizon.
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.07)
        rows = 14
        for row in range(rows):
            ratio = (row + 1) / float(rows)
            y = HORIZON_Y + (h * (1 + BLEED) - HORIZON_Y) * ratio * ratio
            thickness = 1.0 + 6.0 * ratio
            cr.rectangle(-w * BLEED, y, w * (1 + 2 * BLEED), thickness)
        cr.fill()

    def _haze(self, cr, location: Location, w: int, h: int, t: float) -> None:
        for index in range(3):
            alpha = 0.10 + 0.03 * math.sin(t * 0.5 + index)
            y = HORIZON_Y - 30.0 + index * 46.0
            gradient = cairo.LinearGradient(0.0, y - 40.0, 0.0, y + 60.0)
            gradient.add_color_stop_rgba(0.0, *location.haze, 0.0)
            gradient.add_color_stop_rgba(0.5, *location.haze, alpha)
            gradient.add_color_stop_rgba(1.0, *location.haze, 0.0)
            cr.set_source(gradient)
            cr.rectangle(-w * BLEED, y - 40.0, w * (1 + 2 * BLEED), 100.0)
            cr.fill()

    def _motes(self, cr, location: Location, w: int, h: int, t: float) -> None:
        seed = random.Random(91)
        for index in range(26):
            base_x = seed.uniform(-w * 0.4, w * 1.4)
            base_y = seed.uniform(HORIZON_Y - 40.0, h * 0.9)
            phase = seed.uniform(0.0, math.tau)
            x = base_x + math.sin(t * 0.5 + phase) * 26.0
            y = base_y + math.cos(t * 0.4 + phase) * 18.0
            alpha = 0.25 + 0.25 * math.sin(t * 1.6 + phase)
            cr.set_source_rgba(*location.accent, max(0.0, alpha))
            cr.arc(x, y, 2.5 + (index % 3), 0.0, math.tau)
            cr.fill()


class ForegroundLayer:
    """Near-camera foliage, drawn after the cast so characters stand *inside* the scene.

    Kept separate from the environment because the scene renderer has to draw it after the rigs,
    and because it must not move with the same parallax as the floor.
    """

    casts_shadows = False

    def __init__(self, width: int = 1920, height: int = 1080, ground_y: float = 1028.0):
        self.width = width
        self.height = height
        self.ground_y = ground_y

    def render_by_name(self, name: str, cr: cairo.Context, t: float,
                       camera_x: float = 0.0, camera_y: float = 0.0, zoom: float = 1.0):
        location = LOCATIONS.get(name, DEFAULT_LOCATION)
        if not location.leaves:
            return
        cr.save()
        cr.translate(self.width / 2.0, self.height / 2.0)
        cr.scale(zoom, zoom)
        cr.translate(-self.width / 2.0, -self.height / 2.0)
        cr.translate(-camera_x * 1.15, -camera_y * 1.15)

        w, h = self.width, self.height
        seed = random.Random(5)
        # Clustered toward the frame edges: near foliage frames a shot, and foliage across the
        # middle of it hides the characters' feet.
        for index in range(8):
            edge = index % 2 == 0
            slot = index // 2
            # Confined to the outer 12% on each side, which is exactly where the caption band is
            # not: a blade reaching into the band competes with the line the scene is carried by.
            x = ((-w * 0.14) + slot * (w * 0.07)) if edge else (w * 1.14 - slot * (w * 0.07))
            x += seed.uniform(-18.0, 18.0)
            leaves = 5 + index % 3
            for leaf in range(leaves):
                spread = (leaf - (leaves - 1) / 2.0)
                # Kept below the caption zone: foreground foliage that grows into the band
                # competes with the words the scene is being carried by (first stage render).
                height = 44.0 + seed.random() * 62.0 + abs(spread) * 4.0
                sway = math.sin(t * 0.8 + index * 0.7 + leaf * 0.4) * 7.0
                tip_x = x + spread * 26.0 + sway
                tip_y = h - height
                # A rim, then the blade over it: near foliage in the dark needs to be lit by
                # something or it disappears into the floor.
                for pass_index in range(2):
                    if pass_index == 0:
                        cr.set_source_rgba(*location.haze, 0.5)
                        grow = 4.0
                    else:
                        cr.set_source_rgba(0.02, 0.02, 0.03, 0.95)
                        grow = 0.0
                    cr.new_path()
                    cr.move_to(x + spread * 22.0 - 13.0 - grow, h)
                    cr.curve_to(x + spread * 24.0 - 15.0 + sway, h - height * 0.55,
                                tip_x - 4.0 - grow, tip_y + height * 0.15,
                                tip_x, tip_y - grow)
                    cr.curve_to(tip_x + 6.0 + grow, tip_y + height * 0.2,
                                x + spread * 22.0 + 15.0 + sway, h - height * 0.5,
                                x + spread * 22.0 + 13.0 + grow, h)
                    cr.close_path()
                    cr.fill()
        cr.restore()
