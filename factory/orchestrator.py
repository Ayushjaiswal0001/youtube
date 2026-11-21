"""End-to-end per-channel orchestration."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .config import BUILD_ROOT, ChannelSpec, load_channel_specs
from .content.models import Script
from .content.script import build_english_script, build_hindi_script, load_plans_for, story_packet
from .media.captions import build_srt
from .media.english_renderer import render_english
from .media.landscape_renderer import render_landscape
from .media.hindi_renderer import render_hindi_episode
from .media.thumbnail import make_thumbnail, thumbnail_path
from .media.tts import synthesize_script
from .qa.validator import validate_episode
from .state import ChannelState
from .util import read_json, sha256_file, slugify


def plan_identifier(plan: dict[str, Any]) -> str:
    value = plan.get("id") or plan.get("title") or "episode"
    return slugify(str(value))


def episode_out_dir(spec: ChannelSpec, plan: dict[str, Any]) -> Path:
    plan_id = plan_identifier(plan)
    if resolve_engine(spec, plan) == "stage":
        from .media.landscape_stage import stage_story_id

        return BUILD_ROOT / spec.slug / stage_story_id(spec, plan)
    if spec.is_hindi:
        return BUILD_ROOT / spec.slug / f"{spec.slug}_{plan_id}"
    return BUILD_ROOT / spec.slug / plan_id


def _plan_specs(spec: ChannelSpec) -> list[ChannelSpec]:
    """Both composition profiles a channel can render (9:16 and 16:9)."""

    other = "long" if spec.format == "shorts" else "shorts"
    return [spec, replace(spec, format=other)]


def find_plan(spec: ChannelSpec, plan_id: str | None = None) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    for candidate in _plan_specs(spec):
        try:
            plans.extend(load_plans_for(candidate))
        except ValueError:
            continue
    if plan_id:
        wanted = slugify(plan_id)
        for plan in plans:
            if plan_identifier(plan) == wanted:
                return plan
        raise ValueError(f"plan {plan_id!r} not found for {spec.slug}")
    for plan in plans:
        if not (episode_out_dir(spec, plan) / "video.mp4").is_file():
            return plan
    raise ValueError(
        f"all {len(plans)} plans for {spec.slug} are already rendered; "
        "add the next batch before running again"
    )


def _english_script(spec: ChannelSpec, plan: dict[str, Any]) -> tuple[Script, Path]:
    script = build_english_script(spec, plan)
    out_dir = episode_out_dir(spec, plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    return script, out_dir


def _render_english(
    spec: ChannelSpec,
    script: Script,
    out_dir: Path,
    *,
    force: bool,
) -> dict[str, Any]:
    video_path = out_dir / "video.mp4"
    if video_path.is_file() and not force:
        timeline = read_json(out_dir / "timeline.json", {})
        return {
            "video_path": str(video_path),
            "duration": float(timeline.get("duration", 0.0)),
            "skipped": True,
        }
    narration = synthesize_script(script, spec, out_dir / "audio")
    renderer = render_landscape if spec.format == "long" else render_english
    return renderer(
        script,
        narration,
        spec,
        video_path,
        force=force,
    )


def resolve_engine(spec: ChannelSpec, plan: dict[str, Any]) -> str:
    """Which renderer this plan needs.

    Three engines exist and they are not interchangeable: the Shorts character engine (9:16), the
    editorial card renderer (16:9 diagrams and text, no cast) and the landscape stage engine (16:9
    with the cast). Choosing between them is a property of the *plan*, not of which CLI verb the
    operator typed, so every entry point resolves it the same way.
    """

    engine = str(plan.get("engine") or "").strip().lower()
    if engine:
        if engine not in {"stage", "cards", "shorts"}:
            raise ValueError(f"unknown engine {engine!r} for plan {plan_identifier(plan)}")
        return engine
    # No inference from a `scenes` key: the existing Shorts plans carry one too, and guessing
    # routed a 9:16 Short through the landscape stage. A stage plan declares `engine`.
    return "shorts" if spec.format == "shorts" else "cards"


def _render_stage(
    spec: ChannelSpec,
    plan: dict[str, Any],
    *,
    force: bool,
    only_scenes: list[int] | None,
) -> tuple[Script, dict[str, Any], Path, dict[str, Any]]:
    from .media.landscape_stage import render_stage_episode

    result = render_stage_episode(spec, plan, force=force, only_scenes=only_scenes)
    return result["script"], result["story"], result["out_dir"], result


def _render_hindi(
    spec: ChannelSpec,
    plan: dict[str, Any],
    *,
    force: bool,
) -> tuple[Script, dict[str, Any], Path]:
    script = build_hindi_script(spec, plan)
    story = story_packet(script, spec)
    out_dir = episode_out_dir(spec, plan)
    result = render_hindi_episode(
        spec,
        plan,
        force_overlays=force,
        force_rerender=force,
    )
    return script, story, out_dir if out_dir.is_dir() else Path(result["video_path"]).parent


def render_episode(
    spec: ChannelSpec,
    plan: dict[str, Any] | None = None,
    *,
    plan_id: str | None = None,
    force: bool = False,
    only_scenes: list[int] | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    """Produce one episode, whichever engine its plan needs.

    Everything after the render - thumbnail, subtitles, QC, state, the returned payload - is shared.
    That sharing is the point: the landscape stage used to be a separate verb with its own copy of
    those steps, so a fix to QC or to captions had to be made twice and stayed wrong in one place.
    """

    selected = plan or find_plan(spec, plan_id)
    # A plan can request the horizontal profile; the composition system, QA geometry
    # and duration bounds all follow from spec.format.
    requested = str(selected.get("format") or "").lower()
    if requested in {"long", "shorts"} and requested != spec.format:
        spec = replace(spec, format=requested)
    engine = resolve_engine(spec, selected)
    stage_result: dict[str, Any] = {}
    if engine == "stage":
        script, story, out_dir, stage_result = _render_stage(
            spec, selected, force=force, only_scenes=only_scenes)
    elif spec.is_hindi:
        script, story, out_dir = _render_hindi(spec, selected, force=force)
    else:
        script, out_dir = _english_script(spec, selected)
        story = {}
        _render_english(spec, script, out_dir, force=force)

    video_path = out_dir / "video.mp4"
    if not video_path.is_file():
        raise RuntimeError(f"renderer did not produce {video_path}")
    timeline = read_json(out_dir / "timeline.json", {})
    if not timeline:
        raise RuntimeError(f"missing timeline for {video_path}")

    thumb_path = thumbnail_path(out_dir)
    thumb_result = make_thumbnail(
        spec,
        script,
        video_path,
        thumb_path,
        force=force,
    )
    srt_result = build_srt(
        spec,
        script,
        timeline,
        out_dir / "captions.srt",
        story=story or read_json(out_dir / "story.json"),
    )
    qc = validate_episode(
        spec,
        script,
        video_path,
        thumbnail=thumb_path,
        srt=out_dir / "captions.srt",
        report_path=out_dir / "qc.json",
        demo=demo,
    )

    state = ChannelState(spec.slug)
    state.record(
        topic=script.topic,
        title=script.title,
        status="rendered" if qc["ok"] else "qc_failed",
        plan_id=script.metadata.get("plan_id"),
    )
    state.log_run(
        {
            "kind": "render",
            "plan_id": plan_identifier(selected),
            "title": script.title,
            "video_path": str(video_path),
            "duration": qc["duration"],
            "qc_ok": qc["ok"],
            "thumbnail": thumb_result,
            "captions": srt_result,
        }
    )
    payload = {
        "channel": spec.slug,
        "plan_id": plan_identifier(selected),
        "title": script.title,
        "language": spec.language,
        "format": spec.format,
        "engine": engine,
        "video_path": str(video_path),
        "duration": qc["duration"],
        "size_bytes": video_path.stat().st_size,
        "sha256": sha256_file(video_path),
        "thumbnail_path": str(thumb_path),
        "srt_path": srt_result["srt_path"],
        "cue_count": srt_result["cue_count"],
        "qc_ok": qc["ok"],
        "qc_errors": [
            item
            for item in qc["checks"]
            if not item["ok"] and item["severity"] == "error"
        ],
        "qc_report": str(out_dir / "qc.json"),
        "skipped_render": bool(timeline and video_path.is_file() and not force),
    }
    if stage_result:
        payload.update({
            "scene_count": len(stage_result["scenes"]),
            "rendered_scenes": stage_result["rendered_scenes"],
            "reused_scenes": stage_result["reused_scenes"],
            "skipped_render": stage_result["skipped_render"],
            "framing_report": str(out_dir / "framing.json"),
        })
    return payload


def render_channels(
    channels: Iterable[ChannelSpec],
    *,
    plan_id: str | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in channels:
        results.append(render_episode(spec, plan_id=plan_id, force=force))
    return results


def load_specs() -> dict[str, ChannelSpec]:
    return load_channel_specs()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
