"""The approved local asset library.

Drop licensed images into ``assets/library/<channel>/`` and they become available to the resolver,
indexed by filename and by any keywords in a sidecar ``.json``. Nothing is downloaded, so this is the
only route by which a real photograph or a supplied illustration can enter a render in v1.0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ...config import REPO_ROOT
from .base import AssetCandidate
from .cache import sha256_file
from .metadata import ALLOWED_LICENSES, AssetRecord, attribution_line
from .validators import validate_image

# Anchored to the repository, not the working directory: a library that moves with `cd` is not a
# library. FACTORY_ASSET_LIBRARY overrides it for tests.
LIBRARY_ROOT = Path(os.environ.get("FACTORY_ASSET_LIBRARY") or (REPO_ROOT / "assets" / "library"))
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class LibraryEntry:
    path: Path
    record: AssetRecord
    keywords: frozenset[str]


class LocalAssetLibrary:
    """Index of everything in the library, keyed for query matching."""

    def __init__(self, root: str | Path | None = None) -> None:
        configured = os.environ.get("FACTORY_ASSET_LIBRARY")
        self.root = Path(root) if root else Path(configured or LIBRARY_ROOT)
        self._entries: list[LibraryEntry] | None = None
        # Why a file present on disk was refused. Silence here makes an unusable library look
        # identical to an empty one.
        self.rejected: list[str] = []

    def root_for(self, channel: str) -> Path:
        return self.root / channel

    def entries(self, channel: str) -> list[LibraryEntry]:
        if self._entries is None:
            self._entries = self._scan()
        return [entry for entry in self._entries if entry.record.scene_ids == [channel]] or \
               [entry for entry in self._entries if channel in entry.record.scene_ids]

    def _scan(self) -> list[LibraryEntry]:
        entries: list[LibraryEntry] = []
        if not self.root.is_dir():
            return entries
        for channel_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            for path in sorted(channel_dir.iterdir()):
                if path.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                if not self._confined(path, channel_dir):
                    self.rejected.append(f"{path.name}: outside the library root")
                    continue
                record = self._record_for(path, channel_dir.name)
                if record is None:
                    continue
                words = set(path.stem.lower().replace("-", " ").replace("_", " ").split())
                sidecar = path.with_suffix(".json")
                if sidecar.is_file():
                    try:
                        data = json.loads(sidecar.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        data = {}
                    words |= {str(word).lower() for word in data.get("keywords", [])}
                entries.append(LibraryEntry(path=path, record=record, keywords=frozenset(words)))
        return entries

    def _confined(self, path: Path, channel_dir: Path) -> bool:
        """A library file must live inside its channel directory."""

        try:
            path.resolve().relative_to(channel_dir.resolve())
        except ValueError:
            return False
        return True

    def _record_for(self, path: Path, channel: str) -> AssetRecord | None:
        sidecar = path.with_suffix(".json")
        data: dict = {}
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        license_id = str(data.get("license") or "owner-supplied")
        if license_id not in ALLOWED_LICENSES:
            self.rejected.append(f"{path.name}: licence {license_id!r} is not on the allow-list")
            return None
        checked = validate_image(path)
        if not checked.ok:
            self.rejected.append(f"{path.name}: {checked.reason}")
            return None
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            return None
        record = AssetRecord(
            asset_id=data.get("asset_id") or f"local-{path.stem}",
            source="local",
            license=license_id,
            file_hash_sha256=sha256_file(path),
            local_path=str(path),
            width=width,
            height=height,
            scene_ids=[channel],
            source_url=data.get("source_url"),
            creator=data.get("creator"),
            attribution_text=data.get("attribution_text"),
            duration_s=data.get("duration_s"),
            generated=False,
            kind="image",
            notes=data.get("notes") or ("supplied by the channel owner"
                                         if license_id == "owner-supplied"
                                         else "imported from the local library"),
        )
        if record.needs_attribution and not record.attribution_text:
            # A licence that requires credit cannot ship without it; derive the standard line so the
            # record is usable, and let validate_record reject it if even that is impossible.
            record.attribution_text = attribution_line(record)
        return record

    def search(self, channel: str, query: str, *, limit: int = 3) -> list[AssetCandidate]:
        """Rank library entries by how many query words they match, best first."""

        wanted = {word for word in query.lower().split() if len(word) > 2}
        if not wanted:
            return []
        scored: list[tuple[int, LibraryEntry]] = []
        for entry in self.entries(channel):
            overlap = len(wanted & entry.keywords)
            if overlap:
                scored.append((overlap, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].record.asset_id))
        return [AssetCandidate(
            asset_id=entry.record.asset_id,
            source="local",
            license=entry.record.license,
            width=entry.record.width,
            height=entry.record.height,
            source_url=entry.record.source_url,
            creator=entry.record.creator,
            attribution_text=entry.record.attribution_text,
            extra={"path": str(entry.path), "record": entry.record},
        ) for _, entry in scored[:limit]]
