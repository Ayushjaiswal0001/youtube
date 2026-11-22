"""Command line entry point for the autonomous channel factory."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import (
    BUILD_ROOT,
    FONTS_DIR,
    ChannelSpec,
    load_channel_specs,
    selected_channels,
)
from .content.plans import bank_status, generate_plan
from .content.script import build_english_script, build_hindi_script, load_plans_for
from .orchestrator import (
    episode_out_dir,
    find_plan,
    plan_identifier,
    render_episode,
)
from .publisher import analytics_for, publish_episode
from .qa.validator import validate_episode
from .util import IST, publish_at_utc, read_json


@contextlib.contextmanager
def _progress_to_stderr(as_json: bool):
    """Keep stdout clean when the caller asked for JSON.

    The renderer and the stage print their progress, and that progress used to land on stdout ahead
    of the JSON payload, so `render --json | jq` failed on `[Render] Scene 1: ...`. Progress belongs
    on stderr; only the payload belongs on stdout.
    """

    if not as_json:
        yield
        return
    original = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = original


def _print(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif isinstance(payload, list):
        for item in payload:
            print(item)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(payload)


def _specs(value: str) -> list[ChannelSpec]:
    return selected_channels(value, load_channel_specs())


def _script_for(spec: ChannelSpec, plan: dict[str, Any]):
    """Engine-aware: a landscape plan is not a portrait plan with different keys."""

    from .orchestrator import build_script

    return build_script(spec, plan)


def _rendered_plan(spec: ChannelSpec, plan_id: str | None) -> dict[str, Any]:
    if plan_id:
        return find_plan(spec, plan_id)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for plan in load_plans_for(spec):
        video = episode_out_dir(spec, plan) / "video.mp4"
        if video.is_file():
            candidates.append((video.stat().st_mtime, plan))
    if not candidates:
        raise ValueError(f"no rendered plan found for {spec.slug}")
    return max(candidates, key=lambda item: item[0])[1]


def _next_ist_date(spec: ChannelSpec) -> str:
    now_ist = datetime.now(timezone.utc) + IST
    hour, minute = (int(part) for part in (spec.publish_time_ist or "12:00").split(":")[:2])
    target = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_ist:
        target = target + timedelta(days=1)
    return target.date().isoformat()


def cmd_plans(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    for spec in _specs(args.channel):
        if getattr(args, "format", None):
            spec = replace(spec, format=args.format)
        for plan in load_plans_for(spec):
            out_dir = episode_out_dir(spec, plan)
            rows.append(
                {
                    "channel": spec.slug,
                    "plan_id": plan_identifier(plan),
                    "title": plan.get("title", ""),
                    "rendered": (out_dir / "video.mp4").is_file(),
                    "out_dir": str(out_dir),
                }
            )
    _print(rows if args.json else [f"{r['channel']:22} {r['plan_id']:32} {'rendered' if r['rendered'] else 'pending':8} {r['title']}" for r in rows], args.json)
    return 0


def _only_scenes(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(part) for part in str(value).split(",") if part.strip()] or None


def _render_one(
    spec: ChannelSpec,
    plan_id: str | None,
    *,
    force: bool,
    scenes: str | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    return render_episode(
        spec,
        plan_id=plan_id,
        force=force,
        only_scenes=_only_scenes(scenes),
        demo=demo,
    )


def cmd_render_stage(args: argparse.Namespace) -> int:
    """Alias for `render --format long` on a stage plan.

    Kept because it is in the documented workflow, but it no longer *is* a second pipeline: the
    landscape stage is one engine behind `render_episode`, so thumbnails, subtitles, QC and state
    take the same code path as a Short. A second copy of those steps is how two paths drift apart.
    """

    from .config import load_channel_specs
    from .orchestrator import resolve_engine

    specs = load_channel_specs()
    if args.channel not in specs:
        raise ValueError(f"unknown channel {args.channel!r}; known: {', '.join(sorted(specs))}")
    spec = replace(specs[args.channel], format="long")
    plan = find_plan(spec, args.plan_id)
    engine = resolve_engine(spec, plan)
    if engine != "stage":
        raise ValueError(
            f"plan {plan_identifier(plan)} uses the {engine!r} engine; render-stage only drives "
            'stage plans (declare "engine": "stage" in the plan)')
    result = _render_one(spec, args.plan_id, force=args.force, scenes=args.scenes,
                         demo=bool(getattr(args, "demo", False)))
    _print(result, args.json)
    return 0 if result["qc_ok"] else 1


def _stage_scene_state(out_dir: Path, spec: ChannelSpec, plan: dict[str, Any]) -> dict[str, int]:
    from .media.landscape_stage import plan_scenes, scene_is_current

    # `plan_scenes` owns the plan schema (the authored key is "n", not "scene"); asking it is the
    # only way this stays correct. Reading `scene["scene"]` here reported twelve missing scenes for
    # an episode that was entirely on disk.
    scenes = plan_scenes(plan)
    scene_dir = out_dir / "studio" / "intermediate" / f"{spec.slug}_{plan_identifier(plan)}"
    counts = {"scenes": len(scenes), "current": 0, "stale": 0, "missing": 0}
    for scene in scenes:
        target = scene_dir / f"scene_{int(scene['scene_num']):03d}.mp4"
        if not target.is_file():
            counts["missing"] += 1
            continue
        try:
            signature = json.loads(
                target.with_suffix(".json").read_text(encoding="utf-8")).get("signature", "")
        except Exception:
            signature = ""
        if scene_is_current(target, signature):
            counts["current"] += 1
        else:
            counts["stale"] += 1
    return counts


def cmd_status(args: argparse.Namespace) -> int:
    """Production status per plan: what exists, what is stale, and what to run next."""

    from .orchestrator import resolve_engine

    rows: list[dict[str, Any]] = []
    for spec in _specs(args.channel):
        if getattr(args, "format", None):
            spec = replace(spec, format=args.format)
        for plan in load_plans_for(spec):
            plan_id = plan_identifier(plan)
            if args.plan_id and plan_id != args.plan_id:
                continue
            engine = resolve_engine(spec, plan)
            out_dir = episode_out_dir(spec, plan)
            video = out_dir / "video.mp4"
            qc = read_json(out_dir / "qc.json", {})
            row: dict[str, Any] = {
                "channel": spec.slug,
                "format": spec.format,
                "plan_id": plan_id,
                "engine": engine,
                "video": str(video) if video.is_file() else None,
                "qc_ok": qc.get("ok"),
                "next": "render" if not video.is_file() else (
                    "done" if qc.get("ok") else "inspect qc.json, then resume"),
            }
            if engine == "stage":
                row.update(_stage_scene_state(out_dir, spec, plan))
                # A missing scene only matters when the assembled artifact is not verified: an
                # episode whose video passed QC is finished even if an intermediate was cleaned up.
                if (row["missing"] or row["stale"]) and not (video.is_file() and qc.get("ok")):
                    row["next"] = f"resume ({row['missing']} missing, {row['stale']} stale)"
            rows.append(row)
    _print(rows if args.json else [
        f"{r['channel']:18} {r['format']:6} {r['plan_id']:30} {r['engine']:6} "
        f"{('qc-ok' if r['qc_ok'] else ('qc-fail' if r['qc_ok'] is False else 'no-qc')):7} "
        f"{r['next']}" for r in rows], args.json)
    return 0


def _iter_requested_plans(args: argparse.Namespace):
    """Walk the plans this verb should touch, and fail loudly when the requested one is not there.

    Two cloud acceptance runs printed an empty report and exited 0 because `--plan-id nexus-power-grid`
    matched nothing: the plan existed only in the local build that named it, never in `content/`. `validate`
    then returned `[]`, the workflow's QC step crashed with `IndexError: list index out of range`, and the
    run failed three steps away from the cause. A requested plan that cannot be resolved is an error, not an
    empty result, and the error says which plans exist.
    """

    requested = str(getattr(args, "plan_id", "") or "")
    seen: list[str] = []
    matched = False
    for spec in _specs(args.channel):
        if getattr(args, "format", None):
            spec = replace(spec, format=args.format)
        try:
            plans = load_plans_for(spec)
        except ValueError:
            # a channel with no plans for this composition profile is not an error here
            continue
        for plan in plans:
            plan_id = plan_identifier(plan)
            seen.append(plan_id)
            if requested and plan_id != requested:
                continue
            matched = matched or bool(requested)
            yield spec, plan
    if requested and not matched:
        raise ValueError(
            f"plan {requested!r} is not in this repository; known plans: "
            + (", ".join(sorted(set(seen))) or "none")
        )


def cmd_resume(args: argparse.Namespace) -> int:
    """Continue a production without redoing work that is still valid.

    Safe by construction: a scene carries a signature of everything that affects its pixels and its
    audio, so only missing or mismatched scenes are re-rendered, and a verified artifact with passing
    QC is left untouched unless `--force` is given.
    """

    results: list[dict[str, Any]] = []
    for spec, plan in _iter_requested_plans(args):
            plan_id = plan_identifier(plan)
            out_dir = episode_out_dir(spec, plan)
            qc = read_json(out_dir / "qc.json", {})
            if (out_dir / "video.mp4").is_file() and qc.get("ok") and not args.force:
                continue
            results.append(_render_one(spec, plan_id, force=args.force))
    if not results:
        _print([] if args.json else ["nothing to resume: every episode has a verified artifact"],
               args.json)
        return 0
    _print(results if args.json else [
        f"{r['channel']:18} {r['plan_id']:30} rendered={r.get('rendered_scenes', '-')} "
        f"reused={r.get('reused_scenes', '-')} qc_ok={r['qc_ok']}" for r in results], args.json)
    return 0 if all(r["qc_ok"] for r in results) else 2


def cmd_preflight(args: argparse.Namespace) -> int:
    from .ops import cmd_preflight as run

    return run(args, specs=load_channel_specs(), print_fn=lambda value: _print(value, args.json))


def cmd_manifest(args: argparse.Namespace) -> int:
    """Re-hash the package as it stands now. The workflow calls this after its own QC step."""

    from .manifesting import rebuild, verify

    results: list[dict[str, Any]] = []
    for spec, plan in _iter_requested_plans(args):
            plan_id = plan_identifier(plan)
            out_dir = episode_out_dir(spec, plan)
            if not (out_dir / "video.mp4").is_file():
                continue
            manifest = rebuild(out_dir, channel=spec.slug, plan_id=plan_id, format=spec.format)
            problems = verify(out_dir)
            results.append({
                "channel": spec.slug,
                "plan_id": plan_id,
                "path": str(out_dir / "manifest.json"),
                "artifacts": len(manifest["artifacts"]),
                "missing_required": manifest["package"]["missing_required"],
                "problems": problems,
                "ok": not problems and not manifest["package"]["missing_required"],
            })
    if not results:
        _print([] if args.json else ["no rendered artifacts found"], args.json)
        return 1
    _print(results if args.json else [
        f"{item['channel']} {item['plan_id']}: {item['artifacts']} artifacts, "
        f"{'verified' if item['ok'] else 'problems: ' + '; '.join(item['problems'] or item['missing_required'])}"
        for item in results], args.json)
    return 0 if all(item["ok"] for item in results) else 2


def cmd_gate(args: argparse.Namespace) -> int:
    from .ops import cmd_gate as run

    return run(args, specs=load_channel_specs(), print_fn=lambda value: _print(value, args.json),
               script_for=_script_for)


def cmd_ops(args: argparse.Namespace) -> int:
    from .ops import cmd_ops as run

    return run(args, specs=load_channel_specs(), print_fn=lambda value: _print(value, args.json))


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate existing artifacts without producing anything new."""

    results: list[dict[str, Any]] = []
    for spec, plan in _iter_requested_plans(args):
            plan_id = plan_identifier(plan)
            out_dir = episode_out_dir(spec, plan)
            video = out_dir / "video.mp4"
            if not video.is_file():
                continue
            script = _script_for(spec, plan)
            qc = validate_episode(
                spec, script, video,
                thumbnail=out_dir / "thumbnail.jpg",
                srt=out_dir / "captions.srt",
                report_path=out_dir / "qc.json",
                demo=bool(getattr(args, "demo", False)),
            )
            results.append({
                "channel": spec.slug,
                "plan_id": plan_id,
                "video": str(video),
                "qc_ok": qc.get("ok"),
                "checks": len(qc.get("checks", [])),
                "failures": [c["name"] for c in qc.get("checks", []) if not c.get("ok")],
            })
    if not results:
        _print([] if args.json else ["no rendered artifacts found"], args.json)
        return 1
    _print(results if args.json else [
        f"{r['channel']:18} {r['plan_id']:30} qc_ok={r['qc_ok']} failures={r['failures']}"
        for r in results], args.json)
    return 0 if all(r["qc_ok"] for r in results) else 2


def cmd_render(args: argparse.Namespace) -> int:
    if args.plan_id and args.channel == "all":
        raise ValueError("--plan-id requires one --channel")
    formats = [f for f in str(getattr(args, "formats", "") or "").split(",") if f]
    if formats and not args.plan_id:
        raise ValueError("--formats requires --plan-id: one plan is rendered in each format")
    from .controls import ensure_allowed

    ensure_allowed(args.channel, action="render")
    results = []
    with _progress_to_stderr(bool(args.json)):
        for spec in _specs(args.channel):
            for fmt in (formats or [getattr(args, "format", None) or spec.format]):
                results.append(
                    render_episode(
                        replace(spec, format=fmt),
                        plan_id=args.plan_id,
                        force=args.force,
                        only_scenes=_only_scenes(getattr(args, "scenes", None)),
                        demo=bool(getattr(args, "demo", False)),
                    )
                )
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0 if all(item["qc_ok"] for item in results) else 2


def cmd_qc(args: argparse.Namespace) -> int:
    results = []
    for spec in _specs(args.channel):
        plan = _rendered_plan(spec, args.plan_id)
        script = _script_for(spec, plan)
        out_dir = episode_out_dir(spec, plan)
        results.append(
            validate_episode(
                spec,
                script,
                out_dir / "video.mp4",
                thumbnail=out_dir / "thumbnail.jpg",
                srt=out_dir / "captions.srt",
                report_path=out_dir / "qc.json",
            )
        )
    _print(results if args.json else [f"{r['channel']}: {'PASS' if r['ok'] else 'FAIL'} ({r['error_count']} errors)" for r in results], args.json)
    return 0 if all(item["ok"] for item in results) else 2


def cmd_publish(args: argparse.Namespace) -> int:
    if args.plan_id and args.channel == "all":
        raise ValueError("--plan-id requires one --channel")
    # Checked here as well as in `render`: a channel paused between render and upload must not publish, and
    # an operator should never have to remember which verb they started. Nothing is read before this.
    from .controls import ensure_allowed

    for spec in _specs(args.channel):
        ensure_allowed(spec.slug, action="publish")
    results = []
    for spec in _specs(args.channel):
        plan = _rendered_plan(spec, args.plan_id)
        script = _script_for(spec, plan)
        out_dir = episode_out_dir(spec, plan)
        publish_at = None
        if args.schedule:
            date = args.publish_date or _next_ist_date(spec)
            publish_at = publish_at_utc(date, spec.publish_time_ist or "12:00")
        results.append(
            publish_episode(
                spec,
                script,
                out_dir / "video.mp4",
                execute=args.execute,
                confirm_channel=args.confirm_channel,
                publish_at=publish_at,
                thumbnail=out_dir / "thumbnail.jpg",
                allow_public=args.allow_public,
                skip_gate=bool(getattr(args, "skip_gate", False)),
            )
        )
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    """Discover candidate topics from the permitted feeds and write a research record."""

    from . import research as research_engine
    from .state import ChannelState

    results = []
    for spec in _specs(args.channel):
        sources = research_engine.load_sources(Path(args.sources))
        history = ChannelState(spec.slug).history()
        titles = [str(item.get("title") or "") for item in history]
        report = research_engine.discover(
            spec, sources, now=None if not args.date else _research_now(args.date),
            history_titles=titles, limit=args.limit)
        path = research_engine.write_report(report, Path(args.out))
        results.append({"channel": spec.slug, "path": str(path),
                        "candidates": len(report.candidates),
                        "rejected": len(report.rejected),
                        "sources": report.sources,
                        "errors": getattr(report, "errors", []),
                        "digest": research_engine.digest(report),
                        "top": [{"title": c.title, "score": c.score, "url": c.link}
                                for c in report.candidates[: args.limit]]})
    _print(results, args.json)
    return 0


def _research_now(value: str):
    from datetime import datetime, timezone

    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def cmd_pause(args: argparse.Namespace) -> int:
    from .controls import pause, pause_state, resume

    if args.resume:
        removed = resume(args.channel or None)
        _print({"resumed": args.channel or "all", "removed": removed}, args.json)
        return 0
    path = pause(args.channel or None)
    _print({"paused": args.channel or "all", "flag": str(path),
            "state": pause_state(args.channel or None).as_dict()}, args.json)
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    """Send one operational message through the configured notifier (null when unconfigured)."""

    from .observability import notifier_from_env

    notifier = notifier_from_env()
    delivered = notifier.send(args.subject, {"message": args.message})
    _print({"delivered": delivered, "notifier": type(notifier).__name__}, args.json)
    return 0 if delivered else 1


def cmd_analytics(args: argparse.Namespace) -> int:
    results = [analytics_for(spec, limit=args.limit) for spec in _specs(args.channel)]
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    results: list[dict[str, Any]] = []
    for spec in _specs(args.channel):
        rendered = 0
        for _ in range(max(1, args.per_channel)):
            plan = find_plan(spec)
            if args.plan_id and plan_identifier(plan) != args.plan_id:
                continue
            results.append(render_episode(spec, plan, force=args.force))
            rendered += 1
        if rendered == 0:
            results.append({"channel": spec.slug, "skipped": True, "reason": "no pending plans"})
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0 if all(item.get("qc_ok", True) for item in results) else 2


def cmd_doctor(args: argparse.Namespace) -> int:
    import os
    import shutil

    from .config import ensure_runtime_dirs

    # A fresh CI checkout has no build/state/log directories yet; create them the same
    # way the pipeline does so a missing directory is not reported as a broken setup.
    ensure_runtime_dirs()

    checks = []
    for command in ("ffmpeg", "ffprobe"):
        checks.append({"name": command, "ok": shutil.which(command) is not None, "path": shutil.which(command)})
    chrome = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        chrome = os.environ.get("CHROME_PATH") or str(
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe")
        )
    checks.append({"name": "chrome", "ok": Path(chrome).is_file(), "path": chrome})
    checks.append({"name": "fonts", "ok": FONTS_DIR.is_dir(), "path": str(FONTS_DIR)})
    checks.append({"name": "build_root", "ok": BUILD_ROOT.is_dir(), "path": str(BUILD_ROOT)})
    try:
        specs = load_channel_specs()
        checks.append({"name": "channel_configs", "ok": True, "detail": sorted(specs)})
    except Exception as exc:  # noqa: BLE001 - doctor reports setup failures
        checks.append({"name": "channel_configs", "ok": False, "detail": str(exc)})
    payload = {"ok": all(item["ok"] for item in checks), "checks": checks}
    _print(payload if args.json else [f"{item['name']}: {'OK' if item['ok'] else 'FAIL'} {item.get('path') or item.get('detail', '')}" for item in checks], args.json)
    return 0 if payload["ok"] else 2


def cmd_plan_new(args: argparse.Namespace) -> int:
    results = []
    for spec in _specs(args.channel):
        results.append(
            generate_plan(
                spec,
                allow_unpublished=args.allow_unpublished,
                write=not args.no_write,
            )
        )
    _print(
        results
        if args.json
        else [
            f"{item['channel']:22} {item['plan_id']:34} "
            f"{'created' if item['created'] else 'exists':8} {item['plan'].get('title', '')}"
            for item in results
        ],
        args.json,
    )
    return 0


def cmd_plan_status(args: argparse.Namespace) -> int:
    results = [bank_status(spec) for spec in _specs(args.channel)]
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m factory.cli", description="Autonomous multichannel video factory")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plans = subparsers.add_parser("plans")
    plans.add_argument("--channel", default="all")
    plans.add_argument("--format", choices=("shorts", "long"), default=None)
    plans.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    plans.set_defaults(func=cmd_plans)

    render = subparsers.add_parser("render")
    render.add_argument("--channel", default="all")
    render.add_argument("--plan-id", default=None)
    render.add_argument("--format", choices=["shorts", "long"], default=None,
                        help="override the channel's native profile")
    render.add_argument("--formats", default=None,
                        help="comma separated: render one plan in each of these formats")
    render.add_argument("--scenes", default=None,
                        help="stage plans: comma separated scene numbers (demos only)")
    render.add_argument("--demo", action="store_true",
                        help="a deliberate fragment: waives the duration lower bound")
    render.add_argument("--force", action="store_true")
    render.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    render.set_defaults(func=cmd_render)

    stage = subparsers.add_parser(
        "render-stage",
        help="render a 16:9 character episode from a landscape stage plan")
    stage.add_argument("--channel", required=True)
    stage.add_argument("--plan-id", required=True)
    stage.add_argument("--force", action="store_true")
    stage.add_argument("--scenes", default=None,
                       help="comma separated scene numbers, e.g. 1,2,5 (for demos)")
    stage.add_argument("--demo", action="store_true",
                       help="a deliberate fragment: waives the duration lower bound")
    stage.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    stage.set_defaults(func=cmd_render_stage)

    preflight = subparsers.add_parser("preflight", help="can this machine start a production run?")
    preflight.add_argument("--channel", default="all")
    preflight.add_argument("--reserve-mb", type=int, default=4096)
    preflight.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    preflight.set_defaults(func=cmd_preflight)

    manifest = subparsers.add_parser(
        "manifest", help="re-hash an episode package and rebuild manifest.json")
    manifest.add_argument("--channel", default="all")
    manifest.add_argument("--plan-id", default="")
    manifest.add_argument("--format", default="")
    manifest.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    manifest.set_defaults(func=cmd_manifest)

    gate = subparsers.add_parser("gate", help="publishing gate: may this artifact be published?")
    gate.add_argument("--channel", default="all")
    gate.add_argument("--plan-id", default=None)
    gate.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    gate.set_defaults(func=cmd_gate)

    ops = subparsers.add_parser("ops", help="operational view: jobs, artifacts, uploads, blockers")
    ops.add_argument("--channel", default="all")
    ops.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    ops.set_defaults(func=cmd_ops)

    status = subparsers.add_parser("status", help="production status per plan")
    status.add_argument("--channel", default="all")
    status.add_argument("--plan-id", default=None)
    status.add_argument("--format", choices=["shorts", "long"], default=None)
    status.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    status.set_defaults(func=cmd_status)

    resume = subparsers.add_parser("resume", help="continue unfinished productions safely")
    resume.add_argument("--channel", default="all")
    resume.add_argument("--plan-id", default=None)
    resume.add_argument("--format", choices=["shorts", "long"], default=None)
    resume.add_argument("--force", action="store_true")
    resume.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    resume.set_defaults(func=cmd_resume)

    validate = subparsers.add_parser("validate", help="validate existing artifacts (no render)")
    validate.add_argument("--channel", default="all")
    validate.add_argument("--plan-id", default=None)
    validate.add_argument("--format", choices=["shorts", "long"], default=None)
    validate.add_argument("--demo", action="store_true")
    validate.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    validate.set_defaults(func=cmd_validate)

    qc = subparsers.add_parser("qc")
    qc.add_argument("--channel", required=True)
    qc.add_argument("--plan-id", default=None)
    qc.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    qc.set_defaults(func=cmd_qc)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--channel", required=True)
    publish.add_argument("--plan-id", default=None)
    publish.add_argument("--execute", action="store_true")
    publish.add_argument("--skip-gate", action="store_true",
                         help="dry run only: report the gate verdict without enforcing it")
    publish.add_argument("--confirm-channel", default=None)
    publish.add_argument("--schedule", action="store_true")
    publish.add_argument("--publish-date", default=None)
    publish.add_argument("--allow-public", action="store_true")
    publish.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    publish.set_defaults(func=cmd_publish)

    pause = subparsers.add_parser("pause", help="stop all production, or one channel")
    pause.add_argument("--channel", default="")
    pause.add_argument("--resume", action="store_true", help="clear the pause instead of setting it")
    pause.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    pause.set_defaults(func=cmd_pause)

    notify = subparsers.add_parser("notify", help="send one operational message if a notifier is set")
    notify.add_argument("--subject", default="X100 factory")
    notify.add_argument("--message", required=True)
    notify.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    notify.set_defaults(func=cmd_notify)

    research = subparsers.add_parser("research",
                                     help="discover topics from permitted feeds and record sources")
    research.add_argument("--channel", required=True)
    research.add_argument("--limit", type=int, default=10)
    research.add_argument("--date", default="", help="evaluate freshness as of this ISO date")
    research.add_argument("--sources", default="content/research/sources.json")
    research.add_argument("--out", default="build/research")
    research.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    research.set_defaults(func=cmd_research)

    analytics = subparsers.add_parser("analytics")
    analytics.add_argument("--channel", required=True)
    analytics.add_argument("--limit", type=int, default=50)
    analytics.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    analytics.set_defaults(func=cmd_analytics)

    batch = subparsers.add_parser("batch")
    batch.add_argument("--channel", default="all")
    batch.add_argument("--per-channel", type=int, default=1)
    batch.add_argument("--plan-id", default=None)
    batch.add_argument("--force", action="store_true")
    batch.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    batch.set_defaults(func=cmd_batch)

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    doctor.set_defaults(func=cmd_doctor)

    plan = subparsers.add_parser("plan", help="generate and inspect episode plans")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)

    plan_new = plan_sub.add_parser("new", help="write the next plan for a channel")
    plan_new.add_argument("--channel", default="all")
    plan_new.add_argument(
        "--allow-unpublished",
        action="store_true",
        help="Natkhat: plan the next episode even if the previous one has not been uploaded",
    )
    plan_new.add_argument("--no-write", action="store_true", help="preview without touching the batch")
    plan_new.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    plan_new.set_defaults(func=cmd_plan_new)

    plan_status = plan_sub.add_parser("status", help="remaining topics / series position")
    plan_status.add_argument("--channel", default="all")
    plan_status.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    plan_status.set_defaults(func=cmd_plan_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
