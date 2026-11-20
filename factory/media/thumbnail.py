"""YouTube thumbnail generation for both English and Devanagari episodes."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..config import FONTS_DIR, ChannelSpec
from ..content.models import Script
from ..util import ffprobe_duration, run
from .hindi_text import render_thumbnail_overlay

WIDTH = 1280
HEIGHT = 720
TITLE_FONT = FONTS_DIR / "Inter-Black.otf"
SMALL_FONT = FONTS_DIR / "Inter-ExtraBold.otf"
ACCENT_FONT = FONTS_DIR / "Caladea-Bold.ttf"


def thumbnail_path(out_dir: Path | str) -> Path:
    return Path(out_dir) / "thumbnail.jpg"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int = 820,
    max_lines: int = 3,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in (100, 94, 88, 82, 76, 70, 64, 58):
        font = ImageFont.truetype(str(TITLE_FONT), size)
        lines = _wrap(draw, text.upper(), font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = ImageFont.truetype(str(TITLE_FONT), 54)
    return font, _wrap(draw, text.upper(), font, max_width)[:max_lines]


def _extract_frame(video_path: Path, output_path: Path, at: float) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        timeout=60,
    )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f"could not extract thumbnail frame from {video_path}")


def _shade(image: Image.Image) -> Image.Image:
    array = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width = array.shape[:2]
    xx, yy = np.meshgrid(
        np.linspace(0.0, 1.0, width, dtype=np.float32),
        np.linspace(0.0, 1.0, height, dtype=np.float32),
    )
    left = np.clip(1.0 - xx / 0.78, 0.0, 1.0) ** 1.15
    top = np.clip(1.0 - yy / 0.58, 0.0, 1.0) ** 1.4
    alpha = np.clip(left * 195.0 + top * 105.0, 0.0, 226.0)
    shade = np.zeros((height, width, 4), dtype=np.uint8)
    shade[..., 3] = alpha.astype(np.uint8)
    overlay = Image.fromarray(shade, mode="RGBA")
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def _draw_english(base: Image.Image, script: Script, spec: ChannelSpec) -> Image.Image:
    canvas = base.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    accent = spec.colors["accent"]
    muted = "#D7E4F3"
    margin = 54
    handle_font = ImageFont.truetype(str(SMALL_FONT), 22)

    title_font, title_lines = _fit_title(draw, script.title)
    title_height = sum(
        draw.textbbox((0, 0), line, font=title_font)[3]
        - draw.textbbox((0, 0), line, font=title_font)[1]
        for line in title_lines
    ) + (len(title_lines) - 1) * 8
    tagline = script.hook[:150]
    tag_font = ImageFont.truetype(str(SMALL_FONT), 28)
    tag_lines = _wrap(draw, tagline, tag_font, 820)[:2]
    tag_height = 0
    if tag_lines:
        tag_height = len(tag_lines) * 38 + 18

    block_height = 36 + 16 + title_height + tag_height + 44
    y = HEIGHT - margin - block_height
    draw.rounded_rectangle(
        (margin, y, margin + 78, y + 10),
        radius=5,
        fill=accent,
    )
    kicker_font = ImageFont.truetype(str(SMALL_FONT), 24)
    draw.text(
        (margin + 94, y - 5),
        spec.display_name.upper(),
        font=kicker_font,
        fill=accent,
    )
    y += 38
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill="#FFFFFF")
        box = draw.textbbox((0, 0), line, font=title_font)
        y += (box[3] - box[1]) + 8
    if tag_lines:
        y += 10
        for line in tag_lines:
            draw.text((margin, y), line, font=tag_font, fill=muted)
            y += 38

    handle = spec.handle
    handle_box = draw.textbbox((0, 0), handle, font=handle_font)
    draw.rounded_rectangle(
        (
            WIDTH - margin - (handle_box[2] - handle_box[0]) - 28,
            HEIGHT - margin - 38,
            WIDTH - margin,
            HEIGHT - margin,
        ),
        radius=19,
        fill=(5, 10, 20, 150),
    )
    draw.text(
        (WIDTH - margin - (handle_box[2] - handle_box[0]) - 14, HEIGHT - margin - 33),
        handle,
        font=handle_font,
        fill="#E8F2FF",
    )
    return canvas


def _draw_hindi(
    base: Image.Image,
    script: Script,
    spec: ChannelSpec,
    work_dir: Path,
) -> Image.Image:
    canvas = base.convert("RGBA")
    kicker = f"नटखट टून्स • एपिसोड {script.episode:02d}" if script.episode else "नटखट टून्स"
    footer = script.series_title or "हवेली का रहस्य"
    overlay_file = work_dir / "thumbnail_text.png"
    render_thumbnail_overlay(
        script.title,
        overlay_file,
        fonts_dir=FONTS_DIR,
        kicker=kicker,
        footer=footer,
    )
    overlay = Image.open(overlay_file).convert("RGBA")
    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)
    handle_font = ImageFont.truetype(str(SMALL_FONT), 22)
    handle = spec.handle
    handle_box = draw.textbbox((0, 0), handle, font=handle_font)
    draw.rounded_rectangle(
        (
            WIDTH - 54 - (handle_box[2] - handle_box[0]) - 28,
            HEIGHT - 54 - 38,
            WIDTH - 54,
            HEIGHT - 54,
        ),
        radius=19,
        fill=(5, 10, 20, 150),
    )
    draw.text(
        (WIDTH - 54 - (handle_box[2] - handle_box[0]) - 14, HEIGHT - 54 - 33),
        handle,
        font=handle_font,
        fill="#FFF6E4",
    )
    return canvas


def make_thumbnail(
    spec: ChannelSpec,
    script: Script,
    video_path: Path | str,
    output_path: Path | str,
    *,
    frame_time: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    video_path = Path(video_path)
    output_path = Path(output_path)
    if output_path.is_file() and not force:
        return {
            "thumbnail_path": str(output_path),
            "skipped": True,
            "width": WIDTH,
            "height": HEIGHT,
        }
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    duration = ffprobe_duration(video_path)
    at = frame_time if frame_time is not None else max(0.1, duration * 0.42)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thumbnail_") as td:
        work_dir = Path(td)
        frame_path = work_dir / "frame.png"
        _extract_frame(video_path, frame_path, at)
        frame = Image.open(frame_path).convert("RGB")
        crop = ImageOps.fit(
            frame,
            (WIDTH, HEIGHT),
            method=Image.LANCZOS,
            centering=(0.5, 0.58 if spec.is_hindi else 0.48),
        )
        shaded = _shade(crop)
        if spec.is_hindi:
            canvas = _draw_hindi(shaded, script, spec, work_dir)
        else:
            canvas = _draw_english(shaded, script, spec)
        rgb = canvas.convert("RGB")
        for quality in (93, 89, 85, 80):
            rgb.save(output_path, "JPEG", quality=quality, optimize=True, progressive=True)
            if output_path.stat().st_size <= 2 * 1024 * 1024:
                break
    if output_path.stat().st_size > 2 * 1024 * 1024:
        raise RuntimeError(f"thumbnail exceeds YouTube's 2 MB limit: {output_path}")
    return {
        "thumbnail_path": str(output_path),
        "frame_time": round(at, 3),
        "width": WIDTH,
        "height": HEIGHT,
        "size_bytes": output_path.stat().st_size,
        "skipped": False,
    }
