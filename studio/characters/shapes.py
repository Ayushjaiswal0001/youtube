"""Data-driven drawing shapes.

Some of a character's geometry is not an ellipse with radii: the tail is a bezier that waves,
the vest is two mirrored panels, the bowtie is two triangles plus a knot, the whiskers are
line pairs. Those lived as literals inside the rigs, so recolouring a character was data but
re-shaping one was a code change in a 350-line file.

A ``Shape`` is a small, validated description of one stroke or fill:

    kind            "stroke" (path + outline pass), "filled" (path + outline pass),
                    "ellipse", "dots" (one ellipse per point), "segments" (line pairs)
    commands        [["M", x, y], ["C", x1, y1, x2, y2, x, y], ["L", x, y], ["Z"]]
    origin          translate applied before drawing
    wave            per-point x multipliers, applied as x += wave[i] * wave_value,
                    which is how the tail swings with ``tail_wave``
    mirror          draw a second copy with every x negated (vest panels)

Colours are palette keys or explicit [r, g, b, a] values. The interpreter draws with the same
cairo calls the rigs used before, so moving a shape into JSON does not move a pixel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple

import cairo

from studio.characters.rig_base import draw_ellipse

SHAPE_KINDS = ("stroke", "filled", "ellipse", "dots", "segments")
_ARITY = {"M": 2, "L": 2, "C": 6, "Q": 4, "Z": 0}


class ShapeError(ValueError):
    """Raised when a shape definition cannot be drawn."""


@dataclass(frozen=True)
class Shape:
    kind: str
    commands: Tuple[Tuple[Any, ...], ...] = ()
    origin: Tuple[float, float] = (0.0, 0.0)
    width: float = 3.0
    outline_width: float = 0.0
    fill: Any = None
    outline: Any = None
    mirror: bool = False
    wave: Tuple[float, ...] = ()
    center: Tuple[float, float] = (0.0, 0.0)
    rx: float = 0.0
    ry: float = 0.0
    points: Tuple[Tuple[float, float], ...] = ()
    r: float = 0.0
    cap_round: bool = True

    # -- construction -------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], name: str = "<shape>") -> "Shape":
        if not isinstance(data, Mapping):
            raise ShapeError(f"{name}: shape must be an object")
        kind = str(data.get("kind", ""))
        if kind not in SHAPE_KINDS:
            raise ShapeError(
                f"{name}: unknown shape kind '{kind}' (known: {', '.join(SHAPE_KINDS)})"
            )
        commands = _parse_commands(data.get("commands"), name)
        points_needed = _point_count(commands)
        wave_raw = data.get("wave") or ()
        if wave_raw and len(wave_raw) != points_needed:
            raise ShapeError(
                f"{name}: wave has {len(wave_raw)} entries but the path has "
                f"{points_needed} points"
            )
        return cls(
            kind=kind,
            commands=commands,
            origin=_pair(data.get("origin", (0.0, 0.0)), f"{name}.origin"),
            width=float(data.get("width", 3.0)),
            outline_width=float(data.get("outline_width", 0.0)),
            fill=data.get("fill"),
            outline=data.get("outline"),
            mirror=bool(data.get("mirror", False)),
            wave=tuple(float(value) for value in wave_raw),
            center=_pair(data.get("center", (0.0, 0.0)), f"{name}.center"),
            rx=float(data.get("rx", 0.0)),
            ry=float(data.get("ry", 0.0)),
            points=tuple(_pair(point, f"{name}.points") for point in data.get("points", ())),
            r=float(data.get("r", 0.0)),
            cap_round=bool(data.get("cap_round", True)),
        )


def _pair(value: Any, label: str) -> Tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, str) or len(value) != 2:
        raise ShapeError(f"{label} must be [x, y]")
    try:
        return (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise ShapeError(f"{label} must be two numbers") from exc


def _parse_commands(raw: Any, name: str) -> Tuple[Tuple[Any, ...], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ShapeError(f"{name}: commands must be a list")
    parsed = []
    for index, command in enumerate(raw):
        if not isinstance(command, Sequence) or isinstance(command, str) or not command:
            raise ShapeError(f"{name}: command {index} must be a list starting with a letter")
        letter = str(command[0]).upper()
        if letter not in _ARITY:
            raise ShapeError(f"{name}: unknown path command '{command[0]}'")
        values = command[1:]
        if len(values) != _ARITY[letter]:
            raise ShapeError(
                f"{name}: '{letter}' takes {_ARITY[letter]} numbers, got {len(values)}"
            )
        try:
            parsed.append((letter,) + tuple(float(value) for value in values))
        except (TypeError, ValueError) as exc:
            raise ShapeError(f"{name}: command {index} has a non-numeric value") from exc
    return tuple(parsed)


def _point_count(commands: Sequence[Sequence[Any]]) -> int:
    return sum(len(command[1:]) // 2 for command in commands)


# -- drawing ------------------------------------------------------------------


def resolve_color(value: Any, palette: Mapping[str, Sequence[float]]) -> Tuple[float, ...] | None:
    """Palette key or explicit rgba list."""

    if value is None:
        return None
    if isinstance(value, str):
        try:
            entry = palette[value]
        except KeyError as exc:
            raise ShapeError(f"shape colour '{value}' is not in the palette") from exc
        return tuple(float(component) for component in entry)
    if isinstance(value, Sequence):
        return tuple(float(component) for component in value)
    raise ShapeError(f"shape colour {value!r} is neither a palette key nor rgba")


def _build_path(cr: cairo.Context, shape: Shape, wave_value: float,
                mirror: bool) -> None:
    sign = -1.0 if mirror else 1.0
    point_index = 0
    for command in shape.commands:
        letter = command[0]
        values = command[1:]
        if letter == "Z":
            cr.close_path()
            continue
        numbers = []
        for offset in range(0, len(values), 2):
            x = values[offset] * sign
            y = values[offset + 1]
            if shape.wave:
                x += shape.wave[point_index] * wave_value
            point_index += 1
            numbers.extend((x, y))
        if letter == "M":
            cr.move_to(*numbers)
        elif letter == "L":
            cr.line_to(*numbers)
        elif letter == "C":
            cr.curve_to(*numbers)
        elif letter == "Q":
            cr.curve_to(numbers[0], numbers[1], numbers[2], numbers[3])


def draw_shape(cr: cairo.Context, shape: Shape, palette: Mapping[str, Sequence[float]],
               *, wave: float = 0.0) -> None:
    """Draw one shape. Mirrored shapes are drawn twice, in declaration order."""

    passes = (False, True) if shape.mirror else (False,)
    for mirror in passes:
        _draw_once(cr, shape, palette, wave, mirror)


def _draw_once(cr: cairo.Context, shape: Shape, palette: Mapping[str, Sequence[float]],
               wave: float, mirror: bool) -> None:
    fill_color = resolve_color(shape.fill, palette)
    outline_color = resolve_color(shape.outline, palette)
    cr.save()
    sign = -1.0 if mirror else 1.0
    cr.translate(shape.origin[0] * sign, shape.origin[1])
    if shape.cap_round:
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)

    if shape.kind == "ellipse":
        draw_ellipse(cr, shape.center[0] * sign, shape.center[1], shape.rx, shape.ry,
                     fill_color=fill_color, stroke_color=outline_color,
                     stroke_width=shape.width if outline_color else 3.0)
    elif shape.kind == "dots":
        for point in shape.points:
            draw_ellipse(cr, point[0] * sign, point[1], shape.r, shape.r, fill_color=fill_color)
    elif shape.kind == "segments":
        cr.set_source_rgba(*fill_color) if fill_color else None
        cr.set_line_width(shape.width)
        for start, end in zip(shape.points[0::2], shape.points[1::2]):
            cr.move_to(start[0] * sign, start[1])
            cr.line_to(end[0] * sign, end[1])
            cr.stroke()
    else:
        _build_path(cr, shape, wave, mirror)
        if fill_color is not None:
            cr.set_source_rgba(*fill_color)
            if shape.kind == "stroke":
                cr.set_line_width(shape.width)
                cr.stroke_preserve()
            else:
                cr.fill_preserve()
        if outline_color is not None:
            cr.set_source_rgba(*outline_color)
            cr.set_line_width(shape.outline_width or shape.width)
            cr.stroke()
        elif shape.kind == "stroke":
            cr.stroke()
    cr.restore()
