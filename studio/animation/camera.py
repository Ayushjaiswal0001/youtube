"""Dynamic Camera Engine for 2D Animation.
Provides zoom, smooth tracking pan, and impact screen shake.
"""

import math
import random
from dataclasses import dataclass
from typing import Optional, Tuple
import cairo

class Camera:
    """Controls viewport transformation (pan, zoom, shake)."""

    def __init__(self, viewport_w: int = 1080, viewport_h: int = 1920):
        self.vw = viewport_w
        self.vh = viewport_h
        self.center_x = viewport_w / 2.0
        self.center_y = viewport_h / 2.0

        # State
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.shake_trauma = 0.0  # 0.0 to 1.0

    def trigger_shake(self, trauma: float = 0.6):
        """Triggers an impact screen shake (e.g. on landing or punchline)."""
        self.shake_trauma = min(1.0, self.shake_trauma + trauma)

    def update(self, dt: float):
        """Damps shake trauma over time."""
        if self.shake_trauma > 0.001:
            self.shake_trauma = max(0.0, self.shake_trauma - dt * 2.5)
        else:
            self.shake_trauma = 0.0

    def apply(self, cr: cairo.Context, t: float):
        """Applies current camera transform to Cairo context."""
        # Calculate screen shake displacement
        shake_x = 0.0
        shake_y = 0.0
        if self.shake_trauma > 0:
            intensity = self.shake_trauma ** 2
            shake_x = math.sin(t * 55.0) * 25.0 * intensity
            shake_y = math.cos(t * 65.0) * 20.0 * intensity

        # Transform around viewport center
        cr.translate(self.center_x + shake_x, self.center_y + shake_y)
        cr.scale(self.zoom, self.zoom)
        cr.translate(-self.center_x - self.pan_x, -self.center_y - self.pan_y)


# ---------------------------------------------------------------------------
# Camera direction (T35)
# ---------------------------------------------------------------------------
# The renderer used to hard-code two zooms and one slow sine pan, so a scene labelled
# "close_up_chiku" zoomed the middle of the frame instead of framing Chiku. A style is now
# a short, explicit camera move evaluated per frame.

CAMERA_STYLES: Tuple[str, ...] = (
    "medium_pan", "two_shot", "two_shot_zoom", "close_up_chiku", "close_up_gappu",
    "wide_finish", "action_shake",
)

SUBJECT_X = {"chiku": 380.0, "gappu": 780.0}
FACE_Y = 1180.0


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@dataclass(frozen=True)
class CameraFrame:
    """Camera state for one frame."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0


class CameraDirector:
    """Deterministic camera move for one scene.

    A style names the move; the move is a function of scene progress only, so the same scene
    renders identically every time and a cut can be re-timed without re-rendering.
    """

    def __init__(self, style: str = "medium_pan", duration: float = 6.0,
                 viewport: Tuple[int, int] = (1080, 1920)) -> None:
        self.style = style if style in CAMERA_STYLES else "medium_pan"
        self.duration = max(0.1, float(duration))
        self.vw, self.vh = viewport
        self.center_x = self.vw / 2.0
        self.center_y = self.vh / 2.0

    @property
    def subject(self) -> Optional[str]:
        """The character this framing is about, if it is a close-up."""

        if self.style == "close_up_chiku":
            return "chiku"
        if self.style == "close_up_gappu":
            return "gappu"
        return None

    # -- helpers ------------------------------------------------------------

    def _centre_on(self, subject: str, zoom: float,
                   target_y_ratio: float = 0.42) -> Tuple[float, float]:
        """Pan that puts the subject's face on the frame's vertical centre-line.

        ``Camera.apply`` maps x to ``center + zoom * (x - center - pan)``, so centring x is
        independent of the zoom, while the vertical pan must compensate for it: the face is
        placed a little above centre so the framing has headroom and the subtitle band stays
        clear.
        """

        pan_x = SUBJECT_X[subject] - self.center_x
        target_y = self.vh * target_y_ratio
        pan_y = FACE_Y - self.center_y + (self.center_y - target_y) / zoom
        return pan_x, pan_y

    def project(self, x: float, y: float, frame: CameraFrame) -> Tuple[float, float]:
        """Where a world point lands on screen for a given frame (same maths as apply())."""

        return (
            self.center_x + frame.zoom * (x - self.center_x - frame.pan_x),
            self.center_y + frame.zoom * (y - self.center_y - frame.pan_y),
        )

    # -- the move -----------------------------------------------------------

    def state_at(self, t: float) -> CameraFrame:
        u = _smoothstep(t / self.duration)
        style = self.style

        if style in ("close_up_chiku", "close_up_gappu"):
            subject = "chiku" if style.endswith("chiku") else "gappu"
            zoom = 1.06 + 0.64 * _smoothstep(min(1.0, t / 0.9))
            pan_x, pan_y = self._centre_on(subject, zoom)
            # Ease in from a two-shot framing so the cut does not feel like a jump cut.
            settle = _smoothstep(min(1.0, t / 0.6))
            return CameraFrame(zoom=zoom, pan_x=pan_x * settle, pan_y=pan_y * settle)

        if style == "two_shot_zoom":
            return CameraFrame(zoom=1.0 + 0.13 * u, pan_x=0.0, pan_y=-0.02 * self.vh * u)

        if style == "wide_finish":
            return CameraFrame(zoom=1.12 - 0.12 * u, pan_x=0.0, pan_y=0.0)

        if style == "action_shake":
            return CameraFrame(zoom=1.04 + 0.03 * u, pan_x=0.0, pan_y=0.0)

        if style == "two_shot":
            return CameraFrame(zoom=1.0, pan_x=0.0, pan_y=0.0)

        # medium_pan and the fallback: a slow lateral drift plus a hint of push-in.
        drift = math.sin(t * 0.36 - 0.4) * 26.0 * (0.35 + 0.65 * min(1.0, t / 1.5))
        return CameraFrame(zoom=1.01 + 0.03 * u, pan_x=drift, pan_y=0.0)
