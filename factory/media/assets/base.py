"""The provider interface, deliberately unimplemented.

No external image provider is enabled in v1.0: there is no API key, and adding one would be a new
credential and a per-render network dependency. This module exists so that a provider can be added
later without touching the resolver - and so that "no provider configured" is an explicit state
rather than an exception nobody wrote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class AssetCandidate:
    """A provider's offer: what it would give us, and under what terms."""

    asset_id: str
    source: str
    license: str
    width: int
    height: int
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    duration_s: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AssetProvider(Protocol):
    """What a provider has to offer to be plugged in."""

    provider_id: str

    def enabled(self) -> bool:
        """True only when this provider is configured *and* authorised to be used."""

    def search(self, query: str, *, kind: str = "image", limit: int = 3) -> list[AssetCandidate]:
        ...

    def fetch(self, candidate: AssetCandidate, destination: str) -> str:
        ...


class DisabledProvider:
    """The default. Reports itself as unavailable instead of pretending to search."""

    provider_id = "none"
    reason = "no external asset provider is configured (v1.0 runs on local assets and generated diagrams)"

    def enabled(self) -> bool:
        return False

    def search(self, query: str, *, kind: str = "image", limit: int = 3) -> list[AssetCandidate]:
        return []

    def fetch(self, candidate: AssetCandidate, destination: str) -> str:
        raise RuntimeError(self.reason)
