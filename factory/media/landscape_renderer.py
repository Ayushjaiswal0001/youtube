"""Native 1920x1080 (16:9) long-form motion-graphics renderer.

This is a separate composition profile, not a stretched Shorts frame. The horizontal
canvas gets its own layout grammar:

    ┌──────────────────────────────────────────────────────────────┐
    │ brand chrome                                    scene 4 / 12 │
    ├───────────────────────────────┬──────────────────────────────┤
    │ kicker / chapter label        │                              │
    │ 96px headline, fitted         │   animated diagram plate     │
    │ support copy, 44px            │   (nodes, bars, flow, grid)  │
    │ accent rule                   │                              │
    ├───────────────────────────────┴──────────────────────────────┤
    │  word-synced caption band                                   │
    │  progress rail with chapter ticks                           │
    └──────────────────────────────────────────────────────────────┘

It shares the primitives that are resolution independent (palette maths, fonts, text
wrapping, the procedural music bed, the narration mix) and implements its own scene
grammar, motif animation and pacing. Chapter cards and establishing/CTA layouts exist
only here because long-form needs them.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from ..config import FONTS_DIR, FPS, ChannelSpec
from ..content.models import Narration, Script, ScriptLine, WordTiming
from ..util import ffprobe_streams, iso_now
from .english_renderer import BRAND, _font, _mix, _rgb, _rgba, _wrap
from .music import make_bed, mix_narration

WIDTH = 1920
HEIGHT = 1080
FPS_TARGET = FPS

MARGIN = 104
# The frame pans by up to PAN_X[0] px, so text laid out at MARGIN leaves the safe area in the encoded frame -
# measured as 499 "required subjects cropped" on the first panning academic render, which is the report doing
# its job. The layout target is the margin plus the pan amplitude, and the report then measures the panned
# frame against the real margin. Same rule as the Shorts renderer and its 6 % push-in.
TEXT_MARGIN = MARGIN + 36
TEXT_COL = 900          # width of the left editorial column
PANEL_X = 1092          # left edge of the diagram plate
PANEL_TOP = 188
PANEL_BOTTOM = 812
CAPTION_TOP = 836
RAIL_Y = 1040

TITLE_FONT = FONTS_DIR / "Inter-Black.otf"
SMALL_FONT = FONTS_DIR / "Inter-ExtraBold.otf"
SERIF_FONT = FONTS_DIR / "Caladea-Bold.ttf"


@dataclass
class Profile:
    """Composition profile: everything that differs between 9:16 and 16:9."""

    width: int = WIDTH
    height: int = HEIGHT
    margin: int = MARGIN
    text_col: int = TEXT_COL
    caption_size: int = 46
    headline_sizes: tuple[int, ...] = (104, 96, 88, 80, 72, 64)


PROFILES = {
    "long": Profile(),
}


def get_profile(spec: ChannelSpec) -> Profile:
    return PROFILES.get(spec.format, Profile())


# --------------------------------------------------------------------- utilities


def _ease_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1.0 - (1.0 - value) ** 3


def _ease_in_out(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 3 * value**2 - 2 * value**3


def _chunks(line: ScriptLine, words_per_chunk: int = 4) -> list[dict[str, Any]]:
    """Group words into caption chunks with timings, falling back to even spacing."""

    words = line.words or []
    if not words:
        tokens = [token for token in re.findall(r"\S+", line.text) if token]
        if not tokens:
            return []
        span = max(0.2, line.end - line.start)
        step = span / len(tokens)
        words = [
            WordTiming(token, line.start + index * step, line.start + (index + 1) * step)
            for index, token in enumerate(tokens)
        ]
    chunks: list[dict[str, Any]] = []
    for index in range(0, len(words), words_per_chunk):
        group = words[index : index + words_per_chunk]
        chunks.append(
            {
                "start": group[0].start,
                "end": group[-1].end,
                "words": [{"text": word.text, "start": word.start, "end": word.end} for word in group],
            }
        )
    return chunks


def _active_chunk(chunks: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    for chunk in chunks:
        if chunk["start"] - 0.02 <= t <= chunk["end"] + 0.06:
            return chunk
    return None


# ----------------------------------------------------------------- canvas parts


def _base(profile: Profile, spec: ChannelSpec) -> Image.Image:
    c = spec.colors
    top, bottom = np.array(_rgb(c["bg"]), dtype=np.float32), np.array(_rgb(c["bg2"]), dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, profile.height, dtype=np.float32)[:, None, None]
    rows = top * (1 - ramp) + bottom * ramp
    array = np.repeat(rows, profile.width, axis=1).astype(np.uint8)
    base = Image.fromarray(array, mode="RGB").convert("RGBA")

    grid = Image.new("RGBA", base.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(grid)
    grid_color = _rgba(c["grid"], 90)
    for x in range(0, profile.width, 96):
        pen.line((x, 0, x, profile.height), fill=grid_color, width=1)
    for y in range(0, profile.height, 96):
        pen.line((0, y, profile.width, y), fill=grid_color, width=1)

    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gp = ImageDraw.Draw(glow)
    radius = 520
    gp.ellipse(
        (profile.width - radius + 140, -radius + 120, profile.width + radius - 140, radius + 120),
        fill=_rgba(c["accent"], 34),
    )
    gp.ellipse(
        (-radius + 60, profile.height - radius + 60, radius + 60, profile.height + radius + 60),
        fill=_rgba(c["accent2"], 26),
    )

    composed = Image.alpha_composite(base, glow)
    composed = Image.alpha_composite(composed, grid)
    vignette = Image.new("RGBA", base.size, (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    vd.rectangle((0, 0, profile.width, 96), fill=(0, 0, 0, 60))
    vd.rectangle((0, profile.height - 150, profile.width, profile.height), fill=(0, 0, 0, 80))
    return Image.alpha_composite(composed, vignette)


def _chrome(draw: ImageDraw.ImageDraw, profile: Profile, spec: ChannelSpec, brand: tuple[str, str, str], index: int, total: int) -> None:
    c = spec.colors
    name, kicker, handle = brand
    font = _font(SMALL_FONT, 26)
    draw.rectangle((0, 0, profile.width, 4), fill=_rgba(c["accent"], 220))
    draw.text((profile.margin, 42), name, font=font, fill=c["text"])
    spaced = "  ·  ".join(part for part in (kicker, handle) if part)
    draw.text((profile.margin, 74), spaced, font=_font(SMALL_FONT, 18), fill=c["muted"])
    counter = f"{index + 1:02d} / {total:02d}"
    width = draw.textlength(counter, font=font)
    draw.text((profile.width - profile.margin - width, 42), counter, font=font, fill=c["muted"])


def _motif(
    draw: ImageDraw.ImageDraw,
    profile: Profile,
    spec: ChannelSpec,
    kind: str,
    t: float,
    local: float,
) -> None:
    """Animated diagram inside the plate. Coordinates live in panel space."""

    c = spec.colors
    left, top = PANEL_X + 52, PANEL_TOP + 52
    right, bottom = profile.width - profile.margin - 52, PANEL_BOTTOM - 52
    width, height = right - left, bottom - top
    progress = _ease_in_out(local / 0.7)
    accent, accent2 = c["accent"], c["accent2"]

    if kind in {"bars", "chart"}:
        values = [0.34, 0.52, 0.44, 0.72, 0.61, 0.9]
        gap = width / (len(values) * 1.6)
        for index, value in enumerate(values):
            grow = _ease_out(min(1.0, progress * 1.3 - index * 0.08))
            bar_h = height * 0.78 * value * grow
            x = left + index * (gap + gap * 0.6) + gap * 0.3
            base_y = bottom - 40
            draw.rounded_rectangle(
                (x, base_y - bar_h, x + gap, base_y),
                radius=8,
                fill=_rgba(accent if index % 2 == 0 else accent2, 220),
            )
        draw.line((left, bottom - 40, right, bottom - 40), fill=_rgba(c["muted"], 200), width=2)

    elif kind in {"flow", "network", "nodes", "spark"}:
        nodes = [
            (0.14, 0.62),
            (0.34, 0.30),
            (0.46, 0.70),
            (0.62, 0.42),
            (0.82, 0.26),
            (0.88, 0.66),
        ]
        points = [(left + width * x, top + height * y) for x, y in nodes]
        for index in range(len(points) - 1):
            appear = _ease_out(min(1.0, progress * 1.6 - index * 0.12))
            if appear <= 0:
                continue
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            draw.line((x1, y1, x1 + (x2 - x1) * appear, y1 + (y2 - y1) * appear), fill=_rgba(c["muted"], 170), width=3)
        for index, (x, y) in enumerate(points):
            appear = _ease_out(min(1.0, progress * 1.6 - index * 0.1))
            radius = 20 + 6 * math.sin(t * 2.2 + index)
            if appear <= 0:
                continue
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=_rgba(accent if index % 2 == 0 else accent2, int(255 * appear)))

    elif kind in {"grid", "chip"}:
        step = 74
        for row in range(9):
            for col in range(12):
                appear = _ease_out(min(1.0, progress * 2.4 - (row + col) * 0.03))
                if appear <= 0:
                    continue
                x = left + col * step
                y = top + row * step
                size = 26
                pulse = 0.4 + 0.6 * abs(math.sin(t * 1.4 + (row * 12 + col) * 0.25))
                draw.rounded_rectangle(
                    (x, y, x + size, y + size),
                    radius=6,
                    fill=_rgba(accent if (row + col) % 3 else accent2, int(210 * appear * pulse)),
                )

    elif kind in {"shield", "lock"}:
        cx, cy = left + width / 2, top + height / 2
        radius = min(width, height) * 0.32 * _ease_out(progress)
        for ring in range(3):
            r = radius * (1 - ring * 0.22)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=_rgba(accent if ring % 2 == 0 else accent2, 220 - ring * 50), width=4)
        draw.line((cx, cy - radius * 0.7, cx, cy + radius * 0.7), fill=_rgba(c["text"], 200), width=3)

    elif kind in {"scale", "gap"}:
        cx, cy = left + width / 2, top + height / 2
        span = width * 0.36 * _ease_out(progress)
        draw.line((cx - span, cy, cx + span, cy), fill=_rgba(c["muted"], 220), width=4)
        draw.line((cx - span, cy - 46, cx - span, cy + 46), fill=_rgba(accent, 235), width=6)
        draw.line((cx + span, cy - 46, cx + span, cy + 46), fill=_rgba(accent2, 235), width=6)
        x = cx - span + (2 * span) * _ease_in_out(local / 1.6 % 1.0)
        draw.ellipse((x - 14, cy - 14, x + 14, cy + 14), fill=_rgba(c["text"], 235))

    else:  # clock / default: radial progress
        cx, cy = left + width / 2, top + height / 2
        radius = min(width, height) * 0.3
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=_rgba(c["grid"], 255), width=6)
        angle = 2 * math.pi * _ease_in_out(progress)
        draw.arc(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            start=-90,
            end=-90 + math.degrees(angle),
            fill=_rgba(accent, 240),
            width=10,
        )


def _headline(draw: ImageDraw.ImageDraw, profile: Profile, spec: ChannelSpec, text: str, max_width: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in profile.headline_sizes:
        font = _font(TITLE_FONT, size)
        lines = _wrap(draw, text.upper(), font, max_width)
        if len(lines) <= 3:
            return font, lines
    font = _font(TITLE_FONT, 56)
    return font, _wrap(draw, text.upper(), font, max_width)[:3]


def _body_block(
    draw: ImageDraw.ImageDraw,
    profile: Profile,
    spec: ChannelSpec,
    text: str,
    max_width: int,
    top: int,
    bottom: int,
    alpha: float,
    margin: float | None = None,
) -> tuple[float, float, float, float] | None:
    """Draw support copy that always fits above the caption band, and return the rectangle it painted.

    The return value is what `framing.json` measures. A report built from a brightness threshold was wrong on
    one palette in three; the draw call is the ground truth for what the composition actually contains.
    """

    c = spec.colors
    available = max(60, bottom - top)
    for size in (40, 36, 32, 28, 24):
        font = _font(SERIF_FONT, size)
        line_height = int(size * 1.34)
        max_lines = max(1, available // line_height)
        lines = _wrap(draw, text, font, max_width)
        if len(lines) <= max_lines:
            break
    margin = profile.margin if margin is None else margin
    fill = _rgba(c["text"], int(216 * alpha)) if spec.palette == "nexus" else _rgba(c["muted"], int(255 * alpha))
    y = top
    right = float(margin)
    painted = 0
    for line in lines[:max_lines]:
        draw.text((margin, y), line, font=font, fill=fill)
        right = max(right, margin + draw.textlength(line, font=font))
        y += line_height
        painted += 1
    if not painted:
        return None
    return (float(margin), float(top), float(right), float(y - line_height + font.size * 1.05))


def _caption_band(
    draw: ImageDraw.ImageDraw,
    profile: Profile,
    spec: ChannelSpec,
    chunk: dict[str, Any] | None,
    t: float,
) -> tuple[float, float, float, float] | None:
    if not chunk:
        return None
    c = spec.colors
    font = _font(SMALL_FONT, profile.caption_size)
    words = chunk["words"]
    gap = draw.textlength(" ", font=font)
    widths = [draw.textlength(word["text"], font=font) for word in words]
    total = sum(widths) + gap * (len(words) - 1)
    x = (profile.width - total) / 2
    y = CAPTION_TOP
    padding = 26
    draw.rounded_rectangle(
        (x - padding, y - 16, x + total + padding, y + profile.caption_size + 22),
        radius=18,
        fill=(0, 0, 0, 150),
    )
    for word, width in zip(words, widths):
        active = word["start"] - 0.02 <= t <= word["end"] + 0.02
        draw.text((x, y), word["text"], font=font, fill=c["accent"] if active else c["text"])
        x += width + gap
    return (x - total - padding, float(y - 16), x + padding - gap, float(y + profile.caption_size + 22))


def _rail(draw: ImageDraw.ImageDraw, profile: Profile, spec: ChannelSpec, progress: float, chapter_marks: Iterable[float]) -> None:
    c = spec.colors
    left, right = profile.margin, profile.width - profile.margin
    draw.rounded_rectangle((left, RAIL_Y, right, RAIL_Y + 6), radius=3, fill=_mix(c["bg"], c["muted"], 0.25))
    filled = left + (right - left) * max(0.0, min(1.0, progress))
    draw.rounded_rectangle((left, RAIL_Y, max(left + 6, filled), RAIL_Y + 6), radius=3, fill=c["accent"])
    for mark in chapter_marks:
        x = left + (right - left) * mark
        draw.rectangle((x - 1, RAIL_Y - 8, x + 1, RAIL_Y + 14), fill=_rgba(c["muted"], 200))


def _chapter_card(img: Image.Image, spec: ChannelSpec, number: int, title: str, alpha: float) -> Image.Image:
    c = spec.colors
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle((0, 0, img.width, img.height), fill=_rgba(c["bg"], int(255 * alpha)))
    od.rectangle((0, img.height // 2 - 118, 22, img.height // 2 + 118), fill=_rgba(c["accent"], int(255 * alpha)))
    # oversized ghost numeral gives the card depth without extra assets
    ghost = _font(TITLE_FONT, 460)
    numeral = f"{number:02d}"
    ghost_alpha = int(38 * alpha)
    od.text(
        (img.width - od.textlength(numeral, font=ghost) - 40, -90),
        numeral,
        font=ghost,
        fill=_rgba(c["accent"], ghost_alpha),
    )
    od.text((96, img.height // 2 - 132), f"CHAPTER {number}", font=_font(SMALL_FONT, 30), fill=_rgba(c["accent"], int(255 * alpha)))
    font, lines = _font(TITLE_FONT, 96), []
    pen = ImageDraw.Draw(overlay)
    for size in (96, 88, 80, 72):
        font = _font(TITLE_FONT, size)
        lines = _wrap(pen, title.upper(), font, img.width - 240)
        if len(lines) <= 2:
            break
    y = img.height // 2 - 76
    for line in lines:
        pen.text((96, y), line, font=font, fill=_rgba(c["text"], int(255 * alpha)))
        y += int(size * 1.12)
    return Image.alpha_composite(img, overlay)


# ------------------------------------------------------------------- frame drawing


def _draw_motion_ring(draw: ImageDraw.ImageDraw, profile: Profile, spec: ChannelSpec, t: float) -> None:
    """Two counter-rotating dashed rings and orbiting dots, centred on the diagram plate.

    Drawn into the motif layer, so the plate clip keeps it inside the panel and it can never reach the type or
    the caption band. Counter-rotation is deliberate: a single ring moved the frame by about half a grey level
    per second on a flat card, which is inside `freezedetect`'s tolerance; two rings plus six orbiting dots
    churn enough pixels to be unambiguous motion at any duration.
    """

    c = spec.colors
    cx = (PANEL_X + profile.width - profile.margin) / 2
    cy = (PANEL_TOP + PANEL_BOTTOM) / 2
    faint = _mix(c["bg"], c["muted"], 0.55)
    for radius, rate, colour in ((250, 0.42, faint), (206, -0.67, _rgba(c["accent2"], 200))):
        phase = math.degrees(t * rate)
        for index in range(18):
            start = phase + index * 20.0
            draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + 11.0,
                     fill=colour, width=3)
    for index in range(6):
        angle = t * 0.8 + index * (math.pi / 3)
        x = cx + math.cos(angle) * 271
        y = cy + math.sin(angle) * 271
        draw.ellipse((x - 6, y - 6, x + 6, y + 6),
                     fill=_rgba(c["accent"] if index % 2 == 0 else c["accent2"], 235))
    # A soft accent band sweeps across the plate. The rings alone moved 4 529 pixels a second on a still card,
    # which is motion, but not obviously enough motion: the band covers a full-height column, so a held card
    # keeps changing by a wide area instead of a few dashes. Drawn into the motif layer, so the plate clip
    # keeps it inside the panel and it never crosses the type column or the caption band.
    band = 190.0
    span = (profile.width - profile.margin) - PANEL_X
    travel = (t / SWEEP_PERIOD) % 1.0
    left = PANEL_X - band + travel * (span + 2 * band)
    draw.rectangle((left, PANEL_TOP - 40, left + band, PANEL_BOTTOM + 40),
                   fill=_rgba(c["accent2"], 22))


def _draw_frame(
    base: Image.Image,
    line: ScriptLine,
    t: float,
    duration: float,
    index: int,
    total: int,
    spec: ChannelSpec,
    brand: tuple[str, str, str],
    chapter_marks: list[float],
    chapter_for_line: dict[int, tuple[int, str]],
    chapter_starts: set[int] | None = None,
    geometry: dict[str, Any] | None = None,
) -> Image.Image:
    profile = get_profile(spec)
    frame = base.copy()
    draw = ImageDraw.Draw(frame)
    local = max(0.0, t - line.start)
    c = spec.colors

    _chrome(draw, profile, spec, brand, index, total)

    # panel background first, then motif inside it
    draw.rounded_rectangle(
        (PANEL_X, PANEL_TOP, profile.width - profile.margin, PANEL_BOTTOM),
        radius=28,
        fill=_rgba(c["panel"], 235),
        outline=_rgba(c["grid"], 255),
        width=2,
    )
    # Motifs are drawn on their own layer and clipped to the plate, otherwise dense
    # patterns (grid/chip) bleed past the panel edge into the frame.
    motif_layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    _motif(ImageDraw.Draw(motif_layer), profile, spec, line.visual or "network", t, local)
    # Continuous content motion, inside the plate. Several motif kinds (shield, lock, scale) finish their intro
    # animation and then hold, and the caption only changes when a chunk changes, so a long line with a static
    # motif measured as a 5.4 s freeze at 164.5 s in the first local long-form render - a real stall on screen,
    # not a measurement artefact. A camera push-in cannot help: it reaches its 6 % cap at 20 s and then the
    # picture is still again. This ring rotates for the whole episode and its pixels are the motion.
    _draw_motion_ring(ImageDraw.Draw(motif_layer), profile, spec, t)
    mask = Image.new("L", frame.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (PANEL_X, PANEL_TOP, profile.width - profile.margin, PANEL_BOTTOM), radius=24, fill=255
    )
    motif_alpha = motif_layer.getchannel("A").point(lambda value: value)
    motif_layer.putalpha(ImageChops.multiply(motif_alpha, mask))
    frame = Image.alpha_composite(frame, motif_layer)
    draw = ImageDraw.Draw(frame)  # rebind: text must land on the composited frame

    enter = _ease_out(local / 0.42)
    offset = int((1 - enter) * 26)
    margin = float(TEXT_MARGIN)
    max_width = TEXT_COL - 40 - (TEXT_MARGIN - MARGIN)

    kicker = f"CHAPTER {chapter_for_line.get(index, (0, ''))[0]}" if index in chapter_for_line else brand[1]
    draw.text((margin, PANEL_TOP + offset), kicker, font=_font(SMALL_FONT, 24), fill=c["accent"])

    headline_font, headline_lines = _headline(draw, profile, spec, line.headline or line.caption or " ", max_width)
    y = PANEL_TOP + 52 + offset
    headline_right = float(margin)
    headline_top = float(y)
    for text_line in headline_lines:
        draw.text((margin, y), text_line, font=headline_font, fill=_rgba(c["text"], int(255 * enter)))
        headline_right = max(headline_right, margin + draw.textlength(text_line, font=headline_font))
        y += int(headline_font.size * 1.14)

    rule_y = y + 18
    draw.rounded_rectangle((margin, rule_y, margin + 120, rule_y + 6), radius=3, fill=_rgba(c["accent"], int(255 * enter)))

    body_rect = _body_block(draw, profile, spec, line.text, max_width, rule_y + 34, CAPTION_TOP - 34, enter,
                            margin=margin)

    caption_rect = _caption_band(draw, profile, spec, _active_chunk(_chunks(line), t), t)
    _rail(draw, profile, spec, t / max(duration, 0.01), chapter_marks)

    if geometry is not None:
        geometry["headline"] = (float(margin), headline_top, float(headline_right),
                                float(y - int(headline_font.size * 0.14)))
        geometry["body"] = body_rect
        geometry["caption"] = caption_rect
        geometry["chapter_card"] = False

    if chapter_starts and index in chapter_starts:
        number, title = chapter_for_line[index]
        card_start = line.start
        card_alpha = max(0.0, 1.0 - max(0.0, local - 0.9) / 0.5)
        if t - card_start < 1.4:
            # A chapter card covers the frame, so the frame's measurements describe the card, not the layout
            # underneath it. Recorded rather than dropped: a silently skipped frame is how a gate ends up
            # measuring nothing and reporting a pass.
            if geometry is not None:
                geometry["chapter_card"] = True
            return _chapter_card(frame, spec, number, title, card_alpha)
    return frame


# ------------------------------------------------------------------- entry point


def _chapter_map(
    script: Script, lines: list[ScriptLine]
) -> tuple[dict[int, tuple[int, str]], list[float], set[int]]:
    """Map every line index to its (chapter number, title) and list chapter starts."""

    chapters = script.metadata.get("chapters") or []
    mapping: dict[int, tuple[int, str]] = {}
    marks: list[float] = []
    starts_set: set[int] = set()
    if not chapters:
        return mapping, marks, starts_set
    starts = {index: line.start for index, line in enumerate(lines)}
    total_duration = max((line.end for line in lines), default=1.0) or 1.0
    resolved: list[tuple[int, int, str]] = []
    for number, chapter in enumerate(chapters, 1):
        try:
            line_index = int(chapter.get("line", 0))
        except (TypeError, ValueError):
            continue
        resolved.append((line_index, number, str(chapter.get("title", ""))))
        starts_set.add(line_index)
        if line_index in starts:
            marks.append(min(1.0, starts[line_index] / total_duration))
    resolved.sort()
    # Forward-fill: every line after a chapter start belongs to that chapter, so the
    # kicker keeps naming the active chapter instead of falling back to the brand tag.
    for index in range(len(lines)):
        current = None
        for start_index, number, title in resolved:
            if start_index <= index:
                current = (number, title)
        if current:
            mapping[index] = current
    return mapping, marks, starts_set


def render_landscape(
    script: Script,
    narration: Narration,
    spec: ChannelSpec,
    output_path: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Render a 1920x1080 long-form episode and return a machine-readable result."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_file() and not force:
        raise FileExistsError(f"output already exists: {output_path}")

    profile = get_profile(spec)
    lines = narration.lines or script.lines
    if not lines:
        raise ValueError("no narration timeline")
    duration = max(narration.duration, max(line.end for line in lines) + 0.6)

    work_dir = output_path.parent / f"{output_path.stem}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    bed_path = work_dir / "bed.wav"
    mixed_audio = work_dir / "mixed.m4a"
    make_bed(duration, spec.palette, [line.start for line in lines[1:]], bed_path)
    mix_narration(narration.audio_path, bed_path, mixed_audio, duration)

    brand = BRAND.get(spec.slug, (spec.display_name.upper(), "BRIEF", spec.handle))
    base = _base(profile, spec)
    chapter_for_line, chapter_marks, chapter_starts = _chapter_map(script, lines)
    total_frames = max(1, int(math.ceil(duration * FPS_TARGET)))

    command = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{profile.width}x{profile.height}",
        "-r", str(FPS_TARGET), "-i", "-",
        "-i", str(mixed_audio),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        # Copied, not re-encoded: `mix_narration` measured this AAC file's true peak and made it pass the
        # gate, and a second encode added overshoot after that measurement (see english_renderer).
        "-c:a", "copy",
        "-shortest", "-movflags", "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        samples: list[dict[str, Any]] = []
        for frame_index in range(total_frames):
            t = frame_index / FPS_TARGET
            line, line_index = _active_line(lines, t)
            geometry: dict[str, Any] = {}
            frame = _draw_frame(
                base, line, t, duration, line_index, len(lines), spec, brand,
                chapter_marks, chapter_for_line, chapter_starts, geometry=geometry,
            )
            geometry["pan"] = apply_pan(frame, t)
            if frame_index % FRAMING_SAMPLE_STRIDE == 0:
                sample = measure_geometry(geometry, frame)
                sample["t"] = round(t, 3)
                samples.append(sample)
            apply_grain(frame, frame_index)
            process.stdin.write(frame.convert("RGB").tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        code = process.wait(timeout=1800)
        if code != 0:
            raise RuntimeError(f"ffmpeg video encode failed: {stderr[-3000:]}")
    except Exception:
        process.kill()
        raise

    streams = ffprobe_streams(output_path)
    payload = {
        "video_path": str(output_path),
        "duration": round(duration, 3),
        "size": output_path.stat().st_size,
        "profile": "16:9",
        "chapters": [chapter.get("title", "") for chapter in (script.metadata.get("chapters") or [])],
        "streams": [
            {
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
            }
            for stream in streams.get("streams", [])
        ],
        "rendered_at": iso_now(),
    }
    (output_path.parent / "render.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "timeline.json").write_text(json.dumps(narration.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # The publishing gate requires `story.json` and `framing.json` in every episode and treats a missing report
    # as a blocker. The Shorts renderer learned that in cloud run 45045980024; this renderer never wrote either,
    # so an English long-form episode was ungateable by construction - the gate answered "framing.json missing:
    # composition unverified" no matter how good the video was.
    layout_samples = [sample for sample in samples if not sample.get("chapter_card")]
    cropped = [s for s in layout_samples if s["headline_overflow"] > 0 or s["body_overflow"] > 0
               or s["caption_overflow"] > 0]
    collisions = [s for s in layout_samples if s["collision"]]
    unpainted = [s for s in layout_samples if not s["headline_painted"]]
    framing = {
        "schema": "framing/1",
        "channel": spec.slug,
        "plan_id": script.metadata.get("plan_id"),
        "engine": "cards",
        "profile": "16:9",
        "measured": True,
        "method": "rectangles returned by the draw calls, per sampled frame, cross-checked for ink",
        "safe_area": SAFE_AREA_16X9,
        "sample_stride": FRAMING_SAMPLE_STRIDE,
        "frames_sampled": len(samples),
        "layout_frames_sampled": len(layout_samples),
        # a chapter card covers the layout on purpose; counting those frames as cropped would invent defects,
        # and dropping them without recording the count would hide a measurement gap
        "chapter_card_frames": len(samples) - len(layout_samples),
        "cropped_required_frames": len(cropped) + len(unpainted),
        "subtitle_collision_frames": len(collisions),
        "elements": {
            "headline": {
                "painted_frames": len([s for s in layout_samples if s["headline_painted"]]),
                "missing_frames": len(unpainted),
                "max_overflow_px": max((s["headline_overflow"] for s in layout_samples), default=0),
            },
            "body": {
                "max_overflow_px": max((s["body_overflow"] for s in layout_samples), default=0),
            },
            "caption": {
                "painted_frames": len([s for s in layout_samples if s["caption_painted"]]),
                "max_overflow_px": max((s["caption_overflow"] for s in layout_samples), default=0),
                "collisions": len(collisions),
            },
        },
        "samples": samples[:160],
    }
    (output_path.parent / "framing.json").write_text(
        json.dumps(framing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenes = []
    for index, line in enumerate(lines):
        scenes.append({
            "index": index + 1,
            "headline": line.headline,
            "text": line.text,
            "start": round(line.start, 3),
            "end": round(line.end, 3),
            "visual": line.visual or "network",
            "sfx": line.sfx,
            "chapter": chapter_for_line.get(index, (0, ""))[1],
            "assets": {"motif": line.visual or "network", "palette": spec.palette,
                       "plate": "generated/card-plate-16x9"},
        })
    story = {
        "schema": "story/1",
        "story_id": getattr(script, "story_id", None) or script.metadata.get("story_id"),
        "channel": spec.slug,
        "plan_id": script.metadata.get("plan_id"),
        "title": script.title,
        "format": spec.format,
        "language": spec.language,
        "engine": "cards",
        "profile": "16:9",
        "created_at": iso_now(),
        "scene_count": len(scenes),
        "chapters": [{"title": chapter.get("title", ""), "line": chapter.get("line")}
                     for chapter in (script.metadata.get("chapters") or [])],
        "scenes": scenes,
        "sources": list(script.sources or []),
        "provenance": {
            "visuals": "generated in-process from primitives; no stock photography, no third-party media",
            "fonts": [path.name for path in (TITLE_FONT, SERIF_FONT, SMALL_FONT)],
            "music": "synthesised bed (factory.media.music)",
            "narration": "TTS provider declared in script.json",
            "claims": "no statistic is asserted that is not attributable in the plan's source ledger",
        },
    }
    (output_path.parent / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


# A card explainer is mostly type on a flat plate. Diagram motion plus a sweeping band still left a 2.13 s
# `freezetect` window on a held line, because at 30 fps a 300 px/s band is a 10 px column per frame - 0.5 % of the
# frame, which is below the -50 dB floor. Broadcast card animation solves this with animated grain, and so does
# this: a pre-rendered noise field offset per frame, applied to the finished frame. It is nearly invisible, it is
# not a threshold trick (the frames genuinely differ), and it costs one clip per frame.
GRAIN_AMPLITUDE = 3
GRAIN_TILES = 16


def _grain_field(seed: int = 20261123) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(-GRAIN_AMPLITUDE, GRAIN_AMPLITUDE + 1,
                        size=(GRAIN_TILES, HEIGHT, WIDTH), dtype=np.int8)


_GRAIN = _grain_field()


# What actually survives h.264 at CRF 20 is geometry, not noise. Animated grain was quantised away on flat
# panels - measured as 0.1 grey levels of mean frame-to-frame difference after encoding, against the ~0.8 that
# `freezedetect` needs - and both cloud runs kept finding a 2.1 s hold. A whole-frame pan moves every high
# contrast edge in the picture by whole pixels, which the encoder has to reproduce. The excursion is +/-36 px
# horizontally and +/-22 px vertically against a 104 px margin, so it reads as a slow sway, not as motion.
PAN_X = (36.0, 21.0)   # amplitude in px, period in seconds
PAN_Y = (22.0, 33.0)


def pan_offset(t: float) -> tuple[int, int]:
    """Integer pixel offset for time `t`. Two incommensurate periods, so it never repeats within an episode."""

    dx = PAN_X[0] * math.sin(2.0 * math.pi * t / PAN_X[1])
    dy = PAN_Y[0] * math.sin(2.0 * math.pi * t / PAN_Y[1] + 1.7)
    return int(round(dx)), int(round(dy))


def apply_pan(frame: Image.Image, t: float) -> tuple[int, int]:
    dx, dy = pan_offset(t)
    if not dx and not dy:
        return 0, 0
    shifted = frame.transform(frame.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                              resample=Image.BILINEAR)
    frame.paste(shifted)
    return dx, dy


def apply_grain(frame: Image.Image, index: int) -> None:
    """Animate the grain in place: cycle a tile and offset it, so no two frames reuse the same pattern."""

    tile = _GRAIN[index % GRAIN_TILES]
    shift_x = (index * 37) % 251
    shift_y = (index * 53) % 173
    field = np.roll(tile, (shift_y, shift_x), axis=(0, 1))
    pixels = np.asarray(frame.convert("RGB"), dtype=np.int16) + field[..., None]
    frame.paste(Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)))


SAFE_AREA_16X9 = {"left": MARGIN, "right": WIDTH - MARGIN, "top": PANEL_TOP, "bottom": RAIL_Y - 10}
FRAMING_SAMPLE_STRIDE = 6
INK_THRESHOLD = 60
SWEEP_PERIOD = 7.0   # seconds for the plate band to cross once


def _overflow(box: tuple[float, float, float, float] | None) -> int:
    if box is None:
        return 0
    left, top, right, bottom = box
    return int(max(0, SAFE_AREA_16X9["left"] - left, right - SAFE_AREA_16X9["right"],
                   SAFE_AREA_16X9["top"] - top, bottom - SAFE_AREA_16X9["bottom"]))


def _intersects(first: tuple[float, float, float, float] | None,
                second: tuple[float, float, float, float] | None) -> bool:
    if not first or not second:
        return False
    return not (first[2] < second[0] or first[0] > second[2]
                or first[3] < second[1] or first[1] > second[3])


def _has_ink(frame: Image.Image, box: tuple[float, float, float, float]) -> bool:
    """Something is actually painted inside this rectangle, in the encoded frame.

    The report is built from rectangles the draw calls returned, which is exact and would also be exact if a
    call returned a rectangle it never painted. This reads the frame, so the report cannot outrun the picture.
    """

    left, top, right, bottom = (int(max(0, box[0])), int(max(0, box[1])),
                                int(min(WIDTH, box[2])), int(min(HEIGHT, box[3])))
    if right - left < 2 or bottom - top < 2:
        return False
    luma = np.asarray(frame.convert("L"), dtype=np.uint8)[top:bottom, left:right].astype(np.int16)
    gradient = np.abs(np.diff(luma, axis=1)).sum() + np.abs(np.diff(luma, axis=0)).sum()
    return bool(gradient > INK_THRESHOLD)


def measure_geometry(geometry: dict[str, Any], frame: Image.Image) -> dict[str, Any]:
    """One frame's framing evidence for the 16:9 profile."""

    if geometry.get("chapter_card"):
        return {"chapter_card": True, "headline": None, "body": None, "caption": None,
                "headline_overflow": 0, "caption_overflow": 0, "body_overflow": 0,
                "collision": False, "headline_painted": False, "caption_painted": False}

    dx, dy = geometry.get("pan", (0, 0))

    def shifted(box):
        return None if box is None else (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)

    headline = shifted(geometry.get("headline"))
    body = shifted(geometry.get("body"))
    caption = shifted(geometry.get("caption"))
    return {
        "chapter_card": False,
        "headline": list(headline) if headline else None,
        "body": list(body) if body else None,
        "caption": list(caption) if caption else None,
        "headline_overflow": _overflow(headline),
        "body_overflow": _overflow(body),
        "caption_overflow": _overflow(caption),
        # the support copy is what actually sits above the caption, so it is what the caption can collide with
        "collision": _intersects(caption, body),
        "headline_painted": _has_ink(frame, headline) if headline else False,
        "caption_painted": _has_ink(frame, caption) if caption else False,
    }


def _active_line(lines: list[ScriptLine], t: float) -> tuple[ScriptLine, int]:
    for index, line in enumerate(lines):
        if line.start <= t < line.end:
            return line, index
    if t < lines[0].start:
        return lines[0], 0
    return lines[-1], len(lines) - 1
