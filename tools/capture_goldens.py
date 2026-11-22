"""Capture or refresh the per-pose golden frames.

    python -m tools.capture_goldens            # write tests/factory/goldens/poses.json
    python -m tools.capture_goldens --check    # compare without writing

The golden set in ``tests/factory/goldens/manifest.json`` covers four poses per character.
That is not enough: the T33 fix changed the output of ``boast_proud`` and
``skeptical_eyebrow`` and no golden noticed. This tool covers every pose a story can ask
for, so a future change to a rig cannot silently alter a pose nobody tested.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cairo

from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.lipsync import VisemeTrack
from studio.characters.rig_base import Viseme
from studio.characters.visemes import VisemeTimeline

GOLDENS = Path(__file__).resolve().parent.parent / "tests" / "factory" / "goldens"
POSES = {
    "chiku": ["idle", "excited_jump", "boast_proud", "shocked_freeze",
              "embarrassed_smile", "spinning_slip"],
    "gappu": ["idle", "observing", "skeptical_eyebrow", "laughing_point",
              "satisfied_nod", "facepalm", "hands_on_hips"],
}
TIMES = (0.0, 0.9, 2.3)


def render_frame(character: str, pose: str, t: float, talking: bool) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 700)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.12, 0.12, 0.16)
    cr.paint()
    rig = (ChikuRig if character == "chiku" else GappuRig)(x=350, y=620, scale=1.0)
    envelope = VisemeTrack(fps=30, openness=[0.85] * 240)
    timeline = VisemeTimeline(fps=30,
                              shapes=[Viseme.WIDE] * 120 + [Viseme.OPEN_WIDE] * 120,
                              scales=[0.45] * 120 + [0.95] * 120)
    rig.update_pose(pose, t, is_talking=talking, phoneme_intensity=0.8,
                    lipsync=envelope if talking else None,
                    timeline=timeline if talking else None)
    rig.draw(cr)
    surface.flush()
    tmp = GOLDENS / ".tmp_pose.png"
    surface.write_to_png(str(tmp))
    try:
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def build() -> dict:
    manifest = {}
    for character, poses in POSES.items():
        for pose in poses:
            for t in TIMES:
                for talking in (False, True):
                    key = f"{character}__{pose}__t{t}__{'talk' if talking else 'idle'}.png"
                    manifest[key] = hashlib.sha256(
                        render_frame(character, pose, t, talking)).hexdigest()[:16]
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = build()
    path = GOLDENS / "poses.json"
    if args.check:
        if not path.is_file():
            print("no pose goldens recorded yet")
            return 1
        recorded = json.loads(path.read_text(encoding="utf-8"))
        changed = [key for key in recorded if recorded[key] != manifest.get(key)]
        missing = [key for key in manifest if key not in recorded]
        print(f"{len(manifest)} frames, {len(changed)} changed, {len(missing)} new")
        for key in changed[:20]:
            print(f"  CHANGED {key}")
        return 1 if changed or missing else 0
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path} with {len(manifest)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
