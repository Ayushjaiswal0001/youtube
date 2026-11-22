"""Lighting presets and directional shadows (T44).

The environment had a single hard-coded light direction and a single shadow shape. Two characters in
the same scene therefore shared one sun, a jumping character kept the shadow of a standing one, and
every time of day looked like the same time of day with a different palette.

This module is data, not effects: a preset is six numbers and a colour, and everything drawn from it
is derived from the light's geometry.

* ``ShadowGeometry`` computes where a body's shadow lands and how long it is from the light's
  elevation and the body's height above the floor. A character in the air casts a shadow further
  away, longer and softer than one standing - which is most of what makes a jump read as a jump.
* ``LightingPreset`` bundles direction, elevation, intensity, ambient, shadow opacity and softness,
  and a colour grade.
* ``apply_grade()`` tints the finished frame for the time of day. It is a single multiply-blended
  rectangle, not a per-pixel pass, because the target is polished 2D cartoon and the hardware is a
  laptop.

Everything defaults to the previous behaviour when no preset is passed, so existing renders keep
their exact output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cairo

Point = Tuple[float, float]
Rgb = Tuple[float, float, float]


@dataclass(frozen=True)
class ShadowGeometry:
    """Where a shadow goes and how it looks, derived from the light."""

    offset_x: float
    length: float
    opacity: float
    softness: float


@dataclass(frozen=True)
class LightingPreset:
    """A complete, reusable lighting setup."""

    name: str
    # Horizontal component of the light's ray *direction*: +1 means light comes from the left, so
    # shadows fall to the right.
    light_x: float
    # Degrees above the horizon. 90 is directly overhead (shadows under the feet); 8 is nearly
    # horizontal (very long shadows).
    elevation_deg: float
    ambient: float          # 0 = crushed blacks, 1 = washed out
    intensity: float        # multiplies shadow density
    shadow_opacity: float
    shadow_softness: float
    grade: Rgb              # multiply-blended tint
    grade_strength: float

    @property
    def elevation(self) -> float:
        return math.radians(self.elevation_deg)

    def shadow_for(self, height_above_ground: float, body_half_width: float,
                   ground_y: float) -> ShadowGeometry:
        """Shadow geometry for a body ``height_above_ground`` px off the floor.

        A body on the floor gets a contact shadow tucked under its feet. The higher it is, the
        further the shadow moves along the light direction, the longer it gets, and the softer and
        fainter it becomes - the three cues that tell a viewer something is in the air.
        """

        # tan(elevation) maps height to shadow length; clamp so a low sun does not produce an
        # infinite shadow.
        drop = max(0.0, height_above_ground)
        horizontal = drop / max(math.tan(self.elevation), 0.08)
        # Even a standing body casts a little to the side, otherwise the contact shadow hides
        # behind the character's own feet and there is no visible ground contact at all.
        offset = self.light_x * (8.0 + horizontal * 0.55)
        length = body_half_width * (1.0 + min(3.0, horizontal / max(40.0, body_half_width)))
        fade = 1.0 / (1.0 + drop / 160.0)
        opacity = self.shadow_opacity * self.intensity * fade
        softness = self.shadow_softness * (1.0 + min(2.5, drop / 120.0))
        return ShadowGeometry(offset_x=offset, length=length,
                              opacity=max(0.0, min(0.65, opacity)), softness=softness)


PRESETS: Dict[str, LightingPreset] = {
    "daylight": LightingPreset(
        name="daylight", light_x=1.0, elevation_deg=64.0, ambient=0.55, intensity=1.0,
        shadow_opacity=0.30, shadow_softness=1.0, grade=(1.0, 1.0, 1.0), grade_strength=0.0),
    "warm_afternoon": LightingPreset(
        name="warm_afternoon", light_x=1.0, elevation_deg=38.0, ambient=0.48, intensity=1.05,
        shadow_opacity=0.34, shadow_softness=1.15, grade=(1.06, 0.98, 0.86), grade_strength=0.22),
    "sunset": LightingPreset(
        name="sunset", light_x=1.0, elevation_deg=16.0, ambient=0.40, intensity=1.15,
        shadow_opacity=0.40, shadow_softness=1.35, grade=(1.10, 0.86, 0.70), grade_strength=0.34),
    "cool_evening": LightingPreset(
        name="cool_evening", light_x=-1.0, elevation_deg=22.0, ambient=0.34, intensity=0.95,
        shadow_opacity=0.30, shadow_softness=1.6, grade=(0.84, 0.90, 1.10), grade_strength=0.30),
    "indoor_warm": LightingPreset(
        name="indoor_warm", light_x=1.0, elevation_deg=52.0, ambient=0.44, intensity=0.9,
        shadow_opacity=0.26, shadow_softness=1.5, grade=(1.08, 0.94, 0.80), grade_strength=0.26),
    "moonlight": LightingPreset(
        name="moonlight", light_x=-1.0, elevation_deg=34.0, ambient=0.26, intensity=0.7,
        shadow_opacity=0.22, shadow_softness=2.0, grade=(0.78, 0.86, 1.16), grade_strength=0.34),
}

DEFAULT_PRESET = PRESETS["daylight"]


def preset_for(name: Optional[str]) -> LightingPreset:
    """Look up a preset by name, falling back to daylight rather than failing a render."""

    if not name:
        return DEFAULT_PRESET
    return PRESETS.get(str(name).strip().lower(), DEFAULT_PRESET)


def draw_shadow(cr: cairo.Context, preset: LightingPreset, *, x: float, ground_y: float,
                body_half_width: float, height_above_ground: float = 0.0) -> ShadowGeometry:
    """Draw one character or prop shadow on the floor, in world coordinates."""

    geom = preset.shadow_for(height_above_ground, body_half_width, ground_y)
    centre_x = x + geom.offset_x
    radius_x = max(18.0, geom.length)
    # A contact shadow is a flattened ellipse wider than the feet, so it reads as contact from the
    # side as well as from the front.
    radius_y = max(8.0, radius_x * (0.30 if height_above_ground < 1.0 else 0.18))

    cr.save()
    cr.translate(centre_x, ground_y)
    cr.scale(radius_x, radius_y)
    gradient = cairo.RadialGradient(0.0, 0.0, 0.05, 0.0, 0.0, 1.0)
    # Softness stretches the falloff: a hard sun has a tight penumbra, a high body a wide one.
    inner = max(0.02, 0.55 - 0.18 * geom.softness)
    gradient.add_color_stop_rgba(0.0, 0.02, 0.02, 0.05, geom.opacity)
    gradient.add_color_stop_rgba(inner, 0.02, 0.02, 0.05, geom.opacity * 0.82)
    gradient.add_color_stop_rgba(1.0, 0.02, 0.02, 0.05, 0.0)
    cr.set_source(gradient)
    cr.arc(0.0, 0.0, 1.0, 0.0, math.tau)
    cr.fill()
    cr.restore()
    return geom


def apply_grade(cr: cairo.Context, preset: LightingPreset, width: int, height: int) -> None:
    """Tint the finished frame for the time of day.

    One multiply-blended rectangle. A per-pixel grade would look the same and cost the render budget
    this project does not have.
    """

    if preset.grade_strength <= 0.0:
        return
    r, g, b = preset.grade
    strength = preset.grade_strength
    mix = lambda channel: 1.0 + (channel - 1.0) * strength  # noqa: E731
    cr.save()
    cr.set_operator(cairo.OPERATOR_MULTIPLY)
    cr.set_source_rgba(mix(r), mix(g), mix(b), 1.0)
    cr.rectangle(0.0, 0.0, float(width), float(height))
    cr.fill()
    cr.restore()


def ambient_overlay(cr: cairo.Context, preset: LightingPreset, width: int, height: int) -> None:
    """Lift or crush the blacks without touching the highlights."""

    if preset.ambient >= 0.6:
        return
    cr.save()
    cr.set_operator(cairo.OPERATOR_OVER)
    lift = (0.6 - preset.ambient) * 0.16
    cr.set_source_rgba(0.02, 0.03, 0.06, lift)
    cr.rectangle(0.0, 0.0, float(width), float(height))
    cr.fill()
    cr.restore()


def describe(preset: LightingPreset) -> Dict[str, float | str]:
    """Machine-readable description, for reports and tests."""

    return {"name": preset.name, "light_x": preset.light_x,
            "elevation_deg": preset.elevation_deg, "ambient": preset.ambient,
            "intensity": preset.intensity, "shadow_opacity": preset.shadow_opacity,
            "shadow_softness": preset.shadow_softness, "grade_strength": preset.grade_strength}
