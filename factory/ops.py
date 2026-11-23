"""Operational commands: preflight, publishing gate and the ops status view (T49 / Part 9).

A factory that runs unattended needs to answer, without reading logs: what is running, what finished,
what failed, what is ready to publish, what was uploaded, and which channel is blocked. `status` (T46)
answers the per-plan question; this answers the operational one and adds the two commands a workflow
calls before and after production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

from .config import BUILD_ROOT, STATE_ROOT, ChannelSpec
from .content.script import load_plans_for
from .orchestrator import episode_out_dir, plan_identifier
from .reliability import (
    ACTIVE_STATES,
    JOB_STATES,
    JobJournal,
    disk_usage_report,
    job_id_for,
    memory_report,
    preflight,
)
from .util import read_json


def cmd_preflight(args: Any, *, specs: dict[str, ChannelSpec], print_fn) -> int:
    channels = None if args.channel == "all" else [args.channel]
    report = preflight(channels=channels,
                       reserve_mb=int(getattr(args, "reserve_mb", 4096) or 4096))
    payload = report.to_dict()
    payload.update({"disk": disk_usage_report(BUILD_ROOT), "memory": memory_report()})
    print_fn(payload if args.json else (
        [f"{c['name']}: {'OK' if c['ok'] else 'FAIL'} {c['detail']}" for c in report.checks]))
    return 0 if report.ok else 2


def cmd_gate(args: Any, *, specs: dict[str, ChannelSpec], print_fn,
             script_for) -> int:
    from .qa.publish_gate import evaluate_publish_gate

    # Both composition profiles, the same way `orchestrator.episode_out_dir` and the render path decide them.
    # Iterating only the channel's default format made a rendered landscape episode invisible to the gate:
    # `gate --channel natkhat-toons` returned an empty report while its video, QC and manifest were on disk.
    from .orchestrator import plan_specs

    results: List[dict[str, Any]] = []
    skipped: List[str] = []
    for base_spec in specs.values():
        if args.channel != "all" and base_spec.slug != args.channel:
            continue
        for spec in plan_specs(base_spec):
            try:
                plans = load_plans_for(spec)
            except ValueError:
                # Nexus Node and Academic Biohacker have no long-form plan yet. That is a coverage gap for the
                # operator to see, not a reason for `gate` to fail on a channel whose Short is finished: the
                # first cloud run of this loop died here with "no long plans for channel 'academic-biohacker'".
                skipped.append(f"{spec.slug}/{spec.format}")
                continue
            for plan in plans:
                plan_id = plan_identifier(plan)
                if args.plan_id and plan_id != args.plan_id:
                    continue
                out_dir = episode_out_dir(spec, plan)
                video = out_dir / "video.mp4"
                if not video.is_file():
                    continue
                script = script_for(spec, plan)
                gate = evaluate_publish_gate(
                    spec, script, video, out_dir=out_dir,
                    thumbnail=out_dir / "thumbnail.jpg",
                    measure_decode=True, measure_loudness=True,
                )
                report = gate.to_dict()
                report.update({"channel": spec.slug, "plan_id": plan_id, "video": str(video)})
                (out_dir / "publish_gate.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                results.append(report)
    if not results:
        if args.plan_id:
            raise ValueError(
                f"plan {args.plan_id!r} has no rendered artifact to gate for channel {args.channel!r}"
            )
        print_fn([] if args.json else ["no rendered artifacts found"])
        return 1
    print_fn(results if args.json else [
        f"{r['channel']:18} {r['plan_id']:30} gate={'PASS' if r['ok'] else 'BLOCKED'} "
        f"{r['passed']}/{r['total']}"
        + ("" if r["ok"] else f" blockers={r['blockers']}")
        for r in results]
        + ([f"no plans to gate for: {', '.join(sorted(skipped))}"] if skipped else []))
    return 0 if all(r["ok"] for r in results) else 2


def collect_ops(specs: dict[str, ChannelSpec], *, channel: str = "all") -> dict[str, Any]:
    """Everything an operator needs, assembled from state that is already on disk."""

    from .state import ChannelState
    from uploader.config import load_channel_configs
    from uploader.ledger import Ledger

    from .config import CHANNELS_DIR, UPLOAD_STATE_ROOT

    try:
        configs = load_channel_configs(CHANNELS_DIR)
    except Exception:  # noqa: BLE001
        configs = {}

    channels: List[dict[str, Any]] = []
    for spec in specs.values():
        if channel != "all" and spec.slug != channel:
            continue
        jobs: List[dict[str, Any]] = []
        artifacts: List[dict[str, Any]] = []
        for plan in load_plans_for(spec):
            plan_id = plan_identifier(plan)
            out_dir = episode_out_dir(spec, plan)
            journal_root = STATE_ROOT / "jobs" / job_id_for(spec.slug, plan_id)
            journal = JobJournal(job_id_for(spec.slug, plan_id))
            snapshot = journal.snapshot() if journal_root.exists() else {}
            if snapshot:
                jobs.append({
                    "job_id": snapshot.get("job_id"),
                    "plan_id": plan_id,
                    "state": snapshot.get("state"),
                    "at": snapshot.get("at"),
                    "sha256": snapshot.get("sha256"),
                    "error": snapshot.get("error"),
                    "attempts": sum(1 for r in journal.records()
                                    if r.get("state") == "RECOVERABLE"),
                })
            video = out_dir / "video.mp4"
            if video.is_file():
                qc = read_json(out_dir / "qc.json", {})
                gate = read_json(out_dir / "publish_gate.json", {})
                manifest = read_json(out_dir / "manifest.json", {})
                artifacts.append({
                    "plan_id": plan_id,
                    "video": str(video),
                    "qc_ok": qc.get("ok"),
                    "gate_ok": gate.get("ok"),
                    "manifest": bool(manifest),
                    "bytes": video.stat().st_size,
                })

        uploads: List[dict[str, Any]] = []
        try:
            ledger = Ledger(UPLOAD_STATE_ROOT, spec.slug)
            for entry in ledger.entries()[-10:]:
                uploads.append({
                    "video_id": entry.video_id,
                    "status": entry.status,
                    "at": entry.produced_at,
                    "sha256": entry.video_sha256[:16],
                })
        except Exception:  # noqa: BLE001 - a missing ledger means "nothing uploaded yet"
            pass

        state = ChannelState(spec.slug)
        history = state.history()[-5:]
        blocked: List[str] = []
        if configs and spec.slug not in configs:
            blocked.append("no uploader channel config")
        pending = [a for a in artifacts if a["qc_ok"] and a["gate_ok"] is False]
        if pending:
            blocked.append(f"{len(pending)} artifact(s) failed the publishing gate")
        unknown = [u for u in uploads if u["status"] in ("uploading", "unknown")]
        if unknown:
            blocked.append(f"{len(unknown)} upload(s) in an unknown state - investigate before retry")

        channels.append({
            "channel": spec.slug,
            "format": spec.format,
            "language": spec.language,
            "jobs": jobs,
            "artifacts": artifacts,
            "uploads": uploads,
            "recent_history": history,
            "blocked": blocked,
        })

    running = [j for c in channels for j in c["jobs"] if j["state"] in ACTIVE_STATES]
    failed = [j for c in channels for j in c["jobs"] if j["state"] == "FAILED"]
    return {
        "job_states": list(JOB_STATES),
        "running": running,
        "failed": failed,
        "channels": channels,
        "summary": {
            "running": len(running),
            "failed": len(failed),
            "ready_to_publish": sum(
                1 for c in channels for a in c["artifacts"]
                if a["qc_ok"] and a["gate_ok"]),
            "uploaded": sum(len([u for u in c["uploads"] if u["status"] == "uploaded"])
                            for c in channels),
            "blocked_channels": [c["channel"] for c in channels if c["blocked"]],
        },
    }


def cmd_ops(args: Any, *, specs: dict[str, ChannelSpec], print_fn) -> int:
    payload = collect_ops(specs, channel=args.channel)
    if args.json:
        print_fn(payload)
        return 0
    lines = [
        f"running: {payload['summary']['running']}  failed: {payload['summary']['failed']}  "
        f"ready: {payload['summary']['ready_to_publish']}  uploaded: {payload['summary']['uploaded']}"
    ]
    for entry in payload["channels"]:
        lines.append(f"\n{entry['channel']} ({entry['format']}, {entry['language']})")
        for job in entry["jobs"]:
            lines.append(f"  job {job['plan_id']:30} {job['state']:16} {job['at'] or ''}")
        for artifact in entry["artifacts"]:
            lines.append(
                f"  artifact {artifact['plan_id']:30} qc={artifact['qc_ok']} "
                f"gate={artifact['gate_ok']} manifest={artifact['manifest']} "
                f"{artifact['bytes']} B")
        for upload in entry["uploads"][-3:]:
            lines.append(f"  upload {upload['status']:10} {upload['video_id'] or '-'}")
        for reason in entry["blocked"]:
            lines.append(f"  BLOCKED: {reason}")
    print_fn(lines)
    return 0
