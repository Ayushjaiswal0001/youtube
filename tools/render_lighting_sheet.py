"""Render the T44 lighting comparison sheet and a shadow-response clip.

Produces, in ``build/lighting/``:

* ``sheet.png`` - every preset against three body states (standing, crouched, airborne), so shadow
  direction, length, softness and opacity can be compared side by side;
* ``shadow_response.mp4`` - one 1920x1080 clip of a character standing, jumping and landing, with the
  shadow measured every frame;
* ``lighting.json`` - the geometry that was drawn, per preset per state.

Nothing here is asserted from the preset numbers alone: the shadow offsets written to the JSON are the
ones the draw call actually received.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cairo
from PIL import Image

from studio.animation.environment import LandscapeEnvironment
from studio.animation.lighting import PRESETS, draw_shadow, preset_for
from studio.animation.stage import stage_for
from studio.characters.chiku import ChikuRig
from studio.characters.crouch import BodyPose, apply_pose
from studio.characters.schema import load_schema

WIDTH, HEIGHT = 1920, 1080
FPS = 30
OUT = Path("build/lighting")
STAGE = stage_for(WIDTH, HEIGHT)
CELL_W, CELL_H = 640, 400
BACKGROUNDS = {"daylight": "jungle_clearing", "warm_afternoon": "jungle_clearing",
               "sunset": "forest_path", "cool_evening": "village_night",
               "indoor_warm": "haunted_haveli", "moonlight": "village_night"}

STATES = {
    "standing": (BodyPose(), 0.0),
    "crouched": (BodyPose(bend=math.radians(60.0), squash=0.74), 0.0),
    "airborne": (BodyPose(), 150.0),
}


def _frame(preset_name: str, state: str, *, surface=None, t: float = 0.0):
    preset = preset_for(preset_name)
    rig = ChikuRig(**STAGE.anchor("chiku"))
    pose, height = STATES[state]
    apply_pose(rig, pose)
    rig.y = STAGE.ground_y - height

    environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)
    geometry = None

    def paint(cr: cairo.Context) -> None:
        nonlocal geometry
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgb(0.08, 0.10, 0.13)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        environment.render_by_name(BACKGROUNDS[preset_name], cr, t)
        cr.save()
        # Framing has to hold a standing character *and* one 150 px in the air.
        cr.translate(WIDTH / 2.0, HEIGHT * 0.72)
        cr.scale(1.25, 1.25)
        cr.translate(-rig.x, -STAGE.ground_y)
        geometry = draw_shadow(cr, preset, x=rig.x, ground_y=STAGE.ground_y,
                               body_half_width=68.0 * rig.scale,
                               height_above_ground=height)
        rig.draw(cr)
        cr.restore()
        from studio.animation.lighting import ambient_overlay, apply_grade
        ambient_overlay(cr, preset, WIDTH, HEIGHT)
        apply_grade(cr, preset, WIDTH, HEIGHT)

    target = surface or cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    cr = cairo.Context(target)
    paint(cr)
    if surface is not None:
        return target, geometry
    return target, geometry, cr


def render_sheet() -> dict:
    """One PNG per preset row, three states per row, assembled into a single comparison sheet."""

    OUT.mkdir(parents=True, exist_ok=True)
    presets = list(PRESETS)
    rows = []
    report = {"presets": {}, "states": list(STATES), "cell": [CELL_W, CELL_H]}
    for preset_name in presets:
        cells = []
        report["presets"][preset_name] = {}
        for state in STATES:
            full, geom, _ = _frame(preset_name, state)
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, CELL_W, CELL_H)
            # Downsample the 1920x1080 frame into the tile rather than rendering twice.
            cr = cairo.Context(tile)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.scale(CELL_W / WIDTH, CELL_H / HEIGHT)
            cr.set_source_surface(full, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.identity_matrix()
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
            cr.rectangle(0, 0, 210, 26)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(15)
            cr.move_to(8, 18)
            cr.show_text(f"{preset_name} / {state}")
            tile.flush()
            png = OUT / f"{preset_name}_{state}.png"
            tile.write_to_png(str(png))
            cells.append(png)
            report["presets"][preset_name][state] = {
                "offset_x": round(geom.offset_x, 2), "length": round(geom.length, 2),
                "opacity": round(geom.opacity, 3), "softness": round(geom.softness, 3)}
        rows.append(cells)

    sheet = Image.new("RGB", (CELL_W * len(STATES), CELL_H * len(rows)), (14, 14, 18))
    for r, cells in enumerate(rows):
        for c, path in enumerate(cells):
            sheet.paste(Image.open(path), (c * CELL_W, r * CELL_H))
    sheet.save(OUT / "sheet.png")
    report["sheet"] = str(OUT / "sheet.png")
    report["sheet_size"] = list(sheet.size)
    return report


def render_shadow_clip() -> dict:
    """A jump and a landing, with the shadow measured on every frame."""

    clip = OUT / "shadow_response.mp4"
    total = int(3.2 * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostats", "-f", "rawvideo",
           "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(clip)]
    encoder = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    samples = []
    preset = preset_for("warm_afternoon")
    rig = ChikuRig(**STAGE.anchor("chiku"))
    environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)

    try:
        for index in range(total):
            t = index / FPS
            # Anticipation squat, leap, fall, land, recover.
            height, bend = 0.0, 0.0
            if 0.4 <= t < 0.8:
                bend = math.radians(22.0) * math.sin((t - 0.4) / 0.4 * math.pi)
            elif 0.8 <= t < 1.9:
                u = (t - 0.8) / 1.1
                height = 190.0 * math.sin(u * math.pi)
            elif 1.9 <= t < 2.3:
                bend = math.radians(18.0) * math.sin((t - 1.9) / 0.4 * math.pi)
            apply_pose(rig, BodyPose(bend=bend, squash=1.0 - 0.1 * (bend / max(bend, 1e-6)) * (bend > 0)))
            rig.y = STAGE.ground_y - height

            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgb(0.08, 0.10, 0.13)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            environment.render_by_name("jungle_clearing", cr, t)
            cr.save()
            cr.translate(WIDTH / 2.0, HEIGHT * 0.72)
            cr.scale(1.25, 1.25)
            cr.translate(-rig.x, -STAGE.ground_y)
            geom = draw_shadow(cr, preset, x=rig.x, ground_y=STAGE.ground_y,
                               body_half_width=68.0 * rig.scale, height_above_ground=height)
            rig.draw(cr)
            cr.restore()
            from studio.animation.lighting import ambient_overlay, apply_grade
            ambient_overlay(cr, preset, WIDTH, HEIGHT)
            apply_grade(cr, preset, WIDTH, HEIGHT)

            samples.append({"t": round(t, 3), "height": round(height, 1),
                            "bend_deg": round(math.degrees(bend), 1),
                            "shadow_offset": round(geom.offset_x, 1),
                            "shadow_length": round(geom.length, 1),
                            "shadow_opacity": round(geom.opacity, 3)})
            surface.flush()
            stride = surface.get_stride()
            row = WIDTH * 4
            raw = surface.get_data()
            encoder.stdin.write(bytes(raw) if stride == row else b"".join(
                raw[r * stride: r * stride + row] for r in range(HEIGHT)))
        encoder.stdin.close()
        err = encoder.stderr.read().decode("utf-8", "replace") if encoder.stderr else ""
        if encoder.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err[-600:]}")
    finally:
        if encoder.poll() is None:
            encoder.kill()

    return {"clip": str(clip), "frames": total, "bytes": clip.stat().st_size,
            "samples": samples[:: 8]}


def main() -> int:
    sheet = render_sheet()
    clip = render_shadow_clip()
    report = {"presets": sorted(PRESETS), "sheet": sheet, "clip": clip}
    (OUT / "lighting.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[Lighting] sheet {sheet['sheet_size']} presets={len(PRESETS)}")
    print(f"[Lighting] clip {clip['frames']}f {clip['bytes']}B")
    for name, states in sheet["presets"].items():
        stand = states["standing"]
        air = states["airborne"]
        print(f"  {name:16s} stand off={stand['offset_x']:6.1f} op={stand['opacity']:.2f} | "
              f"air off={air['offset_x']:6.1f} op={air['opacity']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
