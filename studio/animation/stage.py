"""Where the staged world sits inside the frame (T41).

The animation stack worked in one coordinate system - the 1080x1920 portrait stage - and that
assumption was scattered: four module constants in `scene_renderer`, a `FACE_Y` constant inside
`camera.py`, slot positions duplicated in `framing.SUBJECT_X`, and effect origins written as raw
numbers (`460, 1150`, `380, 1460`, `380, 1020`). Two characters only met because someone typed
380 and 780 into the constructor.

A `Stage` names one arrangement of that world: which slots the cast occupies, where the ground is,
where the eyes are, and how far the camera may zoom. The aspect ratio then falls out of the stage
rather than being threaded through every drawing call.

What is deliberately *not* here: character scale, proportions or art. A landscape character is the
same rig at the same scale standing in a different place. Stretching a rig to fill 16:9 would be a
different character, which is exactly the failure this module exists to prevent.

Staging is a composition decision, so the numbers below are measurements of the frame, recorded
with the arithmetic that produced them. `tests/factory/test_stage.py` re-derives the portrait
numbers from the schema so they cannot drift from the rigs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

# Vertical composition of a landscape character shot, as fractions of frame height: feet just
# above the caption zone, a small headroom band at the top, eyes high enough to read.
LANDSCAPE_FOOT_RATIO = 0.93
LANDSCAPE_TOP_RATIO = 0.075

# How far above the feet the eyes sit, as a fraction of the body height, measured from the
# portrait stage (eyes at 1180, feet at 1450, a 958-unit body): 270/958.
EYE_ABOVE_GROUND_RATIO = 0.2818

# Zoom ranges. Portrait keeps the bounds framing.py has always used: below 1.0 the portrait
# backgrounds run out of art because they are drawn with a fixed 1.13 overscan. The landscape
# environment is authored to fill any frame, so a landscape establishing shot may pull back much
# further and still be fully painted.
PORTRAIT_ZOOM = (0.85, 2.2)
LANDSCAPE_ZOOM = (0.62, 2.2)


@dataclass(frozen=True)
class Slot:
    """One character's place on a stage."""

    name: str
    x: float
    y: float
    scale: float
    facing: float


@dataclass(frozen=True)
class Stage:
    """A named arrangement of the world within a viewport."""

    name: str
    width: int
    height: int
    ground_y: float
    eye_y: float
    slots: Mapping[str, Slot]
    zoom_range: Tuple[float, float]

    # -- frame --------------------------------------------------------------

    @property
    def viewport(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def landscape(self) -> bool:
        return self.width > self.height

    @property
    def aspect(self) -> float:
        return self.width / float(self.height)

    @property
    def min_zoom(self) -> float:
        return self.zoom_range[0]

    @property
    def max_zoom(self) -> float:
        return self.zoom_range[1]

    # -- cast ---------------------------------------------------------------

    def slot(self, name: str) -> Slot:
        try:
            return self.slots[name]
        except KeyError:
            raise KeyError(
                f"stage {self.name!r} has no slot for {name!r} "
                f"(has {', '.join(sorted(self.slots))})") from None

    def names(self) -> Tuple[str, ...]:
        return tuple(self.slots)

    def anchor(self, name: str) -> dict:
        """The rig kwargs that place a character on this stage."""

        slot = self.slot(name)
        return {"x": slot.x, "y": slot.y, "scale": slot.scale}

    def positions(self) -> dict:
        return {name: slot.x for name, slot in self.slots.items()}

    def facing(self, name: str) -> float:
        return self.slot(name).facing

    # -- scene-local effect anchors -----------------------------------------
    #
    # Effects used to be written as portrait literals. They are expressed here as offsets from a
    # character's slot so a landscape scene puts the dust at that character's feet rather than at
    # 380 px regardless of where the character now stands.

    def at(self, name: str, dx: float = 0.0, dy: float = 0.0) -> Tuple[float, float]:
        slot = self.slot(name)
        return (slot.x + dx, slot.y + dy)


def _eye_y(ground_y: float, body_height: float) -> float:
    return ground_y - body_height * EYE_ABOVE_GROUND_RATIO


# The portrait stage is the stage every existing episode was rendered on. Its numbers are the
# constants that used to live in scene_renderer.py, unchanged: 380/780, feet at 1450, eyes at 1180.
PORTRAIT_BODY_HEIGHT = 958.0
PORTRAIT = Stage(
    name="portrait",
    width=1080,
    height=1920,
    ground_y=1450.0,
    eye_y=1180.0,
    slots={
        "chiku": Slot("chiku", 380.0, 1450.0, 1.35, 1.0),
        "gappu": Slot("gappu", 780.0, 1450.0, 1.12, -1.0),
    },
    zoom_range=PORTRAIT_ZOOM,
)

# The landscape stage stands the same cast, at the same scale, on a 16:9 floor. Feet sit at 0.93 of
# the frame and the top of the head at 0.075 when the camera is at 0.95, which is the full-body
# two-shot: 958 world units tall spanning 923 px of the 1080 available above the caption zone.
LANDSCAPE_GROUND_Y = 1028.0
LANDSCAPE = Stage(
    name="landscape",
    width=1920,
    height=1080,
    ground_y=LANDSCAPE_GROUND_Y,
    eye_y=_eye_y(LANDSCAPE_GROUND_Y, PORTRAIT_BODY_HEIGHT),
    slots={
        # Spaced so a two-shot has 720 world units between the characters - the frame is 16:9 but
        # the characters are not wider, so the extra width becomes environment, not distance.
        "chiku": Slot("chiku", 600.0, LANDSCAPE_GROUND_Y, 1.35, 1.0),
        "gappu": Slot("gappu", 1320.0, LANDSCAPE_GROUND_Y, 1.12, -1.0),
    },
    zoom_range=LANDSCAPE_ZOOM,
)

STAGES = {(stage.width, stage.height): stage for stage in (PORTRAIT, LANDSCAPE)}


def stage_for(width: int, height: int) -> Stage:
    """The stage for a viewport size.

    Only measured stages are returned: a viewport nobody has staged would silently inherit
    portrait constants and put the cast in the wrong place, so it is an error instead.
    """

    try:
        return STAGES[(int(width), int(height))]
    except KeyError:
        known = ", ".join(f"{w}x{h} ({s.name})" for (w, h), s in STAGES.items())
        raise ValueError(f"no stage for {int(width)}x{int(height)}; known stages: {known}") from None
