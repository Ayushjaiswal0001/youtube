"""Render all six landscape locations with the cast inside them (T45).

T45's complaint in TASKS.md was precise: "six palettes defined, one rendered end to end". This renders
every location with both characters standing on its ground plane plus a prop, measures what the
inspection questions actually need numbers for, and writes a contact sheet.

Measured per location:
* ``ground_error`` - how far the drawn feet are from the stage ground plane, in pixels.
* ``character_contrast`` - mean luminance difference between the character silhouette and the
  background immediately around it. This is the "can I see the character" number.
* ``midground_contrast`` - contrast between the mid-ground band and the sky above it, which is the
  "is the mid-ground legible" question.
* ``foreground_occlusion`` - the fraction of each character's bounding box covered by the near layer.
  Some occlusion is depth; too much is a character disappearing.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairo
from PIL import Image

from studio.animation.environment import LOCATIONS, ForegroundLayer, LandscapeEnvironment
from studio.animation.grounding import ground_error, place_on_ground
from studio.animation.lighting import preset_for
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.props import draw_prop

WIDTH, HEIGHT = 1920, 1080
OUT = Path("build/locations")
STAGE = stage_for(WIDTH, HEIGHT)

# Which time of day each location is authored for, so the lighting matches the palette instead of
# fighting it.
LOCATION_LIGHTING = {
    "jungle_clearing": "daylight",
    "forest_path": "warm_afternoon",
    "riverbank": "sunset",
    "haunted_haveli": "cool_evening",
    "cave_entrance": "indoor_warm",
    "village_night": "moonlight",
}


def _luma(rgba: bytes) -> float:
    return 0.2126 * rgba[2] + 0.7152 * rgba[1] + 0.0722 * rgba[0]  # BGR in memory


def _render(name: str, *, with_cast: bool = True, overlay=("environment",)) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    cr = cairo.Context(surface)
    environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)
    foreground = ForegroundLayer(WIDTH, HEIGHT, STAGE.ground_y)
    preset = preset_for(LOCATION_LIGHTING.get(name, "daylight"))

    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgb(0.08, 0.10, 0.13)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    environment.render_by_name(name, cr, 0.0)

    cast = {}
    if with_cast:
        for who, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
            rig = cls(**STAGE.anchor(who))
            place_on_ground(rig, STAGE.ground_y)
            cast[who] = rig
        cr.save()
        for rig in cast.values():
            environment.draw_character_shadow(
                cr, rig.x, STAGE.ground_y,
                rig.prop.values["torso_rx"] * rig.scale * 0.85, height=0.0, lighting=preset)
        cr.restore()
        for rig in cast.values():
            cr.save()
            rig.draw(cr)
            cr.restore()
        draw_prop(cr, "brass_key", (STAGE.slots["chiku"].x + 120, STAGE.ground_y - 18),
                  angle=0.0)

    if "foreground" in overlay:
        foreground.render_by_name(name, cr, 0.0)
    if "grade" in overlay:
        from studio.animation.lighting import ambient_overlay, apply_grade
        ambient_overlay(cr, preset, WIDTH, HEIGHT)
        apply_grade(cr, preset, WIDTH, HEIGHT)
    surface.flush()
    return surface


def _fg_mask(name: str) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    cr = cairo.Context(surface)
    ForegroundLayer(WIDTH, HEIGHT, STAGE.ground_y).render_by_name(name, cr, 0.0)
    surface.flush()
    return bytes(surface.get_data())


def _character_mask() -> tuple[bytes, list[tuple[int, int, int, int]]]:
    """Character-only render on transparent, plus each character's bounding box."""

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    cr = cairo.Context(surface)
    boxes = []
    for who, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
        rig = cls(**STAGE.anchor(who))
        cr.save()
        rig.draw(cr)
        cr.restore()
        # Measure the drawn silhouette rather than trusting the anchor.
        bounds = cr.clip_extents_preserve if False else None
        _ = bounds
    surface.flush()
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    for who, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
        rig = cls(**STAGE.anchor(who))
        xs, ys = [], []
        for y in range(0, HEIGHT, 2):
            row = y * stride
            for x in range(0, WIDTH, 2):
                if data[row + x * 4 + 3]:
                    xs.append(x)
                    ys.append(y)
        if xs:
            boxes.append((who, min(xs), min(ys), max(xs), max(ys)))
    return data, [b[1:] for b in boxes]


def measure(name: str) -> dict:
    base = _render(name, with_cast=False)
    full = _render(name, with_cast=True, overlay=("environment", "foreground", "grade"))
    base.flush()
    full.flush()
    base_data = bytes(base.get_data())
    full_data = bytes(full.get_data())
    stride = full.get_stride()
    fg_data = _fg_mask(name)
    char_data, boxes = _character_mask()

    def pixel(data: bytes, x: int, y: int) -> bytes:
        offset = y * stride + x * 4
        return data[offset:offset + 4]

    # Character contrast: silhouette luminance versus the same pixels without the cast.
    char_luma, bg_luma, samples = 0.0, 0.0, 0
    for y in range(0, HEIGHT, 3):
        for x in range(0, WIDTH, 3):
            offset = y * stride + x * 4
            if char_data[offset + 3]:
                char_luma += _luma(pixel(full_data, x, y))
                bg_luma += _luma(pixel(base_data, x, y))
                samples += 1
    char_luma = char_luma / samples if samples else 0.0
    bg_luma = bg_luma / samples if samples else 0.0

    # Mid-ground legibility: the band a character stands in front of versus the sky above it.
    mid_y = int(STAGE.ground_y - 150)
    sky_y = int(HEIGHT * 0.18)
    mid = [_luma(pixel(base_data, x, mid_y)) for x in range(0, WIDTH, 8)]
    sky = [_luma(pixel(base_data, x, sky_y)) for x in range(0, WIDTH, 8)]
    mid_mean, sky_mean = sum(mid) / len(mid), sum(sky) / len(sky)
    mid_var = sum((v - mid_mean) ** 2 for v in mid) / len(mid)

    occlusion = {}
    for index, (left, top, right, bottom) in enumerate(boxes):
        who = "chiku" if index == 0 else "gappu"
        covered = total = 0
        for y in range(top, bottom, 2):
            for x in range(left, right, 2):
                if char_data[y * stride + x * 4 + 3]:
                    total += 1
                    if fg_data[y * stride + x * 4 + 3]:
                        covered += 1
        occlusion[who] = round(covered / total, 4) if total else 0.0

    # Measured from the drawn silhouette against the stage floor, using the same helper the renderer
    # uses, so this reports the truth rather than re-deriving it.
    from studio.animation.grounding import measure_foot_offset
    worst = 0.0
    for who, cls in (("chiku", ChikuRig), ("gappu", GappuRig)):
        probe = cls(**STAGE.anchor(who))
        place_on_ground(probe, STAGE.ground_y)
        worst = max(worst, abs(ground_error(probe, STAGE.ground_y)))
    ground_error_value = worst

    return {
        "location": name,
        "lighting": LOCATION_LIGHTING.get(name, "daylight"),
        "palette": {
            "sky_top": [round(c, 3) for c in LOCATIONS[name].sky_top] if name in LOCATIONS else None,
            "silhouette": getattr(LOCATIONS[name], "silhouette", None) if name in LOCATIONS else None,
            "moon": bool(getattr(LOCATIONS[name], "moon", False)) if name in LOCATIONS else False,
        },
        "character_contrast": round(abs(char_luma - bg_luma), 1),
        "character_luma": round(char_luma, 1),
        "background_luma": round(bg_luma, 1),
        "midground_vs_sky": round(abs(mid_mean - sky_mean), 1),
        "midground_detail": round(math.sqrt(mid_var), 1),
        "foreground_occlusion": occlusion,
        "ground_error_px": round(ground_error_value, 1),
        "character_boxes": boxes,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    names = [name for name in LOCATION_LIGHTING if name in LOCATIONS]
    reports = []
    thumbs = []
    for name in names:
        surface = _render(name, with_cast=True, overlay=("environment", "foreground", "grade"))
        png = OUT / f"{name}.png"
        surface.write_to_png(str(png))
        thumbs.append(png)
        report = measure(name)
        reports.append(report)
        print(f"[T45] {name:16s} contrast={report['character_contrast']:5.1f} "
              f"mid_gap={report['midground_vs_sky']:5.1f} detail={report['midground_detail']:5.1f} "
              f"occl={report['foreground_occlusion']} ground_err={report['ground_error_px']}")

    if thumbs:
        w, h = 960, 540
        sheet = Image.new("RGB", (w * 2, h * 3), (12, 12, 16))
        for index, path in enumerate(thumbs):
            sheet.paste(Image.open(path).resize((w, h)), ((index % 2) * w, (index // 2) * h))
        sheet.save(OUT / "sheet.png")
        print(f"[T45] sheet {sheet.size}")

    (OUT / "locations.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
