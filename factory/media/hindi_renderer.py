"""Natkhat Toons Hindi episode renderer.

The studio owns the character rigs, backgrounds and scene animation. This wrapper
turns a batch plan into a portable story packet, renders Devanagari overlays with
Chrome, and calls the studio pipeline with build-local paths.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..config import BUILD_ROOT, FONTS_DIR, STATE_ROOT, ChannelSpec
from ..content.script import build_hindi_script, story_packet
from ..util import atomic_write_json, ffprobe_duration, ffprobe_streams, iso_now
from .hindi_text import render_story_overlays


def _attach_overlays(story: dict[str, Any], overlays: dict[int, dict[str, str]]) -> None:
    for scene in story["scenes"]:
        scene.update(overlays.get(int(scene["scene_num"]), {}))


def _scene_durations(project_file: Path) -> list[dict[str, Any]]:
    import json

    if not project_file.is_file():
        return []
    state = json.loads(project_file.read_text(encoding="utf-8"))
    work_dir = project_file.parent
    rows: list[dict[str, Any]] = []
    for scene in state.get("story", {}).get("scenes", []):
        path = work_dir / f"scene_{int(scene['scene_num']):03d}.mp4"
        rows.append(
            {
                "scene": int(scene["scene_num"]),
                "speaker": scene.get("speaker"),
                "dialogue": scene.get("dialogue"),
                "duration": round(ffprobe_duration(path), 3) if path.is_file() else None,
            }
        )
    return rows


def _load_pipeline(studio_out: Path):
    """Import the studio pipeline with paths bound to this episode's build directory.

    ``studio.config`` reads its ``STUDIO_*`` environment variables once, at import
    time, and every studio module binds those directories as module constants. A
    second render in the same process would otherwise keep writing into the first
    episode's folder, so drop the cached modules and import them fresh.
    """

    import sys

    for name in [key for key in list(sys.modules) if key == "studio" or key.startswith("studio.")]:
        del sys.modules[name]

    import studio.config as studio_config

    if studio_config.OUTPUT_DIR != studio_out.resolve():
        raise RuntimeError(
            f"studio config did not pick up STUDIO_OUTPUT_DIR: "
            f"{studio_config.OUTPUT_DIR} != {studio_out.resolve()}"
        )

    from studio.pipeline.episode import EpisodePipeline

    return EpisodePipeline


def render_hindi_episode(
    spec: ChannelSpec,
    plan: dict[str, Any],
    *,
    force_overlays: bool = False,
    force_rerender: bool = False,
) -> dict[str, Any]:
    """Render one Natkhat episode and return a machine-readable result."""
    script = build_hindi_script(spec, plan)
    story = story_packet(script, spec)
    out_dir = BUILD_ROOT / spec.slug / story["story_id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    video_path = out_dir / "video.mp4"
    if video_path.is_file() and not force_rerender:
        return {
            "story_id": story["story_id"],
            "title": story["title"],
            "video_path": str(video_path),
            "duration": ffprobe_duration(video_path),
            "skipped": True,
        }

    overlay_paths = render_story_overlays(
        story,
        out_dir / "overlays",
        fonts_dir=FONTS_DIR,
        kicker="नटखट टून्स",
        force=force_overlays,
    )
    _attach_overlays(story, overlay_paths)

    atomic_write_json(out_dir / "story.json", story)
    atomic_write_json(out_dir / "script.json", asdict(script))

    studio_out = out_dir / "studio"
    if force_rerender and studio_out.exists():
        shutil.rmtree(studio_out)
    os.environ["STUDIO_OUTPUT_DIR"] = str(studio_out)
    os.environ["STUDIO_EPISODES_DIR"] = str(studio_out / "episodes")
    os.environ["STUDIO_INTERMEDIATE_DIR"] = str(studio_out / "intermediate")
    os.environ["STUDIO_LOGS_DIR"] = str(BUILD_ROOT / "logs")
    os.environ["STUDIO_DATA_DIR"] = str(STATE_ROOT / spec.slug / "studio_data")

    EpisodePipeline = _load_pipeline(studio_out)
    for directory in (
        Path(os.environ["STUDIO_OUTPUT_DIR"]),
        Path(os.environ["STUDIO_EPISODES_DIR"]),
        Path(os.environ["STUDIO_INTERMEDIATE_DIR"]),
        Path(os.environ["STUDIO_LOGS_DIR"]),
        Path(os.environ["STUDIO_DATA_DIR"]),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    result = EpisodePipeline().produce_episode(story=story)
    source = Path(result["video_path"])
    if not source.is_file():
        raise RuntimeError(f"studio did not produce the expected episode: {source}")
    shutil.copy2(source, video_path)

    # The framing report travels with the episode so QC can gate on it (T39).
    framing_source = source.with_name(source.stem.replace("_final", "") + "_framing.json")
    if framing_source.is_file():
        shutil.copy2(framing_source, out_dir / "framing.json")

    streams = ffprobe_streams(video_path)
    video_stream = next(
        (stream for stream in streams.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    if not video_stream or (int(video_stream.get("width", 0)), int(video_stream.get("height", 0))) != (1080, 1920):
        raise RuntimeError(f"unexpected video geometry for {video_path}: {video_stream}")
    if not audio_stream:
        raise RuntimeError(f"rendered episode has no audio stream: {video_path}")

    duration = ffprobe_duration(video_path)
    timeline = {
        "story_id": story["story_id"],
        "duration": round(duration, 3),
        "scenes": _scene_durations(studio_out / "intermediate" / story["story_id"] / "project.json"),
    }
    atomic_write_json(out_dir / "timeline.json", timeline)

    render = {
        "story_id": story["story_id"],
        "channel": spec.slug,
        "title": story["title"],
        "video_path": str(video_path),
        "duration": round(duration, 3),
        "size_bytes": video_path.stat().st_size,
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "video_codec": video_stream.get("codec_name"),
        "audio_codec": audio_stream.get("codec_name"),
        "renderer": "studio-cairo+chrome-overlays",
        "rendered_at": iso_now(),
        "source_studio_file": str(source),
    }
    atomic_write_json(out_dir / "render.json", render)
    return {**render, "skipped": False}
