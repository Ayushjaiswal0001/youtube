"""Landscape (16:9) character episodes (T41).

The 16:9 renderer has always drawn editorial cards: a text column, a diagram plate, a caption band.
Chiku and Gappu only ever appeared in 9:16. This module drives the *same* animation engine
(`studio.animation.scene_renderer.SceneRenderer`) on the landscape stage, so every behaviour built
for the Shorts pipeline - viseme lip-sync, blinks and gaze, locomotion, performance beats, two-body
interaction, props and hand-offs, camera direction and framing verification - is available in 16:9
without a second implementation of any of it.

What is landscape-specific here:

* the stage (`studio.animation.stage.LANDSCAPE`),
* the environment (`studio.animation.environment.LandscapeEnvironment`) and its foreground layer,
* caption and title overlays drawn at 1920x1080,
* the episode assembly: per-scene render, concat, timeline, framing aggregation.

A plan drives it. The plan carries its scenes explicitly - speaker, line, poses, camera, background,
optional prop - so a landscape episode is authored, deterministic and reviewable, in the same way the
Shorts series bible is.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from ..config import BUILD_ROOT, FONTS_DIR, STATE_ROOT, ChannelSpec
from ..content.models import Script, ScriptLine
from ..content.script import slugify

WIDTH, HEIGHT = 1920, 1080

# Caption band geometry, as fractions of frame height. The band sits low enough to stay out of the
# cast's faces and high enough to survive the platform's own UI chrome.
BAND_TOP = 0.845
BAND_BOTTOM = 0.955
BAND_MARGIN = 0.12

DEVANAGARI_FONT = "NotoSansDevanagari-Variable.ttf"
LATIN_FONT = "Inter-Black.otf"


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (FONTS_DIR / name, FONTS_DIR / LATIN_FONT, FONTS_DIR / "Baloo2-Variable.ttf"):
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def caption_overlay(text: str, path: Path, *, kicker: str = "",
                    band: tuple[float, float] = (BAND_TOP, BAND_BOTTOM)) -> Path:
    """A transparent 1920x1080 caption band with the line on it.

    Measured from the drawing itself later: QC reads the band's opaque rectangle out of this PNG, so
    what the gate checks is what the viewer sees.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    top, bottom = int(HEIGHT * band[0]), int(HEIGHT * band[1])
    font = _font(DEVANAGARI_FONT, 46)
    lines = _wrap(draw, text, font, int(WIDTH * (1 - 2 * BAND_MARGIN)))
    line_height = int(46 * 1.45)
    # No two-line minimum: a one-line caption gets a one-line band, which is what keeps the band
    # off the characters' feet. Reserving two lines made every band 20% of the frame.
    wanted = len(lines) * line_height + 40 + (42 if kicker else 0)
    if wanted > bottom - top:
        top = max(int(HEIGHT * 0.70), bottom - wanted)
    x0 = int(WIDTH * BAND_MARGIN)
    x1 = WIDTH - x0
    draw.rounded_rectangle((x0, top, x1, bottom), radius=26, fill=(12, 10, 20, 205))
    draw.rounded_rectangle((x0, top, x1, bottom), radius=26, outline=(255, 255, 255, 40), width=2)
    # The kicker is drawn *on* the band, not above it. Above it, the overlay's opaque rectangle
    # started 38 px higher than the band, so QC measured characters as standing behind the caption
    # on every frame of every scene - a real measurement of the wrong rectangle.
    text_top = top
    if kicker:
        small = _font(DEVANAGARI_FONT, 26)
        width = draw.textlength(kicker, font=small)
        draw.text(((WIDTH - width) / 2, top + 10), kicker, font=small, fill=(255, 214, 120, 235))
        text_top = top + 42
    total = len(lines) * line_height
    y = text_top + (bottom - text_top - total) // 2 - 2
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((WIDTH - width) / 2, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height
    image.save(path)
    return path


def title_overlay(title: str, path: Path, *, kicker: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # A top band, not a centre card: at 0.12-0.40 it covered the characters' heads, which on a
    # 16:9 stage sit around 0.28 of frame height.
    band_top, band_bottom = int(HEIGHT * 0.055), int(HEIGHT * 0.215)
    draw.rounded_rectangle((int(WIDTH * 0.18), band_top, int(WIDTH * 0.82), band_bottom),
                           radius=26, fill=(10, 9, 18, 185))
    font = _font(DEVANAGARI_FONT, 52)
    lines = _wrap(draw, title, font, int(WIDTH * 0.60))
    y = band_top + 26
    for line in lines[:2]:
        width = draw.textlength(line, font=font)
        draw.text(((WIDTH - width) / 2, y), line, font=font, fill=(255, 255, 255, 250))
        y += int(52 * 1.3)
    if kicker:
        small = _font(DEVANAGARI_FONT, 28)
        width = draw.textlength(kicker, font=small)
        draw.text(((WIDTH - width) / 2, band_top - 44), kicker, font=small,
                  fill=(255, 214, 120, 240))
    image.save(path)
    return path


# ---------------------------------------------------------------------------
# Plan -> script -> story
# ---------------------------------------------------------------------------


def plan_scenes(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    scenes = plan.get("scenes") or []
    if not scenes:
        raise ValueError(f"landscape stage plan {plan.get('id')!r} has no scenes")
    out = []
    for index, scene in enumerate(scenes, 1):
        if not str(scene.get("line") or "").strip():
            raise ValueError(f"landscape plan scene {index} has no line")
        out.append({
            "scene_num": int(scene.get("n") or index),
            "speaker": str(scene.get("speaker") or "narrator"),
            "dialogue": str(scene["line"]).strip(),
            "chiku_pose": str(scene.get("chiku_pose") or "idle"),
            "gappu_pose": str(scene.get("gappu_pose") or "idle"),
            "camera": str(scene.get("camera") or "two_shot"),
            "bg": str(scene.get("bg") or "haunted_haveli"),
            "sfx": str(scene.get("sfx") or "whoosh"),
            **{key: scene[key] for key in
               ("prop", "prop_holder", "prop_side", "prop_handoff_to", "prop_handoff_side",
                "prop_handoff_at", "prop_handoff_duration", "interaction")
               if scene.get(key) is not None},
        })
    return out


def build_script(spec: ChannelSpec, plan: Dict[str, Any]) -> Script:
    scenes = plan_scenes(plan)
    lines = [ScriptLine(text=scene["dialogue"], headline="", visual="scene",
                        sfx=scene["sfx"], caption=scene["dialogue"]) for scene in scenes]
    title = str(plan.get("title") or "Landscape episode")
    return Script(
        channel=spec.slug,
        language=spec.language,
        format="long",
        topic=str(plan.get("topic") or title),
        title=title,
        hook=str(plan.get("hook") or scenes[0]["dialogue"]),
        lines=lines,
        description=str(plan.get("description") or plan.get("hook") or title),
        tags=list(plan.get("tags") or []),
        style=spec.style,
        moral=str(plan.get("moral") or ""),
        series=plan.get("series"),
        episode=plan.get("episode"),
        series_title=str(plan.get("series_title") or ""),
    )


def build_story(spec: ChannelSpec, plan: Dict[str, Any], script: Script) -> Dict[str, Any]:
    story_id = f"{spec.slug}_render-stage-{slugify(str(plan.get('id') or script.title))}"
    return {
        "story_id": story_id,
        "hash": f"stage:{plan.get('id')}",
        "category": str(plan.get("series") or "stage"),
        "title": script.title,
        "hook": script.hook,
        "moral": script.moral,
        "characters": ["chiku", "gappu"],
        "total_scenes": len(script.lines),
        "series": plan.get("series"),
        "series_title": plan.get("series_title"),
        "episode": plan.get("episode"),
        "scenes": plan_scenes(plan),
    }


# ---------------------------------------------------------------------------
# Studio binding
# ---------------------------------------------------------------------------


def load_studio(out_dir: Path):
    """Import the studio package with its output directories bound to this episode.

    ``studio.config`` reads its environment once, at import time, and every studio module binds
    those directories. The factory already has to do this dance for the Shorts pipeline
    (`factory.media.hindi_renderer._load_pipeline`); doing the same here keeps one behaviour instead
    of two.
    """

    studio_out = out_dir / "studio"
    for directory in (studio_out, studio_out / "episodes", studio_out / "intermediate"):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ["STUDIO_OUTPUT_DIR"] = str(studio_out)
    os.environ["STUDIO_EPISODES_DIR"] = str(studio_out / "episodes")
    os.environ["STUDIO_INTERMEDIATE_DIR"] = str(studio_out / "intermediate")
    os.environ["STUDIO_LOGS_DIR"] = str(BUILD_ROOT / "logs")
    os.environ["STUDIO_DATA_DIR"] = str(STATE_ROOT / out_dir.parent.name / "studio_data")
    for name in [key for key in list(sys.modules) if key == "studio" or key.startswith("studio.")]:
        del sys.modules[name]
    import studio.config as studio_config  # noqa: F401

    from studio.animation.scene_renderer import SceneRenderer
    from studio.animation.stage import LANDSCAPE
    from studio.animation.environment import ForegroundLayer, LandscapeEnvironment
    from studio.audio.tts_engine import TTSEngine
    from studio.animation.transitions import plan_transitions
    return {
        "SceneRenderer": SceneRenderer,
        "LANDSCAPE": LANDSCAPE,
        "LandscapeEnvironment": LandscapeEnvironment,
        "ForegroundLayer": ForegroundLayer,
        "TTSEngine": TTSEngine,
        "plan_transitions": plan_transitions,
    }


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


def _ffprobe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _concat(scenes: List[Path], target: Path) -> Path:
    """Join scene renders into the episode, pinning the delivered frame rate.

    A stream copy here produced 29.93 fps. Each scene's AAC stream is slightly longer than its
    video, so the concat demuxer started the next scene 0.023 s late; the container duration then
    stopped being frames/30. The `fps` filter re-times every frame onto a clean 1/30 grid, which is
    the same defect the portrait pipeline fixed the same way (`studio/pipeline/episode.py`).
    Twelve scenes would have accumulated about a third of a second of A/V drift without it.
    """

    listing = target.with_suffix(".txt")
    listing.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in scenes) + "\n", encoding="utf-8")
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
               "-i", str(listing),
               "-vf", "fps=30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-r", "30", "-fps_mode", "cfr",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    listing.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"landscape concat failed: {result.stderr[-1500:]}")
    return target


def render_stage_episode(spec: ChannelSpec, plan: Dict[str, Any], *, force: bool = False,
                         only_scenes: Optional[List[int]] = None) -> Dict[str, Any]:
    """Render a 16:9 character episode from a landscape stage plan."""

    script = build_script(spec, plan)
    story = build_story(spec, plan, script)
    if only_scenes:
        wanted = set(only_scenes)
        story["scenes"] = [scene for scene in story["scenes"] if scene["scene_num"] in wanted]
        if not story["scenes"]:
            raise ValueError(f"no scenes matched {sorted(wanted)}")
        story["total_scenes"] = len(story["scenes"])

    out_dir = BUILD_ROOT / spec.slug / story["story_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    overlays = out_dir / "overlays"
    if force and overlays.exists():
        shutil.rmtree(overlays)
    overlays.mkdir(parents=True, exist_ok=True)

    kicker = str(plan.get("kicker") or "")
    title_png = title_overlay(script.title, overlays / "title_card.png", kicker=kicker)
    for scene in story["scenes"]:
        scene["subtitle_png"] = str(caption_overlay(
            scene["dialogue"], overlays / f"scene_{scene['scene_num']:03d}_subtitle.png",
            kicker=kicker))
    story["scenes"][0]["title_png"] = str(title_png)

    studio = load_studio(out_dir)
    tts = studio["TTSEngine"]()
    stage = studio["LANDSCAPE"]
    environment = studio["LandscapeEnvironment"](WIDTH, HEIGHT, stage.ground_y)
    foreground = studio["ForegroundLayer"](WIDTH, HEIGHT, stage.ground_y)
    renderer = studio["SceneRenderer"](WIDTH, HEIGHT, stage=stage, environment=environment,
                                       foreground=foreground)

    transitions = studio["plan_transitions"](story["scenes"])
    episode_dir = out_dir / "studio" / "intermediate" / story["story_id"]
    episode_dir.mkdir(parents=True, exist_ok=True)

    scene_paths: List[Path] = []
    rows: List[Dict[str, Any]] = []
    for index, scene in enumerate(story["scenes"]):
        fade_in, fade_out = transitions[index] if index < len(transitions) else (0.0, 0.0)
        audio = tts.generate_dialogue(
            text=scene["dialogue"], speaker=scene["speaker"],
            tag=f"{story['story_id']}_s{scene['scene_num']}")
        target = episode_dir / f"scene_{scene['scene_num']:03d}.mp4"
        renderer.render_scene(
            dict(scene, story_id=story["story_id"], fade_in=fade_in, fade_out=fade_out),
            audio, target, sfx_delay_ms=350)
        scene_paths.append(target)
        rows.append({"scene": scene["scene_num"], "speaker": scene["speaker"],
                     "dialogue": scene["dialogue"],
                     "duration": round(_ffprobe_duration(target), 3)})

    video_path = out_dir / "video.mp4"
    if len(scene_paths) == 1:
        shutil.copy2(scene_paths[0], video_path)
    else:
        _concat(scene_paths, video_path)

    story["created_at"] = story.get("created_at") or ""
    (out_dir / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (out_dir / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    total = sum(row["duration"] for row in rows)
    (out_dir / "timeline.json").write_text(json.dumps(
        {"story_id": story["story_id"], "duration": round(total, 3), "scenes": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")

    # Framing evidence travels with the episode, aggregated from the per-scene reports (T39).
    # Only this episode's scenes: leftover reports from an earlier, longer render of the same plan
    # were being aggregated into a shorter one, which is how a demo reported collisions from scenes
    # it had not rendered.
    wanted_scenes = {scene["scene_num"] for scene in story["scenes"]}
    scenes_report = []
    for path in sorted(episode_dir.glob("scene_*_framing.json")):
        try:
            scene_number = int(path.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        if scene_number not in wanted_scenes:
            continue
        try:
            scenes_report.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    if scenes_report:
        (out_dir / "framing.json").write_text(json.dumps({
            "story_id": story["story_id"],
            "width": WIDTH, "height": HEIGHT,
            "scenes": scenes_report,
            "subtitle_collision_frames": sum(
                int(scene.get("subtitle_collision_frames") or 0) for scene in scenes_report),
            "cropped_required_frames": sum(
                int(scene.get("cropped_required_frames") or 0) for scene in scenes_report),
            "total_cropped_frames": sum(
                int(scene.get("total_cropped_frames") or 0) for scene in scenes_report),
            "max_zoom_rate": max((float(scene.get("max_zoom_rate") or 0.0)
                                  for scene in scenes_report), default=0.0),
            "escalations": [{"scene": scene.get("scene"), "shot": scene.get("shot"),
                             "reason": scene.get("reason")}
                            for scene in scenes_report if scene.get("escalated")],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "story": story,
        "script": script,
        "out_dir": out_dir,
        "video_path": video_path,
        "duration": round(_ffprobe_duration(video_path), 3),
        "scenes": rows,
    }
