from __future__ import annotations

from types import SimpleNamespace

from PIL import Image, ImageChops, ImageDraw

from factory.media.illustrated_styles import (
    CAPTION_TOP,
    HEIGHT,
    WIDTH,
    _draw_evidence_board,
    _draw_pop_info,
)


def _fixture() -> tuple[Image.Image, SimpleNamespace, list[SimpleNamespace]]:
    image = Image.new("RGB", (640, 420), "#8ac7df")
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 60, 425, 265), fill="#ef8b50", outline="#172f47", width=9)
    draw.line((40, 350, 580, 80), fill="#f6d664", width=19)
    lines = [
        SimpleNamespace(headline=f"BEAT {index + 1}", caption="BEAT", text="A moving idea",
                        visual="walk")
        for index in range(4)
    ]
    return image, lines[2], lines


def _render(style: str, index: int) -> tuple[Image.Image, dict[str, object]]:
    image, line, lines = _fixture()
    frame = Image.new("RGB", (WIDTH, HEIGHT), "white")
    if style == "pop-info":
        geometry = _draw_pop_info(frame, image, lines[index], 1.1, 3.0, index, 4,
                                  ("ACADEMIC", "BRIEF", "@example"))
    else:
        geometry = _draw_evidence_board(frame, image, lines[index], lines[:index], 1.1, 3.0,
                                        index, 4, ("NEXUS", "BRIEF", "@example"))
    return frame, geometry


def test_pop_info_changes_scene_composition_and_keeps_visual_out_of_caption_band() -> None:
    rendered = [_render("pop-info", index) for index in range(3)]
    boxes = [item[1]["visual"] for item in rendered]
    assert len(set(boxes)) == 3
    assert all(0 <= box[0] < box[2] <= WIDTH and 0 <= box[1] < box[3] < CAPTION_TOP
               for box in boxes)
    for previous, current in zip(rendered, rendered[1:]):
        assert ImageChops.difference(previous[0], current[0]).getbbox() is not None


def test_evidence_board_changes_card_framing_without_entering_caption_band() -> None:
    rendered = [_render("evidence-board", index) for index in range(3)]
    boxes = [item[1]["visual"] for item in rendered]
    assert len(set(boxes)) == 3
    assert all(0 <= box[0] < box[2] <= WIDTH and 0 <= box[1] < box[3] < CAPTION_TOP
               for box in boxes)
    for previous, current in zip(rendered, rendered[1:]):
        assert ImageChops.difference(previous[0], current[0]).getbbox() is not None
