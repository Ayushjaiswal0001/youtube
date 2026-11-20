"""Subtitle Generator for Shorts/Reels.
Generates SRT, ASS, and frame overlay subtitles in Hindi Devanagari.
Supports automatic text wrapping to prevent overflow on 1080px vertical video.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple
import cairo
from studio.config import HINDI_FONT_NAME


def format_srt_time(seconds: float) -> str:
    """Formats float seconds into SRT timestamp HH:MM:SS,mmm."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def write_srt(subtitles: List[Dict[str, Any]], out_path: Path):
    """Writes standard SRT file."""
    with open(out_path, "w", encoding="utf-8") as f:
        for i, sub in enumerate(subtitles, 1):
            start = format_srt_time(sub["start"])
            end = format_srt_time(sub["end"])
            f.write(f"{i}\n{start} --> {end}\n{sub['text']}\n\n")


def _find_split_point(text: str) -> int:
    """Find the best split point near the middle of a Hindi text string.
    Prefers splitting at spaces, commas, or punctuation marks.
    """
    mid = len(text) // 2
    # Search outward from midpoint for a good break character
    best = -1
    best_dist = len(text)
    for i, ch in enumerate(text):
        if ch in (' ', ',', '।', '!', '?', ':', ';', '—', '-', '–'):
            dist = abs(i - mid)
            if dist < best_dist:
                best_dist = dist
                best = i
    if best > 0:
        return best + 1  # Split after the break character
    # No good split found — split at midpoint
    return mid


def _wrap_text_cairo(cr: cairo.Context, text: str, max_width: float,
                     max_lines: int = 3) -> List[str]:
    """Wraps Hindi text into multiple lines that fit within max_width.
    Uses Cairo text_extents for accurate measurement of Devanagari glyphs.
    Returns a list of line strings (1 to max_lines).
    """
    text = text.strip()
    if not text:
        return []

    # Check if single line fits
    ext = cr.text_extents(text)
    if ext.width <= max_width:
        return [text]

    # Try splitting into 2 lines
    lines = _split_into_n(cr, text, 2, max_width)
    if lines is not None:
        return lines

    # Try splitting into 3 lines
    lines = _split_into_n(cr, text, 3, max_width)
    if lines is not None:
        return lines

    # Fallback: force-split into max_lines chunks by character count
    chunk_len = max(1, len(text) // max_lines)
    result = []
    remaining = text
    for _ in range(max_lines - 1):
        if len(remaining) <= chunk_len:
            break
        sp = _find_split_point(remaining[:chunk_len * 2])
        sp = min(sp, len(remaining) - 1)
        result.append(remaining[:sp].strip())
        remaining = remaining[sp:].strip()
    if remaining:
        result.append(remaining)
    return result


def _split_into_n(cr: cairo.Context, text: str, n: int,
                  max_width: float) -> "List[str] | None":
    """Try splitting text into exactly n lines that each fit within max_width.
    Returns the lines list if successful, or None if any line still overflows.
    """
    if n == 1:
        ext = cr.text_extents(text)
        return [text] if ext.width <= max_width else None

    # Split text into n roughly equal segments
    segments = []
    remaining = text
    for i in range(n - 1):
        # Target split position for balanced distribution
        target_len = len(remaining) // (n - i)
        # Find best split near target
        best_pos = _find_split_near(remaining, target_len)
        segments.append(remaining[:best_pos].strip())
        remaining = remaining[best_pos:].strip()
    segments.append(remaining)

    # Verify all segments fit
    for seg in segments:
        if not seg:
            continue
        ext = cr.text_extents(seg)
        if ext.width > max_width:
            return None

    return [s for s in segments if s]


def _find_split_near(text: str, target_pos: int) -> int:
    """Find a natural split point near target_pos in the text."""
    best = target_pos
    best_dist = len(text)
    search_start = max(0, target_pos - len(text) // 4)
    search_end = min(len(text), target_pos + len(text) // 4)
    for i in range(search_start, search_end):
        if text[i] in (' ', ',', '।', '!', '?', ':', ';', '—', '-', '–'):
            dist = abs(i - target_pos)
            if dist < best_dist:
                best_dist = dist
                best = i + 1  # Split after the break character
    return best


def draw_subtitle_overlay(cr: cairo.Context, text: str,
                          width: int = 1080, height: int = 1920):
    """Draws a punchy cartoon subtitle banner in the lower third (Shorts/Reels style).
    Automatically wraps text to multiple lines to prevent overflow.
    """
    if not text.strip():
        return

    cr.save()
    cr.select_font_face(HINDI_FONT_NAME, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

    # --- Adaptive font sizing ---
    margin = 50  # Safe margin each side
    max_text_width = width - margin * 2  # 980px usable
    base_font_size = 52
    min_font_size = 32

    font_size = base_font_size
    lines = []

    # Try wrapping at current font size, reduce if needed
    while font_size >= min_font_size:
        cr.set_font_size(font_size)
        lines = _wrap_text_cairo(cr, text, max_text_width, max_lines=3)
        if not lines:
            cr.restore()
            return

        # Verify all lines actually fit
        all_fit = True
        for line in lines:
            ext = cr.text_extents(line)
            if ext.width > max_text_width:
                all_fit = False
                break
        if all_fit:
            break
        font_size -= 2

    cr.set_font_size(font_size)

    # --- Measure layout ---
    line_metrics = []
    total_text_height = 0
    line_spacing = font_size * 0.35  # Gap between lines
    max_line_width = 0

    for line in lines:
        ext = cr.text_extents(line)
        line_metrics.append({
            "text": line,
            "width": ext.width,
            "height": ext.height,
            "x_bearing": ext.x_bearing,
            "y_bearing": ext.y_bearing,
        })
        max_line_width = max(max_line_width, ext.width)
        total_text_height += ext.height

    total_text_height += line_spacing * (len(lines) - 1)

    # --- Position pill in lower third (above bottom safe zone) ---
    pad_x = 36.0
    pad_y = 20.0
    box_w = min(width - margin, max_line_width + pad_x * 2)
    box_h = total_text_height + pad_y * 2
    box_cx = width / 2.0
    box_cy = 1580.0
    box_x = box_cx - box_w / 2.0
    box_y = box_cy - box_h / 2.0

    # --- 1. Dark Translucent Rounded Pill Background ---
    cr.save()
    cr.set_source_rgba(0.05, 0.05, 0.08, 0.82)
    radius = 24.0
    cr.arc(box_x + radius, box_y + radius, radius, 3.1415, 4.7123)
    cr.arc(box_x + box_w - radius, box_y + radius, radius, 4.7123, 6.2831)
    cr.arc(box_x + box_w - radius, box_y + box_h - radius, radius, 0, 1.5707)
    cr.arc(box_x + radius, box_y + box_h - radius, radius, 1.5707, 3.1415)
    cr.close_path()
    cr.fill_preserve()
    # Gold Border
    cr.set_source_rgba(1.0, 0.85, 0.15, 0.9)
    cr.set_line_width(4.0)
    cr.stroke()
    cr.restore()

    # --- 2. Draw each line (black outline + yellow fill) ---
    # Start from top of text area inside pill
    current_y = box_y + pad_y

    for lm in line_metrics:
        text_line = lm["text"]
        lw = lm["width"]
        lh = lm["height"]

        # Center each line horizontally
        tx = box_cx - lw / 2.0 - lm["x_bearing"]
        ty = current_y - lm["y_bearing"]  # y_bearing is negative for ascent

        # Text Outline (thick black)
        cr.set_line_width(7.0)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        cr.move_to(tx, ty)
        cr.text_path(text_line)
        cr.set_source_rgba(0.0, 0.0, 0.0, 1.0)
        cr.stroke_preserve()

        # Text Fill (Electric Yellow / Gold)
        cr.set_source_rgba(1.0, 0.95, 0.20, 1.0)
        cr.fill()

        current_y += lh + line_spacing

    cr.restore()
