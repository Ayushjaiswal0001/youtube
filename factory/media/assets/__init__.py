"""Asset layer for the visual engine: library, provenance, cache, generated diagrams, resolver."""

from .base import AssetCandidate, AssetProvider, DisabledProvider
from .cache import AssetCache, sha256_file
from .generated import DiagramSpec, choose_variant, entities_in, render_diagram, spec_for
from .local import LocalAssetLibrary
from .metadata import ALLOWED_LICENSES, AssetRecord, attribution_line
from .resolver import AssetResolver, Resolution
from .validators import aspect_drift, validate_image, validate_record

__all__ = [
    "ALLOWED_LICENSES", "AssetCache", "AssetCandidate", "AssetProvider", "AssetRecord",
    "AssetResolver", "DiagramSpec", "DisabledProvider", "LocalAssetLibrary", "Resolution",
    "aspect_drift", "attribution_line", "choose_variant", "entities_in", "render_diagram",
    "sha256_file", "spec_for", "validate_image", "validate_record",
]
