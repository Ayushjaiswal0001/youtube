"""P0-5: structured provenance, licence enforcement, path confinement, and no leaked handles."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from factory.config import load_channel_specs
from factory.media.assets.local import LocalAssetLibrary
from factory.media.assets.validators import validate_record
from factory.media.assets.resolver import AssetResolver, Resolution

COLORS = load_channel_specs()["nexus-node"].colors


class Scene:
    scene_id = "s01"
    narration_text = "Video pretraining lets a model watch ordinary footage first"
    main_concept = "Video pretraining"
    on_screen_text = "PRETRAIN ON VIDEO"
    visual_category = "diagram"
    duration_ms = 3000


def picture(path: Path, colour: str = "#204060") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), colour).save(path)
    return path


def sidecar(path: Path, **data) -> None:
    path.with_suffix(".json").write_text(json.dumps(data), encoding="utf-8")


class TestResolutionProvenance:
    def test_the_record_carries_structured_provenance(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache")
        resolution = resolver.resolve(Scene(), channel="nexus-node", colors=COLORS)
        data = resolution.to_dict()
        for key in ("entities", "variant", "license", "attribution", "plate_fingerprint"):
            assert key in data, key
        assert data["entities"] == list(resolution.entities)
        assert data["variant"] == resolution.variant
        assert data["license"] == "generated-local"
        assert isinstance(data["entities"], list)

    def test_a_generated_record_is_valid_provenance(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache")
        resolution = resolver.resolve(Scene(), channel="nexus-node", colors=COLORS)
        assert resolution.record is not None
        assert validate_record(resolution.record).ok


class TestLibrarySafety:
    def test_a_licence_outside_the_allow_list_is_refused(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        path = picture(library / "nexus-node" / "robot.png")
        sidecar(path, license="all-rights-reserved")
        scanned = LocalAssetLibrary(library)
        assert scanned.entries("nexus-node") == []
        assert any("allow-list" in message for message in scanned.rejected)

    def test_the_refusal_is_recorded(self, tmp_path: Path) -> None:
        library = LocalAssetLibrary(tmp_path / "library")
        path = picture(library.root / "nexus-node" / "robot.png")
        sidecar(path, license="gpl")
        assert library.entries("nexus-node") == []
        assert any("gpl" in message for message in library.rejected)

    def test_a_file_outside_the_channel_directory_is_not_indexed(self, tmp_path: Path) -> None:
        library = LocalAssetLibrary(tmp_path / "library")
        outside = picture(tmp_path / "outside" / "robot.png")
        assert library._confined(outside, library.root / "nexus-node") is False

    def test_a_cc_by_file_without_attribution_text_gets_the_standard_line(self,
                                                                        tmp_path: Path) -> None:
        library = LocalAssetLibrary(tmp_path / "library")
        path = picture(library.root / "nexus-node" / "warehouse.png")
        sidecar(path, license="cc-by", creator="A. Person", source_url="https://example.test/x")
        entries = library.entries("nexus-node")
        assert entries, library.rejected
        record = entries[0].record
        assert record.license == "cc-by"
        assert record.attribution_text and "A. Person" in record.attribution_text
        assert validate_record(record).ok

    def test_an_owner_supplied_file_needs_no_attribution(self, tmp_path: Path) -> None:
        library = LocalAssetLibrary(tmp_path / "library")
        path = picture(library.root / "nexus-node" / "mine.png")
        sidecar(path, license="owner-supplied")
        entries = library.entries("nexus-node")
        assert entries
        assert entries[0].record.attribution_text is None
        assert validate_record(entries[0].record).ok

    def test_an_invalid_image_is_rejected_with_a_reason(self, tmp_path: Path) -> None:
        library = LocalAssetLibrary(tmp_path / "library")
        path = library.root / "nexus-node" / "broken.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not a png")
        assert library.entries("nexus-node") == []
        assert library.rejected

    def test_the_library_is_anchored_to_the_repository(self) -> None:
        from factory.config import REPO_ROOT

        library = LocalAssetLibrary()
        assert library.root == REPO_ROOT / "assets" / "library"

    def test_the_environment_can_point_the_library_somewhere_else(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("FACTORY_ASSET_LIBRARY", str(tmp_path / "elsewhere"))
        assert LocalAssetLibrary().root == tmp_path / "elsewhere"


class TestHandles:
    def test_a_library_plate_leaves_no_open_handle(self, tmp_path: Path) -> None:
        """On Windows a leaked handle keeps the file locked, so deletion is the observable test."""

        library = tmp_path / "library"
        path = picture(library / "nexus-node" / "robot.png")
        sidecar(path, license="owner-supplied")
        entry = LocalAssetLibrary(library).entries("nexus-node")[0]
        resolution = Resolution(scene_id="s01", category="photo", kind="library",
                                record=entry.record, asset_id=entry.record.asset_id,
                                path=str(path))
        image = resolution.image()
        assert image is not None
        try:
            os.remove(path)
        finally:
            image.close()
        assert not path.exists()

    def test_a_generated_plate_is_redrawn_from_its_spec(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache")
        resolution = resolver.resolve(Scene(), channel="nexus-node", colors=COLORS)
        first = resolution.image()
        second = resolution.image()
        assert first is not None and second is not None
        assert first.tobytes() == second.tobytes()
