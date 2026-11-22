"""Viseme / lip-sync QA report for a rendered episode.

Usage:  python tools/report_visemes.py <episode_dir>

Reads the rendered `story.json` + cached narration audio + boundary sidecars and reports,
per scene: units, shape runs, change rate, hold times, and how the mouth behaves against
the acoustic envelope. Nothing here is synthetic — it measures the same code path the
renderer uses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.audio.tts_engine import TTSEngine  # noqa: E402
from studio.config import INTERMEDIATE_DIR  # noqa: E402
from studio.characters.lipsync import SILENCE_FLOOR, VisemeTrack  # noqa: E402
from studio.characters.rig_base import Viseme  # noqa: E402
from studio.characters.visemes import VisemeTimeline  # noqa: E402

FPS = 30.0


def analyse(episode_dir: Path, fps: float = FPS) -> list[dict]:
    story = json.loads((episode_dir / "story.json").read_text(encoding="utf-8"))
    engine = TTSEngine(output_dir=episode_dir / "studio" / "intermediate")
    stats: list[dict] = []
    for scene in story["scenes"]:
        tag = f"{story['story_id']}_s{scene['scene_num']}"
        voice = episode_dir / "studio" / "intermediate" / f"{tag}_{scene['speaker']}.mp3"
        if not voice.is_file():
            candidates = sorted(episode_dir.rglob(f"*_s{scene['scene_num']}_{scene['speaker']}.mp3"))
            if not candidates:
                candidates = sorted(episode_dir.rglob(f"*_s{scene['scene_num']}_*.mp3"))
            voice = candidates[0] if candidates else voice
        if not voice.is_file():
            candidates = sorted(Path(INTERMEDIATE_DIR).glob(f"*_s{scene['scene_num']}_{scene['speaker']}.mp3"))
            voice = candidates[0] if candidates else voice
        if not voice.is_file():
            continue
        envelope = VisemeTrack.from_audio(voice, fps=fps)
        duration = len(envelope) / fps
        boundaries = engine._load_boundaries(voice)
        timeline = VisemeTimeline.from_text(
            scene["dialogue"], duration=duration, fps=fps,
            boundaries=boundaries, envelope=envelope,
        )
        voiced = [value > SILENCE_FLOOR for value in envelope.openness]
        runs: list[int] = []
        speech_runs: list[int] = []
        index = 0
        while index < len(timeline.shapes):
            start = index
            while index < len(timeline.shapes) and timeline.shapes[index] == timeline.shapes[start]:
                index += 1
            runs.append(index - start)
            if timeline.shapes[start] != Viseme.CLOSED:
                speech_runs.append(index - start)
        articulated = sum(
            1 for position, shape in enumerate(timeline.shapes)
            if voiced[position] and shape not in (Viseme.NEUTRAL, Viseme.SMILE, Viseme.CLOSED)
        )
        voiced_count = sum(1 for flag in voiced if flag)
        stats.append({
            "scene": scene["scene_num"],
            "speaker": scene["speaker"],
            "duration": round(duration, 2),
            "boundaries": len(boundaries or []),
            "units": timeline.unit_count,
            "runs": len(runs),
            "change_rate": round(timeline.change_rate(), 2),
            "median_hold_ms": round(sorted(runs)[len(runs) // 2] / fps * 1000) if runs else 0,
            "min_hold_ms": round(min(runs) / fps * 1000) if runs else 0,
            "min_hold_speech_ms": round(min(speech_runs) / fps * 1000) if speech_runs else 0,
            "articulated_voiced_pct": round(100 * articulated / voiced_count, 1) if voiced_count else 0.0,
            "changes_per_vowel_unit": round(timeline.change_rate() * duration / max(1, _vowel_units(scene["dialogue"])), 2),
            "composition": {k: round(v, 2) for k, v in timeline.composition().items()},
        })
    return stats


def _vowel_units(text: str) -> int:
    from studio.characters.visemes import parse_units

    return sum(1 for unit in parse_units(text) if unit.kind == "vowel")


def main(argv: list[str]) -> int:
    episode_dir = Path(argv[1] if len(argv) > 1 else ".")
    stats = analyse(episode_dir)
    if not stats:
        print(f"no narration audio found under {episode_dir}")
        return 1
    header = f"{'sc':>2} {'speaker':9} {'dur':>5} {'bnd':>3} {'units':>5} {'runs':>4} {'chg/s':>5} {'hold':>5} {'smin':>4} {'art%':>5}"
    print(header)
    print("-" * len(header))
    for row in stats:
        print(f"{row['scene']:>2} {row['speaker']:9} {row['duration']:>5} {row['boundaries']:>3} "
              f"{row['units']:>5} {row['runs']:>4} {row['change_rate']:>5} {row['median_hold_ms']:>5} "
              f"{row['min_hold_speech_ms']:>4} {row['articulated_voiced_pct']:>5}")
    print()
    for row in stats:
        print(f"scene {row['scene']}: {row['composition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
