"""Small shared helpers with no third-party dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable

IST = timedelta(hours=5, minutes=30)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"[^a-zA-Z0-9\u0900-\u097F]+", "-", value).strip("-").lower()
    return value or "item"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u0900-\u097F]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def fingerprint(value: str) -> str:
    normalized = normalize_text(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path | str, default: Any = None) -> Any:
    path = Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def append_jsonl(path: Path | str, entry: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def run(command: list[str], *, timeout: float = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command[:6])}\n{result.stderr[-3000:]}"
        )
    return result


def ffprobe_duration(path: Path | str) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=30,
    )
    text = result.stdout.strip()
    if not text:
        raise RuntimeError(f"ffprobe returned no duration for {path}")
    return float(text)


def ffprobe_streams(path: Path | str) -> dict[str, Any]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
    )
    return json.loads(result.stdout)


def chunk_words(words: list[str], max_words: int = 3) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if len(current) >= max_words:
            chunks.append(current)
            current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def distribute_times(total: float, weights: Iterable[float]) -> list[tuple[float, float]]:
    weights = [max(1.0, float(weight)) for weight in weights]
    if not weights:
        return []
    scale = total / sum(weights)
    result: list[tuple[float, float]] = []
    cursor = 0.0
    for weight in weights:
        end = cursor + weight * scale
        result.append((cursor, end))
        cursor = end
    return result


def hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def publish_at_utc(date_iso: str, time_ist: str) -> str:
    """Converts a date and an IST wall-clock time to an RFC3339 UTC timestamp."""
    if not time_ist:
        raise ValueError("publish time is required")
    hour, minute = (int(part) for part in time_ist.split(":")[:2])
    local = datetime.fromisoformat(date_iso).replace(
        hour=hour, minute=minute, second=0, microsecond=0, tzinfo=timezone.utc
    ) - IST
    return local.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
