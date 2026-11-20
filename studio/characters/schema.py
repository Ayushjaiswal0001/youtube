"""Data-driven character schema.

A character used to be a Python module full of literals: palette, head radius, blink
period, eye spacing. That makes a fourth character a code change and a code review.
This module turns the *definition* of a character into JSON:

    content/characters/chiku.json
    content/characters/gappu.json

`CharacterSchema.load("chiku")` returns a validated, immutable description that the rigs
consume. The rig still owns the drawing *technique* (an "archetype": monkey or mouse);
the schema owns everything an art director would change — colours, proportions, motion
timings, anchor, feature flags, voice.

Validation is strict on purpose: a typo in a colour or a missing proportion should fail
at load time with a readable message, not produce a silently wrong frame.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

CHARACTER_DIR = Path(__file__).resolve().parent.parent.parent / "content" / "characters"

ARCHETYPES = ("monkey", "mouse")
FEATURES = ("tail", "hair_tuft", "vest", "whiskers", "spectacles", "bowtie")

# Every proportion the rigs read. Keeping the list closed makes typos loud.
REQUIRED_PROPORTIONS = (
    "head_center_y", "head_rx", "head_ry",
    "eye_x", "eye_y", "eye_rx", "eye_ry", "pupil_rx", "pupil_ry",
    "brow_y", "brow_rx", "brow_ry",
    "muzzle_rx", "muzzle_ry", "muzzle_y",
    "nose_y", "nose_rx", "nose_ry",
    "ear_x", "ear_y", "ear_rx", "ear_ry", "ear_inner_rx", "ear_inner_ry",
    "torso_y", "torso_rx", "torso_ry",
    "arm_attach_x", "arm_attach_y", "arm_len", "arm_r",
    "leg_attach_x", "leg_attach_y", "leg_len", "leg_r",
    "shadow_rx", "shadow_ry",
    "head_joint_y", "head_draw_y", "torso_draw_offset", "arm_shift", "hand_rx", "hand_ry",
    "foot_rx", "foot_ry", "brow_ctrl_x", "brow_ctrl_y", "brow_anchor_x",
)

REQUIRED_PALETTE = (
    "fur", "muzzle", "eye_white", "pupil", "outline", "shadow",
)

# Tunable fields an expression may override, per character.
EXPRESSION_FIELDS = (
    "lid_closed", "lower_lid", "brow_y", "brow_tilt", "brow_asymmetry",
    "pupil_scale", "gaze_x", "gaze_y", "saccade_scale", "blink_scale",
)

REQUIRED_TIMING = (
    "blink_period", "blink_duration", "blink_phase",
    "breath_rate", "breath_phase", "breath_amplitude",
    "sway_rate", "sway_amplitude",
    "tail_rate", "tail_amplitude",
    "idle_arm_rate",
)


class SchemaError(ValueError):
    """Raised when a character definition is unusable."""


@dataclass(frozen=True)
class Proportions:
    """Geometry shared by an archetype, expressed in the rig's local units."""

    values: Mapping[str, float]

    def __getattr__(self, name: str) -> float:  # pragma: no cover - trivial proxy
        try:
            return self.values[name]
        except KeyError as exc:  # pragma: no cover - guarded by validation
            raise AttributeError(f"proportion '{name}' is not defined") from exc

    def scaled(self, factor: float) -> "Proportions":
        return Proportions({key: value * factor for key, value in self.values.items()})


@dataclass(frozen=True)
class Timing:
    blink_period: float
    blink_duration: float
    blink_phase: float
    breath_rate: float
    breath_phase: float
    breath_amplitude: float
    sway_rate: float
    sway_amplitude: float
    tail_rate: float
    tail_amplitude: float
    idle_arm_rate: float

    def blink(self, t: float) -> float:
        """Blink envelope: 1.0 fully closed, 0.0 open."""

        import math

        if self.blink_period <= 0 or self.blink_duration <= 0:
            return 0.0
        phase = (t + self.blink_phase) % self.blink_period
        if phase >= self.blink_duration:
            return 0.0
        return math.sin((phase / self.blink_duration) * math.pi)

    def breath(self, t: float) -> float:
        import math

        return math.sin(t * self.breath_rate + self.breath_phase) * self.breath_amplitude

    def sway(self, t: float) -> float:
        import math

        return math.sin(t * self.sway_rate) * self.sway_amplitude

    def tail(self, t: float) -> float:
        import math

        return math.sin(t * self.tail_rate) * self.tail_amplitude


@dataclass(frozen=True)
class MouthConfig:
    anchor_y: float
    size: float
    stroke_width: float
    pupil_x_range: float
    pupil_y_range: float


EYE_DEFAULTS: Mapping[str, Any] = {
    "lash_width": 3.5,
    "brow_width": 4.5,
    "closed_curve": [[-14.0, 0.0], [-6.0, 6.0], [6.0, 6.0], [14.0, 0.0]],
    "catchlight_r": 3.5,
    "catchlight_offset": [-3.0, -4.0],
    "catchlight_follow": [4.0, 3.0],
    "catchlight_alpha": 0.95,
    "lid_open_max": 1.12,
    "lower_lid_max": 0.5,
    "lid_curvature": 1.0,
    "pupil_min": 0.82,
    "pupil_max": 1.25,
    "blink_jitter": 0.55,
    "double_blink_chance": 0.12,
    "blink_close_fraction": 0.4,
    "saccade_rate": 0.55,
    "saccade_travel": 0.09,
    "micro_saccade": 0.03,
}

EYE_POSITIVE = ("lash_width", "brow_width", "catchlight_r", "lid_open_max", "pupil_min", "pupil_max", "saccade_rate")
EYE_FRACTIONS = ("catchlight_alpha", "blink_jitter", "double_blink_chance", "blink_close_fraction")


@dataclass(frozen=True)
class EyeConfig:
    """Eyelid geometry, blink rhythm and saccade behaviour.

    Every field has a default, so character files written before T32 still load.
    """

    lash_width: float
    brow_width: float
    closed_curve: Tuple[Tuple[float, float], ...]
    catchlight_r: float
    catchlight_offset: Tuple[float, float]
    catchlight_follow: Tuple[float, float]
    catchlight_alpha: float
    lid_open_max: float
    lower_lid_max: float
    lid_curvature: float
    pupil_min: float
    pupil_max: float
    blink_jitter: float
    double_blink_chance: float
    blink_close_fraction: float
    saccade_rate: float
    saccade_travel: float
    micro_saccade: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None, source: str = "<dict>") -> "EyeConfig":
        data = dict(data or {})
        unknown = [key for key in data if key not in EYE_DEFAULTS]
        if unknown:
            raise SchemaError(
                f"{source}: unknown eye option(s): {', '.join(sorted(unknown))} "
                f"(known: {', '.join(sorted(EYE_DEFAULTS))})"
            )
        merged = dict(EYE_DEFAULTS)
        merged.update(data)
        for key in EYE_POSITIVE:
            if float(merged[key]) <= 0:
                raise SchemaError(f"{source}: eyes.{key} must be positive")
        for key in EYE_FRACTIONS:
            if not 0.0 <= float(merged[key]) <= 1.0:
                raise SchemaError(f"{source}: eyes.{key} must be within 0..1")
        curve = merged["closed_curve"]
        if not isinstance(curve, Sequence) or len(curve) != 4:
            raise SchemaError(f"{source}: eyes.closed_curve must be 4 points")
        points = tuple((float(p[0]), float(p[1])) for p in curve)
        for name in ("catchlight_offset", "catchlight_follow"):
            value = merged[name]
            if not isinstance(value, Sequence) or len(value) != 2:
                raise SchemaError(f"{source}: eyes.{name} must be [x, y]")
        return cls(
            lash_width=float(merged["lash_width"]),
            brow_width=float(merged["brow_width"]),
            closed_curve=points,
            catchlight_r=float(merged["catchlight_r"]),
            catchlight_offset=(float(merged["catchlight_offset"][0]),
                               float(merged["catchlight_offset"][1])),
            catchlight_follow=(float(merged["catchlight_follow"][0]),
                               float(merged["catchlight_follow"][1])),
            catchlight_alpha=float(merged["catchlight_alpha"]),
            lid_open_max=float(merged["lid_open_max"]),
            lower_lid_max=float(merged["lower_lid_max"]),
            lid_curvature=float(merged["lid_curvature"]),
            pupil_min=float(merged["pupil_min"]),
            pupil_max=float(merged["pupil_max"]),
            blink_jitter=float(merged["blink_jitter"]),
            double_blink_chance=float(merged["double_blink_chance"]),
            blink_close_fraction=float(merged["blink_close_fraction"]),
            saccade_rate=float(merged["saccade_rate"]),
            saccade_travel=float(merged["saccade_travel"]),
            micro_saccade=float(merged["micro_saccade"]),
        )


@dataclass(frozen=True)
class CharacterSchema:
    schema_version: int
    character_id: str
    display_name: str
    archetype: str
    voice: str
    anchor: Mapping[str, float]
    palette: Mapping[str, Sequence[float]]
    proportions: Proportions
    timing: Timing
    features: List[str] = field(default_factory=list)
    mouth: MouthConfig = MouthConfig(12.0, 1.0, 3.5, 5.0, 4.0)
    eyes: EyeConfig = field(default_factory=EyeConfig.from_dict)
    expressions: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    source_path: str = ""

    # -- lookups -------------------------------------------------------------

    def color(self, name: str) -> tuple:
        try:
            value = self.palette[name]
        except KeyError as exc:
            raise SchemaError(f"{self.character_id}: palette has no colour '{name}'") from exc
        return tuple(float(component) for component in value)

    def has(self, feature: str) -> bool:
        return feature in self.features

    # -- construction --------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], source: str = "<dict>") -> "CharacterSchema":
        if not isinstance(data, Mapping):
            raise SchemaError(f"{source}: character definition must be an object")

        missing = [key for key in (
            "schema_version", "id", "display_name", "archetype", "voice",
            "anchor", "palette", "proportions", "timing",
        ) if key not in data]
        if missing:
            raise SchemaError(f"{source}: missing required field(s): {', '.join(missing)}")

        version = data["schema_version"]
        if version != 1:
            raise SchemaError(f"{source}: unsupported schema_version {version!r} (expected 1)")

        archetype = str(data["archetype"])
        if archetype not in ARCHETYPES:
            raise SchemaError(
                f"{source}: unknown archetype '{archetype}' (known: {', '.join(ARCHETYPES)})"
            )

        palette = data["palette"]
        if not isinstance(palette, Mapping):
            raise SchemaError(f"{source}: palette must be an object")
        for name in REQUIRED_PALETTE:
            if name not in palette:
                raise SchemaError(f"{source}: palette is missing '{name}'")
        for name, value in palette.items():
            if not isinstance(value, Sequence) or isinstance(value, str) or len(value) not in (3, 4):
                raise SchemaError(f"{source}: colour '{name}' must be [r, g, b] or [r, g, b, a]")
            for component in value:
                if not isinstance(component, (int, float)) or not 0.0 <= float(component) <= 1.0:
                    raise SchemaError(f"{source}: colour '{name}' component {component!r} outside 0..1")

        raw_props = data["proportions"]
        if not isinstance(raw_props, Mapping):
            raise SchemaError(f"{source}: proportions must be an object")
        missing_props = [name for name in REQUIRED_PROPORTIONS if name not in raw_props]
        if missing_props:
            raise SchemaError(f"{source}: missing proportion(s): {', '.join(missing_props)}")
        for name, value in raw_props.items():
            if not isinstance(value, (int, float)):
                raise SchemaError(f"{source}: proportion '{name}' must be a number")

        raw_timing = data["timing"]
        if not isinstance(raw_timing, Mapping):
            raise SchemaError(f"{source}: timing must be an object")
        missing_timing = [name for name in REQUIRED_TIMING if name not in raw_timing]
        if missing_timing:
            raise SchemaError(f"{source}: missing timing field(s): {', '.join(missing_timing)}")
        timing = Timing(**{name: float(raw_timing[name]) for name in REQUIRED_TIMING})
        if timing.blink_period <= 0 or timing.blink_duration <= 0:
            raise SchemaError(f"{source}: blink_period and blink_duration must be positive")

        features = list(data.get("features", []))
        for feature in features:
            if feature not in FEATURES:
                raise SchemaError(
                    f"{source}: unknown feature '{feature}' (known: {', '.join(FEATURES)})"
                )

        anchor = data["anchor"]
        for key in ("x", "y", "scale", "facing"):
            if key not in anchor:
                raise SchemaError(f"{source}: anchor is missing '{key}'")
        if float(anchor["scale"]) <= 0:
            raise SchemaError(f"{source}: anchor.scale must be positive")

        mouth = data.get("mouth", {})
        pupil_range = mouth.get("eye_pupil_range", [5.0, 4.0])
        mouth_config = MouthConfig(
            anchor_y=float(mouth.get("anchor_y", 12.0)),
            size=float(mouth.get("size", 1.0)),
            stroke_width=float(mouth.get("stroke_width", 3.5)),
            pupil_x_range=float(pupil_range[0]),
            pupil_y_range=float(pupil_range[1]),
        )

        eye_config = EyeConfig.from_dict(data.get("eyes"), source=source)

        expressions: Dict[str, Dict[str, float]] = {}
        raw_expressions = data.get("expressions") or {}
        if not isinstance(raw_expressions, Mapping):
            raise SchemaError(f"{source}: expressions must be an object")
        for name, overrides in raw_expressions.items():
            if not isinstance(overrides, Mapping):
                raise SchemaError(f"{source}: expression '{name}' must be an object")
            bad = [key for key in overrides if key not in EXPRESSION_FIELDS]
            if bad:
                raise SchemaError(
                    f"{source}: expression '{name}' has unknown field(s): {', '.join(bad)} "
                    f"(known: {', '.join(EXPRESSION_FIELDS)})"
                )
            expressions[str(name)] = {str(k): float(v) for k, v in overrides.items()}

        return cls(
            schema_version=int(version),
            character_id=str(data["id"]),
            display_name=str(data["display_name"]),
            archetype=archetype,
            voice=str(data["voice"]),
            anchor={key: float(anchor[key]) for key in ("x", "y", "scale", "facing")},
            palette={name: tuple(float(c) for c in value) for name, value in palette.items()},
            proportions=Proportions({name: float(raw_props[name]) for name in REQUIRED_PROPORTIONS}),
            timing=timing,
            features=features,
            mouth=mouth_config,
            eyes=eye_config,
            expressions=expressions,
            source_path=source,
        )

    @classmethod
    def from_file(cls, path: Path | str) -> "CharacterSchema":
        path = Path(path)
        if not path.is_file():
            raise SchemaError(f"character definition not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{path}: invalid JSON ({exc})") from exc
        return cls.from_dict(data, source=str(path))

    @classmethod
    def load(cls, character_id: str, directory: Path | str = CHARACTER_DIR) -> "CharacterSchema":
        directory = Path(directory)
        path = directory / f"{character_id}.json"
        if not path.is_file():
            available = sorted(p.stem for p in directory.glob("*.json"))
            raise SchemaError(
                f"no definition for '{character_id}' in {directory} "
                f"(available: {', '.join(available) or 'none'})"
            )
        schema = cls.from_file(path)
        if schema.character_id != character_id:
            raise SchemaError(
                f"{path}: file name says '{character_id}' but id field says "
                f"'{schema.character_id}'"
            )
        return schema


_CACHE: Dict[str, CharacterSchema] = {}


def load_schema(character_id: str) -> CharacterSchema:
    """Load a bundled character definition, cached per process."""

    if character_id not in _CACHE:
        _CACHE[character_id] = CharacterSchema.load(character_id)
    return _CACHE[character_id]
