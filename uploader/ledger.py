from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import DuplicateUploadError, UploaderError

DUPLICATE_STATUSES = {"uploaded", "uploading", "unknown"}
STATUSES = {"planned", "uploading", "uploaded", "failed", "unknown"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileLock:
    def __init__(self, root: Path | str, timeout: float = 10.0) -> None:
        self.root = Path(root)
        self.path = self.root / ".lock"
        self.timeout = timeout
        self.acquired = False

    def __enter__(self) -> "FileLock":
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(
                    str(self.path),
                    os.O_CREAT | os.O_EXCL | os.O_RDWR,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"{os.getpid()} {utc_now()}\n")
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    age = 0
                if age > 600:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise UploaderError(f"could not acquire ledger lock: {self.path}")
                time.sleep(0.1)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.acquired = False


@dataclass
class LedgerEntry:
    job_id: str
    channel_slug: str
    status: str
    video_sha256: str
    metadata_sha256: str
    title: str
    privacy_status: str
    video_path: str | None = None
    video_id: str | None = None
    video_url: str | None = None
    attempts: int = 0
    error_code: str | None = None
    error_message: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"invalid ledger status: {self.status}")
        if not self.created_at:
            self.created_at = utc_now()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEntry":
        return cls(**data)


class Ledger:
    def __init__(self, root: Path | str, channel_slug: str) -> None:
        self.root = Path(root) / channel_slug
        self.channel_slug = channel_slug
        self.path = self.root / "ledger.jsonl"
        self.history_path = self.root / "history.jsonl"

    def append(self, entry: LedgerEntry) -> None:
        if entry.channel_slug != self.channel_slug:
            raise ValueError("ledger channel mismatch")
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self.root):
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def entries(self) -> list[LedgerEntry]:
        if not self.path.is_file():
            return []
        result: list[LedgerEntry] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    result.append(LedgerEntry.from_dict(data))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return result

    def latest_for_job(self, job_id: str) -> LedgerEntry | None:
        for entry in reversed(self.entries()):
            if entry.job_id == job_id:
                return entry
        return None

    def latest_for_hash(self, video_sha256: str) -> LedgerEntry | None:
        for entry in reversed(self.entries()):
            if entry.video_sha256 == video_sha256:
                return entry
        return None

    def assert_no_duplicate(self, video_sha256: str) -> LedgerEntry | None:
        latest = self.latest_for_hash(video_sha256)
        if latest and latest.status in DUPLICATE_STATUSES:
            raise DuplicateUploadError(
                f"video hash already has ledger status {latest.status} "
                f"for job {latest.job_id}",
                status=latest.status,
            )
        return latest

    def start(
        self,
        *,
        job_id: str,
        video_sha256: str,
        metadata_sha256: str,
        title: str,
        privacy_status: str,
        video_path: str | None,
        attempts: int = 1,
    ) -> LedgerEntry:
        entry = LedgerEntry(
            job_id=job_id,
            channel_slug=self.channel_slug,
            status="uploading",
            video_sha256=video_sha256,
            metadata_sha256=metadata_sha256,
            title=title,
            privacy_status=privacy_status,
            video_path=video_path,
            attempts=attempts,
        )
        self.append(entry)
        return entry

    def mark_uploaded(
        self,
        job_id: str,
        *,
        video_id: str,
        video_url: str,
        attempts: int,
    ) -> LedgerEntry:
        base = self.latest_for_job(job_id)
        if base is None:
            raise UploaderError(f"unknown ledger job: {job_id}")
        entry = LedgerEntry(
            job_id=job_id,
            channel_slug=self.channel_slug,
            status="uploaded",
            video_sha256=base.video_sha256,
            metadata_sha256=base.metadata_sha256,
            title=base.title,
            privacy_status=base.privacy_status,
            video_path=base.video_path,
            video_id=video_id,
            video_url=video_url,
            attempts=attempts,
            created_at=base.created_at,
        )
        self.append(entry)
        with self.root.joinpath("history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    def mark_failed(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
        attempts: int,
    ) -> LedgerEntry:
        return self._mark_terminal(
            job_id,
            status="failed",
            error_code=error_code,
            error_message=error_message,
            attempts=attempts,
        )

    def mark_unknown(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
        attempts: int,
    ) -> LedgerEntry:
        return self._mark_terminal(
            job_id,
            status="unknown",
            error_code=error_code,
            error_message=error_message,
            attempts=attempts,
        )

    def _mark_terminal(
        self,
        job_id: str,
        *,
        status: str,
        error_code: str,
        error_message: str,
        attempts: int,
    ) -> LedgerEntry:
        base = self.latest_for_job(job_id)
        if base is None:
            raise UploaderError(f"unknown ledger job: {job_id}")
        entry = LedgerEntry(
            job_id=job_id,
            channel_slug=self.channel_slug,
            status=status,
            video_sha256=base.video_sha256,
            metadata_sha256=base.metadata_sha256,
            title=base.title,
            privacy_status=base.privacy_status,
            video_path=base.video_path,
            video_id=base.video_id,
            video_url=base.video_url,
            attempts=attempts,
            error_code=error_code,
            error_message=error_message,
            created_at=base.created_at,
        )
        self.append(entry)
        return entry

    def history(self) -> list[LedgerEntry]:
        return [entry for entry in self.entries() if entry.status == "uploaded"]

    def summary(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for entry in self.entries():
            result[entry.status] = result.get(entry.status, 0) + 1
        return result
