"""Render a pickup and a hand-off inside one scene, through the production renderer path.

This is the visual proof for T43B's joined beat: Chiku bends for the brass key, stands with it, takes a
step toward Gappu, they meet, and the key changes hands. Everything on screen comes from the same
objects the episode renderer uses - ``PickupScene``, the stage, ``LandscapeEnvironment`` - so if this
looks wrong, the episode would look wrong.

    python -m tools.render_handoff_demo --out build/handoff

Writes ``handoff.mp4``, ``handoff.json`` (the measured report) and ``sheet.png`` (a contact sheet).
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Dict, List

import cairo

from studio.animation.environment import LandscapeEnvironment
from studio.animation.pickup_scene import PickupScene
from studio.animation.stage import stage_for
from studio.characters.gappu import GappuRig
from studio.characters.chiku import ChikuRig
from tools.render_pickup_demos import FPS, HEIGHT, WIDTH, _encode, _push

STAGE = stage_for(WIDTH, HEIGHT)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="build/handoff")
    parser.add_argument("--duration", type=float, default=7.0)
    parser.add_argument("--background", default="jungle_clearing")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rigs = {"chiku": ChikuRig(**STAGE.anchor("chiku")),
            "gappu": GappuRig(**STAGE.anchor("gappu"))}
    for rig in rigs.values():
        rig.y = STAGE.ground_y

    spec = {"object": "brass_key", "grip": "small_object", "holder": "chiku", "side": "right",
            "offset": 52, "surface": "ground", "keep": True, "handoff_to": "gappu"}
    scene = PickupScene(spec, rigs, args.duration, STAGE.ground_y)
    if not scene.report.handoff_reachable:
        raise SystemExit(f"the hand-off is not reachable: {scene.as_dict()['handoff']}")

    environment = LandscapeEnvironment(WIDTH, HEIGHT, STAGE.ground_y)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    video = out / "handoff.mp4"
    encoder = _encode(video)
    frames: List[Path] = []
    total = int(round(args.duration * FPS))
    samples: List[dict] = []

    try:
        for index in range(total):
            t = index / FPS
            frame = scene.update(t)
            cr = cairo.Context(surface)
            environment.render_by_name(args.background, cr, t)
            for name in ("gappu", "chiku"):
                rigs[name].draw(cr)
            _draw_object(cr, frame["point"], frame["held"])
            _push(encoder, surface)
            samples.append({"t": round(t, 3), "state": frame["state"],
                            "held": bool(frame["held"]),
                            "gap": frame.get("handoff_gap"),
                            "bend": round(float(frame.get("bend") or 0.0), 1)})
            if index % max(1, total // 12) == 0:
                png = out / f"frame_{index:04d}.png"
                surface.write_to_png(str(png))
                frames.append(png)
        encoder.stdin.close()
        error = encoder.stderr.read().decode("utf-8", "replace") if encoder.stderr else ""
        if encoder.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {error[-800:]}")
    finally:
        if encoder.poll() is None:
            encoder.kill()

    _contact_sheet(frames, out / "sheet.png", columns=4)
    report = {"duration": args.duration, "frames": total, "video": str(video),
              "bytes": video.stat().st_size, **scene.as_dict(),
              "samples": samples[:: max(1, total // 40)]}
    (out / "handoff.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    print(json.dumps({"video": str(video), "transferred": scene.report.transferred,
                      "handoff": report["handoff"],
                      "contact_px": report["report"]["handoff_contact_error"],
                      "ownership": report["ownership"]["objects"]}, indent=2,
                     ensure_ascii=False))
    return 0


def _contact_sheet(frames: List[Path], path: Path, columns: int = 4) -> None:
    """A grid of frames scaled down, so twelve moments of the beat can be read at once."""

    if not frames:
        return
    import cairo as _cairo

    columns = min(columns, len(frames))
    rows = math.ceil(len(frames) / columns)
    tile_w, tile_h = WIDTH // columns, HEIGHT // columns
    surface = _cairo.ImageSurface(_cairo.FORMAT_ARGB32, tile_w * columns, tile_h * rows)
    cr = _cairo.Context(surface)
    cr.set_source_rgb(0.05, 0.05, 0.07)
    cr.paint()
    for index, frame in enumerate(frames):
        image = _cairo.ImageSurface.create_from_png(str(frame))
        cr.save()
        cr.translate((index % columns) * tile_w, (index // columns) * tile_h)
        cr.scale(tile_w / WIDTH, tile_h / HEIGHT)
        cr.set_source_surface(image, 0, 0)
        cr.paint()
        cr.restore()
    surface.write_to_png(str(path))


def _draw_object(cr: cairo.Context, point, held: bool) -> None:
    """A small brass key: drawn, not a placeholder box, so a wrong grip is visible."""

    x, y = point
    cr.save()
    cr.translate(x, y)
    cr.set_line_width(2.4)
    cr.set_source_rgb(0.85, 0.70, 0.28)
    cr.arc(0, 0, 7.0, 0, 2 * math.pi)
    cr.fill()
    cr.set_source_rgb(0.55, 0.42, 0.14)
    cr.arc(0, 0, 7.0, 0, 2 * math.pi)
    cr.stroke()
    cr.rectangle(6, -2.0, 18, 4.0)
    cr.fill()
    cr.rectangle(20, 0, 3.0, 6.0)
    cr.fill()
    if held:
        cr.set_source_rgba(1.0, 1.0, 0.8, 0.35)
        cr.arc(0, 0, 12.0, 0, 2 * math.pi)
        cr.fill()
    cr.restore()


if __name__ == "__main__":
    raise SystemExit(main())
