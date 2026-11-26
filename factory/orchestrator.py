"""End-to-end per-channel orchestration."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .config import BUILD_ROOT, STATE_ROOT, ChannelSpec, load_channel_specs

LOCK_ROOT = STATE_ROOT / "locks"
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
from .reliability import (
    JobJournal,
    JobLock,
    LockBusy,
    disk_usage_report,
    job_id_for,
    memory_report,
    preflight,
    production_manifest,
)
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


def build_script(spec: ChannelSpec, plan: dict[str, Any]) -> Script:
    """Build the script a plan's *engine* needs, not the one its channel's language suggests.

    Every read-side verb (`validate`, `manifest`, `gate`, `status`) used to call `build_hindi_script` for Hindi
    channels regardless of engine, so a landscape plan - whose scenes carry `line`, not `dialogue` - was
    rejected as "invalid scene" even though the renderer had produced and QC'd it. The render path already
    dispatched correctly; this makes the read path agree with it instead of duplicating the rule.

    A landscape plan is normalised by `landscape_stage.plan_scenes`, which validates `scenes[].line` and maps it
    to `dialogue` before anything else sees it. Portrait Hindi plans still go through `build_hindi_script`,
    which stays strict about its own schema.

    The plan's own `format` wins over the caller's spec, exactly as it does on the render path. Without that,
    `validate --channel academic-biohacker --plan-id long-academic-study-protocol` (no `--format`, which is
    how an operator naturally types it) built the 627-word 16:9 script against the *shorts* bounds and failed
    with "too long (627 words, shorts allows 140)" - a message about the wrong problem entirely.
    """

    declared = str(plan.get("format") or "").lower()
    if declared in {"shorts", "long"} and declared != spec.format:
        spec = replace(spec, format=declared)

    if resolve_engine(spec, plan) == "stage":
        from .media.landscape_stage import build_script as build_stage_script

        return build_stage_script(spec, plan)
    if spec.is_hindi:
        return build_hindi_script(spec, plan)
    return build_english_script(spec, plan)


def plan_specs(spec: ChannelSpec) -> list[ChannelSpec]:
    """Both composition profiles a channel can render (9:16 and 16:9)."""

    other = "long" if spec.format == "shorts" else "shorts"
    return [spec, replace(spec, format=other)]


def find_plan(spec: ChannelSpec, plan_id: str | None = None) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    for candidate in plan_specs(spec):
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


def build_is_complete(out_dir: Path) -> bool:
    """True when an episode is finished: the video *and* the timeline it was rendered against.

    Found by killing a render 40 s in, while FFmpeg was writing: the directory held a 524 KB truncated
    ``video.mp4`` and no ``timeline.json``. `resume` then failed with "missing timeline" for ever, because
    "a file called video.mp4 exists" was treated as "this episode is done". A cancelled GitHub Actions job
    leaves exactly that, so the recovery path was broken for the most likely interruption there is.
    """

    return (out_dir / "video.mp4").is_file() and (out_dir / "timeline.json").is_file()


def _render_english(
    spec: ChannelSpec,
    script: Script,
    out_dir: Path,
    *,
    force: bool,
) -> dict[str, Any]:
    video_path = out_dir / "video.mp4"
    timeline = read_json(out_dir / "timeline.json", {})
    if video_path.is_file() and timeline and not force:
        return {
            "video_path": str(video_path),
            "duration": float(timeline.get("duration", 0.0)),
            "skipped": True,
        }
    if video_path.is_file() and not force:
        # An interrupted encode. Keeping the fragment would make the episode permanently unresumable:
        # the renderer refuses to overwrite an existing output, and the timeline will never appear while
        # the partial file is mistaken for the result. Only the fragment is removed, so completed scene
        # work and `force` semantics are unchanged.
        video_path.unlink()
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

    # The choke point for every producing path, including `resume` - which is the verb `produce.yml` calls
    # to render, and which was NOT guarded. `FACTORY_PAUSED=1` + `resume` started TTS and created a build
    # directory, so the emergency stop stopped the local `render` verb and nothing else. A guard that lives
    # only in individual CLI verbs is a guard someone will route around.
    from .controls import ensure_allowed

    ensure_allowed(spec.slug, action="render")
    selected = plan or find_plan(spec, plan_id)
    selected_id = plan_identifier(selected)
    selected_job_id = job_id_for(spec.slug, selected_id)
    lock = JobLock(LOCK_ROOT / f"{spec.slug}_{selected_id}.lock",
                   job_id=selected_job_id, ttl=3600.0)
    # Acquire before constructing, inspecting, or updating the shared journal. JobJournal creates
    # its state directory, so even that construction must happen only after ownership is confirmed.
    # A contender that loses must not mutate state or reach a renderer.
    if not lock.acquire():
        raise LockBusy(f"{selected_id} is already being rendered")

    job: JobJournal | None = None
    try:
        job = JobJournal(selected_job_id)
        # pipeline_state is cached across workflow runs; build/ is not. A rerun can therefore find a
        # journal that says READY_TO_PUBLISH with no artifact next to it. Re-rendering is legitimate,
        # so record the rewind rather than bypassing the state machine. Never rewind PUBLISHED without
        # force: reproducing something already on YouTube could publish it twice.
        previous = job.state()
        if previous in {"READY_TO_PUBLISH", "PUBLISHING", "PUBLISHED"}:
            if previous == "PUBLISHED" and not force:
                raise ValueError(
                    f"{selected_id} is already published; pass --force to re-produce it"
                )
            job.transition("RECOVERABLE", reason=f"re-run after {previous}", requeued=True)
        job.transition("QUEUED", channel=spec.slug, plan_id=selected_id)
        result = _render_tracked(
            spec, selected, selected_id, job, lock,
            force=force, only_scenes=only_scenes, demo=demo)
        lock.assert_healthy()
        return result
    except BaseException as exc:
        # A renderer, QC step, or heartbeat error must leave a recoverable journal state. Preserve the
        # original exception if journal persistence itself is unavailable.
        try:
            if job is not None and job.state() not in {"FAILED", "PUBLISHED"}:
                job.transition(
                    "FAILED",
                    error=f"{type(exc).__name__}: {exc}",
                )
        except Exception as journal_error:  # noqa: BLE001
            if hasattr(exc, "add_note"):
                exc.add_note(f"Could not record FAILED state: {journal_error}")
        raise
    finally:
        lock.release()

def _render_tracked(
    spec: ChannelSpec,
    selected: dict[str, Any],
    selected_id: str,
    job: JobJournal,
    lock: JobLock,
    *,
    force: bool,
    only_scenes: list[int] | None,
    demo: bool,
) -> dict[str, Any]:
    """The production run, with its state transitions recorded as it goes.

    Split out of `render_episode` so the lock and the journal have exactly one owner and one exit
    path: a failed render must still release the lock and leave a FAILED record behind.
    """

    job.transition("PREFLIGHT", disk=disk_usage_report(BUILD_ROOT), memory=memory_report())
    report = preflight(channels=(spec.slug,))
    if not report.ok:
        job.transition("FAILED", error="preflight failed", failed=report.to_dict()["failed"])
        raise RuntimeError("preflight failed: " + ", ".join(report.to_dict()["failed"]))
    # A plan can request the horizontal profile; the composition system, QA geometry
    # and duration bounds all follow from spec.format.
    requested = str(selected.get("format") or "").lower()
    if requested in {"long", "shorts"} and requested != spec.format:
        spec = replace(spec, format=requested)
    engine = resolve_engine(spec, selected)
    stage_result: dict[str, Any] = {}
    # Whether this run re-used a finished build has to be read *before* rendering: the payload used to
    # compute it afterwards, when the video always exists, so every fresh render reported
    # `skipped_render: true` - the opposite of what happened, in the field an operator reads first.
    expected_out_dir = episode_out_dir(spec, selected)
    reused_build = build_is_complete(expected_out_dir) and not force
    job.transition("GENERATING", engine=engine)
    if engine == "stage":
        script, story, out_dir, stage_result = _render_stage(
            spec, selected, force=force, only_scenes=only_scenes)
    elif spec.is_hindi:
        script, story, out_dir = _render_hindi(spec, selected, force=force)
    else:
        script, out_dir = _english_script(spec, selected)
        story = {}
        _render_english(spec, script, out_dir, force=force)

    # Refuse to package a render if background ownership renewal failed during the expensive work.
    lock.assert_healthy()
    video_path = out_dir / "video.mp4"
    if not video_path.is_file():
        raise RuntimeError(f"renderer did not produce {video_path}")
    timeline = read_json(out_dir / "timeline.json", {})
    if not timeline:
        raise RuntimeError(f"missing timeline for {video_path}")

    job.transition("RENDERING", video=str(video_path))
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
    job.transition("VALIDATING")
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
    job.transition("PACKAGING")
    artifacts = {
        "video": video_path,
        "thumbnail": thumb_path,
        "captions": out_dir / "captions.srt",
        "qc_report": out_dir / "qc.json",
        "timeline": out_dir / "timeline.json",
    }
    # Explicit name/file pairs. The old loop derived the artifact name by stripping ".json", which turned
    # video.json into "video" and would have shadowed the video.mp4 entry; the canonical names are not all
    # derivable from the filenames (video_probe, scene_plan, creative_qc), so they are written out.
    for name, filename in (("framing", "framing.json"), ("shot_plan", "shot_plan.json"),
                           ("story", "story.json"), ("script", "script.json"),
                           ("continuity", "continuity.json"), ("audio", "audio.json"),
                           ("video_probe", "video.json"),
                           ("scene_plan", "scenes.json"), ("creative_qc", "creative.json")):
        if (out_dir / filename).is_file():
            artifacts[name] = out_dir / filename
    manifest = production_manifest(
        channel=spec.slug,
        plan_id=selected_id,
        engine=engine,
        format=spec.format,
        artifacts=artifacts,
        qc=qc,
        inputs={"plan_id": selected_id, "language": spec.language,
                "engine_digest": engine_digest_for(engine)},
        resources={"disk": disk_usage_report(BUILD_ROOT), "memory": memory_report()},
        job={"id": job.job_id, "lock": str(lock.path)},
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

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
        "skipped_render": reused_build,
    }
    payload["manifest_path"] = str(out_dir / "manifest.json")
    payload["job_id"] = job.job_id
    lock.assert_healthy()
    if qc["ok"]:
        job.transition("READY_TO_PUBLISH", sha256=payload["sha256"],
                       duration=qc["duration"], manifest=str(out_dir / "manifest.json"))
    else:
        job.transition("FAILED", error="qc failed",
                       blockers=[c["name"] for c in qc["checks"] if not c["ok"]])
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


def engine_digest_for(engine: str) -> str:
    """Provenance for the manifest: which engine drew these frames."""

    if engine == "stage":
        from .media.landscape_stage import engine_digest

        return engine_digest()
    return f"{engine}:portrait"


def load_specs() -> dict[str, ChannelSpec]:
    return load_channel_specs()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
