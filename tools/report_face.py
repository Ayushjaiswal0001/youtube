"""Report the face animation a scene will produce, without rendering it.

    python -m tools.report_face build/<channel>/<episode>/

Rebuilding the same controllers the renderer uses means the numbers below describe the
frames that were actually drawn (same seeds, same schedules), and a re-render reproduces
them exactly. This is a QA tool: it answers "did the characters actually blink, look at
each other and change expression?" with numbers instead of impressions.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import zlib
from pathlib import Path

from studio.characters.gaze import FaceController
from studio.characters.schema import load_schema

FPS = 30


def seed_for(*parts) -> int:
    return zlib.crc32(":".join(str(part) for part in parts).encode("utf-8"))


def report(episode_dir: Path) -> int:
    story_path = episode_dir / "story.json"
    if not story_path.is_file():
        print(f"no story.json in {episode_dir}")
        return 1
    story = json.loads(story_path.read_text(encoding="utf-8"))
    story_id = str(story.get("story_id") or episode_dir.name)

    def scene_duration(num: int) -> float:
        candidates = [episode_dir / f"scene_{num:03d}.mp4",
                      episode_dir / "studio" / "intermediate" / episode_dir.name
                      / f"scene_{num:03d}.mp4"]
        clip = next((path for path in candidates if path.is_file()), None)
        if clip is None:
            return 0.0
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(clip)],
            capture_output=True, text=True,
        )
        try:
            return float(out.stdout.strip())
        except ValueError:
            return 0.0
    schema = {"chiku": load_schema("chiku"), "gappu": load_schema("gappu")}

    print(f"episode: {story_id}")
    totals = {name: {"blinks": 0.0, "saccades": 0.0, "seconds": 0.0} for name in schema}
    expressions = {name: {} for name in schema}

    for scene in story["scenes"]:
        num = scene.get("scene_num", 0)
        duration = scene_duration(num)
        if duration <= 0.0:
            print(f"  s{num:02d} skipped: no scene clip to measure")
            continue
        speaker = scene.get("speaker", "narrator")
        for character, pose_key in (("chiku", "chiku_pose"), ("gappu", "gappu_pose")):
            from studio.animation.scene_renderer import (  # local import: renderer needs ffmpeg paths
                _expression_schedule, _gaze_beats, CHIKU_X, GAPPU_X,
            )

            own_x, partner_x = (CHIKU_X, GAPPU_X) if character == "chiku" else (GAPPU_X, CHIKU_X)
            facing = 1.0 if character == "chiku" else -1.0
            face = FaceController(
                schema[character],
                seed=seed_for(story_id, num, character),
                span=duration + 2.0,
                schedule=_expression_schedule(scene, character,
                                              scene.get(pose_key, "idle"),
                                              speaker == character),
                scripted_gaze=_gaze_beats(own_x, partner_x, duration,
                                          speaking=speaker == character, facing=facing),
            )
            blinks = face.blink.count(0.0, duration)
            frames = max(1, int(duration * FPS))
            states = [face.state_at(i / FPS) for i in range(frames)]
            shut = sum(1 for state in states if min(state.lid_left, state.lid_right) > 0.9)
            moves = sum(
                1 for a, b in zip(states, states[1:])
                if abs(a.pupil_left[0] - b.pupil_left[0]) > 1e-4
            )
            lens = [b.start - a.start for a, b in zip(face.blink._blinks, face.blink._blinks[1:])]
            totals[character]["blinks"] += blinks
            totals[character]["saccades"] += face.gaze.moves
            totals[character]["seconds"] += duration
            for state in states:
                expressions[character][state.expression] = expressions[character].get(state.expression, 0) + 1
            print(f"  s{num:02d} {character:6s} {duration:5.2f}s  blinks={blinks:2d} "
                  f"saccades={face.gaze.moves:2d}  shut_frames={shut:3d} "
                  f"({100 * shut / frames:4.1f}%)  blink_interval median="
                  f"{(statistics.median(lens) if lens else 0):.2f}s  expr={states[0].expression}")

    print()
    for character, data in totals.items():
        seconds = max(1e-6, data["seconds"])
        print(f"{character}: {data['blinks'] / seconds * 60:5.1f} blinks/min  "
              f"{data['saccades'] / seconds * 60:5.1f} gaze moves/min")
        mix = expressions[character]
        total = max(1, sum(mix.values()))
        share = ", ".join(f"{name} {100 * count / total:.0f}%"
                          for name, count in sorted(mix.items(), key=lambda kv: -kv[1]))
        print(f"  expressions: {share}")
    return 0


if __name__ == "__main__":
    sys.exit(report(Path(sys.argv[1])))
