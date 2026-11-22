"""The manifest is the package's integrity record, so it must describe the final bytes.

The first cloud run failed its publishing gate with `6 artifacts, hash mismatch: ['qc_report']`. The cause was
ordering, not hashing: the render wrote `manifest.json` (hashing the QC report it had just produced), then the
workflow ran its own QC step, which rewrote `qc.json` with a new `checked_at`. The gate then compared the
manifest against a file that had changed since. Same byte length, different bytes - the worst kind of
mismatch, because a size check would have called it fine.

This module owns one definition of "the package": which files belong in it, how each is hashed, and what
"verifies" means. The rebuild is deliberate and idempotent, so the workflow can run it after any step that
writes a report, and the gate has nothing to guess.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# name -> filename, in the order a reader would want them
CANONICAL: Tuple[Tuple[str, str], ...] = (
    ("video", "video.mp4"),
    ("thumbnail", "thumbnail.jpg"),
    ("captions", "captions.srt"),
    ("qc_report", "qc.json"),
    ("timeline", "timeline.json"),
    ("script", "script.json"),
    ("story", "story.json"),
    ("framing", "framing.json"),
    ("shot_plan", "shot_plan.json"),
    ("continuity", "continuity.json"),
    ("audio", "audio.json"),
    ("video_probe", "video.json"),
)

REQUIRED = ("video", "thumbnail", "captions", "qc_report")


def sha256_file(path: Path | str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_artifacts(out_dir: Path | str) -> Dict[str, Path]:
    """Every canonical artifact that exists in this episode directory."""

    root = Path(out_dir)
    found: Dict[str, Path] = {}
    for name, filename in CANONICAL:
        candidate = root / filename
        if candidate.is_file():
            found[name] = candidate
    return found


def _entry(name: str, path: Path, root: Path) -> Dict[str, Any]:
    return {
        "name": name,
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "complete": True,
    }


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def rebuild(
    out_dir: Path | str,
    *,
    channel: Optional[str] = None,
    plan_id: Optional[str] = None,
    engine: Optional[str] = None,
    format: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-hash the package as it stands now, and write the manifest atomically.

    Metadata the render recorded (inputs, resources, job) is preserved; only the artifact list, the QC record
    and `created_at` are refreshed. Nothing is invented: an artifact that is not on disk is not listed.
    """

    root = Path(out_dir)
    previous = _read(root / "manifest.json") or {}
    qc = _read(root / "qc.json")
    artifacts = [_entry(name, path, root) for name, path in collect_artifacts(root).items()]

    manifest: Dict[str, Any] = {
        "schema": previous.get("schema") or "production-manifest/2",
        "channel": channel or previous.get("channel"),
        "plan_id": plan_id or previous.get("plan_id"),
        "engine": engine or previous.get("engine"),
        "format": format or previous.get("format"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rebuilt": True,
        "artifacts": artifacts,
        "qc": {
            "ok": bool((qc or {}).get("ok")),
            "checked_at": (qc or {}).get("checked_at"),
            "error_count": int((qc or {}).get("error_count") or 0),
            "report": "qc.json",
        } if qc else previous.get("qc"),
        "inputs": previous.get("inputs") or {},
        "resources": previous.get("resources") or {},
        "job": previous.get("job") or {},
        "package": {
            "required": list(REQUIRED),
            "present": [entry["name"] for entry in artifacts],
            "missing_required": [name for name in REQUIRED if name not in {e["name"] for e in artifacts}],
        },
    }

    handle, temp = tempfile.mkstemp(dir=str(root), prefix=".manifest.", suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(temp, root / "manifest.json")
    return manifest


def verify(out_dir: Path | str) -> List[str]:
    """Everything wrong with the package as it stands. Empty list means it verifies.

    Three failures are distinguished, because they have three different causes: a file that changed after it
    was hashed, a file the manifest claims but that is not there, and a package that grew an artifact the
    manifest never saw. The last one is how the first cloud run failed without looking like a hash bug.
    """

    root = Path(out_dir)
    manifest = _read(root / "manifest.json")
    if not manifest:
        return ["manifest.json missing"]

    problems: List[str] = []
    listed: Dict[str, Dict[str, Any]] = {}
    for entry in manifest.get("artifacts") or []:
        name = str(entry.get("name") or "?")
        listed[name] = entry
        candidate = root / str(entry.get("path") or "")
        if not candidate.is_file():
            problems.append(f"{name}: missing")
            continue
        if sha256_file(candidate) != entry.get("sha256"):
            problems.append(f"{name}: hash mismatch")
        elif candidate.stat().st_size != entry.get("bytes"):
            problems.append(f"{name}: size mismatch")

    for name in REQUIRED:
        if name not in listed:
            problems.append(f"{name}: not in manifest")

    for name, path in collect_artifacts(root).items():
        if name not in listed:
            problems.append(f"{name}: unlisted artifact on disk")

    qc = _read(root / "qc.json")
    recorded = (manifest.get("qc") or {}).get("checked_at")
    if qc and recorded and qc.get("checked_at") and qc["checked_at"] != recorded:
        problems.append("qc_report: manifest predates the QC report (rebuild required)")

    return problems
