"""Where the visual engine keeps its cache, its build output and its thresholds.

v1.0 resolved the asset cache as ``Path("x100_asset_cache")``, so the cache lived wherever the process
happened to be standing: a render started from another directory silently rebuilt every plate, and a
test run could leave a cache inside the repository. Every path is now resolved once, here, from the
repository root, and the asset cache can be redirected with ``FACTORY_ASSET_CACHE`` for tests and CI.
"""

from __future__ import annotations

import os
from pathlib import Path

from ...config import BUILD_ROOT, REPO_ROOT

ASSET_CACHE_ENV = "FACTORY_ASSET_CACHE"


def asset_cache_root() -> Path:
    """The content-addressed plate cache. Environment override wins; otherwise the repo root."""

    override = os.environ.get(ASSET_CACHE_ENV)
    return Path(override).expanduser() if override else REPO_ROOT / "x100_asset_cache"


def build_root() -> Path:
    """Where episodes are rendered. Honours ``FACTORY_BUILD_DIR`` exactly as the factory already did."""

    return Path(BUILD_ROOT)


def thresholds_path() -> Path:
    """The creative QC threshold file, found from the repository rather than the working directory."""

    return REPO_ROOT / "content" / "creative_qc.json"
