"""Observability for unattended production: notifications, resource guardrails, structured logs.

T49 gave the factory locks, journals and a publishing gate. What it still lacked was the part an
operator needs at 3am: a way to be *told* something went wrong, a way to know the machine will not die
half-way through, and a log that a machine can read.

Everything here is provider-independent and disabled by default. A notifier that claims to have sent
something it could not send is worse than no notifier, so :func:`notifier_from_env` reports whether it
is actually configured and why not.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

# -- events -----------------------------------------------------------------------------------

JOB_STARTED = "job_started"
RENDER_COMPLETED = "render_completed"
QC_FAILED = "qc_failed"
UPLOAD_BLOCKED = "upload_blocked"
WORKFLOW_FAILED = "workflow_failed"
RECOVERY_SUCCEEDED = "recovery_succeeded"

EVENTS = (JOB_STARTED, RENDER_COMPLETED, QC_FAILED, UPLOAD_BLOCKED, WORKFLOW_FAILED,
          RECOVERY_SUCCEEDED)


class Notifier:
    """Provider-independent sink. Implementations must be safe to call when nothing is configured."""

    name = "null"

    def send(self, event: str, payload: Mapping[str, Any]) -> bool:
        return False

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.name, "enabled": False, "reason": "not configured"}


class NullNotifier(Notifier):
    """Records what it would have sent. The default, and the honest default."""

    def __init__(self, reason: str = "no notification provider configured") -> None:
        self.reason = reason
        self.sent: List[Dict[str, Any]] = []

    def send(self, event: str, payload: Mapping[str, Any]) -> bool:
        self.sent.append({"event": event, "payload": dict(payload), "delivered": False})
        return False

    def describe(self) -> Dict[str, Any]:
        return {"provider": "null", "enabled": False, "reason": self.reason,
                "recorded": len(self.sent)}


class WebhookNotifier(Notifier):
    """POST a small JSON body to a URL.

    The transport is injectable so the body can be tested without a network, and a failed delivery is
    reported as ``False`` rather than swallowed - an alert that silently fails is the worst outcome.
    """

    name = "webhook"

    def __init__(self, url: str, *, timeout: float = 10.0,
                 transport: Optional[Callable[[str, bytes, float], int]] = None) -> None:
        self.url = url
        self.timeout = timeout
        self.transport = transport or _post_json
        self.last_error: Optional[str] = None
        self.delivered = 0

    def send(self, event: str, payload: Mapping[str, Any]) -> bool:
        body = json.dumps({"event": event, "payload": dict(payload)},
                          ensure_ascii=False).encode("utf-8")
        try:
            status = self.transport(self.url, body, self.timeout)
        except Exception as exc:  # network, DNS, TLS: all recorded, none fatal
            self.last_error = str(exc)
            return False
        if 200 <= int(status) < 300:
            self.delivered += 1
            return True
        self.last_error = f"HTTP {status}"
        return False

    def describe(self) -> Dict[str, Any]:
        return {"provider": "webhook", "enabled": True, "delivered": self.delivered,
                "last_error": self.last_error,
                "url_host": self.url.split("//")[-1].split("/")[0] if self.url else ""}


def _post_json(url: str, body: bytes, timeout: float) -> int:
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured URL
        return int(response.status)


def notifier_from_env(environ: Optional[Mapping[str, str]] = None) -> Notifier:
    """Build the notifier the environment asks for, and say plainly when there is none.

    No URL is invented and no credential is looked for: without ``FACTORY_NOTIFY_WEBHOOK`` the result
    is a :class:`NullNotifier` that still records the events, so the pipeline is testable and nothing
    claims to have been delivered.
    """

    env = dict(os.environ if environ is None else environ)
    url = (env.get("FACTORY_NOTIFY_WEBHOOK") or "").strip()
    if not url:
        return NullNotifier()
    if not url.startswith(("https://", "http://")):
        return NullNotifier(reason=f"FACTORY_NOTIFY_WEBHOOK is not an http(s) URL: {url[:12]}...")
    return WebhookNotifier(url)


# -- resources ---------------------------------------------------------------------------------


@dataclass
class ResourceSample:
    at: float
    rss_mb: Optional[float]
    disk_free_mb: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return {"at": round(self.at, 2), "rss_mb": self.rss_mb, "disk_free_mb": self.disk_free_mb}


def process_rss_mb() -> Optional[float]:
    """Resident memory of this process, from the OS, with no third-party dependency."""

    try:
        if Path("/proc/self/status").is_file():
            for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:
        pass
    try:  # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        # The handle has to be declared: GetCurrentProcess returns a pseudo-handle, and without
        # `restype = HANDLE` ctypes hands back an int that the memory call rejects - which is why
        # the first version silently reported no memory at all on Windows.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel32.GetCurrentProcess()
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters),
                                               wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return round(counters.WorkingSetSize / (1024.0 * 1024.0), 1)
    except Exception:
        pass
    return None


def estimate_render_mb(frames: int, width: int, height: int) -> float:
    """Working set a render needs, from the buffers it allocates.

    Two full ARGB surfaces (frame + mask) plus cairo's own overhead, times a safety factor for the
    encoder and the audio pipeline. Deliberately conservative: the point is to refuse a job that
    cannot finish, not to squeeze the last megabyte.
    """

    per_frame = width * height * 4 / (1024.0 * 1024.0)
    return round(per_frame * 3.0 + 220.0, 1)


@dataclass
class ResourceMonitor:
    """Samples memory and disk while a job runs, and says when to stop before corrupting output."""

    output_dir: Path
    floor_mb: float = 512.0
    samples: List[ResourceSample] = field(default_factory=list)
    peak_rss_mb: float = 0.0
    min_disk_mb: Optional[float] = None
    started: float = field(default_factory=time.time)

    def sample(self) -> ResourceSample:
        rss = process_rss_mb()
        try:
            disk = shutil.disk_usage(str(self.output_dir)).free / (1024.0 * 1024.0)
        except OSError:
            disk = None
        record = ResourceSample(at=time.time() - self.started, rss_mb=rss, disk_free_mb=disk)
        self.samples.append(record)
        if rss is not None:
            self.peak_rss_mb = max(self.peak_rss_mb, rss)
        if disk is not None:
            self.min_disk_mb = disk if self.min_disk_mb is None else min(self.min_disk_mb, disk)
        return record

    def healthy(self) -> bool:
        last = self.samples[-1] if self.samples else self.sample()
        if last.disk_free_mb is not None and last.disk_free_mb < self.floor_mb:
            return False
        return True

    def as_dict(self) -> Dict[str, Any]:
        return {"samples": len(self.samples),
                "peak_rss_mb": round(self.peak_rss_mb, 1) or None,
                "min_disk_free_mb": (round(self.min_disk_mb, 1)
                                     if self.min_disk_mb is not None else None),
                "floor_mb": self.floor_mb,
                "platform": platform.platform()}


# -- structured job log -------------------------------------------------------------------------

#: Keys every job record carries. A log that omits them is not parseable in practice, because the
#: first question asked of it is always "which job, which channel, which episode".
REQUIRED_KEYS = ("job_id", "channel", "episode", "started_at", "status")


@dataclass
class JobLog:
    """One line-per-event structured log of a production job, readable by a human and a machine."""

    job_id: str
    channel: str
    episode: str
    path: Optional[Path] = None
    config: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.started_at = time.time()

    def record(self, event: str, **fields: Any) -> Dict[str, Any]:
        entry = {"job_id": self.job_id, "channel": self.channel, "episode": self.episode,
                 "event": event, "at": round(time.time() - self.started_at, 3), **fields}
        self.events.append(entry)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def scene(self, scene_num: int, seconds: float, *, cached: bool, frames: int) -> None:
        self.record("scene_rendered", scene=scene_num, seconds=round(seconds, 2),
                    cached=bool(cached), frames=frames,
                    fps=round(frames / seconds, 2) if seconds > 0 else None)

    def finish(self, status: str, **fields: Any) -> Dict[str, Any]:
        return self.record("finished", status=status, wall_seconds=round(
            time.time() - self.started_at, 2), **fields)

    def as_dict(self) -> Dict[str, Any]:
        cache_hits = sum(1 for e in self.events if e.get("cached"))
        scenes = [e for e in self.events if e.get("event") == "scene_rendered"]
        return {"job_id": self.job_id, "channel": self.channel, "episode": self.episode,
                "config": dict(self.config),
                "started_at": self.started_at,
                "wall_seconds": round(time.time() - self.started_at, 2),
                "scenes": len(scenes), "cache_hits": cache_hits,
                "scene_seconds": {str(e.get("scene")): e.get("seconds") for e in scenes},
                "events": list(self.events)}


def write_job_log(path: Path, log: JobLog) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
