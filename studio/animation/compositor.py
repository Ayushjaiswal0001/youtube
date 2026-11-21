"""Layer-ordered compositing (T45c).

The renderer used to draw in a fixed order: environment, shadows, props, sparkles, cast, foreground.
That is wrong in a way that shows up immediately in production - a held prop is drawn *under* the
hand that holds it, and a cup standing on a table in front of a character is drawn behind them.

Sorting everything by a single screen-y value is also wrong: a cup on a table has a higher screen y
than the character standing behind the table, so depth-by-y puts it behind him.

The model that actually works for 2D cartoon staging is two keys, in order:

1. **Layer** - a coarse, authored band: ground props sit with the cast, held props sit above the
   actor holding them, the near layer sits above everything.
2. **Depth** - within a layer, the world y of the contact point, so two things on the same floor are
   ordered by which is nearer the camera.

Layers are explicit because the ordering between them is a *staging decision*, not something a
geometry heuristic can recover. Depth sorts within a layer because that part genuinely is geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, List, Optional, Tuple


class Layer(IntEnum):
    """Authored compositing bands, lowest drawn first."""

    BACKGROUND = 0
    GROUND_PROP = 10      # props resting on the floor: sorted with actors by depth
    ACTOR = 20            # the cast, and any scenery sorted against it by world depth
    WORLD = 20            # alias of ACTOR: the plane where depth decides who is in front
    HELD_PROP = 30        # anything a hand is holding: always above its holder
    FOREGROUND = 40       # near-camera scenery that occludes the cast
    OVERLAY = 50          # sparkles, dust, effects
    CAPTION = 60          # subtitle band


Draw = Callable[[object], None]


@dataclass(order=False)
class Item:
    layer: Layer
    depth: float
    draw: Draw
    name: str = ""

    def sort_key(self) -> Tuple[int, float]:
        return (int(self.layer), self.depth)


@dataclass
class DrawQueue:
    """Collect drawables, then flush them in layer order."""

    items: List[Item] = field(default_factory=list)

    def add(self, layer: Layer, depth: float, draw: Draw, name: str = "") -> None:
        self.items.append(Item(layer=layer, depth=float(depth), draw=draw, name=name))

    def add_actor(self, depth: float, draw: Draw, name: str = "") -> None:
        self.add(Layer.ACTOR, depth, draw, name)

    def add_prop(self, depth: float, draw: Draw, *, held: bool, name: str = "") -> None:
        self.add(Layer.HELD_PROP if held else Layer.GROUND_PROP, depth, draw, name)

    def flush(self, cr) -> List[str]:
        """Draw everything and return the order used, which is what a test can assert on."""

        order = []
        for item in sorted(self.items, key=lambda entry: entry.sort_key()):
            item.draw(cr)
            order.append(item.name or f"layer{int(item.layer)}")
        self.items.clear()
        return order

    def plan(self) -> List[Tuple[str, int, float]]:
        """The order that *would* be used, without drawing - for tests and reports."""

        return [(item.name, int(item.layer), item.depth)
                for item in sorted(self.items, key=lambda entry: entry.sort_key())]


def actor_depth(feet_y: float) -> float:
    return float(feet_y)


def ground_prop_depth(centre_y: float) -> float:
    return float(centre_y)


def held_prop_depth(holder_feet_y: float, *, above: float = 1.0) -> float:
    """A held prop sorts above its holder whatever its own screen position.

    The depth is deliberately the holder's own depth plus a hair, so within HELD_PROP the order is
    stable and two held props do not flicker against each other.
    """

    return float(holder_feet_y) + above


def occlusion_fraction(mask: bytes, stride: int, box: Tuple[int, int, int, int],
                       width: int) -> float:
    """Fraction of a bounding box covered by a mask's alpha (used for occlusion measurement)."""

    left, top, right, bottom = box
    covered = total = 0
    for y in range(max(0, top), min(bottom, (len(mask) // max(1, stride))), 2):
        row = y * stride
        for x in range(max(0, left), min(right, width), 2):
            offset = row + x * 4
            if offset + 3 < len(mask):
                total += 1
                if mask[offset + 3]:
                    covered += 1
    return covered / total if total else 0.0
