"""P0-4: paths are anchored to the repository and can be redirected for tests and CI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.config import BUILD_ROOT, REPO_ROOT
from factory.media.assets import paths
from factory.media.assets.resolver import AssetResolver
from factory.qa import creative


class TestDefaults:
    def test_the_asset_cache_is_under_the_repository(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FACTORY_ASSET_CACHE", raising=False)
        root = paths.asset_cache_root()
        assert root.is_absolute()
        assert root == REPO_ROOT / "x100_asset_cache"

    def test_the_cache_does_not_move_with_the_working_directory(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("FACTORY_ASSET_CACHE", raising=False)
        before = paths.asset_cache_root()
        monkeypatch.chdir(tmp_path)
        assert paths.asset_cache_root() == before

    def test_the_build_root_honours_the_factory_variable(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(paths, "BUILD_ROOT", tmp_path / "elsewhere", raising=False)
        assert paths.build_root() == tmp_path / "elsewhere"
        # The real default is unchanged when nothing overrides it.
        assert Path(BUILD_ROOT).name in {"build", "elsewhere"}

    def test_the_thresholds_file_is_found_from_any_directory(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        resolved = paths.thresholds_path()
        assert resolved.is_file(), resolved
        assert resolved == REPO_ROOT / "content" / "creative_qc.json"


class TestOverrides:
    def test_the_environment_override_wins(self, monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path) -> None:
        monkeypatch.setenv("FACTORY_ASSET_CACHE", str(tmp_path / "cache"))
        assert paths.asset_cache_root() == tmp_path / "cache"

    def test_the_resolver_uses_the_override(self, monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
        monkeypatch.setenv("FACTORY_ASSET_CACHE", str(tmp_path / "resolver-cache"))
        monkeypatch.chdir(tmp_path)
        resolver = AssetResolver()
        assert resolver.cache.root == tmp_path / "resolver-cache"

    def test_an_explicit_cache_root_still_wins(self, monkeypatch: pytest.MonkeyPatch,
                                               tmp_path: Path) -> None:
        monkeypatch.setenv("FACTORY_ASSET_CACHE", str(tmp_path / "env-cache"))
        resolver = AssetResolver(cache_root=tmp_path / "explicit")
        assert resolver.cache.root == tmp_path / "explicit"

    def test_creative_thresholds_are_read_from_the_repository(
            self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        thresholds = creative.load_thresholds()
        assert thresholds["min_distinct_pixel_ratio"] == 0.5

    def test_a_threshold_file_elsewhere_is_still_honoured(self, tmp_path: Path) -> None:
        override = tmp_path / "creative_qc.json"
        override.write_text(json.dumps({"max_scene_ms": 4000}), encoding="utf-8")
        assert creative.load_thresholds(override)["max_scene_ms"] == 4000
