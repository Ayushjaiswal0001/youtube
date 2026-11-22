"""Render all six locations *with their near-camera set* and measure what it actually covers.

The earlier location sheet measured foreground occlusion and reported 0.0 everywhere. That number was
correct: the foreground layer was confined to the outer 12% of the frame so it could not overlap
anybody. This sheet is the follow-up - the same six locations, but the cast now stands inside a set
that can get in the way, and the sheet reports how much of each character the near layer covers.

Run: python -m tools.render_dressing_sheet [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cairo

from studio.animation import set_dressing
from studio.animation.compositor import Layer
from studio.animation.environment import ForegroundLayer, LandscapeEnvironment, LOCATIONS
from studio.animation.lighting import preset_for
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig

WIDTH, HEIGHT = 1920, 1080
TILE = (960, 540)


def _surface(width: int, height: int) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    context = cairo.Context(surface)
    context.set_source_rgb(0.05, 0.06, 0.09)
    context.paint()
    return surface


def render_location(name: str, stage, t: float = 0.8) -> tuple[cairo.ImageSurface, dict]:
    """Compose one location and return the frame plus its measurements."""

    environment = LandscapeEnvironment(WIDTH, HEIGHT, stage.ground_y)
    legacy = ForegroundLayer(WIDTH, HEIGHT, stage.ground_y)
    location = LOCATIONS.get(name)
    lighting = preset_for(getattr(location, "lighting", None) or "")

    chiku = ChikuRig(**stage.anchor("chiku"))
    gappu = GappuRig(**stage.anchor("gappu"))
    cast = [chiku, gappu]

    # Measure the cast first: a foreground object that would bury a whole character is not set
    # dressing, it is a mistake.
    cast_boxes = []
    for rig in cast:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
        context = cairo.Context(surface)
        rig.draw(context)
        surface.flush()
        cast_boxes.append(_alpha_box(surface))
    items = set_dressing.dressing_for(name, WIDTH, HEIGHT, stage.ground_y, cast_boxes=cast_boxes)

    frame = _surface(WIDTH, HEIGHT)
    cr = cairo.Context(frame)
    environment.render_by_name(name, cr, t, 0.0, 0.0, zoom=1.0)
    if lighting is not None:
        # The scene renderer lights after the near layer; the sheet does the same so the comparison
        # is between comparable images.
        pass

    # World plane: scenery and cast are sorted together by the depth of their base line.
    world: list[tuple[float, str, object]] = []
    for item in items:
        if item.layer is Layer.ACTOR:
            world.append((item.depth, "dressing", item))
    for rig in cast:
        world.append((float(rig.y), "cast", rig))
    for depth, kind, thing in sorted(world, key=lambda entry: entry[0]):
        if kind == "dressing":
            set_dressing.draw(cr, thing, t)
        else:
            thing.draw(cr)

    set_dressing.draw_layer(cr, items, Layer.FOREGROUND, t)
    legacy.render_by_name(name, cr, t, 0.0, 0.0, zoom=1.0)

    if lighting is not None:
        from studio.animation.lighting import ambient_overlay, apply_grade
        ambient_overlay(cr, lighting, WIDTH, HEIGHT)
        apply_grade(cr, lighting, WIDTH, HEIGHT)

    cr.set_source_rgba(1, 1, 1, 0.55)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(32)
    cr.move_to(24, 44)
    cr.show_text(name)
    cr.fill()

    # Signed alpha masks of the drawn cast, for the occlusion measurement.
    actor_surfaces = []
    for rig in cast:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
        context = cairo.Context(surface)
        rig.draw(context)
        surface.flush()
        actor_surfaces.append(surface)

    occlusion = set_dressing.measure_occlusion(WIDTH, HEIGHT, items, actor_surfaces)
    hidden_mid = 0
    for item in items:
        if item.layer is Layer.ACTOR:
            for box in cast_boxes:
                if _overlap(item.box, box) > 0.0:
                    hidden_mid += 1
                    break
    report = {
        "location": name,
        "dressing": set_dressing.describe(items),
        "foreground_occlusion": occlusion,
        "cast_behind_scenery_items": hidden_mid,
        "lighting": getattr(location, "lighting", None),
    }
    return frame, report


def _alpha_box(surface: cairo.ImageSurface) -> tuple[float, float, float, float]:
    data = surface.get_data()
    stride = surface.get_stride()
    width, height = surface.get_width(), surface.get_height()
    left = top = 1 << 30
    right = bottom = -1
    for y in range(0, height, 3):
        row = y * stride
        for x in range(0, width, 3):
            if data[row + x * 4 + 3] > 24:
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
    if right < 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (float(left), float(top), float(right - left), float(bottom - top))


def _overlap(a, b) -> float:
    width = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    height = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return width * height


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/dressing")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    stage = stage_for(WIDTH, HEIGHT)
    rows = []
    frames = []
    for name in sorted(LOCATIONS):
        frame, report = render_location(name, stage)
        rows.append(report)
        frame.write_to_png(str(out / f"{name}.png"))
        small = cairo.ImageSurface(cairo.FORMAT_ARGB32, *TILE)
        cr = cairo.Context(small)
        cr.scale(TILE[0] / WIDTH, TILE[1] / HEIGHT)
        cr.set_source_surface(frame, 0, 0)
        cr.paint()
        frames.append(small)
        print(f"{name:18s} occlusion={report['foreground_occlusion']} "
              f"items={report['dressing']['count']} behind={report['cast_behind_scenery_items']}")

    columns = 2
    rows_count = math.ceil(len(frames) / columns)
    sheet = cairo.ImageSurface(cairo.FORMAT_ARGB32, TILE[0] * columns, TILE[1] * rows_count)
    cr = cairo.Context(sheet)
    cr.set_source_rgb(0.02, 0.02, 0.03)
    cr.paint()
    for index, frame in enumerate(frames):
        cr.set_source_surface(frame, (index % columns) * TILE[0], (index // columns) * TILE[1])
        cr.paint()
    sheet.write_to_png(str(out / "sheet.png"))

    payload = {"locations": rows,
               "max_occlusion": max((max(r["foreground_occlusion"].values(), default=0.0)
                                     for r in rows), default=0.0)}
    (out / "occlusion.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(f"sheet -> {out / 'sheet.png'}")
    print(f"max foreground occlusion of the cast: {payload['max_occlusion']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
