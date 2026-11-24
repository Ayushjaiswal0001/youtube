"""Resolve a planned scene to an actual visual.

Resolution order, and why:

1. **Local library** - a real photograph or supplied illustration is always the best answer, and it
   is the only path by which third-party imagery can enter a render. Nothing is downloaded.
2. **Content cache** - the same generated diagram, already drawn, addressed by its spec hash.
3. **External provider** - disabled in v1.0 (no credentials, no per-render network dependency). The
   step exists so a provider can be enabled later without changing a caller.
4. **Generated diagram** - always available, always deterministic, always about the sentence.

Whatever wins, the resolver reports the *category that was actually rendered*. A scene planned as a
photo that fell back to a diagram is reported as a diagram: relabelling is how a coverage report
starts lying.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .base import AssetProvider, DisabledProvider
from .cache import AssetCache, sha256_file
from .generated import DiagramSpec, motion_plan, render_diagram, spec_for, write_diagram
from .local import LocalAssetLibrary
from .metadata import AssetRecord
from .validators import validate_record

CACHE_ROOT = Path("x100_asset_cache")
DIAGRAM_SIZE = (940, 600)


@dataclass
class Resolution:
    """What a scene actually got."""

    scene_id: str
    category: str                 # the category actually rendered, not the one planned
    kind: str                     # "library" | "generated" | "provider" | "none"
    record: AssetRecord | None = None
    asset_id: str | None = None
    variant: str | None = None
    path: str | None = None
    spec: DiagramSpec | None = None
    motion: dict[str, Any] = field(default_factory=dict)
    visible_text: list[str] = field(default_factory=list)
    reason: str | None = None
    attempts: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.path is not None or self.spec is not None

    def image(self) -> Image.Image | None:
        """The visual. A generated spec is re-drawn from its spec rather than trusted as a file."""

        if self.spec is not None:
            return render_diagram(self.spec, size=DIAGRAM_SIZE)
        if self.path:
            return Image.open(self.path).convert("RGB")
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "category": self.category,
            "kind": self.kind,
            "asset_id": self.asset_id,
            "variant": self.variant,
            "spec_title": self.spec.title if self.spec else None,
            "path": self.path,
            "motion": self.motion,
            "visible_text": self.visible_text,
            "reason": self.reason,
            "attempts": self.attempts,
            "record": self.record.to_dict() if self.record else None,
        }


class AssetResolver:
    def __init__(self, *, cache: AssetCache | None = None, library: LocalAssetLibrary | None = None,
                 provider: AssetProvider | None = None, cache_root: str | Path | None = None) -> None:
        root = Path(cache_root) if cache_root else CACHE_ROOT
        self.cache = cache or AssetCache(root)
        self.library = library or LocalAssetLibrary()
        self.provider = provider or DisabledProvider()

    def resolve(self, scene: Any, *, channel: str, colors: dict[str, str],
                avoid: tuple[str, ...] = ()) -> Resolution:
        attempts: list[str] = []
        query = " ".join(filter(None, [getattr(scene, "search_query", "") or "",
                                       getattr(scene, "main_concept", "") or ""])).strip()

        from_library = self._from_library(channel, query, scene, colors, attempts)
        if from_library is not None:
            return from_library
        from_provider = self._from_provider(channel, query, scene, attempts)
        if from_provider is not None:
            return from_provider
        return self._generated(scene, channel, colors, attempts, avoid)

    # -- library ---------------------------------------------------------------
    def _from_library(self, channel: str, query: str, scene: Any, colors: dict[str, str],
                      attempts: list[str]) -> Resolution | None:
        del colors
        candidates = self.library.search(channel, query) if query else []
        if not candidates:
            attempts.append("library: no entry matched the scene query")
            return None
        for candidate in candidates:
            record = candidate.extra.get("record")
            if record is None:
                attempts.append(f"library: {candidate.asset_id} had no provenance record")
                continue
            checked = validate_record(record)
            if not checked.ok:
                attempts.append(f"library: {candidate.asset_id} rejected ({checked.reason})")
                continue
            stored = self.cache.store(channel, "photo", candidate.extra["path"], record)
            return Resolution(
                scene_id=getattr(scene, "scene_id", ""), category="photo", kind="library",
                record=stored, asset_id=stored.asset_id, path=stored.local_path,
                motion={"treatment": "push_in", "enter_s": 0.3, "asset_id": stored.asset_id},
                attempts=attempts,
            )
        return None

    # -- provider (disabled in v1.0) -------------------------------------------
    def _from_provider(self, channel: str, query: str, scene: Any,
                       attempts: list[str]) -> Resolution | None:
        if not self.provider.enabled():
            attempts.append(f"provider: {getattr(self.provider, 'provider_id', 'none')} is not enabled")
            return None
        for candidate in self.provider.search(query, limit=3):
            try:
                path = self.provider.fetch(candidate, str(self.cache.directory_for(channel, "photo")))
            except Exception as exc:  # a provider failure must not kill a render
                attempts.append(f"provider: fetch failed for {candidate.asset_id} ({type(exc).__name__})")
                continue
            record = AssetRecord(
                asset_id=candidate.asset_id, source=getattr(self.provider, "provider_id", "provider"),
                license=candidate.license, file_hash_sha256=sha256_file(path), local_path=path,
                width=candidate.width, height=candidate.height, source_url=candidate.source_url,
                creator=candidate.creator, attribution_text=candidate.attribution_text,
                duration_s=candidate.duration_s,
            )
            checked = validate_record(record)
            if not checked.ok:
                attempts.append(f"provider: {candidate.asset_id} rejected ({checked.reason})")
                continue
            stored = self.cache.store(channel, "photo", path, record)
            return Resolution(
                scene_id=getattr(scene, "scene_id", ""), category="photo", kind="provider",
                record=stored, asset_id=stored.asset_id, path=stored.local_path,
                motion={"treatment": "push_in", "enter_s": 0.3, "asset_id": stored.asset_id},
                attempts=attempts,
            )
        attempts.append("provider: no usable candidate")
        return None

    # -- generated -------------------------------------------------------------
    def _generated(self, scene: Any, channel: str, colors: dict[str, str],
                   attempts: list[str], avoid: tuple[str, ...] = ()) -> Resolution:
        concept = getattr(scene, "main_concept", "") or ""
        narration = getattr(scene, "narration_text", "") or ""
        objective = getattr(scene, "objective", "") or ""
        spec = spec_for(concept=concept, narration=narration, objective=objective, colors=colors,
                        on_screen=getattr(scene, "on_screen_text", None), avoid=avoid)
        duration_s = (getattr(scene, "duration_ms", 0) or 0) / 1000.0

        cached = self.cache.lookup(channel, "diagram", spec.digest)
        if cached is not None and self.cache.verify(cached):
            attempts.append("generated: cache hit for " + spec.asset_id)
            return self._generated_resolution(spec, cached.local_path, duration_s, attempts)

        destination = self.cache.path_for_hash(channel, "diagram", spec.digest, ".png")
        write_diagram(spec, destination, size=DIAGRAM_SIZE)
        record = AssetRecord(
            asset_id=spec.asset_id, source="generated", license="generated-local",
            file_hash_sha256=sha256_file(destination), local_path=str(destination),
            width=DIAGRAM_SIZE[0], height=DIAGRAM_SIZE[1], scene_ids=[channel],
            generated=True, generation_spec=spec.canonical(), kind="diagram",
            notes=f"variant={spec.variant} entities={','.join(spec.entities)}",
        )
        self.cache.write_record(channel, "diagram", record)
        attempts.append("generated: drew " + spec.variant + " as " + spec.asset_id)
        return self._generated_resolution(spec, str(destination), duration_s, attempts)

    def _generated_resolution(self, spec: DiagramSpec, path: str, duration_s: float,
                              attempts: list[str]) -> Resolution:
        return Resolution(
            scene_id="", category="diagram", kind="generated",
            record=self.cache.read_record(path), asset_id=spec.asset_id, variant=spec.variant,
            path=path, spec=spec, motion=motion_plan(spec, duration_s),
            visible_text=[spec.title, *spec.labels], attempts=attempts,
        )
