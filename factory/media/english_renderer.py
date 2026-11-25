"""Premium 1080x1920 English motion-graphics renderer built on Pillow + ffmpeg."""

from __future__ import annotations

import hashlib

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..config import FONTS_DIR, FPS, ChannelSpec
from ..content.models import Narration, Script, ScriptLine, WordTiming
from ..util import ffprobe_streams, iso_now, run
from .music import make_bed, mix_narration

WIDTH = 1080
HEIGHT = 1920

TITLE_FONT = FONTS_DIR / "Inter-Black.otf"
SMALL_FONT = FONTS_DIR / "Inter-ExtraBold.otf"
SERIF_FONT = FONTS_DIR / "Caladea-Bold.ttf"

BRAND = {
    "nexus-node": ("NEXUS NODE", "SYSTEM BRIEF", "@nexusnode012"),
    "academic-biohacker": ("ACADEMIC BIOHACKER", "EVIDENCE BRIEF", "@academicbiohacker"),
    "natkhat-toons": ("NATKHAT TOONS", "KAHANI", "@NatkhatToons-n5"),
}


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (*_rgb(value), alpha)


def _mix(first: str, second: str, amount: float) -> str:
    one = _rgb(first)
    two = _rgb(second)
    mixed = tuple(round(a * (1 - amount) + b * amount) for a, b in zip(one, two))
    return "#" + "".join(f"{value:02x}" for value in mixed)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_headline(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int = 900,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in (100, 92, 84, 76, 68, 60):
        font = _font(TITLE_FONT, size)
        lines = _wrap(draw, text.upper(), font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(TITLE_FONT, 58)
    return font, _wrap(draw, text.upper(), font, max_width)[:max_lines]


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    y: int,
    fill: str | tuple[int, ...],
    width: int = WIDTH,
) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    x = (width - (box[2] - box[0])) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return y + (box[3] - box[1])


def _letter_spaced(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, x: int, y: int, fill: str, spacing: int = 3) -> int:
    cursor = x
    for character in text:
        draw.text((cursor, y), character, font=font, fill=fill)
        cursor += draw.textlength(character, font=font) + spacing
    return cursor


def _base_image(spec: ChannelSpec) -> Image.Image:
    c = spec.colors
    top = np.array(_rgb(c["bg"]), dtype=np.float32)
    bottom = np.array(_rgb(c["bg2"]), dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, HEIGHT, dtype=np.float32)[:, None]
    array = (top[None, :] * (1.0 - ramp) + bottom[None, :] * ramp)[:, None, :]
    array = np.repeat(array, WIDTH, axis=1)
    base = Image.fromarray(np.uint8(np.clip(array, 0, 255)), mode="RGB").convert("RGBA")

    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    accent = _rgb(c["accent"])
    accent2 = _rgb(c["accent2"])
    for radius, alpha in ((520, 30), (380, 24), (250, 18)):
        gd.ellipse(
            (WIDTH - radius + 120, 260 - radius, WIDTH + radius + 120, 260 + radius),
            fill=(*accent, alpha),
        )
    for radius, alpha in ((450, 22), (300, 16)):
        gd.ellipse(
            (-radius - 80, HEIGHT - 380 - radius, radius - 80, HEIGHT - 380 + radius),
            fill=(*accent2, alpha),
        )
    base = Image.alpha_composite(base, glow)

    grid = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    grid_color = _rgba(c["grid"], 60)
    for x in range(0, WIDTH, 72):
        g.line((x, 0, x, HEIGHT), fill=grid_color, width=1)
    for y in range(0, HEIGHT, 72):
        g.line((0, y, WIDTH, y), fill=grid_color, width=1)
    base = Image.alpha_composite(base, grid)

    if spec.palette == "academic":
        rng = np.random.default_rng(11)
        noise = rng.normal(0, 7, (HEIGHT, WIDTH, 1)).repeat(3, axis=2)
        grain = Image.fromarray(np.uint8(np.clip(128 + noise, 0, 255)), mode="RGB").convert("RGBA")
        grain.putalpha(10)
        base = Image.alpha_composite(base, grain)
        paper = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        pd = ImageDraw.Draw(paper)
        pd.rectangle((46, 46, WIDTH - 46, HEIGHT - 46), outline=_rgba(c["muted"], 80), width=2)
        base = Image.alpha_composite(base, paper)
    else:
        vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vignette)
        vd.rectangle((0, 0, WIDTH, 130), fill=(0, 0, 0, 55))
        vd.rectangle((0, HEIGHT - 200, WIDTH, HEIGHT), fill=(0, 0, 0, 70))
        base = Image.alpha_composite(base, vignette)
    return base


def _motif_plate(draw: ImageDraw.ImageDraw, c: dict[str, str]) -> None:
    panel = _mix(c["bg"], c["panel"], 0.65)
    draw.rounded_rectangle((180, 700, 900, 1250), radius=48, fill=panel, outline=_mix(c["bg"], c["accent"], 0.35), width=2)


def _line(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float, fill: str, width: int = 4) -> None:
    draw.line((x1, y1, x2, y2), fill=fill, width=width)


def _dot(draw: ImageDraw.ImageDraw, x: float, y: float, r: float, fill: str) -> None:
    draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _arrow(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, fill: str, direction: str = "right") -> None:
    if direction == "right":
        points = [(x, y - size), (x + size, y), (x, y + size)]
    elif direction == "down":
        points = [(x - size, y), (x, y + size), (x + size, y)]
    elif direction == "left":
        points = [(x, y - size), (x - size, y), (x, y + size)]
    else:
        points = [(x - size, y), (x, y - size), (x + size, y)]
    draw.polygon(points, fill=fill)


def _draw_motif(draw: ImageDraw.ImageDraw, kind: str, t: float, c: dict[str, str], pulse: float) -> None:
    _motif_plate(draw, c)
    cx, cy = 540, 980
    accent = c["accent"]
    accent2 = c["accent2"]
    muted = _mix(c["bg"], c["muted"], 0.75)
    text = c["text"]
    panel = _mix(c["bg"], c["panel"], 0.8)
    s = 1.0 + 0.025 * math.sin(t * 2.0) * pulse

    if kind == "network":
        points = []
        for index in range(7):
            angle = t * 0.25 + index * (2 * math.pi / 7)
            radius = 155 * s
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        for index, point in enumerate(points):
            _line(draw, cx, cy, point[0], point[1], muted, 3)
            if index % 2 == 0:
                _line(draw, point[0], point[1], points[(index + 2) % len(points)][0], points[(index + 2) % len(points)][1], _mix(c["bg"], accent, 0.5), 2)
        for index, point in enumerate(points):
            _dot(draw, point[0], point[1], 12 + (index % 3) * 3, accent if index % 2 == 0 else accent2)
        _dot(draw, cx, cy, 26, text)
        _dot(draw, cx, cy, 14, accent)
    elif kind == "chip":
        _draw_centered(draw, "AI", _font(TITLE_FONT, 150), 900, accent)
        draw.rounded_rectangle((cx - 155, cy - 155, cx + 155, cy + 155), radius=28, outline=accent, width=5)
        draw.rounded_rectangle((cx - 105, cy - 105, cx + 105, cy + 105), radius=18, outline=accent2, width=2)
        for index in range(8):
            offset = -140 + index * 40
            _line(draw, cx + offset, cy - 185, cx + offset, cy - 155, muted, 4)
            _line(draw, cx + offset, cy + 155, cx + offset, cy + 185, muted, 4)
            _line(draw, cx - 185, cy + offset, cx - 155, cy + offset, muted, 4)
            _line(draw, cx + 155, cy + offset, cx + 185, cy + offset, muted, 4)
    elif kind == "screen":
        draw.rounded_rectangle((cx - 210, cy - 150, cx + 210, cy + 120), radius=18, outline=accent, width=5)
        draw.rectangle((cx - 185, cy - 125, cx + 185, cy + 85), fill=_mix(c["bg"], panel, 0.5), outline=muted, width=2)
        draw.rectangle((cx - 45, cy + 120, cx + 45, cy + 170), fill=accent2)
        draw.rectangle((cx - 120, cy + 170, cx + 120, cy + 182), fill=accent2)
        for index in range(3):
            _line(draw, cx - 150, cy - 80 + index * 45, cx - 30 + index * 20, cy - 80 + index * 45, _mix(c["bg"], text, 0.5), 5)
        _arrow(draw, cx + 60 + 10 * math.sin(t * 3), cy + 10 + 8 * math.cos(t * 3), 18, accent2)
    elif kind == "loop":
        draw.arc((cx - 160, cy - 160, cx + 160, cy + 160), 30, 320, fill=accent, width=6)
        draw.arc((cx - 120, cy - 120, cx + 120, cy + 120), 210, 500, fill=accent2, width=3)
        for angle in (30, 150, 270):
            x = cx + math.cos(math.radians(angle + t * 12)) * 160
            y = cy + math.sin(math.radians(angle + t * 12)) * 160
            _dot(draw, x, y, 16, accent2)
        _arrow(draw, cx + 150, cy - 85, 22, accent, "down")
    elif kind == "robot":
        draw.rounded_rectangle((cx - 130, cy - 110, cx + 130, cy + 95), radius=38, fill=panel, outline=accent, width=4)
        _line(draw, cx, cy - 110, cx, cy - 185, accent, 4)
        _dot(draw, cx, cy - 195, 12, accent2)
        _dot(draw, cx - 55, cy - 25, 18, accent)
        _dot(draw, cx + 55, cy - 25, 18, accent)
        draw.rounded_rectangle((cx - 55, cy + 35, cx + 55, cy + 55), radius=10, fill=accent2)
        draw.rounded_rectangle((cx - 110, cy + 110, cx + 110, cy + 210), radius=24, outline=muted, width=3)
    elif kind == "shield":
        points = [(cx, cy - 190), (cx + 160, cy - 120), (cx + 130, cy + 90), (cx, cy + 200), (cx - 130, cy + 90), (cx - 160, cy - 120)]
        draw.polygon(points, outline=accent, width=5, fill=_mix(c["bg"], panel, 0.4))
        draw.line((cx - 65, cy + 5, cx - 10, cy + 65, cx + 90, cy - 60), fill=accent2, width=12)
    elif kind == "sandbox":
        for index in range(4):
            dash = 24
            y = cy - 170 + index * 115
            for x in range(cx - 190, cx + 190, dash * 2):
                _line(draw, x, y, x + dash, y, muted, 3)
        _dot(draw, cx, cy, 38, accent)
        _dot(draw, cx, cy, 16, text)
        _line(draw, cx, cy + 38, cx, cy + 120, accent2, 5)
        _line(draw, cx, cy + 120, cx - 45, cy + 175, accent2, 5)
        _line(draw, cx, cy + 120, cx + 45, cy + 175, accent2, 5)
    elif kind == "flow":
        for index in range(3):
            y = cy - 170 + index * 135
            draw.rounded_rectangle((cx - 210, y, cx - 20, y + 90), radius=18, fill=panel, outline=accent if index == 1 else muted, width=3)
            _line(draw, cx - 185, y + 35, cx - 50, y + 35, accent2, 5)
            _line(draw, cx - 185, y + 58, cx - 80, y + 58, muted, 4)
            if index < 2:
                _line(draw, cx - 10, y + 45, cx + 60, y + 45, muted, 4)
                _arrow(draw, cx + 60, y + 45, 14, accent)
        draw.rounded_rectangle((cx + 85, cy - 80, cx + 205, cy + 80), radius=18, outline=accent2, width=3)
        _dot(draw, cx + 145, cy, 18, accent2)
    elif kind == "target":
        for radius, color in ((170, muted), (125, accent), (80, accent2)):
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=color, width=4)
        _dot(draw, cx, cy, 35, text)
        _arrow(draw, cx + 90, cy - 90, 24, accent, "down")
    elif kind == "laptop":
        draw.rounded_rectangle((cx - 190, cy - 130, cx + 190, cy + 90), radius=16, outline=accent, width=4, fill=panel)
        draw.polygon([(cx - 250, cy + 120), (cx + 250, cy + 120), (cx + 210, cy + 170), (cx - 210, cy + 170)], fill=accent2)
        for index in range(5):
            x = cx - 120 + index * 60
            _dot(draw, x, cy - 40 + (index % 2) * 45, 10, accent)
        _line(draw, cx - 150, cy - 40, cx - 60, cy + 5, muted, 2)
        _line(draw, cx - 60, cy + 5, cx + 60, cy - 50, muted, 2)
        _line(draw, cx + 60, cy - 50, cx + 150, cy + 5, muted, 2)
    elif kind == "scale":
        heights = [70, 120, 190, 260, 330]
        for index, height in enumerate(heights):
            x = cx - 190 + index * 85
            draw.rounded_rectangle((x, cy + 120 - height, x + 50, cy + 120), radius=8, fill=accent if index < 3 else accent2)
        _line(draw, cx - 210, cy + 120, cx + 230, cy + 120, muted, 3)
    elif kind == "memory":
        for index in range(3):
            offset = index * 22
            draw.rounded_rectangle((cx - 190 + offset, cy - 150 + offset, cx + 150 + offset, cy + 100 + offset), radius=20, fill=panel, outline=_mix(c["bg"], accent, 0.5), width=3)
        _dot(draw, cx - 100, cy - 60, 14, accent)
        _dot(draw, cx - 40, cy - 60, 14, accent2)
        _dot(draw, cx + 20, cy - 60, 14, accent)
        _line(draw, cx - 120, cy + 5, cx + 100, cy + 5, muted, 4)
        _line(draw, cx - 120, cy + 35, cx + 60, cy + 35, muted, 4)
    elif kind == "database":
        draw.ellipse((cx - 150, cy - 160, cx + 150, cy - 100), outline=accent, width=4, fill=panel)
        draw.rectangle((cx - 150, cy - 130, cx + 150, cy + 130), fill=panel, outline=accent, width=4)
        draw.ellipse((cx - 150, cy + 100, cx + 150, cy + 160), outline=accent, width=4, fill=panel)
        for index in range(3):
            draw.arc((cx - 150, cy - 40 + index * 55, cx + 150, cy + 20 + index * 55), 0, 180, fill=muted, width=3)
        _arrow(draw, cx + 210, cy - 80, 22, accent2, "down")
    elif kind == "warning":
        draw.polygon([(cx, cy - 170), (cx + 190, cy + 140), (cx - 190, cy + 140)], outline=accent2, width=6, fill=_mix(c["bg"], panel, 0.35))
        draw.rounded_rectangle((cx - 14, cy - 80, cx + 14, cy + 55), radius=12, fill=accent2)
        _dot(draw, cx, cy + 100, 18, accent2)
    elif kind == "question":
        _draw_centered(draw, "?", _font(TITLE_FONT, 300), 820, accent)
        draw.arc((cx - 220, cy - 220, cx + 220, cy + 220), 20 + t * 8, 300 + t * 8, fill=accent2, width=4)
        _dot(draw, cx + 215, cy, 14, accent2)
    elif kind == "brain":
        draw.arc((cx - 170, cy - 150, cx + 170, cy + 130), 180, 360, fill=accent, width=6)
        draw.arc((cx - 140, cy - 100, cx + 140, cy + 110), 170, 350, fill=accent2, width=4)
        for index in range(4):
            _line(draw, cx - 120 + index * 55, cy - 110, cx - 100 + index * 55, cy + 80, muted, 3)
        _line(draw, cx, cy + 130, cx, cy + 200, accent, 6)
        _line(draw, cx, cy + 200, cx - 60, cy + 250, accent, 4)
        _line(draw, cx, cy + 200, cx + 60, cy + 250, accent, 4)
    elif kind == "wave":
        for index in range(3):
            points = []
            for step in range(120):
                x = cx - 200 + step * (400 / 119)
                y = cy - 60 + index * 55 + math.sin(step * 0.18 + t * 2 + index) * (22 + index * 6)
                points.append((x, y))
            draw.line(points, fill=accent if index == 0 else accent2, width=5 - index)
        for index in range(4):
            _dot(draw, cx - 130 + index * 85, cy + 120 + (index % 2) * 25, 9, muted)
    elif kind == "cell":
        draw.ellipse((cx - 180, cy - 180, cx + 180, cy + 180), outline=accent, width=5, fill=panel)
        draw.ellipse((cx - 65, cy - 65, cx + 65, cy + 65), fill=accent2)
        for angle in range(0, 360, 45):
            x = cx + math.cos(math.radians(angle + t * 10)) * 125
            y = cy + math.sin(math.radians(angle + t * 10)) * 125
            _dot(draw, x, y, 10, accent)
    elif kind == "flask":
        draw.polygon([(cx - 70, cy - 180), (cx + 70, cy - 180), (cx + 70, cy - 60), (cx + 160, cy + 140), (cx - 160, cy + 140), (cx - 70, cy - 60)], outline=accent, width=5, fill=panel)
        draw.polygon([(cx - 115, cy + 40), (cx + 115, cy + 40), (cx + 160, cy + 140), (cx - 160, cy + 140)], fill=accent2)
        for index in range(4):
            _dot(draw, cx - 45 + index * 30, cy + 80 - index * 18, 8 + index * 2, text)
    elif kind == "moon":
        draw.ellipse((cx - 150, cy - 180, cx + 150, cy + 180), fill=accent, outline=None)
        draw.ellipse((cx - 40, cy - 190, cx + 210, cy + 120), fill=_mix(c["bg"], panel, 0.55), outline=None)
        for index in range(5):
            x = cx - 190 + (index * 95) % 380
            y = cy - 220 + (index * 140) % 300
            _dot(draw, x, y, 5 + index % 2 * 3, accent2)
    elif kind == "sun":
        _dot(draw, cx, cy, 95, accent)
        for index in range(12):
            angle = index * math.pi / 6 + t * 0.15
            x1 = cx + math.cos(angle) * 130
            y1 = cy + math.sin(angle) * 130
            x2 = cx + math.cos(angle) * 185
            y2 = cy + math.sin(angle) * 185
            _line(draw, x1, y1, x2, y2, accent2, 6)
    elif kind == "clock":
        draw.ellipse((cx - 180, cy - 180, cx + 180, cy + 180), outline=accent, width=6, fill=panel)
        for index in range(12):
            angle = index * math.pi / 6
            _line(draw, cx + math.cos(angle) * 145, cy + math.sin(angle) * 145, cx + math.cos(angle) * 160, cy + math.sin(angle) * 160, muted, 3)
        _line(draw, cx, cy, cx + math.cos(t * 0.8) * 90, cy + math.sin(t * 0.8) * 90, accent2, 6)
        _line(draw, cx, cy, cx + math.cos(t * 0.12) * 130, cy + math.sin(t * 0.12) * 130, accent, 5)
        _dot(draw, cx, cy, 12, text)
    elif kind == "cloud":
        _dot(draw, cx + 70, cy - 70, 65, accent2)
        for offset in ((-120, 40, 70), (-20, 10, 95), (100, 40, 70)):
            draw.ellipse((cx + offset[0] - offset[2], cy + offset[1] - offset[2], cx + offset[0] + offset[2], cy + offset[1] + offset[2]), fill=panel, outline=accent, width=3)
        draw.rectangle((cx - 170, cy + 40, cx + 170, cy + 110), fill=panel)
        for index in range(3):
            _line(draw, cx - 120 + index * 65, cy + 145, cx - 100 + index * 65, cy + 205, muted, 4)
    elif kind == "walk":
        _dot(draw, cx - 40, cy - 140, 32, accent)
        _line(draw, cx - 40, cy - 105, cx - 40, cy + 20, text, 8)
        _line(draw, cx - 40, cy - 60, cx - 110, cy - 10 + math.sin(t * 4) * 15, text, 7)
        _line(draw, cx - 40, cy - 60, cx + 30, cy - 20 - math.sin(t * 4) * 15, text, 7)
        _line(draw, cx - 40, cy + 20, cx - 100 + math.sin(t * 4) * 20, cy + 130, text, 8)
        _line(draw, cx - 40, cy + 20, cx + 40 - math.sin(t * 4) * 20, cy + 130, text, 8)
        _dot(draw, cx + 180, cy - 120, 55, accent2)
    elif kind == "gut":
        points = []
        for step in range(150):
            x = cx - 220 + step * (440 / 149)
            y = cy + math.sin(step * 0.11 + t * 1.4) * 95
            points.append((x, y))
        draw.line(points, fill=accent, width=18, joint="curve")
        draw.line(points, fill=panel, width=8, joint="curve")
        for index in range(9):
            x = cx - 200 + index * 50
            y = cy + math.sin(index * 0.9 + t * 1.4) * 95
            _dot(draw, x, y - 28 - (index % 2) * 12, 6, accent2)
    elif kind == "nerve":
        _dot(draw, cx - 160, cy + 120, 20, accent)
        for index, (dx, dy) in enumerate(((0, -130), (45, -80), (90, -20), (130, 50))):
            _line(draw, cx - 160, cy + 120, cx - 120 + dx, cy + 120 + dy, muted, 6)
            _dot(draw, cx - 120 + dx, cy + 120 + dy, 12, accent2)
        _line(draw, cx - 40, cy + 10, cx + 150, cy - 120, accent, 8)
        _line(draw, cx + 150, cy - 120, cx + 190, cy - 170, accent, 5)
    elif kind == "microbe":
        draw.ellipse((cx - 130, cy - 90, cx + 130, cy + 100), fill=panel, outline=accent, width=5)
        for index in range(6):
            angle = index * math.pi / 3
            _dot(draw, cx + math.cos(angle) * 70, cy + math.sin(angle) * 50, 12, accent2)
        for index in range(4):
            x = cx + 120
            _line(draw, x, cy, x + 60, cy - 50 + index * 30, muted, 3)
    elif kind == "fiber":
        for index in range(5):
            y = cy - 120 + index * 55
            draw.arc((cx - 190, y - 35, cx + 190, y + 95), 190, 350, fill=accent if index % 2 == 0 else accent2, width=5)
        for index in range(4):
            _dot(draw, cx - 120 + index * 80, cy + 130, 10, muted)
    elif kind == "capsule":
        draw.rounded_rectangle((cx - 170, cy - 70, cx + 170, cy + 70), radius=70, fill=accent)
        draw.rounded_rectangle((cx, cy - 70, cx + 170, cy + 70), radius=70, fill=panel)
        draw.arc((cx - 170, cy - 70, cx + 170, cy + 70), 90, 270, fill=text, width=4)
        _line(draw, cx, cy - 70, cx, cy + 70, muted, 4)
    elif kind == "spark":
        for index in range(10):
            angle = index * math.pi / 5 + t * 0.3
            inner = 40
            outer = 150 if index % 2 == 0 else 100
            _line(draw, cx + math.cos(angle) * inner, cy + math.sin(angle) * inner, cx + math.cos(angle) * outer, cy + math.sin(angle) * outer, accent if index % 2 == 0 else accent2, 6)
        _dot(draw, cx, cy, 40, text)
    else:
        _draw_centered(draw, "01", _font(TITLE_FONT, 220), 850, accent)


def _caption_chunks(line: ScriptLine) -> list[dict[str, Any]]:
    words = line.words
    if not words:
        tokens = line.text.split()
        if not tokens:
            return []
        groups = [tokens[index : index + 2] for index in range(0, len(tokens), 2)]
        span = max(0.45, (line.end - line.start) / max(1, len(groups)))
        return [
            {
                "words": group,
                "start": line.start + index * span,
                "end": line.start + (index + 1) * span,
            }
            for index, group in enumerate(groups)
        ]
    chunks: list[dict[str, Any]] = []
    index = 0
    while index < len(words):
        group = words[index : index + 2]
        if len(words) - index >= 3 and len(group[0].text) + len(group[1].text) < 18:
            group = words[index : index + 3]
        start = group[0].start
        end = max(group[-1].end, start + 0.35)
        chunks.append({"words": group, "start": start, "end": end})
        index += len(group)
    return chunks


def _active_chunk(line: ScriptLine, t: float) -> dict[str, Any] | None:
    chunks = _caption_chunks(line)
    if not chunks:
        return None
    for chunk in chunks:
        if chunk["start"] <= t < chunk["end"]:
            return chunk
    return chunks[0] if t < chunks[0]["start"] else chunks[-1]


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    line: ScriptLine,
    t: float,
    c: dict[str, str],
) -> tuple[float, float, float, float] | None:
    if t < line.start - 0.05:
        return None
    chunk = _active_chunk(line, t)
    if not chunk:
        return None
    words: list[WordTiming] = chunk["words"]
    text = " ".join(word.text for word in words)
    pad_x, pad_y = 34, 22
    # The capsule has to fit the same safe width as everything else, with 8 px of clearance so its outline is
    # not drawn on the boundary. It used to be sized against a fixed 930 px of type, which put the capsule
    # outside the safe margin on long lines; then against `textlength(text)`, which is not the width that gets
    # drawn - the drawn width is the sum of the word advances plus the spaces, and the two differ by enough to
    # leave 8 px of overflow on a caption with many words. So the loop measures what it is about to draw.
    available = LAYOUT_HALF_WIDTH - 2 * pad_x - 8
    size = 78
    while True:
        font = _font(TITLE_FONT, size)
        space = draw.textlength(" ", font=font)
        widths = [draw.textlength(word.text, font=font) for word in words]
        total = sum(widths) + space * max(0, len(words) - 1)
        if total <= available or size <= 44:
            break
        size -= 4
    x = (WIDTH - total) / 2
    y = 1480
    capsule = (x - pad_x, y - pad_y, x + total + pad_x, y + size + pad_y + 12)
    draw.rounded_rectangle(
        capsule,
        radius=26,
        fill=_mix(c["bg"], "#000000", 0.72),
        outline=_mix(c["bg"], c["accent"], 0.4),
        width=2,
    )
    highlight = line.highlight.lower().strip(".,!?;:")
    longest = max(words, key=lambda word: len(word.text)).text.lower().strip(".,!?;:")
    target = highlight or longest
    for word, width in zip(words, widths):
        clean = word.text.lower().strip(".,!?;:")
        fill = c["accent"] if clean == target or clean == longest else c["text"]
        draw.text((x, y), word.text, font=font, fill=fill)
        x += width + space
    return tuple(round(value, 2) for value in capsule)


# The visual plate. The legacy card reserved 720x550 for a drawn motif; a diagram with labels needs
# real estate, so the plate now spans 912 px - the safe width divided by the maximum camera push-in -
# and stops above the caption band. Everything else about the card (brand row, headline, captions,
# progress) is byte-for-byte the same code, because typography and safe areas were already right.
VISUAL_PLATE = {"left": 84, "top": 716, "right": 996, "bottom": 1330}
VISUAL_PLATE_SIZE = (VISUAL_PLATE["right"] - VISUAL_PLATE["left"],
                     VISUAL_PLATE["bottom"] - VISUAL_PLATE["top"])
VISUAL_ENTER_S = 0.30        # rise + fade at the start of a scene
VISUAL_PUSH_IN = 0.055       # how much the plate grows across one scene
VISUAL_PAN_PX = 14           # lateral drift at the end of a scene


def _draw_chrome(
    draw: ImageDraw.ImageDraw,
    line: ScriptLine,
    brand: tuple[str, str, str],
    c: dict[str, str],
    index: int,
    total: int,
) -> dict[str, Any]:
    """Brand row, counter and headline. Shared by both card renderers so they cannot drift apart."""

    accent = c["accent"]
    muted = c["muted"]
    small = _font(SMALL_FONT, 28)
    serif = _font(SERIF_FONT, 30)
    kicker_y = 138
    _letter_spaced(draw, brand[0], small, 112, kicker_y, c["text"], 3)
    draw.text((112, kicker_y + 42), brand[1], font=serif, fill=accent)
    counter = f"{index + 1:02d} / {total:02d}"
    counter_width = draw.textlength(counter, font=small)
    draw.text((WIDTH - 70 - counter_width, kicker_y), counter, font=small, fill=muted)
    draw.rounded_rectangle((52, 130, 88, 166), radius=8, fill=accent)
    draw.rounded_rectangle((64, 142, 76, 154), radius=2, fill=c["bg"])

    headline = line.headline or line.caption or line.text[:40]
    font, lines = _fit_headline(draw, headline, int(LAYOUT_HALF_WIDTH) - 13, 3)
    y = 250
    drawn = []
    for text in lines:
        box = draw.textbbox((0, 0), text, font=font)
        x = (WIDTH - (box[2] - box[0])) / 2
        draw.text((x + 3, y + 3), text, font=font, fill=_mix(c["bg"], "#000000", 0.65))
        draw.text((x, y), text, font=font, fill=c["text"])
        drawn.append((x, y, x + (box[2] - box[0]), y + (box[3] - box[1])))
        y += (box[3] - box[1]) + 10
    draw.rounded_rectangle((WIDTH / 2 - 60, y + 15, WIDTH / 2 + 60, y + 21), radius=3, fill=accent)
    headline_rect = (min(r[0] for r in drawn), min(r[1] for r in drawn),
                     max(r[2] for r in drawn), max(r[3] for r in drawn)) if drawn else None
    return {"headline": headline_rect}


def _draw_footer(draw: ImageDraw.ImageDraw, t: float, duration: float,
                 c: dict[str, str], brand: tuple[str, str, str]) -> None:
    handle = brand[2]
    hfont = _font(SMALL_FONT, 24)
    draw.text((70, 1772), handle, font=hfont, fill=c["muted"])
    progress = min(1.0, max(0.0, t / max(0.001, duration)))
    draw.rounded_rectangle((70, 1820, WIDTH - 70, 1828), radius=4, fill=_mix(c["bg"], c["muted"], 0.25))
    draw.rounded_rectangle((70, 1820, 70 + (WIDTH - 140) * progress, 1828), radius=4, fill=c["accent"])


def _draw_entrance(draw: ImageDraw.ImageDraw, local: float, c: dict[str, str]) -> None:
    if local >= 0.34:
        return
    alpha = 1.0 - local / 0.34
    # The entrance wipe sweeps down to the caption band and stops there. It used to run to the bottom of
    # the card, crossing the caption for the first frames of every line: measured as 6 collisions of 180
    # sampled frames on academic-cool-to-sleep, where the light palette makes the bar an obvious edge.
    y_line = int((CAPTION_BAND[0] - 24) * min(1.0, local / 0.34))
    draw.rectangle((0, max(0, y_line - 8), WIDTH, y_line + 8), fill=_mix(c["bg"], c["accent"], 0.45 * alpha))
    radius = 80 * (1 + local)
    draw.ellipse(
        (WIDTH / 2 - radius, 980 - radius, WIDTH / 2 + radius, 980 + radius),
        outline=_mix(c["bg"], c["accent2"], max(0.0, min(1.0, alpha))),
        width=3,
    )


def _draw_scene(
    frame: Image.Image,
    line: ScriptLine,
    t: float,
    duration: float,
    index: int,
    total: int,
    spec: ChannelSpec,
    brand: tuple[str, str, str],
) -> None:
    c = spec.colors
    draw = ImageDraw.Draw(frame)
    local = max(0.0, t - line.start)

    drawn = _draw_chrome(draw, line, brand, c, index, total)
    _draw_motif(draw, line.visual or "network", t, c, 1.0 if local > 0 else 0.0)
    if local > 0.0:
        # After the motif: the motif plate is opaque, so a ring drawn first is painted over. It was, and the
        # measurement showed it - 0.28 grey levels of change where a rotating 36-segment ring should be
        # obvious. The overlay is thin and stays inside the empty band around the motif.
        _draw_motion_ring(draw, t, c)

    drawn["caption"] = _draw_caption(draw, line, t, c)
    _draw_footer(draw, t, duration, c, brand)
    _draw_entrance(draw, local, c)
    return drawn


def _plate_image(image: "Image.Image", local: float, span: float) -> "Image.Image":
    """Push in slowly and drift sideways, cropped from supersampled source pixels.

    The plate is a still picture, and a held still measures as a freeze. Growing it by 5.5 % across a
    scene moves the edges by tens of pixels - well above the encoder's noise floor - while staying
    inside the plate's own margin, so nothing is cropped away from the composition.
    """

    progress = min(1.0, max(0.0, local / max(0.001, span)))
    zoom = 1.0 + VISUAL_PUSH_IN * progress
    width, height = image.size
    scaled_w, scaled_h = int(width * zoom), int(height * zoom)
    scaled = image.resize((scaled_w, scaled_h), Image.BILINEAR)
    offset_x = int((scaled_w - width) / 2 + VISUAL_PAN_PX * (progress - 0.5) * 0.5)
    offset_y = int((scaled_h - height) / 2)
    return scaled.crop((offset_x, offset_y, offset_x + width, offset_y + height))


def _paste_visual(
    frame: "Image.Image",
    image: "Image.Image",
    local: float,
    span: float,
    c: dict[str, str],
) -> tuple[float, float, float, float]:
    """Composite the scene's visual into the plate, with an entrance rise and fade.

    Returns the rectangle the plate occupies, which the framing report measures against the safe area.
    """

    left, top = VISUAL_PLATE["left"], VISUAL_PLATE["top"]
    width, height = VISUAL_PLATE_SIZE
    plate = _plate_image(image, local, span).resize((width, height), Image.BILINEAR)

    if local < VISUAL_ENTER_S:
        alpha = local / VISUAL_ENTER_S
        rise = int(16 * (1.0 - alpha))
        backdrop = Image.new("RGB", (width, height), _rgb(_mix(c["bg"], c["panel"], 0.6)))
        plate = Image.blend(backdrop, plate, max(0.0, min(1.0, alpha)) ** 0.7)
        top = top + rise

    frame.paste(plate, (left, top))
    if local < VISUAL_ENTER_S:
        # A short accent rule marks the cut, so a scene change reads as a deliberate transition.
        draw = ImageDraw.Draw(frame)
        draw.rectangle((left, top - 3, left + int(width * min(1.0, local / VISUAL_ENTER_S)), top),
                       fill=c["accent"])
    return (float(left), float(top), float(left + width), float(top + height))


def _draw_scene_planned(
    frame: Image.Image,
    line: ScriptLine,
    image: "Image.Image | None",
    local: float,
    span: float,
    t: float,
    duration: float,
    index: int,
    total: int,
    spec: ChannelSpec,
    brand: tuple[str, str, str],
) -> dict[str, Any]:
    """The planned card: same chrome and captions, the visual plate where the motif used to be."""

    c = spec.colors
    draw = ImageDraw.Draw(frame)
    drawn = _draw_chrome(draw, line, brand, c, index, total)
    if image is not None:
        drawn["visual"] = _paste_visual(frame, image, local, span, c)
    else:
        # No visual resolved: draw nothing rather than a placeholder that pretends to be one. The
        # creative report counts it as uncovered.
        drawn["visual"] = None
    drawn["caption"] = _draw_caption(draw, line, t, c)
    _draw_footer(draw, t, duration, c, brand)
    _draw_entrance(draw, local, c)
    return drawn


def plate_fingerprint(image: Any) -> str:
    """A 16x16 greyscale fingerprint of a rendered plate.

    v1.0 measured visual diversity by counting distinct spec hashes, which is a statement about
    identifiers rather than about pictures. Two specs that happen to draw near-identical plates counted
    as two visuals. This is the picture itself, at a size where a phrase-length difference does not
    change the result but a different drawing does.
    """

    return compared_fingerprint(image)


def compared_fingerprint(image: Any) -> str | None:
    from PIL import Image as _Image

    if image is None:
        return None

    small = image.convert("L").resize((16, 16), _Image.BILINEAR)
    return hashlib.sha256(small.tobytes()).hexdigest()[:16]


def fingerprint_distance(first: str, second: str) -> int:
    """Hamming distance between two fingerprints, on the 64-bit prefix of the hash."""

    try:
        return bin(int(first[:16], 16) ^ int(second[:16], 16)).count("1")
    except (TypeError, ValueError):
        return 64


class VisualDispatcher:
    """Scene plan -> resolved visuals, held for the length of one render.

    Built once per video: planning and drawing nine diagrams costs a couple of seconds, and doing it
    per frame would dominate the encode. It is the only object the frame loop needs, and it reports
    what each scene actually got so the report can distinguish a diagram from a placeholder.
    """

    def __init__(self, plans: Any, resolutions: list[Any], spec: ChannelSpec,
                 lines: list[ScriptLine] | None = None) -> None:
        self.plans = plans
        self.spec = spec
        self.lines = list(lines or [])
        self.resolutions = {resolution.scene_id: resolution for resolution in resolutions}

    @classmethod
    def build(
        cls,
        script: Script,
        spec: ChannelSpec,
        lines: list[ScriptLine],
        *,
        cache_root: Path | str | None = None,
    ) -> "VisualDispatcher":
        from dataclasses import replace as _replace

        from ..content.scene_plan import plan_scenes
        from .assets.resolver import AssetResolver

        policy = getattr(spec, "visual_policy", None) or {}
        # Plan against the *timed* lines. `script.json` carries the prose with zeroed timings, and
        # planning on it produced a zero-length narration and an empty plan that looked successful.
        plans = plan_scenes(
            spec, _replace(script, lines=list(lines)),
            min_scene_ms=int(policy.get("min_scene_ms") or 2000),
            max_scene_ms=int(policy.get("max_scene_ms") or 8000),
        )
        resolver = AssetResolver(cache_root=cache_root) if cache_root else AssetResolver()
        resolutions = []
        images: dict[str, Any] = {}
        previous_variant: tuple[str, ...] = ()
        for scene in plans.scenes:
            resolution = resolver.resolve(scene, channel=spec.slug, colors=spec.colors,
                                          avoid=previous_variant)
            previous_variant = ((resolution.variant,) if resolution.variant
                                and resolution.variant != "cta" else ())
            resolution.scene_id = scene.scene_id
            scene.coverage_category = resolution.category  # what was drawn, not what was planned
            scene.asset_id = resolution.asset_id
            scene.asset_source = resolution.kind
            scene.license = resolution.record.license if resolution.record else None
            scene.attribution_text = resolution.record.attribution_text if resolution.record else None
            resolutions.append(resolution)
            plate = resolution.image()
            images[scene.scene_id] = plate
            if plate is not None:
                resolution.plate_fingerprint = plate_fingerprint(plate)
        dispatcher = cls(plans, resolutions, spec, lines=lines)
        dispatcher.images = images
        return dispatcher

    # -- lookup ---------------------------------------------------------------
    def at(self, t: float) -> Any:
        return self.plans.at(t) or self.plans.scenes[0]

    def image_for(self, scene: Any) -> Any:
        return getattr(self, "images", {}).get(getattr(scene, "scene_id", ""))

    def coverage(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for scene in self.plans.scenes:
            key = scene.coverage_category or "unresolved"
            counts[key] = counts.get(key, 0) + 1
        return {
            "scenes": len(self.plans.scenes),
            "by_category": counts,
            "styles": sorted({scene.asset_id for scene in self.plans.scenes if scene.asset_id}),
        }

    def line_agreement(self) -> dict[str, Any] | None:
        """Which line the headline comes from, at each scene's midpoint, versus the scene's own line.

        This is the evidence for the defect that shipped: during an inter-line pause the card used to
        show the *last* line's headline and counter while the plate showed the current scene. Measured
        with the same function the renderer uses, so it cannot drift from the drawing.
        """

        if not self.lines:
            return None
        mismatches: list[str] = []
        for scene in self.plans.scenes:
            derived = scene.derived_from or {}
            expected = {str(index) for index in (derived.get("lines") or [derived.get("line_index")])}
            moment = (scene.start_ms + scene.end_ms) / 2000.0
            _, index = _active_line(self.lines, moment)
            if expected and str(index) not in expected:
                mismatches.append(scene.scene_id)
        return {"checked": len(self.plans.scenes), "mismatches": mismatches,
                "method": "active-line index at each scene midpoint, from the renderer's own function"}

    def report(self) -> dict[str, Any]:
        from ..content.scene_plan import scene_plan_problems

        return {
            "schema": "scene-plan/1",
            "channel": self.spec.slug,
            "narration_ms": self.plans.narration_ms,
            "allowed_scene_count": list(self.plans.allowed_scene_count),
            "min_scene_ms": self.plans.min_scene_ms,
            "max_scene_ms": self.plans.max_scene_ms,
            "problems": scene_plan_problems(self.plans),
            "coverage": self.coverage(),
            "decisions": self.plans.decisions,
            "line_agreement": self.line_agreement(),
            "scenes": [dict(scene.to_dict(),
                            resolution=self.resolutions.get(scene.scene_id).to_dict()
                            if self.resolutions.get(scene.scene_id) else None)
                       for scene in self.plans.scenes],
        }


# The card is a composition, not a photograph: the motif for several kinds (chip, robot, shield,
# sandbox, screen) is entirely still, and the only thing that changed between frames was a 8 px
# progress bar, which is below `freezedetect`'s noise tolerance. A card held for one narration line
# therefore measured as a 1.5-2.2 s freeze. The fix is a slow, continuous camera drift over the whole
# card: constant velocity, no reset, no cut, so a line boundary never produces a pop.
DRIFT_PER_SECOND = 0.0030   # ~5.8 px/s at 1080 wide: above freezedetect's -50 dB floor on a flat card
DRIFT_MAX = 0.060           # never more than a 6 % push-in
RING_RATE = 0.55            # radians per second, the accent ring's rotation


def camera_scale(t: float) -> float:
    """Deterministic push-in for a time in seconds: linear, so it never stalls, then held at the cap.

    An earlier version added a sine "breath" on top of the ramp. That was worse than useless: wherever the
    breath's derivative cancelled the ramp the picture stopped moving for a few frames, which is exactly
    what `freezedetect` measures - academic-biohacker froze at 3.4 s because of it.
    """

    t = max(0.0, float(t))
    return 1.0 + min(DRIFT_MAX, DRIFT_PER_SECOND * t)


def _draw_motion_ring(draw: ImageDraw.ImageDraw, t: float, c: dict[str, str]) -> None:
    """A slow accent ring around the motif: real content motion that survives any duration.

    The push-in alone is a camera move, and once it reaches its cap a long card would be still again. This
    ring rotates for as long as the video runs, sits behind the motif in a band that holds no type, and
    keeps the composition and the safe margins exactly where they were.
    """

    cx, cy = 540, 980
    accent = c["accent"]
    accent2 = c["accent2"]
    faint = _mix(c["bg"], c["muted"], 0.55)
    # Two counter-rotating rings: one ring at this width moved the frame by 0.45 grey levels a second, which
    # is still inside freezedetect's tolerance on a flat card. Counter-rotation doubles the churn without
    # making the card any busier to read.
    for radius, rate, width in ((342, RING_RATE, 2.0), (296, -RING_RATE * 1.6, 1.0)):
        phase = t * rate
        for index in range(24):
            start = math.degrees(phase + index * 15)
            draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + 8.0,
                     fill=accent2 if index % 4 == 0 else faint, width=int(3 * width) or 3)
    outer = 366
    for index in range(6):
        angle = t * RING_RATE * 1.9 + index * (math.pi / 3)
        x = cx + math.cos(angle) * outer
        y = cy + math.sin(angle) * outer
        _dot(draw, x, y, 6 + (index % 3) * 3, accent if index % 2 == 0 else accent2)


def apply_camera_drift(frame: "Image.Image", t: float) -> None:
    """Push the finished card in by :func:`camera_scale`. In place, so the encode loop copies nothing."""

    scale = camera_scale(t)
    if abs(scale - 1.0) < 1e-6:
        return
    width, height = frame.size
    inner = frame.resize((int(width * scale + 0.5), int(height * scale + 0.5)), Image.BILINEAR)
    left = (inner.width - width) // 2
    top = (inner.height - height) // 2
    frame.paste(inner.crop((left, top, left + width, top + height)), (0, 0))


# Composition evidence. The publishing gate requires `framing.json` for every channel and refused an
# English video with "framing.json missing: composition unverified". Writing a report with zeroes would be
# worse than writing nothing, so these boxes are measured from the frames that were actually encoded.
SAFE_AREA = {"left": 56, "right": WIDTH - 56, "top": 150, "bottom": HEIGHT - 150}
# The camera pushes in by up to DRIFT_MAX, which moves everything further from the centre by that factor. Text
# laid out to the safe width and then pushed in lands outside it: a full-width caption measured 29 frames of
# overflow for exactly this reason. So the layout target is the safe area *divided by the maximum push-in*, and
# the framing report measures the pushed-in result against the real safe area.
DRIFT_MAX_SCALE = 1.0 + 0.060
LAYOUT_HALF_WIDTH = (SAFE_AREA["right"] - SAFE_AREA["left"]) / DRIFT_MAX_SCALE
HEADLINE_BAND = (232, 720)      # below the brand row (ends ~215) and above the motif plate
CAPTION_BAND = (1430, 1680)     # the caption capsule is drawn at y=1480
FRAMING_SAMPLE_STRIDE = 6       # every sixth frame is measured; a card does not change fast
INK_THRESHOLD = 60               # local gradient that counts as ink, for the sanity check only


def _scale_rect(box: tuple[float, float, float, float] | None, scale: float) -> tuple[float, float, float, float] | None:
    """Map a rectangle through the camera push-in, which is a centre crop about the frame centre.

    Without this the report would describe the composition before the camera moved it, and 6 % of drift is
    32 px at the frame edge - more than the clearance a caption has.
    """

    if box is None:
        return None
    cx, cy = WIDTH / 2.0, HEIGHT / 2.0
    left, top, right, bottom = box
    return ((left - cx) * scale + cx, (top - cy) * scale + cy,
            (right - cx) * scale + cx, (bottom - cy) * scale + cy)


def _overflow(box: tuple[float, float, float, float] | None) -> int:
    """How far a rectangle leaves the safe area, in pixels. Zero means it is inside."""

    if box is None:
        return 0
    left, top, right, bottom = box
    return int(max(0, SAFE_AREA["left"] - left, right - SAFE_AREA["right"],
                   SAFE_AREA["top"] - top, bottom - SAFE_AREA["bottom"]))


def _has_ink(frame: "Image.Image", box: tuple[float, float, float, float]) -> bool:
    """Is there actually something drawn inside this rectangle?

    The framing report is built from the rectangles the draw calls returned, which is exact but would also be
    exact if a call reported a rectangle it never painted. This reads the encoded frame and requires an edge
    inside the box, so a report cannot outrun the picture.
    """

    left, top, right, bottom = (int(max(0, box[0])), int(max(0, box[1])),
                                int(min(WIDTH, box[2])), int(min(HEIGHT, box[3])))
    if right - left < 2 or bottom - top < 2:
        return False
    luma = np.asarray(frame.convert("L"), dtype=np.uint8)[top:bottom, left:right].astype(np.int16)
    gradient = np.abs(np.diff(luma, axis=1)).sum() + np.abs(np.diff(luma, axis=0)).sum()
    return bool(gradient > INK_THRESHOLD)


def measure_geometry(geometry: dict[str, Any], frame: "Image.Image") -> dict[str, Any]:
    """One frame's framing evidence, from the rectangles the renderer drew on that frame."""

    headline = geometry.get("headline")
    caption = geometry.get("caption")
    collision = False
    if headline and caption:
        collision = not (caption[2] < headline[0] or caption[0] > headline[2]
                         or caption[3] < headline[1] or caption[1] > headline[3])
    visual = geometry.get("visual")
    visual_caption_collision = False
    if visual and caption:
        visual_caption_collision = not (caption[2] < visual[0] or caption[0] > visual[2]
                                        or caption[3] < visual[1] or caption[1] > visual[3])
    return {
        "headline": list(headline) if headline else None,
        "caption": list(caption) if caption else None,
        "visual": list(visual) if visual else None,
        "headline_overflow": _overflow(headline),
        "caption_overflow": _overflow(caption),
        "visual_overflow": _overflow(visual),
        "collision": collision,
        "visual_caption_collision": visual_caption_collision,
        "headline_painted": _has_ink(frame, headline) if headline else False,
        "caption_painted": _has_ink(frame, caption) if caption else False,
        "visual_painted": _has_ink(frame, visual) if visual else False,
    }


def compose_frame(
    base: "Image.Image",
    lines: list[ScriptLine],
    t: float,
    duration: float,
    spec: ChannelSpec,
    brand: tuple[str, str, str],
    geometry: dict[str, Any] | None = None,
    dispatcher: "VisualDispatcher | None" = None,
) -> "Image.Image":
    """One finished frame. The encode loop and the tests call this, so they measure the same pixels.

    `geometry` is an out-parameter: when given, it receives the rectangles that were drawn on this frame, which
    is what the framing report is built from. It is filled before the camera and light passes, so the numbers
    describe the layout the frame was composed with.
    """

    line, line_index = _active_line(lines, t)
    frame = base.convert("RGB")
    if dispatcher is None:
        drawn = _draw_scene(frame, line, t, duration, line_index, len(lines), spec, brand)
    else:
        scene = dispatcher.at(t)
        drawn = _draw_scene_planned(
            frame, line, dispatcher.image_for(scene),
            max(0.0, t - scene.start_ms / 1000.0), scene.duration_ms / 1000.0,
            t, duration, line_index, len(lines), spec, brand,
        )
    apply_camera_drift(frame, t)
    apply_light_sweep(frame, t, spec.colors["accent"])
    if geometry is not None:
        scale = camera_scale(t)
        geometry.update({name: _scale_rect(box, scale) for name, box in (drawn or {}).items()})
    return frame


SWEEP_PERIOD = 6.5          # seconds for one pass
SWEEP_PEAK = 0.13           # how much of the accent colour the band mixes in at its centre
SWEEP_WIDTH = 0.16          # band half-width as a fraction of the card


def _sweep_band(phase: float) -> "np.ndarray":
    """A soft vertical band of accent light, one column weight per x. Cached per phase step."""

    key = int(round(phase * 128)) % 128
    cached = _SWEEP_CACHE.get(key)
    if cached is not None:
        return cached
    # Two passes half a period apart, max-combined: a single pass fades to nothing at the wrap point, and the
    # measurement showed the picture going quiet there (0.28 grey levels a second). Two of them always leave
    # one band on the card, so the light never switches off.
    columns = np.arange(WIDTH) / WIDTH
    band = None
    for phase_offset in (0.0, 0.5):
        shifted = (key / 128.0 + phase_offset) % 1.0
        centre = -0.35 + 1.7 * shifted
        offset = (columns - centre) / SWEEP_WIDTH
        envelope = 0.25 + 0.75 * math.sin(math.pi * shifted) ** 0.7
        current = np.exp(-offset * offset) * envelope * SWEEP_PEAK
        band = current if band is None else np.maximum(band, current)
    band = band.astype(np.float32)
    _SWEEP_CACHE[key] = band
    return band


def apply_light_sweep(frame: "Image.Image", t: float, accent: str) -> None:
    """Move a band of light across the card.

    The push-in is the primary motion, but it reaches its cap on a long video, and a rotating ring touches
    too few pixels: `freezedetect` compares whole frames, so 20 000 changed pixels out of 2 073 600 still
    measured as a freeze at -50 dB. A broad, slow sweep is a real motion-graphics element - the same "shine"
    pass used in title design - and it keeps a large area of the card moving for as long as the video runs.

    The blend is done by PIL as a masked paste of one flat colour, not by numpy arithmetic on the frame:
    the first version did the arithmetic and cost 60 ms a frame, most of it copying 6 MB three times.
    """

    band = _sweep_band((t % SWEEP_PERIOD) / SWEEP_PERIOD)
    if not band.any():
        return
    mask = Image.fromarray(np.broadcast_to((band * 89.0).astype(np.uint8)[None, :],
                                           (frame.height, frame.width)).copy(), "L")
    frame.paste(accent, (0, 0), mask)


_SWEEP_CACHE: dict[int, "np.ndarray"] = {}

def _active_line(lines: list[ScriptLine], t: float) -> tuple[ScriptLine, int]:
    """The line being spoken, or the last one that was.

    A timeline has real silences between lines (the TTS pause, ~180 ms here). Returning the *final*
    line for those gaps made the card flash the last headline and "07 / 07" mid-video - measured on the
    encoded baseline as six windows of 180 ms, about 2.8 % of the runtime, with the plate and caption
    still showing the current scene. A gap belongs to the line that just finished; only after the last
    line ends does the last line remain correct.
    """

    if not lines:
        raise ValueError("timeline is empty")
    if t <= lines[0].start:
        return lines[0], 0
    for index, line in enumerate(lines):
        if line.start <= t < line.end:
            return line, index
    previous = 0
    for index, line in enumerate(lines):
        if line.start <= t:
            previous = index
    return lines[previous], previous


def render_english(
    script: Script,
    narration: Narration,
    spec: ChannelSpec,
    output_path: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_file() and not force:
        raise FileExistsError(f"output already exists: {output_path}")

    lines = narration.lines or script.lines
    if not lines:
        raise ValueError("no narration timeline")
    duration = max(narration.duration, max(line.end for line in lines) + 0.45)

    work_dir = output_path.parent / f"{output_path.stem}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    bed_path = work_dir / "bed.wav"
    mixed_audio = work_dir / "mixed.m4a"
    make_bed(duration, spec.palette, [line.start for line in lines[1:]], bed_path)
    mix_narration(narration.audio_path, bed_path, mixed_audio, duration)

    brand = BRAND.get(spec.slug, (spec.display_name.upper(), "BRIEF", spec.handle))
    base = _base_image(spec)

    # Scene planning is opt-in per channel. A channel that has not been validated for the new visual
    # layer renders exactly as it did before, which is what "compatibility, not deployment" means.
    policy = getattr(spec, "visual_policy", None) or {}
    dispatcher: VisualDispatcher | None = None
    if policy.get("scene_planning"):
        from dataclasses import replace as _replace

        plan_script = _replace(script, lines=lines)
        dispatcher = VisualDispatcher.build(
            plan_script, spec, lines, cache_root=policy.get("cache_root") or None)
        # Audio-visual sync is a property, not an intention: the plan must span exactly the narration it
        # was planned from (the plan's clock starts at the first spoken word, not at zero), and no scene
        # may run past the video. Measured as a span, because comparing an absolute end time against a
        # duration shifted by the opening pause and failed a plan that was in fact exact to the millisecond.
        scenes = dispatcher.plans.scenes
        span_ms = scenes[-1].end_ms - scenes[0].start_ms
        first_ms = scenes[0].start_ms
        drift = [scene.scene_id for scene in scenes
                 if scene.end_ms > int(round(duration * 1000)) + 40
                 or scene.start_ms < -1
                 or scene.duration_ms <= 0]
        if abs(span_ms - dispatcher.plans.narration_ms) > 40 or first_ms < 0:
            drift.append(f"plan spans {span_ms} ms, narration is {dispatcher.plans.narration_ms} ms")
        if drift:
            raise RuntimeError(f"scene plan is not synchronised with the narration: {drift}")
    total_frames = max(1, int(math.ceil(duration * FPS)))
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-i",
        str(mixed_audio),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        # Copy, do not re-encode. `mix_narration` measures the true peak of the AAC file it wrote and
        # tightens its limiter until that file passes the -1.0 dBTP gate; encoding it a second time added
        # inter-sample overshoot after the measurement, so an episode could pass the guard and still
        # arrive at QC at -0.23 dBTP. Copying makes the measured file the delivered file.
        "-c:a",
        "copy",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    samples: list[dict[str, Any]] = []
    try:
        for frame_index in range(total_frames):
            t = frame_index / FPS
            geometry: dict[str, Any] = {}
            frame = compose_frame(base, lines, t, duration, spec, brand,
                                 geometry=geometry, dispatcher=dispatcher)
            if frame_index % FRAMING_SAMPLE_STRIDE == 0:
                sample = measure_geometry(geometry, frame)
                sample["t"] = round(t, 3)
                samples.append(sample)
            process.stdin.write(frame.convert("RGB").tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait(timeout=180)
        if return_code != 0:
            raise RuntimeError(f"ffmpeg video encode failed: {stderr[-3000:]}")
    except Exception:
        process.kill()
        raise

    streams = ffprobe_streams(output_path)
    payload = {
        "video_path": str(output_path),
        "duration": round(duration, 3),
        "size": output_path.stat().st_size,
        "streams": [
            {"codec_type": s.get("codec_type"), "codec_name": s.get("codec_name"), "width": s.get("width"), "height": s.get("height")}
            for s in streams.get("streams", [])
        ],
        "rendered_at": iso_now(),
    }
    if dispatcher is not None:
        plan_report = dispatcher.report()
        plan_report["plan_id"] = script.metadata.get("plan_id")
        (output_path.parent / "scenes.json").write_text(
            json.dumps(plan_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["scene_plan"] = {
            "scenes": plan_report["scenes"] and len(plan_report["scenes"]),
            "allowed_scene_count": plan_report["allowed_scene_count"],
            "coverage": plan_report["coverage"],
            "problems": plan_report["problems"],
            "report": "scenes.json",
        }
    (output_path.parent / "render.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "timeline.json").write_text(json.dumps(narration.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    headline_bad = [s for s in samples if s["headline_overflow"] > 0]
    caption_bad = [s for s in samples
                   if s["caption_overflow"] > 0 or s["collision"]
                   or s.get("visual_caption_collision")]
    missing_headline = [s for s in samples if s["headline"] is None]
    framing = {
        "schema": "framing/1",
        "channel": spec.slug,
        "plan_id": script.metadata.get("plan_id"),
        "engine": "shorts",
        "measured": True,
        "method": "rectangles returned by the draw calls, per sampled frame, cross-checked for ink",
        "safe_area": SAFE_AREA,
        "sample_stride": FRAMING_SAMPLE_STRIDE,
        "frames_sampled": len(samples),
        "cropped_required_frames": len(headline_bad) + len(missing_headline),
        "subtitle_collision_frames": len(caption_bad),
        "elements": {
            "headline": {
                "band": list(HEADLINE_BAND),
                "painted_frames": len([s for s in samples if s["headline_painted"]]),
                "missing_frames": len(missing_headline),
                "max_overflow_px": max((s["headline_overflow"] for s in samples), default=0),
            },
            "caption": {
                "band": list(CAPTION_BAND),
                "painted_frames": len([s for s in samples if s["caption_painted"]]),
                "max_overflow_px": max((s["caption_overflow"] for s in samples), default=0),
                "collisions": len([s for s in samples if s["collision"]]),
            },
        },
        "samples": samples[:120],
    }
    if dispatcher is not None:
        # A legacy card has no plate. Reporting a zero-valued element for it reads as "measured and
        # passed" for something that does not exist, so the element is present only when it was drawn.
        framing["elements"]["visual"] = {
            "band": [VISUAL_PLATE["left"], VISUAL_PLATE["top"],
                     VISUAL_PLATE["right"], VISUAL_PLATE["bottom"]],
            "painted_frames": len([s for s in samples if s.get("visual_painted")]),
            "measured_frames": len([s for s in samples if s.get("visual")]),
            "max_overflow_px": max((s.get("visual_overflow") or 0 for s in samples), default=0),
            "caption_collisions": len([s for s in samples if s.get("visual_caption_collision")]),
        }
    (output_path.parent / "framing.json").write_text(
        json.dumps(framing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    scenes = []
    if dispatcher is not None:
        # The scene plan is the story: what is on screen, when, and where the picture came from.
        for scene in dispatcher.plans.scenes:
            resolution = dispatcher.resolutions.get(scene.scene_id)
            scenes.append({
                "index": int(scene.scene_id.lstrip("s") or 0),
                "scene_id": scene.scene_id,
                "headline": scene.main_concept,
                "text": scene.narration_text,
                "start": round(scene.start_ms / 1000.0, 3),
                "end": round(scene.end_ms / 1000.0, 3),
                "visual": resolution.variant if resolution else None,
                "category_planned": scene.visual_category,
                "category_rendered": scene.coverage_category,
                "asset_id": scene.asset_id,
                "asset_source": scene.asset_source,
                "license": scene.license,
                "attribution": scene.attribution_text,
                "motion": resolution.motion if resolution else None,
                "derived_from": scene.derived_from,
                "assets": {
                    "path": resolution.path if resolution else None,
                    "palette": spec.palette,
                    "base": "generated/diagram" if resolution and resolution.kind == "generated"
                            else (resolution.kind if resolution else "none"),
                },
            })
    else:
        for index, line in enumerate(lines):
            scenes.append({
                "index": index + 1,
                "headline": line.headline,
                "text": line.text,
                "start": round(line.start, 3),
                "end": round(line.end, 3),
                "visual": line.visual or "network",
                "sfx": line.sfx,
                "assets": {"motif": line.visual or "network", "palette": spec.palette,
                           "base": "generated/card-plate"},
            })
    story = {
        "schema": "story/1",
        "story_id": getattr(script, "story_id", None) or script.metadata.get("story_id"),
        "channel": spec.slug,
        "plan_id": script.metadata.get("plan_id"),
        "title": script.title,
        "format": spec.format,
        "language": spec.language,
        "engine": "shorts",
        "created_at": iso_now(),
        "scene_count": len(scenes),
        "scenes": scenes,
        "provenance": {
            "visuals": ("scene-planned diagrams generated in-process; no stock photography, no "
                        "third-party media" if dispatcher is not None
                        else "generated in-process from primitives; no stock photography, no third-party media"),
            "fonts": [p.name for p in (TITLE_FONT, SERIF_FONT, SMALL_FONT)],
            "music": "synthesised bed (factory.media.music)",
            "narration": "TTS provider declared in script.json",
        },
    }
    (output_path.parent / "story.json").write_text(
        json.dumps(story, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if dispatcher is not None:
        from ..qa.creative import evaluate, load_thresholds

        creative = evaluate(
            channel=spec.slug,
            scene_plan=json.loads((output_path.parent / "scenes.json").read_text(encoding="utf-8")),
            framing=framing,
            thresholds=load_thresholds((policy or {}).get("creative_thresholds") or None),
        )
        creative.write(output_path.parent / "creative.json")
        payload["creative"] = {
            "ok": creative.ok,
            "failures": creative.failures,
            "warnings": creative.warnings,
            "metrics": creative.metrics,
            "report": "creative.json",
        }
    return payload
