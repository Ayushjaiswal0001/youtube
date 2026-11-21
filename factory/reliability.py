"""Production reliability: preflight, locks, job states, retries, manifests (T49).

Unattended production fails in ways an attended run does not. Nobody is watching the disk fill up,
nobody notices that the last run left a lock behind, and nobody is there to press render again when
a runner is killed mid-encode. This module is the machinery that makes those failures survivable:

* **preflight** - refuse to start a job that cannot finish (no disk, no RAM, no ffmpeg, no fonts).
* **job locks** - two runs for the same channel and plan must not both render; a lock left by a
  killed process must not block production forever.
* **job states** - every job records the states it passed through, so a crashed job can be resumed
  rather than guessed at.
* **retry classification** - retry what a retry can fix (network, timeout, a busy file); never
  retry what it cannot (invalid content, a QC failure, a rejected credential).
* **manifests** - a package describes itself: what was produced, from which inputs, verified how.

Everything here is deliberately dependency-free and testable without rendering anything.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import BUILD_ROOT, STATE_ROOT

# ---------------------------------------------------------------------------
# Job states
# ---------------------------------------------------------------------------

# The lifecycle of one production job. The order is the calendar order, not a menu: a job may skip
# stages (a render-only run stops at READY_TO_PUBLISH), and may go from any active state to FAILED
# or RECOVERABLE.
JOB_STATES: Tuple[str, ...] = (
    "QUEUED",
    "PREFLIGHT",
    "GENERATING",
    "RENDERING",
    "VALIDATING",
    "PACKAGING",
    "READY_TO_PUBLISH",
    "PUBLISHING",
    "PUBLISHED",
    "FAILED",
    "RECOVERABLE",
)

TERMINAL_STATES = frozenset({"PUBLISHED", "FAILED"})
# RECOVERABLE is intentionally not terminal: it means "stopped in a way a later run can continue".
ACTIVE_STATES = frozenset({"QUEUED", "PREFLIGHT", "GENERATING", "RENDERING", "VALIDATING",
                           "PACKAGING", "READY_TO_PUBLISH", "PUBLISHING", "RECOVERABLE"})

# Which transitions are legal. Kept explicit so a bug that jumps from RENDERING to PUBLISHED is
# rejected rather than recorded as history.
ALLOWED_TRANSITIONS: Dict[str, frozenset] = {
    "QUEUED": frozenset({"PREFLIGHT", "FAILED", "RECOVERABLE"}),
    # A resumed job goes straight from preflight to rendering when its plan and script already
    # exist, so the skip edges are part of the machine rather than an exception in the caller.
    "PREFLIGHT": frozenset({"GENERATING", "RENDERING", "VALIDATING", "FAILED", "RECOVERABLE"}),
    "GENERATING": frozenset({"RENDERING", "FAILED", "RECOVERABLE", "VALIDATING"}),
    "RENDERING": frozenset({"VALIDATING", "FAILED", "RECOVERABLE", "PACKAGING"}),
    "VALIDATING": frozenset({"PACKAGING", "FAILED", "RECOVERABLE", "READY_TO_PUBLISH"}),
    "PACKAGING": frozenset({"READY_TO_PUBLISH", "FAILED", "RECOVERABLE"}),
    "READY_TO_PUBLISH": frozenset({"PUBLISHING", "PUBLISHED", "FAILED", "RECOVERABLE"}),
    "PUBLISHING": frozenset({"PUBLISHED", "FAILED", "RECOVERABLE"}),
    "PUBLISHED": frozenset(),
    "FAILED": frozenset({"RECOVERABLE", "QUEUED"}),
    "RECOVERABLE": frozenset({"PREFLIGHT", "GENERATING", "RENDERING", "VALIDATING",
                              "PACKAGING", "PUBLISHING", "FAILED", "QUEUED"}),
}


class InvalidTransition(RuntimeError):
    """A job tried to move between states that do not connect."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_id_for(channel: str, plan_id: str, *, run: Optional[str] = None) -> str:
    """A stable identity for a production job.

    Deliberately *not* random: two runs of the same plan on the same day are the same job, which is
    what lets a resumed run find the state a crashed one left behind.
    """

    stamp = run or datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{channel}_{plan_id}_{stamp}"


class JobJournal:
    """Append-only record of everything that happened to one job.

    Written as JSON lines so a crash leaves a readable prefix rather than a corrupt document, and
    mirrored into `job.json` so a status command reads one small file instead of replaying history.
    """

    def __init__(self, job_id: str, root: Optional[Path] = None) -> None:
        self.job_id = job_id
        self.root = Path(root or (STATE_ROOT / "jobs")) / job_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = self.root / "journal.jsonl"
        self.snapshot_path = self.root / "job.json"

    # -- reading ---------------------------------------------------------
    def records(self) -> List[dict[str, Any]]:
        if not self.journal.is_file():
            return []
        out: List[dict[str, Any]] = []
        for line in self.journal.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # A killed process can leave one torn line; everything before it is still valid.
                continue
        return out

    def snapshot(self) -> dict[str, Any]:
        if self.snapshot_path.is_file():
            try:
                return json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        records = self.records()
        return records[-1] if records else {}

    def state(self) -> Optional[str]:
        return self.snapshot().get("state")

    # -- writing ---------------------------------------------------------
    def transition(self, to: str, **detail: Any) -> dict[str, Any]:
        current = self.state()
        if current and to not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidTransition(f"{self.job_id}: {current} -> {to} is not a legal transition")
        record = {
            "job_id": self.job_id,
            "state": to,
            "previous": current,
            "at": utc_now(),
            **detail,
        }
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp = self.snapshot_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        os.replace(tmp, self.snapshot_path)
        return record

    def attempts(self) -> int:
        return sum(1 for record in self.records() if record.get("state") == "RECOVERABLE")


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

@dataclass
class LockInfo:
    pid: int
    host: str
    acquired_at: str
    job_id: str
    heartbeat: float


class JobLock:
    """One lock file per channel+plan, safe across processes and across runners.

    Three properties matter and each has a failure it prevents:

    * **exclusive creation** (`O_EXCL`) - two runs starting in the same second cannot both win.
    * **heartbeat** - a long render keeps its lock alive, so a slow job is not mistaken for a dead
      one and cannot have its lock stolen mid-encode.
    * **stale detection** - a lock whose process is gone, or whose heartbeat stopped, is taken over.
      Without it, one killed run blocks that channel forever, which is how an unattended factory
      stops producing silently.
    """

    def __init__(self, path: Path | str, *, job_id: str, ttl: float = 900.0) -> None:
        self.path = Path(path)
        self.job_id = job_id
        self.ttl = float(ttl)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._held = False

    # -- inspection ------------------------------------------------------
    def read(self) -> Optional[LockInfo]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None
        try:
            return LockInfo(
                pid=int(data["pid"]), host=str(data["host"]),
                acquired_at=str(data["acquired_at"]), job_id=str(data["job_id"]),
                heartbeat=float(data.get("heartbeat", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def is_stale(self, info: Optional[LockInfo] = None) -> bool:
        info = info or self.read()
        if info is None:
            # An unreadable lock is not a reason to refuse work; it is a reason to replace it.
            return self.path.exists()
        age = time.time() - info.heartbeat
        if age > self.ttl:
            return True
        # A different host cannot be probed; trust the heartbeat. Same host: check the pid, because
        # a killed process leaves a fresh heartbeat behind for as long as the ttl.
        if info.host == socket.gethostname():
            try:
                os.kill(info.pid, 0)
            except (ProcessLookupError, PermissionError):
                return True
            except OSError:
                return True
        return False

    # -- acquisition -----------------------------------------------------
    def acquire(self, *, blocking: bool = False, poll: float = 1.0,
                timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self.is_stale():
                    # Replace atomically: unlink then retry the exclusive create, so a race between
                    # two sweepers still leaves exactly one winner.
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if not blocking:
                    return False
                if deadline is not None and time.time() > deadline:
                    return False
                time.sleep(poll)
                continue
            payload = json.dumps({
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "acquired_at": utc_now(),
                "job_id": self.job_id,
                "heartbeat": time.time(),
            }).encode("utf-8")
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            self._held = True
            return True

    def heartbeat(self) -> None:
        if not self._held:
            return
        info = self.read()
        payload = {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": info.acquired_at if info else utc_now(),
            "job_id": self.job_id,
            "heartbeat": time.time(),
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)

    def release(self) -> None:
        if not self._held:
            return
        info = self.read()
        # Only the owner removes the lock: a stolen lock must not be deleted by its previous owner.
        if info is None or info.job_id == self.job_id:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._held = False

    def __enter__(self) -> "JobLock":
        if not self.acquire():
            raise LockBusy(f"{self.path.name} is held by another job")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


class LockBusy(RuntimeError):
    """Another job already owns this channel and plan."""


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

# Measured on the development machine: a 64.5 s landscape episode at 1080p needs ~1.3 GB of scene
# output plus the episode, an ~8 MB final artifact and a few hundred MB of intermediates. The
# reserve is deliberately generous because running out of disk mid-encode wastes the whole render.
DEFAULT_DISK_RESERVE_MB = 4096
DEFAULT_MIN_RAM_MB = 512


@dataclass
class PreflightReport:
    ok: bool
    checks: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: Any = "", *, severity: str = "error") -> None:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail,
                            "severity": severity})
        if not ok and severity == "error":
            self.ok = False

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks,
                "failed": [c["name"] for c in self.checks
                           if not c["ok"] and c["severity"] == "error"]}


def available_memory_mb() -> Optional[float]:
    """Free RAM without a third-party dependency.

    `/proc/meminfo` on Linux (which is what the runner is) and the Win32 global memory status
    locally. Returns None when the platform offers neither, and preflight then reports memory as
    unenforced rather than inventing a number - a wrong number here would block production for the
    wrong reason.
    """

    proc = Path("/proc/meminfo")
    if proc.is_file():
        try:
            for line in proc.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024.0
        except Exception:  # noqa: BLE001
            return None
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return float(status.ullAvailPhys) / (1024 * 1024)
        except Exception:  # noqa: BLE001
            return None
    return None


def _memory_mb() -> Optional[float]:
    return available_memory_mb()


def _which_versions(commands: Sequence[str]) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for command in commands:
        path = shutil.which(command)
        if not path:
            continue
        try:
            out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20)
            found[command] = (out.stdout or out.stderr).splitlines()[0][:120] if out.stdout or out.stderr else path
        except Exception:  # noqa: BLE001
            found[command] = path
    return found


def preflight(
    *,
    disk_paths: Optional[Iterable[Path]] = None,
    reserve_mb: int = DEFAULT_DISK_RESERVE_MB,
    min_ram_mb: int = DEFAULT_MIN_RAM_MB,
    require_fonts: bool = True,
    fonts_dir: Optional[Path] = None,
    require_chrome: bool = False,
    channels: Optional[Iterable[str]] = None,
) -> PreflightReport:
    """Refuse to start work the machine cannot finish.

    Each check answers a question that has actually stopped a production run: is ffmpeg installed,
    can both codecs encode, does the runner have the Devanagari font, is there room for another
    episode, is there RAM to draw frames, can we write to the build and state roots.
    """

    report = PreflightReport(ok=True)
    versions = _which_versions(("ffmpeg", "ffprobe"))
    for name in ("ffmpeg", "ffprobe"):
        report.add(name, name in versions, versions.get(name, "not found"))

    if "ffmpeg" in versions:
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                  capture_output=True, text=True, timeout=30)
        for encoder in ("libx264", "aac"):
            report.add(f"encoder_{encoder}", encoder in (encoders.stdout or ""),
                       "available" if encoder in (encoders.stdout or "") else "missing")

    if require_fonts:
        from .config import FONTS_DIR

        fonts = Path(fonts_dir or FONTS_DIR)
        devanagari = sorted(fonts.glob("*Devanagari*")) if fonts.is_dir() else []
        report.add("fonts_dir", fonts.is_dir(), str(fonts))
        report.add("devanagari_font", bool(devanagari),
                   [path.name for path in devanagari] or "no Devanagari font found")
        # Devanagari needs shaping, not just a glyph table: an unshaped string renders as boxes.
        try:
            from PIL import ImageFont

            if devanagari:
                ImageFont.truetype(str(devanagari[0]), 24)
                report.add("font_loadable", True, devanagari[0].name)
        except Exception as exc:  # noqa: BLE001
            report.add("font_loadable", False, str(exc))

    if require_chrome:
        chrome = os.environ.get("CHROME_PATH") or shutil.which("google-chrome") \
            or shutil.which("chromium")
        report.add("chrome", bool(chrome) and Path(str(chrome)).exists(), str(chrome))

    for path in (disk_paths or (BUILD_ROOT, STATE_ROOT)):
        path = Path(path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
            free_mb = usage.free // (1024 * 1024)
            report.add(f"disk:{path.name}", free_mb >= reserve_mb,
                       f"{free_mb} MB free, {reserve_mb} MB reserved")
            probe = path / ".preflight-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            report.add(f"writable:{path.name}", True, str(path))
        except Exception as exc:  # noqa: BLE001
            report.add(f"disk:{path.name}", False, str(exc))

    ram = _memory_mb()
    if ram is None:
        report.add("memory", True, "unavailable (psutil missing) - not enforced",
                   severity="warning")
    else:
        report.add("memory", ram >= min_ram_mb, f"{ram:.0f} MB available")

    if channels is not None:
        from .config import load_channel_specs

        try:
            specs = load_channel_specs()
            missing = [slug for slug in channels if slug not in specs]
            report.add("channel_configs", not missing,
                       f"known: {sorted(specs)}" + (f"; unknown: {missing}" if missing else ""))
        except Exception as exc:  # noqa: BLE001
            report.add("channel_configs", False, str(exc))

    return report


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------

# What a retry can fix. The distinction matters more than the retry itself: retrying a QC failure
# wastes ten minutes to fail identically, while not retrying a dropped connection loses a whole
# render that would have succeeded.
TRANSIENT_MARKERS: Tuple[str, ...] = (
    "timed out", "timeout", "connection reset", "connection aborted", "temporarily unavailable",
    "temporary failure", "network is unreachable", "broken pipe", "server error", "502", "503",
    "504", "429", "rate limit", "resource temporarily unavailable", "permission denied",
    "text file busy", "device or resource busy", "no space left", "unexpected eof",
)

PERMANENT_MARKERS: Tuple[str, ...] = (
    "invalid", "no scenes matched", "unknown channel", "not found", "schema", "unsupported",
    "refused", "forbidden", "401", "403", "404", "quota", "duplicate", "does not exist",
)


def classify_failure(error: BaseException | str) -> str:
    """`transient`, `permanent` or `unknown`."""

    if isinstance(error, (TimeoutError, ConnectionError)):
        return "transient"
    if isinstance(error, (ValueError, KeyError, FileNotFoundError, ImportError)):
        return "permanent"
    text = (str(error) or error.__class__.__name__).lower()
    if any(marker in text for marker in PERMANENT_MARKERS):
        return "permanent"
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return "transient"
    return "unknown"


@dataclass
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = 30.0
    sleep: Callable[[float], None] = time.sleep

    def delay_for(self, attempt: int) -> float:
        # Exponential with a hard ceiling. No jitter: production logs are compared across runs and
        # randomness there makes "why did this take 41 s" unanswerable.
        return min(self.max_delay, self.base_delay * (2 ** max(0, attempt - 1)))

    def call(self, func: Callable[[], Any], *, on_retry: Optional[Callable[[int, Exception], None]] = None,
             what: str = "operation") -> Any:
        last: Optional[BaseException] = None
        for attempt in range(1, self.attempts + 1):
            try:
                return func()
            except BaseException as exc:  # noqa: BLE001 - classification decides what happens next
                last = exc
                kind = classify_failure(exc)
                if kind == "permanent" or attempt == self.attempts:
                    raise
                if on_retry is not None:
                    on_retry(attempt, exc if isinstance(exc, Exception) else Exception(str(exc)))
                self.sleep(self.delay_for(attempt))
        raise last if last else RuntimeError(f"{what} failed")


# ---------------------------------------------------------------------------
# Process timeouts
# ---------------------------------------------------------------------------

def run_process(command: Sequence[str], *, timeout: float, cwd: Optional[Path] = None,
                env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run a child with a hard timeout and no orphan processes.

    A hung ffmpeg on a runner burns the whole job timeout and leaves a half-written MP4 that a later
    run must not trust. `start_new_session` plus a kill of the whole process group means the timeout
    actually stops the work rather than detaching it.
    """

    process = subprocess.Popen(
        list(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=str(cwd) if cwd else None, env=env, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        raise TimeoutError(
            f"{command[0]} exceeded {timeout:.0f}s and was killed: {' '.join(command[:3])}...")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _kill_group(process: subprocess.Popen) -> None:
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows only
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), 9)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        process.communicate(timeout=10)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Cleanup that cannot eat a finished product
# ---------------------------------------------------------------------------

# Only these are ever deleted. A finished artifact is never in this list, so "clean up" can never
# destroy a video somebody is about to publish.
DISPOSABLE_PATTERNS: Tuple[str, ...] = (
    "*.partial.mp4", "*.mp4.partial", "*.tmp", "*.txt.tmp", "*.partial", "*.wav.tmp",
)

# Anything a production run may legitimately still need, even if it is old.
PROTECTED_NAMES: Tuple[str, ...] = (
    "video.mp4", "video_normalized.mp4", "qc.json", "timeline.json", "story.json",
    "script.json", "captions.srt", "thumbnail.jpg", "manifest.json", "shot_plan.json",
    "framing.json", "publish_manifest.json",
)


def sweep_disposable(root: Path | str, *, older_than: float = 3600.0,
                     now: Optional[float] = None) -> List[str]:
    """Delete abandoned temporary files, and nothing else."""

    root = Path(root)
    now = time.time() if now is None else now
    removed: List[str] = []
    if not root.is_dir():
        return removed
    for pattern in DISPOSABLE_PATTERNS:
        for path in root.rglob(pattern):
            if path.name in PROTECTED_NAMES or not path.is_file():
                continue
            try:
                if now - path.stat().st_mtime < older_than:
                    continue
                path.unlink()
                removed.append(str(path))
            except OSError:
                continue
    return removed


def disk_usage_report(path: Path | str) -> Dict[str, Any]:
    usage = shutil.disk_usage(str(path))
    return {
        "path": str(path),
        "total_mb": usage.total // (1024 * 1024),
        "used_mb": usage.used // (1024 * 1024),
        "free_mb": usage.free // (1024 * 1024),
    }


def memory_report() -> Dict[str, Any]:
    available = available_memory_mb()
    if available is None:
        return {"available_mb": None, "note": "unavailable on this platform"}
    return {"available_mb": int(available)}


# ---------------------------------------------------------------------------
# Media integrity
# ---------------------------------------------------------------------------

def media_is_complete(path: Path | str) -> bool:
    """Is this file a finished, decodable MP4?

    Used before cache reuse. A file that exists is not a file that finished: a killed encode leaves
    an MP4 with a header and no moov atom, and treating that as done is how a corrupt episode reaches
    a viewer.
    """

    path = Path(path)
    if not path.is_file() or path.stat().st_size < 10_000:
        return False
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,nb_frames", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:  # noqa: BLE001
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return False
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    has_video = any(stream.get("codec_type") == "video"
                    for stream in payload.get("streams") or [])
    return duration > 0.2 and has_video


# ---------------------------------------------------------------------------
# Production manifest
# ---------------------------------------------------------------------------

def sha256_file(path: Path | str, chunk: int = 1 << 20) -> str:
    import hashlib

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def production_manifest(
    *,
    channel: str,
    plan_id: str,
    engine: str,
    format: str,
    artifacts: Mapping_like,
    qc: Optional[Dict[str, Any]] = None,
    inputs: Optional[Dict[str, Any]] = None,
    resources: Optional[Dict[str, Any]] = None,
    job: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Describe a package: what it is, what made it, and how it was verified.

    The hashes are the point. An artifact with a manifest can be checked by whoever receives it -
    a runner, an uploader, a human - without trusting the process that produced it.
    """

    entries: List[Dict[str, Any]] = []
    for name, path in dict(artifacts).items():
        path = Path(path)
        if not path.is_file():
            continue
        entries.append({
            "name": name,
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "complete": media_is_complete(path) if path.suffix == ".mp4" else True,
        })
    return {
        "schema": "factory.manifest.v1",
        "channel": channel,
        "plan_id": plan_id,
        "engine": engine,
        "format": format,
        "created_at": utc_now(),
        "artifacts": entries,
        "qc": {
            "ok": bool((qc or {}).get("ok")),
            "checks": len((qc or {}).get("checks") or []),
            "failed": [c.get("name") for c in (qc or {}).get("checks") or []
                       if not c.get("ok")],
        },
        "inputs": dict(inputs or {}),
        "resources": dict(resources or {}),
        "job": dict(job or {}),
    }


# A minimal structural type so the signature reads well without importing typing.Mapping at runtime
# in a way that confuses older tooling.
Mapping_like = Dict[str, Any]
