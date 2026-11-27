"""Illustrated scene treatments adapted from the user's Nafay 3D style references.

These are complete moving compositions around the planned visual, rather than an animated
transition on a fixed slide. All layout and texture randomness is deterministic per scene.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from ..config import FONTS_DIR

WIDTH, HEIGHT = 1080, 1920
CAPTION_TOP = 1430
TITLE_FONT = FONTS_DIR / "Inter-Black.otf"
ROUNDED_FONT = FONTS_DIR / "Baloo2-Variable.ttf"
NOTE_FONT = FONTS_DIR / "Caladea-Bold.ttf"


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), size)
    if path.name == "Baloo2-Variable.ttf":
        try:
            font.set_variation_by_axes([700])
        except (AttributeError, OSError):
            pass
    return font


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    rows: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            rows.append(current)
            current = word
    rows.append(current)
    return rows


def _fit_text(draw: ImageDraw.ImageDraw, text: str, path: Path, width: int,
              start_size: int, min_size: int = 38, max_lines: int = 2
              ) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(start_size, min_size - 1, -2):
        font = _font(path, size)
        rows = _wrap(draw, text.upper(), font, width)
        if len(rows) <= max_lines:
            return font, rows
    font = _font(path, min_size)
    return font, _wrap(draw, text.upper(), font, width)[:max_lines]


def _centered(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
              y: int, fill: str, left: int = 0, right: int = WIDTH) -> tuple[int, int, int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    x = (left + right - (box[2] - box[0])) / 2
    draw.text((x, y), text, font=font, fill=fill)
    return int(x), y, int(x + box[2] - box[0]), int(y + box[3] - box[1])


def _ease_out(value: float) -> float:
    x = min(1.0, max(0.0, value))
    return 1 + 2.3 * (x - 1) ** 3 + 1.3 * (x - 1) ** 2


def _progress(local: float, span: float) -> float:
    return min(1.0, max(0.0, local / max(0.001, span)))


@lru_cache(maxsize=1)
def _paper_background(kind: str) -> Image.Image:
    if kind == "board":
        image = Image.new("RGB", (WIDTH, HEIGHT), "#9B6840")
        draw = ImageDraw.Draw(image)
        # Large cork panels keep texture visible without competing with the evidence cards.
        draw.rectangle((38, 38, WIDTH - 38, HEIGHT - 38), fill="#A8754C", outline="#5D3928", width=18)
        rng = random.Random(7421)
        for _ in range(1850):
            x, y = rng.randrange(54, WIDTH - 54), rng.randrange(54, HEIGHT - 54)
            radius = rng.choice((1, 2, 3))
            color = rng.choice(("#B78358", "#8A5836", "#96613D", "#C18B5C"))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        for y in (430, 920, 1370):
            draw.line((48, y, WIDTH - 48, y + 6), fill="#855532", width=2)
        return image
    if kind == "zine":
        image = Image.new("RGB", (WIDTH, HEIGHT), "#D7C3A3")
        draw = ImageDraw.Draw(image)
        rng = random.Random(8153)
        for _ in range(950):
            x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
            radius = rng.choice((1, 2, 3))
            color = rng.choice(("#C8B18E", "#E3D1B3", "#A88F70"))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        return image
    image = Image.new("RGB", (WIDTH, HEIGHT), "#F5EEDB")
    draw = ImageDraw.Draw(image)
    draw.ellipse((690, -250, 1270, 380), fill="#F7D9CD")
    draw.ellipse((-270, 1040, 420, 1760), fill="#D4EEE0")
    draw.polygon(((0, 1230), (1080, 1140), (1080, 1470), (0, 1470)), fill="#E8DDC3")
    rng = random.Random(9271)
    for _ in range(210):
        x, y = rng.randrange(40, 1040), rng.randrange(70, 1390)
        draw.ellipse((x, y, x + 3, y + 3), fill="#D7C9AE")
    return image


def _fit_pan(image: Image.Image | None, size: tuple[int, int], progress: float) -> Image.Image:
    width, height = size
    if image is None:
        blank = Image.new("RGB", size, "#F4ECD9")
        d = ImageDraw.Draw(blank)
        d.ellipse((width * .38, height * .2, width * .62, height * .7), fill="#E9D9B9")
        return blank
    # Keep the camera travelling through the full beat: a subtle 5% push read as a fixed slide
    # at phone size, so these illustrated treatments use a more visible documentary push-in.
    zoom = 1.035 + .095 * progress
    scaled = ImageOps.fit(image.convert("RGB"),
                          (int(width * zoom), int(height * zoom)),
                          method=Image.Resampling.LANCZOS,
                          centering=(.43 + .14 * progress, .48))
    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def _paste_rounded(frame: Image.Image, image: Image.Image, box: tuple[int, int, int, int],
                   radius: int, outline: str, shadow: str = "#443327") -> None:
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((x1 + 10, y1 + 15, x2 + 10, y2 + 15), radius=radius, fill=shadow)
    draw.rounded_rectangle(box, radius=radius, fill="#FFFDF7", outline=outline, width=5)
    image = image.resize((width - 28, height - 28), Image.Resampling.LANCZOS)
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius=max(4, radius - 12), fill=255)
    frame.paste(image, (x1 + 14, y1 + 14), mask)


def _paste_pop_window(frame: Image.Image, image: Image.Image, box: tuple[int, int, int, int],
                      local: float, span: float, index: int, total: int) -> None:
    x1, y1, x2, y2 = box
    draw = ImageDraw.Draw(frame)
    draw.rounded_rectangle((x1 + 10, y1 + 15, x2 + 10, y2 + 15), radius=38, fill="#B49F7D")
    draw.rounded_rectangle(box, radius=38, fill="#FFFDF7", outline="#43A79A", width=5)
    inner = (x1 + 15, y1 + 15, x2 - 15, y2 - 15)
    picture = _fit_pan(image, (inner[2] - inner[0], inner[3] - inner[1]), _progress(local, span))
    reveal = min(1.0, max(0.0, local / .34))
    if index == total - 1 and local > max(0.0, span - .34):
        reveal = min(reveal, max(0.0, (span - local) / .34))
    if reveal < 1.0:
        width, height = picture.size
        radius = int(math.hypot(width, height) * .55 * reveal)
        mask = Image.new("L", picture.size, 0)
        ImageDraw.Draw(mask).ellipse((width // 2 - radius, height // 2 - radius,
                                      width // 2 + radius, height // 2 + radius), fill=255)
        frame.paste(picture, (inner[0], inner[1]), mask)
        ring = ImageDraw.Draw(frame)
        ring.ellipse((width // 2 + inner[0] - radius, height // 2 + inner[1] - radius,
                      width // 2 + inner[0] + radius, height // 2 + inner[1] + radius),
                     outline="#E45D4F", width=5)
    else:
        frame.paste(picture, (inner[0], inner[1]))


def _draw_pop_prop(draw: ImageDraw.ImageDraw, kind: str, local: float) -> None:
    """Small scene props are symbolic illustrations and add no unspoken measurements."""
    cx, cy = 296, 1195
    ink = "#514239"
    if kind in {"walk", "meal", "plate"}:
        draw.ellipse((cx - 94, cy - 22, cx + 94, cy + 38), fill="#FFF9E9", outline=ink, width=5)
        draw.ellipse((cx - 69, cy - 10, cx + 69, cy + 25), outline="#D69E57", width=4)
        draw.ellipse((cx - 43, cy - 6, cx - 10, cy + 16), fill="#78A768")
        draw.ellipse((cx + 2, cy - 9, cx + 33, cy + 14), fill="#E89058")
        draw.arc((cx - 15, cy - 58, cx + 18, cy - 20), 190, 350, fill="#D48655", width=4)
        draw.arc((cx + 15, cy - 73, cx + 46, cy - 22), 190, 350, fill="#D48655", width=4)
        for step in range(4):
            phase = (local * 2.4 + step * .25) % 1.0
            x = 116 + step * 37 + int(phase * 20)
            y = 1228 - step * 15
            draw.ellipse((x, y, x + 12, y + 23), fill="#E45D4F")
    elif kind in {"clock", "thermo", "bath"}:
        draw.ellipse((cx - 72, cy - 72, cx + 72, cy + 72), fill="#FFFDF7", outline="#43A79A", width=7)
        draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=ink)
        angle = -math.pi / 2 + local * .9
        draw.line((cx, cy, cx + math.cos(angle) * 48, cy + math.sin(angle) * 48), fill="#E45D4F", width=8)
        draw.line((cx, cy, cx - 25, cy - 20), fill=ink, width=6)
    elif kind in {"scale", "balance"}:
        draw.line((cx, cy - 65, cx, cy + 48), fill=ink, width=8)
        draw.line((cx - 74, cy - 35, cx + 74, cy - 35), fill="#43A79A", width=8)
        draw.line((cx - 50, cy - 35, cx - 70, cy + 18), fill=ink, width=4)
        draw.line((cx + 50, cy - 35, cx + 70, cy + 18), fill=ink, width=4)
        draw.arc((cx - 94, cy + 5, cx - 44, cy + 33), 0, 180, fill="#E45D4F", width=6)
        draw.arc((cx + 44, cy + 5, cx + 94, cy + 33), 0, 180, fill="#E45D4F", width=6)
        draw.line((cx - 50, cy + 54, cx + 50, cy + 54), fill=ink, width=8)
    else:
        draw.rounded_rectangle((cx - 92, cy - 65, cx + 92, cy + 56), radius=18,
                               fill="#FFFDF7", outline="#43A79A", width=5)
        for row in range(3):
            draw.line((cx - 54, cy - 29 + row * 28, cx + 48, cy - 29 + row * 28),
                      fill="#E45D4F" if row == 1 else "#9E8B72", width=5)
        draw.polygon(((cx + 49, cy - 4), (cx + 72, cy + 7), (cx + 49, cy + 18)), fill="#E45D4F")


def _draw_study_group(draw: ImageDraw.ImageDraw,
                      box: tuple[int, int, int, int], local: float) -> None:
    """Show an illustrative participant group when the narration names a trial cohort."""

    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=28, fill="#EAF2E9", outline="#5E9A8D", width=4)
    draw.ellipse((x1 + 18, y1 + 42, x2 - 18, y2 + 56), fill="#D5E5D5")
    # These figures are illustrative people, not a count of the study sample.
    palette = ("#D96C55", "#628EAA", "#E0B54D", "#8F7AB5", "#4B9B87")
    centers = [x1 + 104 + index * 108 for index in range(5)]
    people = []
    for index, center in enumerate(centers):
        phase = local * 4.2 + index * .78
        bob = int(7 * math.sin(phase))
        head_y = y1 + 156 + bob
        body_top = head_y + 42
        walk = math.sin(phase) if index == 2 else 0.0
        skin = ("#E8B184", "#D59A73", "#F0C5A0", "#C98362", "#E3A47D")[index]
        draw.ellipse((center - 27, head_y - 27, center + 27, head_y + 27),
                     fill=skin, outline="#57483B", width=4)
        draw.arc((center - 13, head_y - 1, center + 13, head_y + 15), 5, 175,
                 fill="#684C3F", width=3)
        draw.rounded_rectangle((center - 36, body_top, center + 36, body_top + 92), radius=22,
                               fill=palette[index], outline="#57483B", width=4)
        draw.line((center - 27, body_top + 25, center - 53 - int(walk * 13), body_top + 64),
                  fill=skin, width=13)
        draw.line((center + 27, body_top + 25, center + 52 + int(walk * 13), body_top + 62),
                  fill=skin, width=13)
        left_stride = int(walk * 19)
        right_stride = -left_stride
        left_lift = max(0, int(abs(walk) * 8))
        right_lift = max(0, int(abs(walk) * 8))
        draw.line((center - 17, body_top + 89, center - 28 + left_stride,
                   body_top + 148 - left_lift), fill="#51463E", width=14)
        draw.line((center + 17, body_top + 89, center + 30 + right_stride,
                   body_top + 148 - right_lift), fill="#51463E", width=14)
        draw.ellipse((center - 42 + left_stride, body_top + 140 - left_lift,
                      center - 14 + left_stride, body_top + 154 - left_lift), fill="#51463E")
        draw.ellipse((center + 15 + right_stride, body_top + 140 - right_lift,
                      center + 45 + right_stride, body_top + 154 - right_lift), fill="#51463E")
        people.append((center, head_y))
    # A moving halo points to each participant in turn without implying an experiment result.
    active = int((local * .85) % len(people))
    center, head_y = people[active]
    radius = 38 + int(4 * math.sin(local * 4.5))
    draw.ellipse((center - radius, head_y - radius, center + radius, head_y + radius),
                 outline="#E5B94F", width=5)
    draw.text((x1 + 22, y2 - 40), "STUDY GROUP", font=_font(ROUNDED_FONT, 23), fill="#3D5148")


def _draw_brand(draw: ImageDraw.ImageDraw, brand: tuple[str, str, str], label: str,
                bg: str, fg: str, accent: str) -> None:
    draw.rounded_rectangle((66, 72, 1014, 190), radius=28, fill=bg, outline=fg, width=3)
    draw.rounded_rectangle((82, 91, 97, 170), radius=7, fill=accent)
    draw.text((122, 91), brand[0], font=_font(TITLE_FONT, 27), fill=fg)
    draw.text((122, 132), label, font=_font(NOTE_FONT, 26), fill=accent)


def _draw_pop_guide(draw: ImageDraw.ImageDraw, local: float, *, hx: int, hy: int,
                    scale: float, walking: bool) -> None:
    """Draw the recurring Pop Info guide at a layout-specific size and position."""

    def point(x: float, y: float) -> tuple[int, int]:
        return hx + int(round(x * scale)), hy + int(round(y * scale))

    def box(x1: float, y1: float, x2: float, y2: float) -> tuple[int, int, int, int]:
        left, top = point(x1, y1)
        right, bottom = point(x2, y2)
        return left, top, right, bottom

    width = lambda value: max(2, int(round(value * scale)))
    bob = int(10 * math.sin(local * 4.0) * scale)
    hy += bob
    draw.ellipse(box(-60, -61, 60, 59), fill="#EAA870", outline="#4E382D", width=width(6))
    draw.ellipse(box(-27, -16, -13, 1), fill="#31271F")
    draw.ellipse(box(15, -16, 29, 1), fill="#31271F")
    draw.arc(box(-20, -1, 23, 34), 5, 165, fill="#7E3E34", width=width(5))
    draw.rounded_rectangle(box(-61, 52, 62, 193), radius=width(35), fill="#56B5A5",
                           outline="#3D4139", width=width(6))
    hand_wave = int(18 * math.sin(local * 2.8))
    arm_y = 74 + int(12 * math.sin(local * 5.0))
    draw.line((*point(-48, arm_y), *point(-105 + hand_wave // 2, arm_y - 62),
               *point(-168 + hand_wave, arm_y - 110)), fill="#EAA870", width=width(24))
    draw.ellipse(box(-179 + hand_wave, arm_y - 122, -157 + hand_wave, arm_y - 100),
                 fill="#EAA870", outline="#4E382D", width=width(3))
    stride = math.sin(local * 5.2) if walking else 0.0
    left_dx, right_dx = int(stride * 22), int(-stride * 22)
    left_up = right_up = max(0, int(abs(stride) * 10))
    draw.line((*point(-26, 185), *point(-44 + left_dx, 243 - left_up)),
              fill="#3A3330", width=width(22))
    draw.line((*point(30, 185), *point(49 + right_dx, 243 - right_up)),
              fill="#3A3330", width=width(22))
    draw.ellipse(box(-69 + left_dx, 231 - left_up, -28 + left_dx, 253 - left_up), fill="#51443A")
    draw.ellipse(box(30 + right_dx, 231 - right_up, 71 + right_dx, 253 - right_up), fill="#51443A")


def _draw_pop_info(frame: Image.Image, image: Image.Image | None, line: Any,
                   local: float, span: float, index: int, total: int,
                   brand: tuple[str, str, str]) -> dict[str, Any]:
    frame.paste(_paper_background("pop"))
    draw = ImageDraw.Draw(frame)
    _draw_brand(draw, brand, "IDEAS IN MOTION", "#FFF8E8", "#382D25", "#E45D4F")
    progress = _progress(local, span)
    spring = min(1.08, max(.01, _ease_out(local / .44)))
    composition = index % 3
    headline_font, rows = _fit_text(draw, line.headline or line.caption or line.text[:38],
                                    ROUNDED_FONT, 770, 78, 48, 2)
    bubble_top = 230 + int(15 * (1 - spring)) + int(5 * math.sin(local * 1.8))
    bubble = (92, bubble_top, 918, bubble_top + (174 if len(rows) == 1 else 226))
    if composition == 1:
        # A punchy burst card breaks the speech-bubble rhythm on every third beat.
        draw.rounded_rectangle((bubble[0] + 7, bubble[1] + 9, bubble[2] + 7, bubble[3] + 9),
                               radius=38, fill="#D8B453")
        draw.rounded_rectangle(bubble, radius=38, fill="#FFD96C", outline="#5E4634", width=5)
        draw.line((bubble[0] + 30, bubble[3] - 17, bubble[2] - 30, bubble[3] - 17),
                  fill="#E45D4F", width=7)
    else:
        draw.rounded_rectangle(bubble, radius=48, fill="#FFFDF7", outline="#5E4634", width=5)
        if composition == 0:
            draw.polygon(((812, bubble[3] - 4), (856, bubble[3] - 5), (828, bubble[3] + 31)), fill="#FFFDF7")
            draw.line((812, bubble[3] - 3, 828, bubble[3] + 31, 856, bubble[3] - 4), fill="#5E4634", width=4)
    row_height = headline_font.size + 2
    text_top = bubble_top + (bubble[3] - bubble_top - len(rows) * row_height) // 2 - 4
    title_boxes = []
    for row in rows:
        title_boxes.append(_centered(draw, row, headline_font, text_top, "#33291F", 126, 884))
        text_top += row_height
    # The image takes a different role in each beat: wide evidence reveal, guide-led split scene,
    # then a close illustrated prop scene. Reusing one fixed panel was making the film read as slides.
    enter = max(.04, min(1.0, spring))
    float_x = int(7 * math.sin(local * 1.35))
    float_y = int(9 * math.sin(local * 1.7))
    if composition == 1:
        target_box = (64 + float_x, 500 + int(24 * (1 - enter)) + float_y,
                      1016 + float_x, 1330 + int(24 * (1 - enter)) + float_y)
    elif composition == 2:
        target_box = (370 + float_x, 520 + int(24 * (1 - enter)) + float_y,
                      1010 + float_x, 1270 + int(24 * (1 - enter)) + float_y)
    else:
        target_box = (92 + float_x, 515 + int(28 * (1 - enter)) + float_y,
                      736 + float_x, 966 + int(28 * (1 - enter)) + float_y)
        # The prop shelf belongs only to the guide-led layout; avoiding it elsewhere opens the frame.
        shelf_x = 774 + int(100 * (1 - enter)) + int(4 * math.sin(local * 1.1))
        draw.rounded_rectangle((shelf_x, 600, 1025, 1055), radius=28, fill="#E2D6BD", outline="#77614A", width=5)
        for y in (740, 885, 1028):
            draw.rounded_rectangle((shelf_x + 10, y, 1015, y + 15), radius=7, fill="#92795B")
        for col, x in enumerate((shelf_x + 24, shelf_x + 88, shelf_x + 151, shelf_x + 206)):
            for row, y in enumerate((650, 790, 934)):
                color = ("#E98D68", "#64AFA1", "#E7C252", "#8F9FD0")[(col + row) % 4]
                draw.rounded_rectangle((x, y, x + 38, y + 72), radius=12, fill=color, outline="#69553D", width=3)
                draw.ellipse((x + 12, y + 8, x + 25, y + 21), fill="#FFF4D3")
    _paste_pop_window(frame, image, target_box, local, span, index, total)
    draw = ImageDraw.Draw(frame)
    if "trial" in line.text.lower() and any(word in line.text.lower()
                                             for word in ("group", "adult", "participant")):
        _draw_study_group(draw, target_box, local)
    # In the middle beat the illustration fills the screen; the guide returns on the side beat only.
    if composition != 1:
        hx, hy, guide_scale = (868, 1045, 1.0) if composition == 0 else (205, 1035, .72)
        _draw_pop_guide(draw, local, hx=hx, hy=hy, scale=guide_scale,
                        walking=line.visual == "walk")
        if composition == 0:
            _draw_pop_prop(draw, line.visual, local)
        start = (760, 1135) if composition == 0 else (310, 1140)
        end = (650 - int(progress * 65), 980) if composition == 0 else (430, 900)
        control = (650, 1020) if composition == 0 else (360, 1000)
        for step in range(13):
            phase = step / 12
            x = (1 - phase) ** 2 * start[0] + 2 * (1 - phase) * phase * control[0] + phase ** 2 * end[0]
            y = (1 - phase) ** 2 * start[1] + 2 * (1 - phase) * phase * control[1] + phase ** 2 * end[1]
            if phase <= progress:
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#E45D4F")
        bead = (local * .48) % 1.0
        bead_x = (1 - bead) ** 2 * start[0] + 2 * (1 - bead) * bead * control[0] + bead ** 2 * end[0]
        bead_y = (1 - bead) ** 2 * start[1] + 2 * (1 - bead) * bead * control[1] + bead ** 2 * end[1]
        draw.ellipse((bead_x - 10, bead_y - 10, bead_x + 10, bead_y + 10),
                     fill="#F4D36E", outline="#5E4634", width=3)
    # Beat count is a sequence marker, not a scientific quantity.
    draw.ellipse((936, 420, 1024, 508), fill="#FFD96C", outline="#513C2C", width=4)
    count = max(1, min(index + 1, int(math.ceil((index + 1) * max(progress, .18)))))
    _centered(draw, f"{count:02d}", _font(ROUNDED_FONT, 35), 442, "#49362B", 936, 1024)
    # Hand-drawn footer replaces the rigid progress bar.
    draw.text((76, 1780), brand[2], font=_font(ROUNDED_FONT, 27), fill="#5E5141")
    draw.line((75, 1840, 1005, 1840), fill="#C6B89D", width=5)
    route_end = 75 + int(930 * min(1.0, (index + progress) / max(1, total)))
    draw.line((75, 1840, route_end, 1840), fill="#E45D4F", width=7)
    draw.ellipse((route_end - 11, 1829, route_end + 11, 1851), fill="#F1C64F", outline="#4A392D", width=3)
    return {
        "headline": (float(bubble[0]), float(bubble[1]), float(bubble[2]), float(bubble[3])),
        "visual": tuple(float(value) for value in target_box),
    }


def _draw_note(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int],
               angle: int, seed: int, color: str) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    draw.polygon(((x1 + 8, y1 + 9), (x2 + 5, y1 + 4), (x2, y2 + 8), (x1 + 4, y2)), fill="#67422C")
    draw.polygon(((x1 + 4, y1), (x2 - 5, y1 + 2), (x2, y2 - 5), (x1, y2)), fill=color, outline="#5F432C")
    tape = "#E8D8B3"
    draw.polygon(((x1 + 18, y1 - 8), (x1 + 120, y1 - 5), (x1 + 116, y1 + 16), (x1 + 20, y1 + 12)), fill=tape)
    font, rows = _fit_text(draw, text, NOTE_FONT, x2 - x1 - 34, 33, 24, 3)
    y = y1 + 32
    for row in rows:
        draw.text((x1 + 18, y), row, font=font, fill="#3D3027")
        y += font.size + 1
    pin_x, pin_y = (x1 + x2) // 2, y1 + 6
    draw.ellipse((pin_x - 11, pin_y - 10, pin_x + 11, pin_y + 11), fill="#C7352D", outline="#6F2822", width=2)
    draw.ellipse((pin_x - 5, pin_y - 7, pin_x + 2, pin_y), fill="#F4B5A6")
    return float(pin_x), float(pin_y + 4), float(pin_x), float(pin_y + 4)


def _bezier(start: tuple[float, float], control: tuple[float, float], end: tuple[float, float],
            progress: float) -> list[tuple[float, float]]:
    points = []
    for step in range(31):
        amount = step / 30
        if amount > progress:
            break
        inverse = 1 - amount
        x = inverse * inverse * start[0] + 2 * inverse * amount * control[0] + amount * amount * end[0]
        y = inverse * inverse * start[1] + 2 * inverse * amount * control[1] + amount * amount * end[1]
        points.append((x, y))
    return points


def _draw_evidence_board(frame: Image.Image, image: Image.Image | None, line: Any,
                         context_lines: list[Any], local: float, span: float,
                         index: int, total: int, brand: tuple[str, str, str]) -> dict[str, Any]:
    frame.paste(_paper_background("board"))
    draw = ImageDraw.Draw(frame)
    _draw_brand(draw, brand, "FIELD NOTES  •  CLAIMS AND CONTEXT", "#F2E4C8", "#3B281D", "#B82F2C")
    # Three editorial framings keep the evidence-board motif while changing the shot size and balance.
    composition = index % 3
    older = context_lines[max(0, index - 2):index]
    if composition == 2:
        note_boxes = [(60, 335, 310, 515), (60, 790, 310, 970)]
    elif composition == 1:
        note_boxes = [(66, 320, 344, 445), (736, 320, 1014, 445)]
    else:
        note_boxes = [(66, 335, 344, 500), (736, 345, 1014, 510)]
    note_colors = ("#E8D77A", "#D7E8D8")
    note_pins = []
    for offset, previous in enumerate(older):
        note_pins.append(_draw_note(draw, previous.headline or previous.caption or previous.text[:38],
                                    note_boxes[offset], 0, index * 11 + offset, note_colors[offset]))
    progress = _progress(local, span)
    enter = max(.02, min(1.06, _ease_out(local / .42)))
    scale = .92 + .08 * enter
    scale += .008 * math.sin(local * 1.8)
    if composition == 1:
        base_w, base_h, base_x, base_y, picture_h, title_offset = 940, 860, 70, 465, 510, 585
    elif composition == 2:
        base_w, base_h, base_x, base_y, picture_h, title_offset = 690, 900, 350, 425, 495, 565
    else:
        base_w, base_h, base_x, base_y, picture_h, title_offset = 790, 825, 145, 470, 490, 575
    card_w, card_h = int(base_w * scale), int(base_h * scale)
    card_x = int(base_x + (base_w - card_w) / 2 + 16 * math.sin(local * 1.25))
    card_y = int(base_y + 18 * (1 - enter) - 14 * progress + 8 * math.sin(local * 1.6))
    # Curved red string is drawn in stages and tied to the moving scene pin.
    target_pin = (card_x + card_w / 2, card_y + 6.0)
    for offset, pin in enumerate(note_pins):
        path = _bezier((pin[0], pin[1]), (card_x + card_w / 2 + (offset - .5) * 180, 470), target_pin,
                       min(1.0, progress * 1.65 + offset * .08))
        if len(path) > 1:
            draw.line(path, fill="#B5252A", width=6)
            for point in (path[0], path[-1]):
                draw.ellipse((point[0] - 6, point[1] - 6, point[0] + 6, point[1] + 6), fill="#C7352D")
            bead = path[int(((local * .62 + offset * .31) % 1.0) * (len(path) - 1))]
            bead_radius = 7 + int(2 * (1 + math.sin(local * 5.0 + offset)))
            draw.ellipse((bead[0] - bead_radius, bead[1] - bead_radius,
                          bead[0] + bead_radius, bead[1] + bead_radius),
                         fill="#F1D276", outline="#8E2C2B", width=3)
    # Off-white polaroid with darkroom print, taped top edge and evidence caption.
    draw.rounded_rectangle((card_x + 14, card_y + 18, card_x + card_w + 14, card_y + card_h + 18),
                           radius=8, fill="#573922")
    draw.rectangle((card_x, card_y, card_x + card_w, card_y + card_h), fill="#F7F1E1", outline="#4D3829", width=5)
    picture_h = int(picture_h * scale)
    picture = _fit_pan(image, (card_w - 82, picture_h), progress)
    frame.paste(picture, (card_x + 41, card_y + 42))
    image_left, image_top = card_x + 41, card_y + 42
    image_right = card_x + card_w - 41
    image_bottom = image_top + picture_h
    draw.rectangle((image_left, image_top, image_right, image_bottom), outline="#594538", width=3)
    sweep = .5 + .5 * math.sin(local * 1.25)
    if composition == 1:
        # A moving scan rule and corner marks make this a wide exhibit shot instead of another card.
        scan_x = image_left + int(sweep * max(0, image_right - image_left))
        draw.line((scan_x, image_top + 8, scan_x, image_bottom - 8), fill="#B82F2C", width=5)
        arm = 34
        for x, y, dx, dy in ((image_left, image_top, 1, 1), (image_right, image_top, -1, 1),
                             (image_left, image_bottom, 1, -1), (image_right, image_bottom, -1, -1)):
            draw.line((x, y, x + arm * dx, y), fill="#F1D276", width=7)
            draw.line((x, y, x, y + arm * dy), fill="#F1D276", width=7)
    else:
        # The magnifier is reserved for the close-up and classic shots, rather than every beat.
        lens_x = image_left + 58 + int(sweep * max(0, image_right - image_left - 116))
        lens_y = image_top + picture_h // 2 + int(18 * math.sin(local * 1.9))
        radius = min(58, picture_h // 5)
        draw.line((lens_x + 30, lens_y + 30, lens_x + 96, lens_y + 96), fill="#49372B", width=19)
        draw.line((lens_x + 28, lens_y + 28, lens_x + 93, lens_y + 93), fill="#D6AE55", width=12)
        draw.ellipse((lens_x - radius, lens_y - radius, lens_x + radius, lens_y + radius),
                     outline="#49372B", width=18)
        draw.ellipse((lens_x - radius + 7, lens_y - radius + 7,
                      lens_x + radius - 7, lens_y + radius - 7), outline="#F1D276", width=8)
        draw.arc((lens_x - radius + 13, lens_y - radius + 12,
                  lens_x + 5, lens_y + 3), 200, 315, fill="#FFF7D9", width=7)
    title_font, rows = _fit_text(draw, line.headline or line.caption or line.text[:48], NOTE_FONT,
                                 card_w - 76, 46, 34, 2)
    title_y = card_y + int(title_offset * scale)
    title_boxes = []
    for row in rows:
        title_boxes.append((card_x + 42, title_y,
                            card_x + 42 + int(draw.textlength(row, font=title_font)), title_y + title_font.size))
        draw.text((card_x + 42, title_y), row, font=title_font, fill="#312820")
        title_y += title_font.size + 6
    # A moving pointer and a tiny pin glint make the evidence photo feel handled, not pasted in.
    pin_x, pin_y = card_x + card_w // 2, card_y + 6
    draw.ellipse((pin_x - 21, pin_y - 22, pin_x + 21, pin_y + 20), fill="#B8282E", outline="#64201F", width=3)
    draw.ellipse((pin_x - 11, pin_y - 14, pin_x - 1, pin_y - 5), fill="#F5B6A4")
    draw.polygon(((card_x + 95, card_y - 11), (card_x + 288, card_y - 5),
                  (card_x + 281, card_y + 34), (card_x + 104, card_y + 29)), fill="#E8D8B3")
    # The closing stamp is a neutral scope reminder, never a factual verdict.
    if index == total - 1 and local > max(0.0, span - 1.45):
        stamp = Image.new("RGBA", (330, 110), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        sd.rounded_rectangle((5, 5, 325, 105), radius=8, outline=(183, 39, 44, 225), width=8)
        sd.rounded_rectangle((14, 14, 316, 96), radius=5, outline=(183, 39, 44, 180), width=2)
        sd.text((28, 27), "SCOPE CHECK", font=_font(TITLE_FONT, 43), fill=(183, 39, 44, 235))
        stamp = stamp.rotate(-8 + 2 * math.sin(local * 24), resample=Image.Resampling.BICUBIC, expand=True)
        frame.paste(stamp, (630, 1200), stamp)
    draw = ImageDraw.Draw(frame)
    draw.text((74, 1784), brand[2], font=_font(NOTE_FONT, 27), fill="#F5EBD5")
    draw.text((828, 1780), f"CLUE {index + 1:02d}", font=_font(TITLE_FONT, 24), fill="#F5EBD5")
    route_y = 1840
    draw.line((74, route_y, 1006, route_y), fill="#765036", width=5)
    route_end = 74 + int(932 * min(1.0, (index + progress) / max(1, total)))
    draw.line((74, route_y, route_end, route_y), fill="#C7352D", width=8)
    return {
        "headline": (float(card_x + 38), float(card_y + 566), float(card_x + card_w - 38), float(title_y)),
        "visual": (float(card_x), float(card_y), float(card_x + card_w), float(card_y + card_h)),
    }


def _torn_polygon(box: tuple[int, int, int, int], seed: int, teeth: int = 18) -> list[tuple[int, int]]:
    x1, y1, x2, y2 = box
    rng = random.Random(seed)
    points: list[tuple[int, int]] = []
    for step in range(teeth + 1):
        x = x1 + (x2 - x1) * step / teeth
        points.append((int(x), y1 + rng.randint(-7, 7)))
    for step in range(teeth + 1):
        y = y1 + (y2 - y1) * step / teeth
        points.append((x2 + rng.randint(-7, 7), int(y)))
    for step in range(teeth + 1):
        x = x2 - (x2 - x1) * step / teeth
        points.append((int(x), y2 + rng.randint(-7, 7)))
    for step in range(teeth + 1):
        y = y2 - (y2 - y1) * step / teeth
        points.append((x1 + rng.randint(-7, 7), int(y)))
    return points


def _draw_zine(frame: Image.Image, image: Image.Image | None, line: Any,
               local: float, span: float, t: float, index: int, total: int,
               brand: tuple[str, str, str]) -> dict[str, Any]:
    frame.paste(_paper_background("zine"))
    draw = ImageDraw.Draw(frame)
    beat_clock = math.floor(t * 8) / 8
    jitter = random.Random(4700 + index * 19 + int(beat_clock * 8))
    dx, dy = jitter.randint(-5, 5), jitter.randint(-4, 4)
    draw.polygon(((64, 77), (1018, 68), (1010, 175), (71, 188)), fill="#211D1B")
    draw.text((94, 99), brand[0], font=_font(TITLE_FONT, 27), fill="#FFF1D8")
    draw.text((793, 101), "CUT / PASTE / THINK", font=_font(ROUNDED_FONT, 24), fill="#FFD34E")
    headline = line.headline or line.caption or line.text[:42]
    title_font, rows = _fit_text(draw, headline, TITLE_FONT, 850, 76, 50, 2)
    paper_boxes = [(88, 230 + dy, 992, 443 + dy)]
    title_color = "#171414"
    title_y = 266 + dy
    title_boxes = []
    for row_index, row in enumerate(rows):
        # Individual words land as cut paper; time quantization gives the source's hand-built cadence.
        pieces = row.split()
        widths = [draw.textlength(word, font=title_font) + 26 for word in pieces]
        gap = 14
        start_x = int((WIDTH - sum(widths) - gap * (len(widths) - 1)) / 2)
        x = start_x
        colors = ("#FFF2D5", "#EF5C4F", "#F5C840", "#171414")
        for word_index, word in enumerate(pieces):
            ordinal = row_index * 4 + word_index
            if local < ordinal * .10:
                x += widths[word_index] + gap
                continue
            pop = min(1.0, max(.08, _ease_out((local - ordinal * .10) / .22)))
            tile_w = int(widths[word_index] * pop)
            tile_h = title_font.size + 25
            tile = (x + dx, title_y - 10 + dy, x + dx + tile_w, title_y - 10 + tile_h + dy)
            draw.polygon(_torn_polygon(tile, index * 101 + ordinal, 8), fill=colors[(index + ordinal) % len(colors)])
            fill = "#FFF7E5" if colors[(index + ordinal) % len(colors)] == "#171414" else "#1B1715"
            draw.text((x + 12 + dx, title_y + dy), word, font=title_font, fill=fill)
            title_boxes.append((tile[0], tile[1], tile[2], tile[3]))
            x += widths[word_index] + gap

    # Photostat drops onto torn paper with a brief slap and a held, low-rate jitter.
    picture_box = (122 + dx, 505 + int(22 * (1 - _progress(local, .34))) + dy,
                   958 + dx, 1155 + int(22 * (1 - _progress(local, .34))) + dy)
    draw.polygon(_torn_polygon((picture_box[0] - 24, picture_box[1] - 23,
                                picture_box[2] + 24, picture_box[3] + 24), 992 + index), fill="#211D1B")
    draw.polygon(_torn_polygon((picture_box[0] - 13, picture_box[1] - 12,
                                picture_box[2] + 13, picture_box[3] + 13), 993 + index), fill="#FFF2D5")
    picture = _fit_pan(image, (picture_box[2] - picture_box[0], picture_box[3] - picture_box[1]),
                       _progress(local, span))
    frame.paste(picture, (picture_box[0], picture_box[1]))
    draw = ImageDraw.Draw(frame)
    # Two translucent tape strips and halftone dots remain in the margins, away from chart labels.
    draw.polygon(((154 + dx, 482 + dy), (370 + dx, 478 + dy), (378 + dx, 515 + dy), (162 + dx, 520 + dy)), fill="#E6A6A0")
    draw.polygon(((763 + dx, 1138 + dy), (940 + dx, 1134 + dy), (946 + dx, 1168 + dy), (771 + dx, 1174 + dy)), fill="#E8D89F")
    for row in range(5):
        for col in range(9):
            cx, cy = 80 + col * 22, 750 + row * 22
            if cx < picture_box[0] - 35:
                draw.ellipse((cx, cy, cx + 5, cy + 5), fill="#2C2621")
    for row in range(5):
        for col in range(6):
            cx, cy = 970 + col * 18, 670 + row * 18
            if cx > picture_box[2] + 5:
                draw.ellipse((cx, cy, cx + 4, cy + 4), fill="#C94B42")
    draw.text((78, 1783), brand[2], font=_font(ROUNDED_FONT, 26), fill="#312821")
    draw.line((78, 1840, 1002, 1840), fill="#88755A", width=5)
    end_x = 78 + int(924 * min(1.0, (index + _progress(local, span)) / max(1, total)))
    draw.line((78, 1840, end_x, 1840), fill="#E34F45", width=8)
    return {
        "headline": (float(min(box[0] for box in title_boxes) if title_boxes else 88),
                    float(min(box[1] for box in title_boxes) if title_boxes else 230),
                    float(max(box[2] for box in title_boxes) if title_boxes else 992),
                    float(max(box[3] for box in title_boxes) if title_boxes else 443)),
        "visual": tuple(float(value) for value in picture_box),
    }


def draw_illustrated_scene(
    frame: Image.Image,
    image: Image.Image | None,
    line: Any,
    context_lines: list[Any],
    local: float,
    span: float,
    t: float,
    duration: float,
    index: int,
    total: int,
    brand: tuple[str, str, str],
    style: str,
) -> dict[str, Any]:
    """Draw a beat as a live illustrated composition, preserving the planned diagram and wording."""

    if style == "pop-info":
        return _draw_pop_info(frame, image, line, local, span, index, total, brand)
    if style == "evidence-board":
        return _draw_evidence_board(frame, image, line, context_lines, local, span, index, total, brand)
    if style == "zine-collage":
        return _draw_zine(frame, image, line, local, span, t, index, total, brand)
    raise ValueError(f"unsupported illustrated animation style: {style}")
