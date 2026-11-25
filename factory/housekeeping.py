"""Storage housekeeping that cannot delete an unreleased episode.

Every episode leaves a build directory: roughly 8 MB of video plus, for Natkhat, a studio tree of
intermediates. Nothing ever removed them, so `build/` grows without bound - and on a €0/month machine the
disk is the budget.

The dangerous version of this feature is a `find build -mtime +14 -delete`, which is one typo away from
removing the only copy of a video that was rendered but never uploaded, or an artifact that failed QC and
is the only evidence of why. So the rules are: an artifact is only ever removed when it is **released**
(recorded as uploaded), **valid** (QC passed, manifest complete), **not running**, and **older than the
keep window**. Everything else is reported and kept, with the reason.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import BUILD_ROOT, ChannelSpec
from .state import ChannelState

#: Job states in which a build directory may still be being written.
ACTIVE_STATES = frozenset({"QUEUED", "PREFLIGHT", "GENERATING", "RENDERING", "VALIDATING", "PACKAGING"})


@dataclass
class Entry:
    """One build directory and the verdict on it."""

    channel: str
    plan_id: str
    path: Path
    bytes: int
    age_days: float
    action: str          # "delete" | "keep"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "plan_id": self.plan_id,
            "path": str(self.path),
            "bytes": self.bytes,
            "age_days": round(self.age_days, 1),
            "action": self.action,
            "reason": self.reason,
        }


def _tree_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    for item in path.rglob("*"):
        try:
            newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    return newest


def _active_job(state_root: Path | None, channel: str, plan_id: str) -> bool:
    """True when a job for this episode is still writing into its build directory."""

    if state_root is None:
        return False
    jobs = state_root / "jobs"
    if not jobs.is_dir():
        return False
    prefix = f"{channel}_{plan_id}"
    for job_dir in jobs.glob(f"{prefix}*"):
        record = _read(job_dir / "job.json")
        if str(record.get("state") or "") in ACTIVE_STATES:
            return True
    return False


def classify(root: Path, slug: str, out_dir: Path, *, keep_days: int,
             state_root: Path | None, now: datetime | None = None) -> Entry:
    """Decide what may happen to one build directory, and say why."""

    now = now or datetime.now(timezone.utc)
    age = (now.timestamp() - _newest_mtime(out_dir)) / 86_400
    plan_id = out_dir.name
    state = ChannelState(slug, root=state_root) if state_root is not None else ChannelState(slug)
    status = (state.plan_status(plan_id) or "").strip()

    def keep(reason: str) -> Entry:
        return Entry(slug, plan_id, out_dir, _tree_bytes(out_dir), age, "keep", reason)

    manifest = _read(out_dir / "manifest.json")
    qc = _read(out_dir / "qc.json")
    gate = _read(out_dir / "publish_gate.json")

    if not (out_dir / "video.mp4").is_file():
        return keep("no video.mp4: a partial build is evidence, not garbage")
    if not qc:
        return keep("no qc.json: validity is unknown")
    if not qc.get("ok"):
        return keep("QC failed: kept as evidence")
    if gate and not gate.get("ok", True):
        return keep("publishing gate blocked: kept for the blocker to be investigated")
    if not manifest or not manifest.get("artifacts"):
        return keep("no manifest: the package was never verified")
    if not all(item.get("complete") for item in manifest["artifacts"]):
        return keep("manifest has incomplete artifacts")
    if _active_job(state_root, slug, plan_id):
        return keep("a job is still writing here")
    if status != "uploaded":
        return keep(f"not released (status {status or 'unknown'}): only an uploaded episode is removed")
    if age < keep_days:
        return keep(f"released {age:.1f} days ago; the keep window is {keep_days}")

    return Entry(slug, plan_id, out_dir, _tree_bytes(out_dir), age, "delete",
                 f"released and {age:.1f} days old")


def scan(specs: Iterable[ChannelSpec], *, build_root: Path | str | None = None,
         state_root: Path | str | None = None, keep_days: int = 14,
         now: datetime | None = None) -> list[Entry]:
    root = Path(build_root or BUILD_ROOT)
    state = Path(state_root) if state_root else None
    entries: list[Entry] = []
    for spec in specs:
        channel_dir = root / spec.slug
        if not channel_dir.is_dir():
            continue
        for out_dir in sorted(p for p in channel_dir.iterdir() if p.is_dir()):
            entries.append(classify(root, spec.slug, out_dir, keep_days=keep_days,
                                    state_root=state, now=now))
    return entries


def apply(entries: Iterable[Entry]) -> dict[str, Any]:
    """Delete the entries classified as deletable. Returns what happened, not what was intended."""

    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for entry in entries:
        if entry.action != "delete":
            continue
        try:
            shutil.rmtree(entry.path)
        except OSError as exc:
            failed.append({**entry.to_dict(), "error": f"{type(exc).__name__}: {exc}"})
            continue
        deleted.append(entry.to_dict())
    return {
        "deleted": deleted,
        "failed": failed,
        "freed_bytes": sum(item["bytes"] for item in deleted),
    }


def summary(entries: list[Entry], *, keep_days: int) -> dict[str, Any]:
    deletable = [entry for entry in entries if entry.action == "delete"]
    return {
        "keep_days": keep_days,
        "build_entries": len(entries),
        "deletable": len(deletable),
        "reclaimable_bytes": sum(entry.bytes for entry in deletable),
        "total_bytes": sum(entry.bytes for entry in entries),
    }


def cutoff(keep_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat(timespec="seconds")
