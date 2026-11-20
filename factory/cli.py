"""Command line entry point for the autonomous channel factory."""

from __future__ import annotations

import argparse
import json
import sys
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
    return build_hindi_script(spec, plan) if spec.is_hindi else build_english_script(spec, plan)


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


def cmd_render(args: argparse.Namespace) -> int:
    if args.plan_id and args.channel == "all":
        raise ValueError("--plan-id requires one --channel")
    results = []
    for spec in _specs(args.channel):
        results.append(
            render_episode(
                spec,
                plan_id=args.plan_id,
                force=args.force,
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
            )
        )
    _print(results if args.json else [json.dumps(item, ensure_ascii=False, indent=2) for item in results], args.json)
    return 0


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
    import shutil

    checks = []
    for command in ("ffmpeg", "ffprobe"):
        checks.append({"name": command, "ok": shutil.which(command) is not None, "path": shutil.which(command)})
    chrome = shutil.which("chrome") or str(Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m factory.cli", description="Autonomous multichannel video factory")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plans = subparsers.add_parser("plans")
    plans.add_argument("--channel", default="all")
    plans.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    plans.set_defaults(func=cmd_plans)

    render = subparsers.add_parser("render")
    render.add_argument("--channel", default="all")
    render.add_argument("--plan-id", default=None)
    render.add_argument("--force", action="store_true")
    render.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    render.set_defaults(func=cmd_render)

    qc = subparsers.add_parser("qc")
    qc.add_argument("--channel", required=True)
    qc.add_argument("--plan-id", default=None)
    qc.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    qc.set_defaults(func=cmd_qc)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--channel", required=True)
    publish.add_argument("--plan-id", default=None)
    publish.add_argument("--execute", action="store_true")
    publish.add_argument("--confirm-channel", default=None)
    publish.add_argument("--schedule", action="store_true")
    publish.add_argument("--publish-date", default=None)
    publish.add_argument("--allow-public", action="store_true")
    publish.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    publish.set_defaults(func=cmd_publish)

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
