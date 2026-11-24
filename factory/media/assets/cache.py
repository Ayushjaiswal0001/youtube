"""Content-addressed asset cache.

Layout: ``<root>/<channel>/<kind>/<sha256[:16]>.<ext>`` with a sidecar ``.json`` holding the
provenance record. Content addressing means the same bytes are stored once no matter how many
scenes or episodes ask for them, deduplication is a hash comparison rather than a heuristic, and a
render that produced a given manifest can be reproduced from the cache with no network at all.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .metadata import AssetRecord

DEFAULT_CACHE_ROOT = Path(".cache") / "x100_assets"


def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


class AssetCache:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else DEFAULT_CACHE_ROOT

    # -- layout -----------------------------------------------------------------
    def directory_for(self, channel: str, kind: str) -> Path:
        path = self.root / channel / kind
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for_hash(self, channel: str, kind: str, digest: str, suffix: str) -> Path:
        return self.directory_for(channel, kind) / f"{digest[:16]}{suffix}"

    # -- operations -------------------------------------------------------------
    def store(self, channel: str, kind: str, source: str | Path, record: AssetRecord) -> AssetRecord:
        """Copy bytes into the cache and write the provenance sidecar next to them."""

        suffix = Path(source).suffix.lower() or ".png"
        target = self.path_for_hash(channel, kind, record.file_hash_sha256, suffix)
        if not target.is_file() or sha256_file(target) != record.file_hash_sha256:
            shutil.copy2(source, target)
        stored = AssetRecord(**{**record.__dict__, "local_path": str(target)})
        self.write_record(channel, kind, stored)
        return stored

    def sidecar_path(self, record: AssetRecord) -> Path:
        return Path(record.local_path).with_suffix(".json")

    def write_record(self, channel: str, kind: str, record: AssetRecord) -> Path:
        del channel, kind  # layout is already encoded in local_path
        sidecar = self.sidecar_path(record)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(record.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        return sidecar

    def read_record(self, path: str | Path) -> AssetRecord | None:
        sidecar = Path(path).with_suffix(".json")
        if not sidecar.is_file():
            return None
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        allowed = {field for field in AssetRecord.__dataclass_fields__}
        return AssetRecord(**{key: value for key, value in data.items() if key in allowed})

    def lookup(self, channel: str, kind: str, digest: str) -> AssetRecord | None:
        directory = self.root / channel / kind
        if not directory.is_dir():
            return None
        for candidate in directory.glob(f"{digest[:16]}.*"):
            if candidate.suffix == ".json":
                continue
            return self.read_record(candidate)
        return None

    def verify(self, record: AssetRecord) -> bool:
        """True only when the file is present and still hashes to what the record claims."""

        path = Path(record.local_path)
        # A cached record points into the cache; an uncached one points at its origin. Verification
        # asks the same question either way, which is what makes corruption detectable.
        return path.is_file() and sha256_file(path) == record.file_hash_sha256

    def invalidate(self, record: AssetRecord) -> None:
        for path in (Path(record.local_path), self.sidecar_path(record)):
            if path.is_file():
                path.unlink()

    def size_bytes(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
