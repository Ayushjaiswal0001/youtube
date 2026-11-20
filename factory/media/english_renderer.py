"""Premium 1080x1920 English motion-graphics renderer built on Pillow + ffmpeg."""

from __future__ import annotations

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
) -> None:
    if t < line.start - 0.05:
        return
    chunk = _active_chunk(line, t)
    if not chunk:
        return
    words: list[WordTiming] = chunk["words"]
    text = " ".join(word.text for word in words)
    size = 78
    font = _font(TITLE_FONT, size)
    while size > 52 and draw.textlength(text, font=font) > 930:
        size -= 4
        font = _font(TITLE_FONT, size)
    space = draw.textlength(" ", font=font)
    widths = [draw.textlength(word.text, font=font) for word in words]
    total = sum(widths) + space * max(0, len(words) - 1)
    x = (WIDTH - total) / 2
    y = 1480
    pad_x, pad_y = 34, 22
    draw.rounded_rectangle(
        (x - pad_x, y - pad_y, x + total + pad_x, y + size + pad_y + 12),
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
    accent = c["accent"]
    muted = c["muted"]
    local = max(0.0, t - line.start)

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
    font, lines = _fit_headline(draw, headline, 900, 3)
    y = 250
    for text in lines:
        box = draw.textbbox((0, 0), text, font=font)
        x = (WIDTH - (box[2] - box[0])) / 2
        draw.text((x + 3, y + 3), text, font=font, fill=_mix(c["bg"], "#000000", 0.65))
        draw.text((x, y), text, font=font, fill=c["text"])
        y += (box[3] - box[1]) + 10
    draw.rounded_rectangle((WIDTH / 2 - 60, y + 15, WIDTH / 2 + 60, y + 21), radius=3, fill=accent)

    _draw_motif(draw, line.visual or "network", t, c, 1.0 if local > 0 else 0.0)

    _draw_caption(draw, line, t, c)

    handle = brand[2]
    hfont = _font(SMALL_FONT, 24)
    draw.text((70, 1772), handle, font=hfont, fill=muted)
    progress = min(1.0, max(0.0, t / max(0.001, duration)))
    draw.rounded_rectangle((70, 1820, WIDTH - 70, 1828), radius=4, fill=_mix(c["bg"], c["muted"], 0.25))
    draw.rounded_rectangle((70, 1820, 70 + (WIDTH - 140) * progress, 1828), radius=4, fill=accent)

    if local < 0.34:
        alpha = 1.0 - local / 0.34
        y_line = int(HEIGHT * min(1.0, local / 0.34))
        draw.rectangle((0, max(0, y_line - 8), WIDTH, y_line + 8), fill=_mix(c["bg"], accent, 0.45 * alpha))
        radius = 80 * (1 + local)
        draw.ellipse(
            (WIDTH / 2 - radius, 980 - radius, WIDTH / 2 + radius, 980 + radius),
            outline=_mix(c["bg"], c["accent2"], max(0.0, min(1.0, alpha))),
            width=3,
        )


def _active_line(lines: list[ScriptLine], t: float) -> tuple[ScriptLine, int]:
    if not lines:
        raise ValueError("timeline is empty")
    if t <= lines[0].start:
        return lines[0], 0
    for index, line in enumerate(lines):
        if line.start <= t < line.end:
            return line, index
    return lines[-1], len(lines) - 1


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
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame_index in range(total_frames):
            t = frame_index / FPS
            line, line_index = _active_line(lines, t)
            frame = base.copy()
            _draw_scene(frame, line, t, duration, line_index, len(lines), spec, brand)
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
    (output_path.parent / "render.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "timeline.json").write_text(json.dumps(narration.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_path.parent / "script.json").write_text(json.dumps(script.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
