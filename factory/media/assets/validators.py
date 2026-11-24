"""Asset validation: refuse what cannot be rendered well, before it reaches the compositor.

A visual that is corrupt, unreadably small, or the wrong aspect ratio is worse than no visual: it
fails late, in the middle of a render, or ships stretched. These checks run at resolve time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

from .metadata import ALLOWED_LICENSES, AssetRecord

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MIN_SHORT_EDGE = 480          # below this a still looks soft at 1080 wide
MAX_ASPECT_DRIFT = 0.02       # 2% tolerance before we call it distortion
SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str | None = None


def validate_file(path: str | Path) -> ValidationResult:
    file_path = Path(path)
    if not file_path.is_file():
        return ValidationResult(False, f"file does not exist: {file_path.name}")
    if file_path.suffix.lower() not in ALLOWED_SUFFIXES:
        return ValidationResult(False, f"unsupported file type {file_path.suffix!r}")
    if file_path.stat().st_size == 0:
        return ValidationResult(False, "file is empty")
    try:
        with Image.open(file_path) as image:
            image.verify()
    except Exception as exc:  # corrupt payload from a download or a bad generator
        return ValidationResult(False, f"not a readable image: {type(exc).__name__}")
    return ValidationResult(True)


def validate_image(path: str | Path, *, min_short_edge: int = MIN_SHORT_EDGE) -> ValidationResult:
    checked = validate_file(path)
    if not checked.ok:
        return checked
    try:
        with Image.open(path) as image:
            if image.format not in SUPPORTED_FORMATS:
                return ValidationResult(False, f"format {image.format!r} is not supported")
            width, height = image.size
    except Exception as exc:
        return ValidationResult(False, f"cannot read dimensions: {type(exc).__name__}")
    if width <= 0 or height <= 0:
        return ValidationResult(False, "image has no area")
    if min(width, height) < min_short_edge:
        return ValidationResult(False, f"{width}x{height} is below the {min_short_edge}px short edge")
    return ValidationResult(True)


def validate_record(record: AssetRecord) -> ValidationResult:
    problem = record.problem()
    if problem:
        return ValidationResult(False, problem)
    if record.license not in ALLOWED_LICENSES:
        return ValidationResult(False, f"licence {record.license!r} is not allowed")
    checked = validate_image(record.local_path)
    if not checked.ok:
        return checked
    return ValidationResult(True)


def aspect_drift(source: tuple[int, int], target: tuple[int, int]) -> float:
    """How far a source image has to be stretched to fill a target box, as a fraction.

    Used instead of a hard-coded crop rule: 0.0 means cover-fitting is exact, and anything above
    ``MAX_ASPECT_DRIFT`` is reported so the compositor never silently distorts a photograph.
    """

    source_ratio = source[0] / source[1]
    target_ratio = target[0] / target[1]
    return abs(source_ratio - target_ratio) / target_ratio


def validate_all(records: Iterable[AssetRecord]) -> list[tuple[AssetRecord, str]]:
    """Every record that cannot be used, with its reason."""

    failures: list[tuple[AssetRecord, str]] = []
    for record in records:
        result = validate_record(record)
        if not result.ok:
            failures.append((record, result.reason or "invalid"))
    return failures
