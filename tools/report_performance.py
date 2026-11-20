"""Report the performance beats for one rendered episode.

Reads the rendered scene durations (so the plan matches the render exactly), rebuilds the
same deterministic plans the renderer used, and prints the beat table plus how much of each
scene is actually animated by a beat. Run it after a render when a scene looks too still or
too twitchy.

    python -m tools.report_performance build/natkhat-toons/natkhat-toons_natkhat-haveli-e1
"""

from __future__ import annotations

import json
import subprocess
import sys
import zlib
from pathlib import Path

from studio.characters.performance import PerformanceTrack, plan_performance

FPS = 30


def _duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    episode_dir = Path(argv[1]).resolve()
    story_id = episode_dir.name
    if story_id.startswith("natkhat-toons_"):
        story_id = story_id[len("natkhat-toons_"):]

    series = json.loads(Path("content/series/natkhat-toons.json").read_text(encoding="utf-8"))
    # Plan ids are "<series>-e<N>", where N counts episodes inside that series.
    series_key, _, episode_part = story_id.rpartition("-e")
    episode = None
    if episode_part.isdigit():
        for item in series["series"]:
            if item["series"] == series_key:
                index = int(episode_part) - 1
                if 0 <= index < len(item["episodes"]):
                    episode = item["episodes"][index]
    if episode is None:
        print(f"no episode matches '{story_id}' in content/series/natkhat-toons.json")
        return 1

    intermediate = episode_dir / "studio" / "intermediate" / episode_dir.name
    total_beats = 0
    for index, scene in enumerate(episode["scenes"], start=1):
        scene_path = intermediate / f"scene_{index:03d}.mp4"
        if not scene_path.exists():
            print(f"scene {index}: missing {scene_path}")
            continue
        duration = _duration(scene_path)
        seed = zlib.crc32(f"{episode_dir.name}:{index}:performance".encode("utf-8"))
        plan = plan_performance(scene["dialogue"], duration=duration,
                                speaker=scene["speaker"], seed=seed)
        lines = []
        for character in ("chiku", "gappu"):
            beats = plan.for_character(character)
            total_beats += len(beats)
            track = PerformanceTrack(beats, duration)
            animated = sum(
                1 for frame in range(int(duration * FPS))
                if not track.accent_at(frame / FPS).is_empty()
            )
            described = ", ".join(f"{b.at:.2f}s {b.kind}" for b in beats) or "-"
            share = animated / max(1, int(duration * FPS)) * 100
            lines.append(f"    {character:6s} {len(beats)} beat(s) {share:4.1f}% of frames | "
                         f"{described}")
        print(f"  scene {index} [{scene['speaker']}] {duration:.2f}s")
        print("\n".join(lines))
    print(f"  total beats: {total_beats}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
