"""The asset layer: provenance, hashing, validation, generation, resolution.

These tests are about the promises the layer makes, not about pixels looking nice: an asset without a
licence is refused, a corrupted cache entry is detected, a generated diagram is reproducible from its
spec, and the category reported is the one that was actually rendered.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from factory.media.assets.base import AssetCandidate, DisabledProvider
from factory.media.assets.cache import AssetCache, sha256_file
from factory.media.assets.generated import (
    DiagramSpec,
    choose_variant,
    entities_in,
    render_diagram,
    short_title,
    spec_for,
)
from factory.media.assets.local import LocalAssetLibrary
from factory.media.assets.metadata import AssetRecord, attribution_line
from factory.media.assets.resolver import AssetResolver
from factory.media.assets.validators import aspect_drift, validate_image, validate_record

COLORS = {"bg": "#050B16", "panel": "#10243A", "accent": "#4FD1E8", "accent2": "#FFB84D",
          "text": "#F5F9FF", "muted": "#8899AA"}


def write_png(path: Path, size: tuple[int, int] = (960, 640), colour: str = "#334455") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    return path


def make_record(path: Path, **overrides) -> AssetRecord:
    digest = sha256_file(path)
    data = dict(asset_id="local-test", source="local", license="owner-supplied",
                file_hash_sha256=digest, local_path=str(path), width=960, height=640)
    data.update(overrides)
    return AssetRecord(**data)


class FakeScene:
    def __init__(self, concept: str, narration: str, *, duration_ms: int = 4000,
                 on_screen: str = "", category: str = "diagram") -> None:
        self.scene_id = "s01"
        self.main_concept = concept
        self.narration_text = narration
        self.objective = "show the mechanism"
        self.duration_ms = duration_ms
        self.search_query = concept
        self.on_screen_text = on_screen
        self.visual_category = category
        self.coverage_category = None
        self.asset_id = None
        self.asset_source = None
        self.license = None
        self.attribution_text = None


class TestProvenance:
    def test_an_unknown_licence_is_refused(self) -> None:
        record = AssetRecord(asset_id="x", source="web", license="all-rights-reserved-ish",
                             file_hash_sha256="a" * 64, local_path="x.png", width=10, height=10,
                             source_url="https://example.test/x.png")
        assert "allow-list" in (record.problem() or "")

    def test_attribution_is_required_where_the_licence_demands_it(self) -> None:
        record = AssetRecord(asset_id="x", source="web", license="cc-by",
                             file_hash_sha256="a" * 64, local_path="x.png", width=10, height=10,
                             source_url="https://example.test/x.png", creator="Someone")
        assert "requires attribution" in (record.problem() or "")
        record.attribution_text = "Someone - CC BY"
        assert record.problem() is None

    def test_a_generated_asset_must_carry_its_spec(self) -> None:
        record = AssetRecord(asset_id="gen", source="generated", license="generated-local",
                             file_hash_sha256="a" * 64, local_path="x.png", width=10, height=10,
                             generated=True)
        assert "generation spec" in (record.problem() or "")
        record.generation_spec = '{"v":"pipeline"}'
        assert record.problem() is None

    def test_an_external_asset_needs_a_creator_or_a_url(self) -> None:
        record = AssetRecord(asset_id="x", source="web", license="cc0", file_hash_sha256="a" * 64,
                             local_path="x.png", width=10, height=10)
        assert "source URL or creator" in (record.problem() or "")

    def test_attribution_line_states_the_licence(self) -> None:
        record = AssetRecord(asset_id="x", source="web", license="cc-by-sa",
                             file_hash_sha256="a" * 64, local_path="x.png", width=10, height=10,
                             source_url="https://example.test/x.png", creator="Someone",
                             attribution_text="Photo: Someone")
        line = attribution_line(record)
        assert line and "Someone" in line and "example.test" in line


class TestCache:
    def test_store_then_lookup_round_trips_the_record(self, tmp_path: Path) -> None:
        source = write_png(tmp_path / "src.png")
        cache = AssetCache(tmp_path / "cache")
        record = make_record(source, source_url="https://example.test/a.png", creator="Owner")
        stored = cache.store("nexus-node", "photo", source, record)
        assert Path(stored.local_path).is_file()
        found = cache.lookup("nexus-node", "photo", record.file_hash_sha256)
        assert found is not None
        assert found.asset_id == record.asset_id
        assert found.creator == "Owner"
        assert cache.verify(found)

    def test_content_addressing_stores_identical_bytes_once(self, tmp_path: Path) -> None:
        first = write_png(tmp_path / "a.png")
        second = write_png(tmp_path / "b.png")
        assert sha256_file(first) == sha256_file(second)
        cache = AssetCache(tmp_path / "cache")
        cache.store("nexus-node", "photo", first, make_record(first))
        cache.store("nexus-node", "photo", second, make_record(second, asset_id="local-other"))
        images = [p for p in (tmp_path / "cache" / "nexus-node" / "photo").iterdir()
                  if p.suffix == ".png"]
        assert len(images) == 1

    def test_corruption_is_detected_rather_than_trusted(self, tmp_path: Path) -> None:
        source = write_png(tmp_path / "src.png")
        cache = AssetCache(tmp_path / "cache")
        stored = cache.store("nexus-node", "photo", source, make_record(source))
        Path(stored.local_path).write_bytes(b"not the same bytes")
        assert cache.verify(stored) is False

    def test_invalidate_removes_the_file_and_its_sidecar(self, tmp_path: Path) -> None:
        source = write_png(tmp_path / "src.png")
        cache = AssetCache(tmp_path / "cache")
        stored = cache.store("nexus-node", "photo", source, make_record(source))
        sidecar = cache.sidecar_path(stored)
        assert sidecar.is_file()
        cache.invalidate(stored)
        assert not Path(stored.local_path).exists() and not sidecar.exists()


class TestValidation:
    def test_missing_file_is_reported(self, tmp_path: Path) -> None:
        assert not validate_image(tmp_path / "nope.png").ok

    def test_a_tiny_image_is_below_the_floor(self, tmp_path: Path) -> None:
        path = write_png(tmp_path / "tiny.png", size=(120, 80))
        result = validate_image(path)
        assert not result.ok and "short edge" in (result.reason or "")

    def test_a_non_image_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "fake.png"
        path.write_bytes(b"GIF89a nonsense")
        assert not validate_image(path).ok

    def test_an_unsupported_suffix_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        assert not validate_image(path).ok

    def test_aspect_drift_measures_how_far_a_crop_would_stretch(self) -> None:
        assert aspect_drift((1920, 1080), (1920, 1080)) == 0.0
        assert aspect_drift((1080, 1080), (1920, 1080)) == pytest.approx(0.4375)


class TestGenerated:
    def test_the_same_spec_draws_the_same_bytes(self) -> None:
        spec = spec_for(concept="Pretrain on Video",
                        narration="Video pretraining lets a model watch footage.",
                        objective="", colors=COLORS)
        first = render_diagram(spec).tobytes()
        second = render_diagram(spec).tobytes()
        assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()

    def test_different_sentences_get_different_assets(self) -> None:
        first = spec_for(concept="Pretrain on Video", narration="A model watches footage.",
                         objective="", colors=COLORS)
        second = spec_for(concept="The Grid Queue", narration="Interconnection stretches for years.",
                          objective="", colors=COLORS)
        assert first.asset_id != second.asset_id

    def test_entities_come_from_the_sentence(self) -> None:
        # "grasp" is a synonym of the action entity, so it is drawn - the order is narrative order.
        assert entities_in("A robot arm learns a grasp from video.") == ["robot", "action", "video"]
        assert entities_in("Nothing drawable is named here at all.") == []

    def test_a_gap_sentence_gets_the_gap_composition(self) -> None:
        entities = entities_in("The gap is action: a video shows what happened, not the forces.")
        assert choose_variant(entities, "The gap is action: not the exact forces") == "gap"

    def test_a_call_to_action_gets_the_cta_composition(self) -> None:
        assert choose_variant(["model"], "Follow for more on AI in the physical world") == "cta"

    def test_titles_are_cut_on_a_word_boundary(self) -> None:
        title = short_title("A ROBOT ARM NEEDS THOUSANDS OF EXAMPLES TO LEARN")
        assert len(title) <= 30
        assert not title.endswith(("EXA", "EXAMP"))
        assert title.split()[-1].lower() not in {"of", "the", "for", "to"}

    def test_a_repeated_composition_steps_down_the_ladder(self) -> None:
        spec = spec_for(concept="Video to model", narration="Video pretraining lets a model watch.",
                        objective="", colors=COLORS, avoid=("pipeline",))
        assert spec.variant != "pipeline"

    def test_the_plate_is_drawn_at_the_layout_size(self) -> None:
        spec = spec_for(concept="Video", narration="A model watches video.", objective="",
                        colors=COLORS)
        assert render_diagram(spec).size == (912, 600)


class TestLocalLibrary:
    def test_sidecar_keywords_make_an_entry_findable(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library" / "nexus-node"
        image = write_png(library_root / "robot-arm.png")
        (library_root / "robot-arm.json").write_text(json.dumps({
            "asset_id": "owner-robot-arm", "license": "owner-supplied",
            "creator": "Channel owner", "keywords": ["robot", "arm", "gripper"],
        }), encoding="utf-8")
        library = LocalAssetLibrary(tmp_path / "library")
        hits = library.search("nexus-node", "robot arm gripper")
        assert hits and hits[0].asset_id == "owner-robot-arm"
        assert hits[0].extra["record"].file_hash_sha256 == sha256_file(image)

    def test_another_channels_library_is_not_offered(self, tmp_path: Path) -> None:
        other = tmp_path / "library" / "academic-biohacker"
        write_png(other / "sleep-study.png")
        library = LocalAssetLibrary(tmp_path / "library")
        assert library.search("nexus-node", "sleep study") == []

    def test_a_query_without_content_words_matches_nothing(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library" / "nexus-node"
        write_png(library_root / "arm.png")
        library = LocalAssetLibrary(tmp_path / "library")
        assert library.search("nexus-node", "a b c") == []


class FakeProvider:
    """A provider that is switched on, to prove the wiring exists without enabling one for real."""

    provider_id = "fake"

    def __init__(self, candidate: AssetCandidate, source: Path | None) -> None:
        self.candidate = candidate
        self.source = source

    def enabled(self) -> bool:
        return True

    def search(self, query: str, *, kind: str = "image", limit: int = 3) -> list[AssetCandidate]:
        return [self.candidate]

    def fetch(self, candidate: AssetCandidate, destination: str) -> str:
        destination_path = Path(destination) / "fetched.png"
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(self.source.read_bytes() if self.source else b"")
        return str(destination_path)


class TestResolver:
    def test_without_a_library_or_provider_a_diagram_is_generated(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"))
        resolution = resolver.resolve(FakeScene("Pretrain on Video", "A model watches video."),
                                      channel="nexus-node", colors=COLORS)
        assert resolution.kind == "generated"
        assert resolution.category == "diagram"
        assert resolution.image() is not None
        assert any("not enabled" in attempt for attempt in resolution.attempts)

    def test_a_second_resolve_hits_the_cache(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"))
        scene = FakeScene("Pretrain on Video", "A model watches video.")
        resolver.resolve(scene, channel="nexus-node", colors=COLORS)
        second = resolver.resolve(scene, channel="nexus-node", colors=COLORS)
        assert any("cache hit" in attempt for attempt in second.attempts)

    def test_a_library_photo_wins_and_is_reported_as_a_photo(self, tmp_path: Path) -> None:
        library_root = tmp_path / "library" / "nexus-node"
        write_png(library_root / "robot-arm.png")
        (library_root / "robot-arm.json").write_text(json.dumps({
            "asset_id": "owner-robot-arm", "license": "owner-supplied",
            "creator": "Channel owner", "keywords": ["robot", "arm"],
        }), encoding="utf-8")
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"))
        resolution = resolver.resolve(FakeScene("Robot arm", "A robot arm picks up a part.",
                                                category="photo"),
                                      channel="nexus-node", colors=COLORS)
        assert resolution.kind == "library" and resolution.category == "photo"
        assert resolution.record is not None
        assert resolution.record.license == "owner-supplied"

    def test_a_provider_that_returns_unlicensed_media_falls_through(self, tmp_path: Path) -> None:
        source = write_png(tmp_path / "fetched.png")
        candidate = AssetCandidate(asset_id="web-1", source="fake", license="unknown",
                                   width=960, height=640, source_url="https://example.test/1.png")
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"),
                                 provider=FakeProvider(candidate, source))
        resolution = resolver.resolve(FakeScene("Video", "A model watches video."),
                                      channel="nexus-node", colors=COLORS)
        assert resolution.kind == "generated"
        assert any("rejected" in attempt for attempt in resolution.attempts)

    def test_a_valid_provider_candidate_is_used_and_attributed(self, tmp_path: Path) -> None:
        source = write_png(tmp_path / "fetched.png")
        candidate = AssetCandidate(asset_id="web-2", source="fake", license="cc-by",
                                   width=960, height=640, source_url="https://example.test/2.png",
                                   creator="Photographer", attribution_text="Photo: Photographer")
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"),
                                 provider=FakeProvider(candidate, source))
        resolution = resolver.resolve(FakeScene("Video", "A model watches video."),
                                      channel="nexus-node", colors=COLORS)
        assert resolution.kind == "provider" and resolution.category == "photo"
        assert attribution_line(resolution.record) is not None

    def test_the_default_provider_is_disabled(self) -> None:
        assert DisabledProvider().enabled() is False
        assert DisabledProvider().search("anything") == []

    def test_the_resolution_records_the_plate_title(self, tmp_path: Path) -> None:
        resolver = AssetResolver(cache_root=tmp_path / "cache",
                                 library=LocalAssetLibrary(tmp_path / "library"))
        resolution = resolver.resolve(
            FakeScene("Pretrain on Video", "A model watches video.", on_screen="Pretrain on Video"),
            channel="nexus-node", colors=COLORS)
        payload = resolution.to_dict()
        assert payload["spec_title"]
        assert len(payload["spec_title"]) <= 30
        assert payload["record"]["problem"] is None

    def test_records_missing_a_file_fail_validation(self, tmp_path: Path) -> None:
        record = AssetRecord(asset_id="x", source="local", license="owner-supplied",
                             file_hash_sha256="a" * 64, local_path=str(tmp_path / "gone.png"),
                             width=960, height=640)
        assert not validate_record(record).ok
