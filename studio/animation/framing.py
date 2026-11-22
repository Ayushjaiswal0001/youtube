"""Shot planning and framing verification (T39).

The camera used to be a style with no idea what it was pointing at. `close_up_chiku` zoomed to
1.70 around x=380 because someone worked that out by eye once, and nothing checked that the
characters - let alone the gesture they were performing - were inside the frame. A gesture aimed
at a partner could be aimed at empty frame, and nothing detected it.

This module separates the two things that were fused together in `camera.py`:

* **geometry** - where a character actually is in world space, how big it is drawn, and whether a
  given camera frame contains it. This is arithmetic, and it can be tested;
* **the shot decision** - given the script's intent, the participants, and which characters must
  be on screen, pick the framing (and escalate a crop to a wider shot rather than shipping it).

The camera keeps the *move* (easing, drift, shake). It asks this module *what to cover*.

Both aspects are supported by construction: every fit is expressed against the viewport the
caller passes, so 1080x1920 and 1920x1080 take the same code path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping, Optional, Sequence, Tuple

# Fraction of the frame kept clear of the subject at the edge. It also keeps a character's
# silhouette off the frame line, which reads as a mistake rather than a composition.
DEFAULT_MARGIN = 0.055

# How far a gesture swings the arm past the body, as a fraction of the rig's arm length. Used to
# widen a subject's box while it is gesturing so the reach is covered, not just the torso.
GESTURE_REACH = 1.0

# Zoom bounds. Below 1.0 the frame would show art the background never drew; above 2.2 a 2D rig
# starts to look like a xerox rather than a drawing.
MIN_ZOOM = 0.85
MAX_ZOOM = 2.2

# Shot kinds, widest last. Escalation only ever moves right.
SHOT_ORDER = ("close_up", "medium", "two_shot", "wide")


@dataclass(frozen=True)
class Subject:
    """A character's drawn extent in world space, at its current position."""

    name: str
    x: float
    y: float
    half_w: float
    top: float
    bottom: float
    # Half-width while an arm is fully extended toward the partner. Bigger than `half_w`, so a
    # gesture cannot quietly leave the frame.
    reach: float = 0.0

    def bounds(self, reach: float = 0.0) -> Tuple[float, float, float, float]:
        """``(x0, y0, x1, y1)`` in world space, widened by ``reach`` when gesturing."""

        half = max(self.half_w, self.reach * max(0.0, min(1.0, reach)))
        return (self.x - half, self.top, self.x + half, self.bottom)

    def moved(self, x: float) -> "Subject":
        return replace(self, x=float(x))


def subject_from_schema(name: str, schema) -> Subject:
    """Build a subject box from a character schema.

    The schema is the single source of truth for geometry: anchors, scale and proportions. The
    old camera module carried its own copy of the anchors, and the renderer a third, so moving a
    character desynchronised the framing from the drawing.
    """

    prop = schema.proportions.values
    anchor = schema.anchor
    scale = float(anchor.get("scale", 1.0))
    x = float(anchor["x"])
    y = float(anchor["y"])

    # Shoulders out to a hanging hand, or the shadow, whichever is wider.
    body_half = max(float(prop.get("torso_rx", 60.0)),
                    float(prop.get("shadow_rx", prop.get("torso_rx", 60.0))),
                    float(prop.get("arm_attach_x", 0.0)) + float(prop.get("arm_r", 12.0)))
    reach = (float(prop.get("arm_attach_x", 0.0)) + float(prop.get("arm_len", 60.0))
             * GESTURE_REACH + float(prop.get("hand_rx", 12.0)))
    # Feet are 10 px below the anchor; the top of the head is the head ellipse plus its offset.
    top = y + (float(prop.get("head_center_y", 0.0)) + float(prop.get("head_draw_y", 0.0))
               - float(prop.get("head_ry", 60.0)) - 18.0) * scale
    bottom = y + 10.0 * scale
    return Subject(name=name, x=x, y=y, half_w=body_half * scale, top=top, bottom=bottom,
                   reach=reach * scale)


# ---------------------------------------------------------------------------
# Frame geometry
# ---------------------------------------------------------------------------


def project(x: float, y: float, zoom: float, pan_x: float, pan_y: float,
            viewport: Tuple[int, int]) -> Tuple[float, float]:
    """Where a world point lands on screen. Mirrors ``Camera.apply`` exactly."""

    vw, vh = viewport
    cx, cy = vw / 2.0, vh / 2.0
    return cx + zoom * (x - cx - pan_x), cy + zoom * (y - cy - pan_y)


def world_y_for_screen(screen_y: float, zoom: float, pan_y: float,
                       viewport: Tuple[int, int]) -> float:
    """Inverse of ``project`` on the vertical axis: which world row a screen row shows."""

    _, vh = viewport
    cy = vh / 2.0
    return cy + (screen_y - cy) / zoom + pan_y


def frame_box(zoom: float, pan_x: float, pan_y: float,
              viewport: Tuple[int, int]) -> Tuple[float, float, float, float]:
    """The world rectangle a camera frame can see: ``(x0, y0, x1, y1)``."""

    vw, vh = viewport
    cx, cy = vw / 2.0, vh / 2.0
    x0 = cx - (vw / 2.0) / zoom + pan_x
    x1 = cx + (vw / 2.0) / zoom + pan_x
    y0 = cy - (vh / 2.0) / zoom + pan_y
    y1 = cy + (vh / 2.0) / zoom + pan_y
    return x0, y0, x1, y1


def fits(bounds: Tuple[float, float, float, float], zoom: float, pan_x: float, pan_y: float,
         viewport: Tuple[int, int], margin: float = DEFAULT_MARGIN) -> bool:
    """True when every corner of the world box lands inside the frame with a margin."""

    vw, vh = viewport
    mx, my = vw * margin, vh * margin
    x0, y0 = project(bounds[0], bounds[1], zoom, pan_x, pan_y, viewport)
    x1, y1 = project(bounds[2], bounds[3], zoom, pan_x, pan_y, viewport)
    return x0 >= mx and x1 <= vw - mx and y0 >= my and y1 <= vh - my


def overflow(bounds: Tuple[float, float, float, float], zoom: float, pan_x: float, pan_y: float,
             viewport: Tuple[int, int]) -> float:
    """How far, in screen pixels, the box spills outside the frame. 0.0 when it fits."""

    vw, vh = viewport
    x0, y0 = project(bounds[0], bounds[1], zoom, pan_x, pan_y, viewport)
    x1, y1 = project(bounds[2], bounds[3], zoom, pan_x, pan_y, viewport)
    return max(0.0, -x0, x1 - vw, -y0, y1 - vh)


def fit_zoom(bounds: Iterable[Tuple[float, float, float, float]],
             viewport: Tuple[int, int], margin: float = DEFAULT_MARGIN,
             clamp: bool = True, min_zoom: float = MIN_ZOOM,
             max_zoom: float = MAX_ZOOM) -> float:
    """Widest zoom (i.e. least crop) that still fits every box.

    Zoom is a magnification: a *larger* zoom shows *less* world. So the constraint is an upper
    bound per box, and the answer is the smallest of them.

    ``clamp`` is deliberately explicit. A 16:9 frame is wide enough that the geometric bound can
    exceed ``MAX_ZOOM``, and silently clamping there would return a zoom at which the boxes do
    *not* fit - breaking this function's own promise. Callers that need the raw bound pass
    ``clamp=False``; the pair shots keep the clamp and rely on the vertical framing to place the
    characters, which is why a 16:9 character renderer needs its own vertical rules.
    """

    boxes = [box for box in bounds]
    if not boxes:
        return 1.0
    vw, vh = viewport
    usable_w = vw * (1.0 - 2.0 * margin)
    usable_h = vh * (1.0 - 2.0 * margin)
    x0 = min(box[0] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y0 = min(box[1] for box in boxes)
    y1 = max(box[3] for box in boxes)
    span_w = max(1.0, x1 - x0)
    span_h = max(1.0, y1 - y0)
    zoom = min(usable_w / span_w, usable_h / span_h)
    if not clamp:
        return max(1e-3, zoom)
    return max(min_zoom, min(max_zoom, zoom))


def screen_box(bounds: Tuple[float, float, float, float], zoom: float, pan_x: float,
               pan_y: float, viewport: Tuple[int, int]) -> Tuple[float, float, float, float]:
    """World box projected into screen space, normalised so x0 < x1 and y0 < y1."""

    x0, y0 = project(bounds[0], bounds[1], zoom, pan_x, pan_y, viewport)
    x1, y1 = project(bounds[2], bounds[3], zoom, pan_x, pan_y, viewport)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def overlap_area(a: Tuple[float, float, float, float],
                 b: Tuple[float, float, float, float]) -> float:
    """Area shared by two screen rectangles. 0.0 when they do not touch."""

    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return float(width * height)


def opaque_rect(surface, alpha_threshold: int = 16) -> Optional[Tuple[float, float, float, float]]:
    """Bounding rectangle of a Cairo surface's non-transparent pixels.

    The subtitle overlay is a full-frame PNG with a caption band inside it. Measuring the band
    from the overlay itself means occlusion is computed against the artwork that will really be
    painted, instead of against a number someone typed.
    """

    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    span = stride // 4
    # ARGB32 is premultiplied BGRA in memory; alpha is byte 3 of each pixel. Only rows and
    # columns that contain alpha are wanted, so this scans the alpha plane, not the colours.
    columns = [False] * width
    top = bottom = -1
    for y in range(height):
        row = data[y * stride: y * stride + width * 4]
        alphas = row[3::4]
        if max(alphas) <= alpha_threshold:
            continue
        if top < 0:
            top = y
        bottom = y
        for x in range(width):
            if alphas[x] > alpha_threshold:
                columns[x] = True
    if top < 0:
        return None
    xs = [x for x, hit in enumerate(columns) if hit]
    if not xs:
        return None
    return (float(min(xs)), float(top), float(max(xs) + 1), float(bottom + 1))


def centre_of(bounds: Iterable[Tuple[float, float, float, float]]) -> Tuple[float, float]:
    boxes = list(bounds)
    if not boxes:
        return 0.0, 0.0
    return ((min(box[0] for box in boxes) + max(box[2] for box in boxes)) / 2.0,
            (min(box[1] for box in boxes) + max(box[3] for box in boxes)) / 2.0)


# ---------------------------------------------------------------------------
# The shot decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    """What to cover, and how tightly."""

    kind: str
    subjects: Tuple[str, ...]
    zoom: float
    centre_x: float
    centre_y: float
    scripted: str = ""
    escalated: bool = False
    reason: str = ""
    # The tightest zoom that still holds every required subject. `zoom` is what the shot asks
    # for; `limit` is what it may not exceed. Keeping them apart lets a style keep its push-in
    # (two_shot_zoom) while still being unable to crop anyone out.
    limit: float = MAX_ZOOM

    @property
    def subject(self) -> Optional[str]:
        return self.subjects[0] if len(self.subjects) == 1 else None


def _subject_style(style: str) -> Optional[str]:
    """The character a single-subject style is about, if any.

    Landscape dialogue needs a medium shot *of* one character (shot/reverse-shot), which is neither
    a close-up nor a relational two-shot. The style name carries the subject, as it does for
    close-ups.
    """

    for prefix in ("close_up_", "reaction_", "medium_"):
        if style.startswith(prefix):
            return style[len(prefix):]
    return None


def _scripted_kind(style: str) -> str:
    if style.startswith("close_up"):
        return "close_up"
    if style.startswith("reaction_"):
        return "close_up"
    if style.startswith("medium_") and style != "medium_pan":
        return "subject_medium"
    if style in ("two_shot", "two_shot_zoom", "two_shot_hold", "action_shake",
                 "tracking_left", "tracking_right"):
        return "two_shot"
    if style.startswith("wide"):
        return "wide"
    return "medium"


def _order_index(kind: str) -> int:
    """Where a kind sits in the widening order: a subject medium sits where a medium does."""

    if kind == "subject_medium":
        return SHOT_ORDER.index("medium")
    return SHOT_ORDER.index(kind)


def _kind_zoom(kind: str) -> float:
    """The zoom a kind asks for when nothing needs to fit tighter than it."""

    return {"close_up": 1.70, "medium": 1.04, "two_shot": 1.0, "wide": 1.12}.get(kind, 1.0)


def plan_shot(scripted: str, subjects: Mapping[str, Subject], viewport: Tuple[int, int],
              *, speaker: Optional[str] = None, must_show: Sequence[str] = (),
              reach: Mapping[str, float] | None = None,
              extras: Sequence[Tuple[float, float, float, float]] = (),
              margin: float = DEFAULT_MARGIN,
              zoom_range: Tuple[float, float] = (MIN_ZOOM, MAX_ZOOM),
              kind_zoom: Mapping[str, float] | None = None) -> Shot:
    """Choose the framing for one scene.

    The script's style is a request, not an order, and a shot kind carries an implied cast:

    * ``close_up_<name>`` is about one character, so it needs that character - but only if that
      character is the one performing. Pointing a close-up at a silent character while the other
      one gestures is the defect this function exists to stop;
    * ``medium``, ``two_shot`` and ``wide`` are relational shots. They need the whole cast,
      because a "two shot" that frames one character is not one - the first version of this
      function centred the speaker and cropped his partner out of a wide shot entirely.

    Only widening is allowed, never tightening, and a widened shot says so in its reason. Every
    shot reserves each required subject's full arm reach, so a gesture cannot trail outside a
    frame that was planned for the idle silhouette.
    """

    available = dict(subjects)
    cast = list(available)
    must_show = list(must_show or ())
    reach_override = dict(reach or {})

    def reserve(names: Sequence[str]) -> dict:
        reserved = {name: 1.0 for name in names}
        reserved.update({name: value for name, value in reach_override.items()
                         if name in reserved})
        return reserved

    kind = _scripted_kind(scripted)
    start = _order_index(kind)
    # A stage may want a different composition per shot kind (T41): the same "two shot" is a
    # different distance in 16:9 than in 9:16. Absent an override the module defaults apply.
    wanted = dict(kind_zoom or {})

    def aimed(candidate: str) -> float:
        return float(wanted.get(candidate, _kind_zoom(candidate)))

    def subject_shot(name: str, why: str, reason: str, escalated: bool) -> Optional[Shot]:
        box = available[name].bounds(reserve([name])[name])
        limit = min(fit_zoom([box], viewport, margin, min_zoom=zoom_range[0],
                             max_zoom=zoom_range[1]), zoom_range[1])
        zoom = min(aimed(why), limit)
        return Shot("close_up" if why == "close_up" else "medium", (name,), zoom,
                    available[name].x, centre_of([box])[1], scripted,
                    escalated=escalated, reason=reason, limit=limit)

    # A style that names one character - `close_up_<name>`, `medium_<name>` - is a subject shot,
    # not a relational one. Handling it inside the widening loop below meant `medium_gappu` matched
    # the relational "medium" case first and silently became a two-shot that framed both of them,
    # which is why the landscape renders reported "widened from subject_medium to medium" on exactly
    # the scenes that were meant to isolate Gappu.
    named = _subject_style(scripted)
    # `subject_medium` is the kind `_scripted_kind` reports for `medium_<name>`, and it is the one
    # that has to be handled here: leaving it out of this tuple is what let it fall through to the
    # relational "medium" case and become a two-shot.
    if named in available and kind in ("close_up", "medium", "subject_medium"):
        why = "close_up" if kind == "close_up" else "medium"
        off_speaker = (kind == "close_up" and speaker is not None
                       and speaker in available and speaker != named)
        if not off_speaker and not (set(must_show) - {named}):
            return subject_shot(named, why, "", False)

    for candidate in SHOT_ORDER[start:]:
        if candidate == "close_up":
            # Reached only when a subject shot was refused above (an off-speaker close-up, or a
            # must_show the subject cannot satisfy), which is the widening path this loop exists for.
            name = _subject_style(scripted) or ""
            if name not in available:
                continue
            # A close-up is only honest if the character it points at is the one performing. A
            # medium *of* the listener is a legitimate shot and does not carry that rule.
            if kind == "close_up" and speaker is not None and speaker in available and speaker != name:
                continue
            # `must_show` adds characters a shot has to hold; it never narrows a shot. A
            # close-up can only survive it if the extra subjects are nobody but the subject.
            if set(must_show) - {name}:
                continue
            box = available[name].bounds(reserve([name])[name])
            limit = min(fit_zoom([box], viewport, margin, min_zoom=zoom_range[0],
                                 max_zoom=zoom_range[1]), zoom_range[1])
            why = "close_up" if kind == "close_up" else "medium"
            zoom = min(aimed(why), limit)
            return Shot("close_up", (name,), zoom, available[name].x, centre_of([box])[1],
                        scripted, escalated=(candidate != kind),
                        reason="" if candidate == kind
                        else f"widened from {kind} to {why} of {name}", limit=limit)

        # Relational shots hold the whole cast, and `must_show` can only add to that.
        required = list(cast)
        required += [name for name in must_show if name not in required]
        reserved = reserve(required)
        # A prop the scene is about has to be in frame too, but it is not cast: it must not
        # change which characters the shot holds, only how wide the frame has to be.
        boxes = [available[name].bounds(reserved[name]) for name in required]
        boxes += [tuple(box) for box in extras]
        limit = min(fit_zoom(boxes, viewport, margin, min_zoom=zoom_range[0],
                             max_zoom=zoom_range[1]), zoom_range[1])
        zoom = min(aimed(candidate), limit)
        cx, cy = centre_of(boxes)
        return Shot(candidate, tuple(required), zoom, cx, cy, scripted,
                    escalated=(candidate != kind),
                    reason="" if candidate == kind else f"widened from {kind} to {candidate}",
                    limit=limit)

    required = list(cast)
    reserved = reserve(required)
    boxes = [available[name].bounds(reserved[name]) for name in required]
    limit = min(fit_zoom(boxes, viewport, margin, min_zoom=zoom_range[0],
                         max_zoom=zoom_range[1]), zoom_range[1])
    zoom = min(aimed("wide"), limit)
    cx, cy = centre_of(boxes)
    return Shot("wide", tuple(required), zoom, cx, cy, scripted, True, "fallback wide",
                limit=limit)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass
class FrameRecord:
    t: float
    zoom: float
    visible: dict = field(default_factory=dict)
    overflow: dict = field(default_factory=dict)
    #: True on the first frame after a shot change. A cut is a discontinuity by design, so it must
    #: not be read as a camera move that was too fast - the zoom-rate check exists to catch a *move*
    #: that races, and an in-line cut otherwise failed that check on every episode that had one.
    cut: bool = False


class FramingReport:
    """Per-frame record of what the camera actually covered.

    This is the honest part of T39: the planner's opinion is checked against the frame the
    renderer will really draw, using the same projection maths ``Camera.apply`` uses.
    """

    def __init__(self, viewport: Tuple[int, int], margin: float = DEFAULT_MARGIN,
                 required: Sequence[str] = ()):
        self.viewport = viewport
        self.margin = margin
        # A subject the shot is *for* must never leave the frame. A listener that the shot
        # deliberately excludes is recorded, but is not a failure - a close-up is allowed to
        # crop a reaction.
        self.required = tuple(required)
        self.records: list[FrameRecord] = []

    def add(self, t: float, zoom: float, pan_x: float, pan_y: float,
            subjects: Mapping[str, Subject], reach: Mapping[str, float] | None = None,
            extras: Mapping[str, Tuple[float, float, float, float]] | None = None,
            cut: bool = False) -> None:
        reach = dict(reach or {})
        boxes = {name: subject.bounds(reach.get(name, 0.0))
                 for name, subject in subjects.items()}
        # Props are checked exactly like characters; they are simply not `required` unless the
        # caller says so, which keeps a prop from failing a gate it was never asked to meet.
        boxes.update({name: tuple(box) for name, box in (extras or {}).items()})
        visible, spill = {}, {}
        for name, box in boxes.items():
            visible[name] = fits(box, zoom, pan_x, pan_y, self.viewport, self.margin)
            spill[name] = overflow(box, zoom, pan_x, pan_y, self.viewport)
        self.records.append(FrameRecord(t, zoom, visible, spill, cut))

    def cropped_frames(self, name: str) -> int:
        return sum(1 for record in self.records if not record.visible.get(name, True))

    def worst_overflow(self, name: str) -> float:
        return max([record.overflow.get(name, 0.0) for record in self.records], default=0.0)

    def zoom_rates(self) -> list[float]:
        """Per-frame zoom change in units/second, for the continuity check."""

        rates = []
        for previous, current in zip(self.records, self.records[1:]):
            if current.cut:
                continue
            dt = current.t - previous.t
            if dt > 0:
                rates.append(abs(current.zoom - previous.zoom) / dt)
        return rates

    def summary(self) -> dict:
        names = sorted({name for record in self.records for name in record.visible})
        return {
            "frames": len(self.records),
            "required": list(self.required),
            "cropped_required": sum(self.cropped_frames(name) for name in self.required),
            "subjects": {
                name: {
                    "required": name in self.required,
                    "cropped_frames": self.cropped_frames(name),
                    "worst_overflow_px": round(self.worst_overflow(name), 1),
                    "visible_fraction": round(
                        sum(1 for record in self.records if record.visible.get(name))
                        / max(1, len(self.records)), 4),
                }
                for name in names
            },
            "max_zoom_rate": round(max(self.zoom_rates(), default=0.0), 3),
        }
