"""Asset metadata and provenance.

Every visual that is not drawn from the channel palette has to be traceable: where it came from,
under what licence, and - when it was synthesised locally - the exact specification that reproduces
it. Nothing here invents a licence. A record either carries one that was declared by its source, or
it is marked generated and carries a generation spec instead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

AssetKind = Literal["image", "diagram", "illustration", "footage", "software_demo"]

# Licences this project is willing to render. Anything else is rejected by the validator: an
# unknown licence is not "probably fine", it is unverified.
ALLOWED_LICENSES = {
    "generated-local": "Synthesised by this repository from its own drawing code; no third-party rights",
    "public-domain": "Public domain",
    "cc0": "Creative Commons Zero",
    "cc-by": "Creative Commons Attribution (attribution required on screen and in the description)",
    "cc-by-sa": "Creative Commons Attribution-ShareAlike (attribution required)",
    "owner-supplied": "Supplied by the channel owner with permission to use",
}

REQUIRES_ATTRIBUTION = {"cc-by", "cc-by-sa"}


@dataclass
class AssetRecord:
    asset_id: str
    source: str
    license: str
    file_hash_sha256: str
    local_path: str
    width: int
    height: int
    scene_ids: list[str] = field(default_factory=list)
    source_url: str | None = None
    creator: str | None = None
    attribution_text: str | None = None
    duration_s: float | None = None
    generated: bool = False
    generation_spec: str | None = None
    acquired_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    kind: AssetKind = "image"
    notes: str | None = None

    @property
    def needs_attribution(self) -> bool:
        return self.license in REQUIRES_ATTRIBUTION

    def problem(self) -> str | None:
        """Why this record cannot be used, or None when it can."""

        if not self.asset_id or not self.file_hash_sha256 or not self.local_path:
            return "incomplete provenance (asset_id, hash and path are required)"
        if self.license not in ALLOWED_LICENSES:
            return f"licence {self.license!r} is not on the allow-list"
        if self.width <= 0 or self.height <= 0:
            return "dimensions were never measured"
        if self.needs_attribution and not self.attribution_text:
            return f"licence {self.license!r} requires attribution text and none was recorded"
        if self.generated and not self.generation_spec:
            return "generated asset without a generation spec is not reproducible"
        if not self.generated and not (self.source_url or self.creator):
            return "external asset without a source URL or creator"
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["needs_attribution"] = self.needs_attribution
        data["problem"] = self.problem()
        return data


def attribution_line(record: AssetRecord) -> str | None:
    """The credit that goes into the video description."""

    if not record.needs_attribution and not record.attribution_text:
        return None
    text = record.attribution_text or ""
    creator = f" by {record.creator}" if record.creator else ""
    licence = ALLOWED_LICENSES.get(record.license, record.license)
    url = f" ({record.source_url})" if record.source_url else ""
    if text:
        return f"{text}{url}"
    return f"{record.asset_id}{creator} - {licence}{url}"
