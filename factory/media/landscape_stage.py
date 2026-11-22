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

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from ..config import BUILD_ROOT, FONTS_DIR, STATE_ROOT, ChannelSpec
from ..content.models import Script, ScriptLine
from ..content.script import slugify
from ..util import atomic_write_json as write_json_atomic, sha256_file

WIDTH, HEIGHT = 1920, 1080

# Caption band geometry, as fractions of frame height. The band sits low enough to stay out of the
# cast's faces and high enough to survive the platform's own UI chrome.
BAND_TOP = 0.845
BAND_BOTTOM = 0.955
BAND_MARGIN = 0.12

# The engine is its source. A cached scene hashes the bytes of the animation engine and the character
# schemas, so changing framing, camera behaviour, the shot planner, the rig drawing or a palette
# invalidates the cache instead of silently reusing frames the previous engine drew.
#
# A manual version string was the first attempt, and I forgot to bump it for a framing fix: the
# render reused twelve scenes and reported success while showing the old shots. Hashing the source
# cannot be forgotten.
ENGINE_SOURCES: tuple[str, ...] = (
    "studio/animation",
    "studio/characters",
    "studio/audio",
    "content/characters",
)

# Bumped only for changes that are not in those files (fonts, overlay geometry baked into stills).
ENVIRONMENT_SIGNATURE = "env-2024-11-t41"

_ENGINE_DIGEST: Optional[str] = None


def engine_digest() -> str:
    """A hash of every file that decides what a frame looks like."""

    global _ENGINE_DIGEST
    if _ENGINE_DIGEST is not None:
        return _ENGINE_DIGEST
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[2]
    for relative in ENGINE_SOURCES:
        base = root / relative
        if not base.exists():
            continue
        paths = sorted(p for p in base.rglob("*") if p.suffix in (".py", ".json"))
        for path in paths:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    _ENGINE_DIGEST = digest.hexdigest()[:16]
    return _ENGINE_DIGEST

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
                "prop_handoff_at", "prop_handoff_duration", "interaction", "pickup", "lighting")
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


def stage_story_id(spec: ChannelSpec, plan: Dict[str, Any]) -> str:
    """The one identifier for a stage episode's build directory.

    `orchestrator.episode_out_dir` and this module used to compute different names for the same
    episode (`..._render-stage-<plan>` versus `..._<plan>`), so `status` reported twelve missing
    scenes for an episode whose twelve scenes were on disk. One formula, used by both.
    """

    return f"{spec.slug}_{slugify(str(plan.get('id') or plan.get('title') or 'episode'))}"


def build_story(spec: ChannelSpec, plan: Dict[str, Any], script: Script) -> Dict[str, Any]:
    story_id = stage_story_id(spec, plan)
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
    from studio.animation.shot_plan import apply_plan as apply_shot_plan
    from studio.animation.shot_plan import plan_conversation
    from studio.animation.transitions import plan_transitions
    return {
        "SceneRenderer": SceneRenderer,
        "LANDSCAPE": LANDSCAPE,
        "LandscapeEnvironment": LandscapeEnvironment,
        "ForegroundLayer": ForegroundLayer,
        "TTSEngine": TTSEngine,
        "plan_transitions": plan_transitions,
        "plan_conversation": plan_conversation,
        "apply_shot_plan": apply_shot_plan,
    }


# ---------------------------------------------------------------------------
# Episode
# ---------------------------------------------------------------------------


def scene_signature(scene: Dict[str, Any], fade_in: float, fade_out: float,
                    stage_signature: str = "", audio_digest: str = "") -> str:
    """Stable hash of everything that changes a scene's pixels or its audio.

    Only what the renderer actually reads goes in: the artwork and framing inputs, the dialogue and
    speaker (they decide the TTS take and the visemes) and the fades. Anything else - a title, a
    plan-level note - must not force a re-render, and anything here must never be dropped, or a
    changed scene would be silently reused from cache.
    """

    # Deny-list the render-only fields rather than allow-list the authored ones: the first version
    # listed "pose" while the authored key is "chiku_pose"/"gappu_pose", so a pose change reused a
    # scene drawn with the previous pose. A new scene key is now covered by default.
    render_only = {"subtitle_png", "title_png", "story_id", "fade_in", "fade_out"}
    payload = {
        "scene": {key: value for key, value in scene.items() if key not in render_only},
        "fade_in": round(float(fade_in), 4),
        "fade_out": round(float(fade_out), 4),
        "stage": stage_signature,
        # The narration take, not just the line: visemes come from the audio envelope, so a fresh
        # dub with identical text produces a different mouth track. Omitting it meant
        # FACTORY_FRESH_AUDIO=1 could reuse scenes lip-synced to the previous take.
        "audio": audio_digest,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _scene_state_path(video: Path) -> Path:
    return video.with_suffix(".json")


def scene_is_current(video: Path, signature: str) -> bool:
    """A cached scene is reusable only if its recorded inputs still match and it decodes.

    The state file is written *after* the encode returns, and the probe is a second gate, so an
    interrupted render (a truncated MP4 with a matching state file) is never mistaken for a
    finished one. This is what makes a resumed production safe rather than merely convenient.
    """

    state = _scene_state_path(video)
    if not video.is_file() or video.stat().st_size < 10_000:
        return False
    try:
        recorded = json.loads(state.read_text(encoding="utf-8"))
    except Exception:
        return False
    if recorded.get("signature") != signature:
        return False
    return _ffprobe_duration(video) > 0.2


def _record_scene_state(video: Path, signature: str, scene: Dict[str, Any],
                        duration: float) -> None:
    write_json_atomic(_scene_state_path(video), {
        "signature": signature,
        "scene": scene.get("scene_num"),
        "speaker": scene.get("speaker"),
        "duration": round(float(duration), 3),
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def _log(message: str) -> None:
    print(message, file=sys.stderr)


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
    # Encode beside the destination and rename into place: a failed or interrupted join must never
    # leave a half-written video.mp4 where a later run would accept it as finished.
    # Keep the .mp4 extension: ffmpeg infers the muxer from it, and ".mp4.partial" has no container
    # it can name, so the whole join failed with "Invalid argument" after every scene had rendered.
    partial = target.with_name(target.name.replace(".mp4", ".partial.mp4"))
    partial.unlink(missing_ok=True)
    command[-1] = str(partial)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    listing.unlink(missing_ok=True)
    if result.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"landscape concat failed: {result.stderr[-1500:]}")
    os.replace(partial, target)
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

    # Conversational direction (T42): when a scene asks for "auto", the conversation decides the
    # shot - who owns the line, who is listening, whether the location changed, what was framed on
    # the previous cut. Authored cameras are left alone.
    if any(str(scene.get("camera") or "").lower() in ("auto", "director")
           for scene in story["scenes"]):
        planner = studio["plan_conversation"]
        anchors = [(slot.name, slot.x) for slot in studio["LANDSCAPE"].slots.values()]
        shot_plan = planner(story["scenes"], anchors=anchors)
        story["scenes"] = studio["apply_shot_plan"](story["scenes"], shot_plan)
        plan_doc = shot_plan.to_dict()
        plan_doc["story_id"] = story["story_id"]
        (out_dir / "shot_plan.json").write_text(
            json.dumps(plan_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Stage] directed {len(shot_plan.decisions)} shots, "
              f"{len(shot_plan.warnings)} continuity violations", file=sys.stderr)
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
    rendered = 0
    reused = 0
    stage_signature = hashlib.sha256(
        f"{WIDTH}x{HEIGHT}|{stage.ground_y}|{stage.eye_y}|"
        f"{','.join(f'{slot.name}:{slot.x}' for slot in stage.slots.values())}|"
        f"{engine_digest()}|{ENVIRONMENT_SIGNATURE}|{kicker}".encode("utf-8")
    ).hexdigest()[:16]
    for index, scene in enumerate(story["scenes"]):
        fade_in, fade_out = transitions[index] if index < len(transitions) else (0.0, 0.0)
        target = episode_dir / f"scene_{scene['scene_num']:03d}.mp4"
        audio = tts.generate_dialogue(
            text=scene["dialogue"], speaker=scene["speaker"],
            tag=f"{story['story_id']}_s{scene['scene_num']}")
        signature = scene_signature(
            scene, fade_in, fade_out, stage_signature=stage_signature,
            audio_digest=sha256_file(Path(audio["audio_path"]))[:16])
        if not force and scene_is_current(target, signature):
            cached = json.loads(_scene_state_path(target).read_text(encoding="utf-8"))
            scene_paths.append(target)
            rows.append({"scene": scene["scene_num"], "speaker": scene["speaker"],
                         "dialogue": scene["dialogue"],
                         "duration": round(float(cached.get("duration") or 0.0), 3),
                         "cached": True})
            reused += 1
            continue

        renderer.render_scene(
            dict(scene, story_id=story["story_id"], fade_in=fade_in, fade_out=fade_out),
            audio, target, sfx_delay_ms=350)
        duration = _ffprobe_duration(target)
        _record_scene_state(target, signature, scene, duration)
        scene_paths.append(target)
        rows.append({"scene": scene["scene_num"], "speaker": scene["speaker"],
                     "dialogue": scene["dialogue"], "duration": round(duration, 3),
                     "cached": False})
        rendered += 1

    video_path = out_dir / "video.mp4"
    assemble = force or rendered > 0 or not video_path.is_file()
    if assemble:
        if len(scene_paths) == 1:
            partial = video_path.with_name(video_path.name.replace(".mp4", ".partial.mp4"))
            shutil.copy2(scene_paths[0], partial)
            os.replace(partial, video_path)
        else:
            _concat(scene_paths, video_path)
    elif video_path.is_file():
        _log(f"[Stage] keeping existing {video_path.name}: all {len(scene_paths)} scenes are current")

    story["created_at"] = story.get("created_at") or ""
    (out_dir / "story.json").write_text(json.dumps(story, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (out_dir / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    total = sum(row["duration"] for row in rows)
    (out_dir / "timeline.json").write_text(json.dumps(
        {"story_id": story["story_id"], "duration": round(total, 3), "scenes": rows},
        ensure_ascii=False, indent=2), encoding="utf-8")

    # Continuity travels with the episode (T47). Built from the normalised plan, so it describes
    # what was actually rendered rather than what the author intended.
    try:
        from studio.animation.continuity import validate_episode
        report = validate_episode(story["scenes"], characters=("chiku", "gappu"),
                                  ground_y=stage.ground_y)
        (out_dir / "continuity.json").write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # a broken continuity pass must not lose a finished render
        _log(f"[Stage] continuity report unavailable: {exc}")

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
        "rendered_scenes": rendered,
        "reused_scenes": reused,
        "skipped_render": rendered == 0 and not force,
    }
