"""Dynamic Camera Engine for 2D Animation.
Provides zoom, smooth tracking pan, and impact screen shake.
"""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple
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
    # Landscape vocabulary (T41). A 16:9 frame has somewhere for a camera to move sideways, and a
    # dialogue needs shot/reverse-shot, so these exist as named moves rather than as one "medium".
    "wide_establishing", "two_shot_hold", "tracking_left", "tracking_right",
    "medium_chiku", "medium_gappu", "reaction_chiku", "reaction_gappu",
)

# Read from the character schemas, which are the single source of truth for where a character
# stands. The camera used to carry its own copy of these numbers, and the renderer a third, so
# moving a character desynchronised the framing from the drawing (T39).
from studio.animation.framing import MAX_ZOOM, MIN_ZOOM  # noqa: E402
from studio.characters.schema import load_schema  # noqa: E402  (kept below Camera on purpose)

_SUBJECT_X_CACHE: dict = {}


def subject_x(name: str) -> float:
    """World x of a character's anchor, straight from its schema."""

    if name not in _SUBJECT_X_CACHE:
        _SUBJECT_X_CACHE[name] = float(load_schema(name).anchor["x"])
    return _SUBJECT_X_CACHE[name]


class _SubjectX(dict):
    """Mapping view over the schemas, so `SUBJECT_X["chiku"]` still works for callers."""

    def __getitem__(self, name):
        return subject_x(name)


SUBJECT_X = _SubjectX()

# Where the framing puts the subject's head. A composition choice (headroom above, subtitle band
# below), not geometry, so it stays a constant.
FACE_Y = 1180.0

# Where a pair shot puts the cast's vertical centre, as a fraction of frame height. The vertical
# value is the ratio the pre-T39 pair shots produced at zoom 1.12, so the wide shot keeps its
# composition exactly; at zoom 1.0 the same rule lifts the pair by 44 px, which is the one part of
# this change that restyles existing shots (measured, not assumed). The landscape value pulls the
# cast up, because a 16:9 frame has no room to waste under it.
PAIR_TARGET_RATIO_VERTICAL = 0.7125
PAIR_TARGET_RATIO_LANDSCAPE = 0.55


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
                 viewport: Tuple[int, int] = (1080, 1920), shot=None,
                 face_y: Optional[float] = None,
                 zoom_range: Optional[Tuple[float, float]] = None) -> None:
        self.style = style if style in CAMERA_STYLES else "medium_pan"
        self.duration = max(0.1, float(duration))
        self.vw, self.vh = viewport
        self.center_x = self.vw / 2.0
        self.center_y = self.vh / 2.0
        # A planned shot (T39) says what must be on screen and how tight the frame may get.
        # With no shot the director behaves exactly as it did before shot planning existed.
        self.shot = shot
        # The eye line is a stage property (T41): a 16:9 floor stands the cast higher, so a
        # close-up that centred on the portrait value would frame a character's chest.
        self.face_y = FACE_Y if face_y is None else float(face_y)
        # A stage may allow a wider pull-back than a portrait background can paint.
        self.zoom_range = zoom_range or (MIN_ZOOM, MAX_ZOOM)
        # A cut inside a line (T42b): the style changes at a beat and the move's clock restarts, so
        # the new shot begins with its own push-in rather than half-way through the previous one.
        self.base_style = self.style
        self.cuts: List[Tuple[float, str]] = []

    def cut_to(self, style: str, t: float) -> None:
        """Schedule a new shot from ``t``. Idempotent, so a frame loop may call it every frame."""

        if style not in CAMERA_STYLES:
            return
        for existing_t, existing_style in self.cuts:
            if abs(existing_t - t) < 1e-6 and existing_style == style:
                return
        self.cuts = sorted(self.cuts + [(float(t), style)])
        self.style = style

    def shot_at(self, t: float) -> Tuple[str, float]:
        """The style in effect at ``t`` and when it started.

        A cut must not reach backwards: before this, calling ``cut_to`` made every earlier frame use
        the *new* style, so a scene that cut once at four seconds opened on the second shot.
        """

        style, start = self.base_style, 0.0
        for at, s in self.cuts:
            if t + 1e-9 >= at:
                style, start = s, at
        return style, start

    @property
    def subject(self) -> Optional[str]:
        """The character this framing is about, if it is a close-up."""

        if self.shot is not None:
            return self.shot.subject
        if self.style == "close_up_chiku":
            return "chiku"
        if self.style == "close_up_gappu":
            return "gappu"
        return None

    # -- helpers ------------------------------------------------------------

    def _centre_on(self, subject: str, zoom: float,
                   target_y_ratio: float = 0.42,
                   live_x: Optional[float] = None) -> Tuple[float, float]:
        """Pan that puts the subject's face on the frame's vertical centre-line.

        ``Camera.apply`` maps x to ``center + zoom * (x - center - pan)``, so centring x is
        independent of the zoom, while the vertical pan must compensate for it: the face is
        placed a little above centre so the framing has headroom and the subtitle band stays
        clear.
        """

        pan_x = (live_x if live_x is not None else subject_x(subject)) - self.center_x
        target_y = self.vh * target_y_ratio
        pan_y = self.face_y - self.center_y + (self.center_y - target_y) / zoom
        return pan_x, pan_y

    def project(self, x: float, y: float, frame: CameraFrame) -> Tuple[float, float]:
        """Where a world point lands on screen for a given frame (same maths as apply())."""

        return (
            self.center_x + frame.zoom * (x - self.center_x - frame.pan_x),
            self.center_y + frame.zoom * (y - self.center_y - frame.pan_y),
        )

    # -- the move -----------------------------------------------------------

    def _style_frame(self, t: float, u: float, style: str) -> CameraFrame:
        """The style's own move, with no knowledge of what has to fit."""

        if style == "two_shot_zoom":
            return CameraFrame(zoom=1.0 + 0.13 * u, pan_x=0.0, pan_y=-0.02 * self.vh * u)
        if style == "wide_finish":
            return CameraFrame(zoom=1.12 - 0.12 * u, pan_x=0.0, pan_y=0.0)
        if style == "action_shake":
            return CameraFrame(zoom=1.04 + 0.03 * u, pan_x=0.0, pan_y=0.0)
        if style == "two_shot":
            return CameraFrame(zoom=1.0, pan_x=0.0, pan_y=0.0)
        if style == "two_shot_hold":
            # The calm version: no drift at all, so a joke can land without the frame wandering.
            return CameraFrame(zoom=1.25, pan_x=0.0, pan_y=0.0)
        if style == "wide_establishing":
            # Open wide and settle in, which is what an establishing shot is for.
            return CameraFrame(zoom=0.86 + 0.16 * u, pan_x=0.0, pan_y=0.0)
        if style == "tracking_left":
            return CameraFrame(zoom=1.18, pan_x=-52.0 * u, pan_y=0.0)
        if style == "tracking_right":
            return CameraFrame(zoom=1.18, pan_x=52.0 * u, pan_y=0.0)
        if style.startswith("reaction_"):
            return CameraFrame(zoom=1.30 + 0.22 * u, pan_x=0.0, pan_y=0.0)
        if style.startswith("medium_") and style != "medium_pan":
            # `medium_pan` is the original portrait style and keeps its slow drift below; it only
            # shares a prefix with the landscape subject-medium shots. Matching it here silently
            # changed every portrait scene that uses it from zoom ~1.01 to 1.30.
            return CameraFrame(zoom=1.30 + 0.04 * u, pan_x=0.0, pan_y=0.0)
        drift = math.sin(t * 0.36 - 0.4) * 26.0 * (0.35 + 0.65 * min(1.0, t / 1.5))
        return CameraFrame(zoom=1.01 + 0.03 * u, pan_x=drift, pan_y=0.0)

    def state_at(self, t: float, positions: Optional[dict] = None) -> CameraFrame:
        # Cuts restart the clock: without this the second shot of a line would open at the zoom the
        # first shot had already pushed to, which reads as a jump rather than a cut. Frames *before*
        # the cut keep their own time - clamping them to zero silently changed the opening of every
        # scene that had a cut anywhere in it.
        style, cut_start = self.shot_at(t)
        if cut_start:
            t = t - cut_start
        u = _smoothstep(t / self.duration)
        shot = self.shot

        if shot is not None and shot.kind == "close_up":
            # Track the subject where it actually is this frame. It can be walking, pushed aside
            # by the separation clamp, or shifted by a performance beat, and a close-up that
            # used the nominal anchor would drift off the character's face.
            name = shot.subjects[0]
            live_x = float((positions or {}).get(name, subject_x(name)))
            zoom = 1.06 + max(0.0, shot.zoom - 1.06) * _smoothstep(min(1.0, t / 0.9))
            target_y = self.vh * 0.42
            pan_y = self.face_y - self.center_y + (self.center_y - target_y) / zoom
            settle = _smoothstep(min(1.0, t / 0.6))
            return CameraFrame(zoom=zoom, pan_x=(live_x - self.center_x) * settle,
                               pan_y=pan_y * settle)

        if shot is not None:
            # Pair and wide shots centre the pair rather than the frame, because the two
            # characters do not sit symmetrically about the middle: chiku is 160 px off-centre.
            base = self._style_frame(t, u, style)
            # The style keeps its own move (a slow push-in, a settle) but can never exceed the
            # shot's limit, which is the widest zoom that still holds every required subject.
            zoom = min(base.zoom, shot.limit)
            pan_x = shot.centre_x - self.center_x + base.pan_x
            # Vertical framing has to follow the viewport. A 9:16 frame has room below the cast
            # (subtitle band) and the target ratio below reproduces the existing composition to
            # within a third of a pixel, so existing episodes do not move. A 16:9 frame is short:
            # leaving pan_y at zero there put the characters below the bottom edge entirely.
            target = self.vh * (PAIR_TARGET_RATIO_LANDSCAPE if self.vw > self.vh
                                else PAIR_TARGET_RATIO_VERTICAL)
            # The style's vertical drift is replaced by this centring, not added to it: two
            # competing offsets would fight over the same margin.
            pan_y = shot.centre_y - self.center_y + (self.center_y - target) / zoom
            return CameraFrame(zoom=zoom, pan_x=pan_x, pan_y=pan_y)

        if style in ("close_up_chiku", "close_up_gappu"):
            subject = "chiku" if style.endswith("chiku") else "gappu"
            zoom = 1.06 + 0.64 * _smoothstep(min(1.0, t / 0.9))
            pan_x, pan_y = self._centre_on(
                subject, zoom, live_x=float((positions or {}).get(subject, subject_x(subject))))
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
        if style == "two_shot_hold":
            # The calm version: no drift at all, so a joke can land without the frame wandering.
            return CameraFrame(zoom=1.25, pan_x=0.0, pan_y=0.0)
        if style == "wide_establishing":
            # Open wide and settle in, which is what an establishing shot is for.
            return CameraFrame(zoom=0.86 + 0.16 * u, pan_x=0.0, pan_y=0.0)
        if style == "tracking_left":
            return CameraFrame(zoom=1.18, pan_x=-52.0 * u, pan_y=0.0)
        if style == "tracking_right":
            return CameraFrame(zoom=1.18, pan_x=52.0 * u, pan_y=0.0)
        if style.startswith("reaction_"):
            return CameraFrame(zoom=1.30 + 0.22 * u, pan_x=0.0, pan_y=0.0)
        if style.startswith("medium_") and style != "medium_pan":
            # `medium_pan` is the original portrait style and keeps its slow drift below; it only
            # shares a prefix with the landscape subject-medium shots. Matching it here silently
            # changed every portrait scene that uses it from zoom ~1.01 to 1.30.
            return CameraFrame(zoom=1.30 + 0.04 * u, pan_x=0.0, pan_y=0.0)

        # medium_pan and the fallback: a slow lateral drift plus a hint of push-in.
        drift = math.sin(t * 0.36 - 0.4) * 26.0 * (0.35 + 0.65 * min(1.0, t / 1.5))
        return CameraFrame(zoom=1.01 + 0.03 * u, pan_x=drift, pan_y=0.0)
