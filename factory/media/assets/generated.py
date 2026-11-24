"""Generated diagrams: the visual that explains the sentence it belongs to.

With no image provider and no supplied library, this module decides whether the video shows anything
at all. It draws *pictograms* - a robot arm, video frames, a model graph, force arrows, a substation -
and composes them into schematics that say what the narration says.

Two rules keep it honest:

* The composition comes from what the sentence is about (its entities), not from a rotating template.
* Labels are the sentence's own nouns. Nothing is invented: no numbers are drawn that the narration
  does not assert, and no pictogram claims a specific product or place.

Every diagram is deterministic - a pure function of its spec - so the same episode renders the same
bytes, and the provenance record carries the spec that reproduces it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

SUPERSAMPLE = 2

# Entities we can actually draw. The value is (label, synonyms): a sentence mentioning any synonym
# earns the entity, and the label is what goes on screen.
LEXICON: dict[str, tuple[str, tuple[str, ...]]] = {
    "video": ("video", ("video", "footage", "film", "clip", "watch", "watching", "youtube")),
    "model": ("model", ("model", "network", "policy", "neural", "brain", "infer", "pretrain")),
    "action": ("action", ("action", "force", "forces", "torque", "grip", "grasp", "touch")),
    "robot": ("robot", ("robot", "robots", "machine", "machines", "arm", "automation")),
    "demonstration": ("demos", ("demonstration", "demonstrations", "demos", "demo",
                                "teleoperation", "human")),
    "data": ("data", ("data", "dataset", "examples", "samples", "library")),
    "grid": ("grid", ("grid", "interconnection", "interconnect", "substation", "transmission")),
    "queue": ("queue", ("queue", "backlog", "waiting", "timeline", "timelines", "approval")),
    "energy": ("power", ("power", "electricity", "megawatt", "load", "demand", "solar", "wind")),
    "cost": ("cost", ("cost", "expensive", "cheaper", "price", "slow", "costly", "budget")),
    "time": ("time", ("year", "years", "month", "months", "decade", "future", "later", "next")),
    # Deliberately excludes generic verbs like "learning": they matched sentences that had nothing to do
    # with study and produced a plate labelled STUDY for a sentence about videos.
    "study": ("study", ("study", "sleep", "focus", "memory", "recall", "students")),
}
ENTITY_ORDER = tuple(LEXICON)

# Entities that describe a property of the thing being discussed, not a step in a process. Drawing
# "cost" as a pipeline stage asserts an ordering the narration never states ("demos -> cost -> data"),
# which is exactly the class of invented relationship this module must not produce.
ATTRIBUTE_ENTITIES = frozenset({"cost", "time"})

# Compositions that only make sense with two different things on screen. A single-entity video got
# `IndexError: list index out of range` from both of these before the guard below existed.
NEEDS_TWO = frozenset({"gap", "comparison", "topology", "panels"})

# A sentence that explicitly compares things earns a comparison; one that merely states a property
# does not. Without this distinction "human demonstrations are slow and costly" was drawn as a
# "demos vs data" comparison, which is neither what it says nor a relationship it asserts.
_COMPARATIVE = re.compile(
    r"\b(more|fewer|less|than|versus|vs|compare|compared|twice|double|half)\b", re.IGNORECASE)

# The cue that actually splits a sentence into two sides. "more" alone ("more slowly") contrasts
# nothing, so the pair test below needs one of these.
_COMPARATOR = re.compile(
    r"\b(?:versus|vs\.?|than|compared\s+(?:to|with)|less\s+like|more\s+like|instead\s+of)\b",
    re.IGNORECASE)


def comparison_pair(entities: list[str], text: str) -> tuple[str, str] | None:
    """The two entities a comparative sentence actually contrasts, or None.

    "The future of robot training looks less like programming and more like a very large video
    library" mentions four lexicon nouns; drawing TIME vs ROBOT because those came first would assert
    a relationship the sentence never makes. The sentence does put one thing on each side of the cue,
    and that pair is the one to draw.
    """

    if len(entities) < 2:
        return None
    def subject(side: list[str]) -> str:
        # A property ("cost", "time") is what the sentence says about a subject, so it is only the
        # thing being contrasted when the side names nothing else.
        concrete = [entity for entity in side if entity not in ATTRIBUTE_ENTITIES]
        return (concrete or side)[0]

    for match in _COMPARATOR.finditer(text):
        left = [entity for entity in entities_in(text[:match.start()]) if entity in entities]
        right = [entity for entity in entities_in(text[match.end():]) if entity in entities]
        if left and right and subject(left) != subject(right):
            return subject(left), subject(right)
    return None

STOPWORDS = frozenset(
    "the a an and or but so then now that this these those it its is are was were be been being "
    "to of in on at for with from by as not no more most less than very much many few into over "
    "under about after before while when where which who whom what how why can could would should "
    "will may might must do does did done has have had they them their we our you your he she his "
    "her i me my us one two three also just only even still because instead there here lets looks "
    "let look like get gets makes make made uses use used needs need turns turn keeps keep".split()
)

BOLD_CANDIDATES = ("Inter-Black.otf", "Inter-ExtraBold.otf", "Inter-Bold.otf", "Caladea-Bold.ttf")
MONO_CANDIDATES = ("Inter-ExtraBold.otf", "Inter-Bold.otf", "Caladea-Bold.ttf")


def font(names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    # Import the fonts directory from config, not from the renderer: the renderer imports this package,
    # and a lazy import back into it is a circular dependency waiting to bite at import time.
    from ...config import FONTS_DIR

    for name in names:
        candidate = FONTS_DIR / name
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


@dataclass(frozen=True)
class DiagramSpec:
    """Everything needed to reproduce a diagram, and nothing that depends on the environment.

    ``figures`` carries the figures the sentence states, as ``(phrase, value, unit)``. ``value`` is
    None for a vague quantifier ("thousands", "half"): it is on the card as words and can never become
    a number. ``note`` records why a requested visual was not delivered (a chart with no stated figure,
    a statement with no subject), so the gap is auditable rather than silent.
    """

    variant: str
    title: str
    entities: tuple[str, ...]
    emphasis: str
    palette: tuple[str, str, str, str, str]   # bg, panel, accent, accent2, text
    figures: tuple[tuple[str, float | None, str], ...] = ()
    # The words the narration uses for each figure ("human demonstrations", "video"), so a bar is
    # labelled with the subject it belongs to instead of repeating its own number.
    figure_labels: tuple[str, ...] = ()
    note: str = ""

    def canonical(self) -> str:
        return json.dumps({"v": self.variant, "t": self.title, "e": list(self.entities),
                           "m": self.emphasis, "p": list(self.palette),
                           "f": [list(figure) for figure in self.figures],
                           "l": list(self.figure_labels), "n": self.note},
                          sort_keys=True, ensure_ascii=False)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    @property
    def asset_id(self) -> str:
        return f"gen-{self.variant}-{self.digest[:8]}"

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(LEXICON[entity][0] for entity in self.entities)


# Synonym -> entity, so a word is matched once rather than scanned per entity.
_SYNONYM_INDEX: dict[str, str] = {
    synonym: entity for entity, (_, synonyms) in LEXICON.items() for synonym in synonyms
}


def _singular_forms(word: str) -> tuple[str, ...]:
    """The word plus its singular, so "videos" finds "video" and "studies" finds "study".

    The lexicon used to miss every plural: "learning from videos" matched nothing for video, which is
    how the plate ended up saying STUDY (via a different, wrong synonym) instead of VIDEO.
    """

    forms = [word]
    if word.endswith("ies") and len(word) > 4:
        forms.append(word[:-3] + "y")
    if word.endswith("s") and len(word) > 3:
        forms.append(word[:-1])
    return tuple(forms)


def entities_in(text: str, limit: int = 4) -> list[str]:
    """Entities the sentence is about, in the order the narration introduces them."""

    words = [word.strip(".,;:!?\"'()").lower() for word in
             text.replace("-", " ").replace("/", " ").split()]
    first_hit: dict[str, int] = {}
    for index, word in enumerate(words):
        for form in _singular_forms(word):
            entity = _SYNONYM_INDEX.get(form)
            if entity is not None and entity not in first_hit:
                first_hit[entity] = index
                break
    ordered = sorted(first_hit.items(), key=lambda pair: (pair[1], ENTITY_ORDER.index(pair[0])))
    return [entity for entity, _ in ordered][:limit]


def content_words(text: str, limit: int = 3) -> list[str]:
    """Fallback labels when a sentence names nothing drawable: its own longest nouns."""

    seen: list[str] = []
    for raw in text.replace(":", " ").replace(",", " ").replace(".", " ").split():
        word = raw.strip(".,;:!?\"'()").lower()
        if len(word) > 4 and word not in STOPWORDS and word not in seen and not word.endswith("ly"):
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def choose_variant(entities: list[str], text: str) -> str:
    """Pick the composition that explains this sentence."""

    lowered = f" {text.lower()} "
    lowered = lowered.replace("cannot", " can not ")
    if any(word in lowered for word in (" follow ", " subscribe ", " comment ", " share ",
                                        " like this ", " hit the bell ")):
        return "cta"

    def has(*needles: str) -> bool:
        return any(needle in lowered for needle in needles)

    if len(entities) >= 2 and has(" not ", " gap ", " missing ", " without ", " short of ", " instead "):
        return "gap"
    if comparison_pair(entities, text) is not None:
        return "comparison"
    # The components drawer is a labelled cutaway ("shoulder, elbow, gripper"), which asserts the
    # sentence is about hardware parts. Ordinary robotics prose mentions "arm" and "grasp" constantly,
    # so only an explicit part word earns that plate.
    if has(" joint ", " gripper ", " motor ", " sensor ", " actuator ", " end effector "):
        return "components"
    if has(" layer ", " stack ", " architecture ", " pipeline ", " stage "):
        return "layers"
    if has(" grid ", " interconnection ", " substation ", " queue ", " backlog "):
        return "topology"
    sequenced = has_sequence_cue(lowered)
    if sequenced and has(" year ", " years ", " month ", " months ", " decade ", " future ", " next "):
        return "timeline"
    if sequenced and len(entities) >= 2:
        return "pipeline"
    # Today's sentences often state two things without ordering or comparing them. Panels say only
    # "both of these are in this sentence", which is the one claim that is always true.
    if len(entities) >= 2:
        return "panels"
    return "statement"


_TRAILING_STOPWORDS = frozenset("for on the in and of to a an with at by from".split())
CC_TITLE_CHARS = 30


def short_title(text: str, *, max_chars: int = 30) -> str:
    """A plate title that fits: whole words, no mid-word cut, no dangling preposition.

    "A ROBOT ARM NEEDS THOUSANDS OF EXA" - the first version truncated on a character count, so every
    long sentence produced a broken word in the most prominent line on the card.
    """

    words = str(text or "").strip().split()
    kept: list[str] = []
    for word in words:
        candidate = " ".join([*kept, word])
        if len(candidate) > max_chars:
            break
        kept.append(word)
    while kept and kept[-1].lower().strip(".,:;") in _TRAILING_STOPWORDS:
        kept.pop()
    title = " ".join(kept)
    return title or " ".join(words[:2]) or "VISUAL"


_LADDER: dict[str, tuple[str, ...]] = {
    "pipeline": ("topology", "timeline"),
    "gap": ("comparison", "pipeline"),
    "comparison": ("pipeline", "panels", "gap"),
    "panels": ("pipeline", "timeline"),
    "topology": ("pipeline", "timeline"),
    "components": ("pipeline", "topology"),
    "layers": ("pipeline", "topology"),
    "timeline": ("pipeline", "topology"),
    "cta": ("cta",),
    "statement": ("pipeline", "timeline"),
    "bars": ("ratio", "panels"),
    "ratio": ("bars", "statement"),
}


def spec_for(*, concept: str, narration: str, objective: str,
             colors: dict[str, str], variant: str | None = None,
             on_screen: str | None = None, avoid: tuple[str, ...] = (),
             figures: tuple[tuple[str, float | None, str], ...] = (),
             category: str = "", chart_values: bool = True) -> DiagramSpec:
    entities = entities_in(f"{narration} {concept}")
    # The narration is the authority for what the plate may claim; the on-screen headline only helps
    # choose a composition style. A headline that says "video versus model" over a sentence about
    # video alone must not produce a plate asserting a contest.
    sentence_pair = comparison_pair(entities, narration)
    # v1.0 appended a "data" entity when a sentence named nothing it recognised, which put a noun on
    # the plate that the narration never said. A sentence with no subject gets a statement, not an
    # invented one.
    chosen = variant or choose_variant(entities, f"{concept} {narration} {objective}")
    note = ""
    stageable = [entity for entity in entities if entity not in ATTRIBUTE_ENTITIES]
    attributes = [entity for entity in entities if entity in ATTRIBUTE_ENTITIES]

    # Two identical compositions back to back read as a rendering bug. When the previous scene used
    # the same one, step down a fixed ladder to the next composition that still explains the sentence -
    # skipping alternatives that need two subjects when only one is available.
    if chosen in avoid:
        for alternative in _LADDER.get(chosen, ()):
            if alternative in avoid:
                continue
            if alternative in NEEDS_TWO and len(stageable) < 2:
                continue
            chosen = alternative
            break

    # A property is not a stage, and one thing cannot be compared with itself. Fall back to the
    # simplest composition that is still true: a single pictured subject, plus its stated properties.
    if chosen in NEEDS_TWO and len(stageable) < 2:
        chosen = "statement" if attributes else "pipeline"
    elif chosen == "pipeline" and len(stageable) < 2 and attributes:
        chosen = "statement"
    # A stated property (cost, time) with no comparison in the sentence is a statement about its
    # subject, not an ordering and not a contest between two things.
    comparative = sentence_pair is not None
    if attributes and not comparative and chosen in {"pipeline", "comparison", "gap",
                                                     "topology", "panels"}:
        chosen = "statement"
    # Comparison or co-mention? A sentence that never compares anything gets panels, so the plate
    # cannot claim a contest the narration does not make.
    if chosen == "comparison" and not comparative and len(stageable) >= 2:
        chosen = "panels"
    if chosen in {"pipeline", "timeline"} and not has_sequence_cue(f"{concept} {narration}"):
        chosen = "panels" if len(stageable) >= 2 else "statement"

    # A stated figure earns a chart. A vague quantifier, a mixed-unit sentence, a single count, a
    # percentage of change, or a scene the plan did not ask to be a chart does not: those would need a
    # baseline or a category the narration never gives, so the plate keeps its words instead.
    charted = chart_kind(figures, narration=narration, category=category) if figures else None
    if charted and not chart_values:
        note = (f"chart_values is disabled for this channel: the stated figure "
                f"{figures[0][0]!r} is drawn as text, not as a bar")
        charted = None
    if charted:
        chosen = charted
    elif chosen in {"bars", "ratio"}:
        # A variant forced by a caller still has to be true: a filled track for a percentage of change
        # would assert a whole the sentence never names.
        if chosen == "ratio" and not share_framed(narration):
            chosen = "statement"
            note = note or (f"a ratio was requested for a share of a change, not of a whole: "
                            f"the plate states the figure as text instead")
    elif category == "dataviz" and not note:
        numeric = [figure for figure in figures if figure[1] is not None]
        if not figures:
            note = "no stated figure: a chart would need a number the narration does not say"
        elif not numeric:
            note = (f"only a vague quantifier ({figures[0][0]!r}): a bar would invent the number "
                    f"the narration never gives")
        elif len(numeric) == 1 and numeric[0][2] == "%" and not share_framed(narration):
            note = (f"{numeric[0][0]!r} is a share of a change, not of a whole: a filled track would "
                    f"invent the whole it is a share of")
        else:
            note = (f"stated figures {[figure[0] for figure in figures]} cannot share one scale: "
                    f"no chart drawn")
    elif figures and category and category != "dataviz" and chart_kind(
            figures, narration=narration, category=""):
        # The sentence states a chartable figure but the plan asked for another kind of visual.
        note = (f"planned as {category!r}: the stated figure {figures[0][0]!r} stays as text rather "
                f"than overriding the planned category")

    palette = (
        colors.get("bg", "#050B16"), colors.get("panel", "#10243A"),
        colors.get("accent", "#4FD1E8"), colors.get("accent2", "#FFB84D"),
        colors.get("text", "#F5F9FF"),
    )
    title = short_title(on_screen or concept)
    if chosen == "comparison":
        # Draw exactly the pair the sentence contrasts, in the order it says them, so a plate cannot
        # pair two nouns that merely appear in the same sentence.
        if sentence_pair is not None:
            entities = [sentence_pair[0], sentence_pair[1]]
        else:
            chosen = "panels" if len(stageable) >= 2 else "statement"
    if not entities and not charted:
        chosen = "statement"
        note = note or "no subject named in the sentence: statement plate, no invented subject"
    return DiagramSpec(variant=chosen, title=title,
                       entities=tuple(entities), emphasis=entities[0] if entities else "idea",
                       palette=palette, figures=tuple(figures),
                       figure_labels=figure_labels(narration, tuple(figures)), note=note)


# ---------------------------------------------------------------------------
# drawing surface
# ---------------------------------------------------------------------------
class Canvas:
    """Supersampled surface with the primitives the pictograms are made of."""

    def __init__(self, width: int, height: int, palette: tuple[str, str, str, str, str]) -> None:
        self.scale = SUPERSAMPLE
        self.width, self.height = width, height
        self.bg, self.panel, self.accent, self.accent2, self.text = palette
        self.image = Image.new("RGB", (width * SUPERSAMPLE, height * SUPERSAMPLE), self.bg)
        self.draw = ImageDraw.Draw(self.image, "RGBA")

    def px(self, value: float) -> int:
        return int(round(value * self.scale))

    def box(self, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return (self.px(x0), self.px(y0), self.px(x1), self.px(y1))

    def point(self, x: float, y: float) -> tuple[int, int]:
        return (self.px(x), self.px(y))

    def rect(self, x0: float, y0: float, x1: float, y1: float, *, radius: float = 0,
             fill: str | None = None, outline: str | None = None, width: float = 2,
             alpha: int = 255) -> None:
        box = self.box(x0, y0, x1, y1)
        fill_rgba = _rgba(fill, alpha) if fill else None
        outline_rgba = _rgba(outline, alpha) if outline else None
        if radius:
            self.draw.rounded_rectangle(box, radius=self.px(radius), fill=fill_rgba,
                                        outline=outline_rgba,
                                        width=self.px(width) if outline else 1)
        else:
            self.draw.rectangle(box, fill=fill_rgba, outline=outline_rgba,
                                width=self.px(width) if outline else 1)

    def line(self, points: list[tuple[float, float]], *, fill: str, width: float = 3,
             alpha: int = 255) -> None:
        self.draw.line([self.point(x, y) for x, y in points], fill=_rgba(fill, alpha),
                       width=self.px(width), joint="curve")

    def circle(self, cx: float, cy: float, radius: float, *, fill: str | None = None,
               outline: str | None = None, width: float = 2, alpha: int = 255) -> None:
        self.draw.ellipse(self.box(cx - radius, cy - radius, cx + radius, cy + radius),
                          fill=_rgba(fill, alpha) if fill else None,
                          outline=_rgba(outline, alpha) if outline else None,
                          width=self.px(width) if outline else 1)

    def polygon(self, points: list[tuple[float, float]], *, fill: str, alpha: int = 255) -> None:
        self.draw.polygon([self.point(x, y) for x, y in points], fill=_rgba(fill, alpha))

    def text_at(self, x: float, y: float, text: str, size: int = 18, *,
                fill: str | None = None, anchor: str = "la", bold: bool = True,
                alpha: int = 255) -> None:
        face = font(BOLD_CANDIDATES if bold else MONO_CANDIDATES, self.px(size))
        self.draw.text((self.px(x), self.px(y)), text, font=face,
                       fill=_rgba(fill or self.text, alpha), anchor=anchor)

    def finish(self) -> Image.Image:
        return self.image.resize((self.width, self.height), Image.LANCZOS)


def _rgba(color: str, alpha: int) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


# ---------------------------------------------------------------------------
# pictograms: recognisable objects, drawn from primitives
# ---------------------------------------------------------------------------
def icon_video(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    w, h = size, size * 0.72
    canvas.rect(cx - w / 2 + 10, cy - h / 2 - 10, cx + w / 2 + 10, cy + h / 2 - 10, radius=8,
                fill=canvas.bg, outline=canvas.accent2, width=2.5, alpha=190)
    canvas.rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, radius=8,
                fill=canvas.bg, outline=canvas.accent, width=3.5)
    for index in range(4):
        x = cx - w / 2 + 14 + index * (w - 28) / 3.4
        for y in (cy - h / 2 + 9, cy + h / 2 - 9):
            canvas.rect(x, y - 3, x + 9, y + 3, radius=1.5, fill=canvas.accent2)
    canvas.polygon([(cx - 9, cy - 15), (cx - 9, cy + 15), (cx + 16, cy)], fill=canvas.accent)


def icon_model(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    columns = ((cx - size * 0.36, 3), (cx, 4), (cx + size * 0.36, 2))
    radius = size * 0.055
    nodes: list[list[tuple[float, float]]] = []
    for x, count in columns:
        spread = size * 0.44
        step = spread / max(1, count - 1)
        nodes.append([(x, cy - spread / 2 + index * step) for index in range(count)])
    for left, right in zip(nodes, nodes[1:]):
        for start in left:
            for end in right:
                canvas.line([start, end], fill=canvas.accent2, width=1.6, alpha=110)
    for index, column in enumerate(nodes):
        for x, y in column:
            canvas.circle(x, y, radius, fill=canvas.accent if index == 1 else canvas.bg,
                          outline=canvas.accent, width=3)


def icon_action(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    """A gripper closing on a block, with the forces it applies."""

    canvas.rect(cx - size * 0.16, cy + size * 0.06, cx + size * 0.16, cy + size * 0.30,
                radius=6, fill=canvas.accent2)
    for direction in (-1, 1):
        x = cx + direction * size * 0.12
        canvas.line([(x, cy - size * 0.30), (x, cy + size * 0.04)], fill=canvas.accent, width=9)
        canvas.line([(x, cy + size * 0.04), (x + direction * size * 0.03, cy + size * 0.10)],
                    fill=canvas.accent, width=9)
    for direction in (-1, 1):
        tip = cx + direction * size * 0.42
        start = cx + direction * size * 0.24
        canvas.line([(start, cy), (tip, cy)], fill=canvas.text, width=3, alpha=190)
        canvas.polygon([(tip, cy), (tip - direction * 11, cy - 7), (tip - direction * 11, cy + 7)],
                       fill=canvas.text, alpha=190)


def icon_robot(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    """A two-link arm on a base, drawn the way a lab arm looks."""

    base_y = cy + size * 0.34
    canvas.rect(cx - size * 0.20, base_y, cx + size * 0.20, base_y + size * 0.08, radius=5,
                fill=canvas.accent2)
    joints = [(cx, base_y), (cx, base_y - size * 0.38), (cx + size * 0.30, base_y - size * 0.56)]
    for (x0, y0), (x1, y1) in zip(joints, joints[1:]):
        canvas.line([(x0, y0), (x1, y1)], fill=canvas.text, width=size * 0.075)
        canvas.line([(x0, y0), (x1, y1)], fill=canvas.panel, width=size * 0.04)
    for index, (x, y) in enumerate(joints):
        canvas.circle(x, y, size * 0.055 if index else size * 0.07, fill=canvas.accent,
                      outline=canvas.bg, width=3)
    gx, gy = joints[-1]
    for direction in (-1, 1):
        canvas.line([(gx + direction * 10, gy), (gx + direction * size * 0.14,
                                                 gy + size * 0.16)],
                    fill=canvas.accent2, width=7)
    canvas.rect(gx - size * 0.05, gy + size * 0.20, gx + size * 0.05, gy + size * 0.28,
                radius=4, fill=canvas.text, alpha=210)


def icon_data(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    for index in range(3):
        offset = index * size * 0.09
        canvas.rect(cx - size * 0.30 + offset, cy - size * 0.26 - offset,
                    cx + size * 0.30 + offset, cy + size * 0.02 - offset, radius=6,
                    fill=canvas.bg, outline=canvas.accent2, width=3, alpha=235 - index * 30)
    for index in range(3):
        x = cx - size * 0.18 + index * size * 0.18
        canvas.circle(x + size * 0.09, cy - size * 0.12, size * 0.035, fill=canvas.accent)


def icon_grid(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    """Two lattice towers carrying a line between them.

    The first version was two thin legs with a crossarm and read as the letters "A A" on the encoded
    frame. Lattice bracing plus two conductors makes it a transmission line at a glance.
    """

    for x in (cx - size * 0.34, cx + size * 0.34):
        top, bottom = cy - size * 0.20, cy + size * 0.26
        spread_top, spread_bottom = size * 0.07, size * 0.15
        canvas.line([(x - spread_bottom, bottom), (x - spread_top, top)], fill=canvas.text, width=5)
        canvas.line([(x + spread_bottom, bottom), (x + spread_top, top)], fill=canvas.text, width=5)
        for index in range(2):
            y0 = top + (bottom - top) * index / 2
            y1 = top + (bottom - top) * (index + 1) / 2
            t = (y0 - top) / (bottom - top)
            half0 = spread_top + (spread_bottom - spread_top) * t
            half1 = spread_top + (spread_bottom - spread_top) * (t + 0.5)
            canvas.line([(x - half0, y0), (x + half1, y1)], fill=canvas.text, width=3, alpha=210)
            canvas.line([(x + half0, y0), (x - half1, y1)], fill=canvas.text, width=3, alpha=210)
        for arm_y, arm_w in ((top + size * 0.02, 0.15), (top + size * 0.14, 0.10)):
            canvas.line([(x - size * arm_w, arm_y), (x + size * arm_w, arm_y)],
                        fill=canvas.text, width=4)
            for side in (-1, 1):
                canvas.circle(x + side * size * arm_w, arm_y, size * 0.022, fill=canvas.accent2)
    for offset in (size * 0.02, size * 0.14):
        canvas.line([(cx - size * 0.34, cy - size * 0.20 + offset),
                     (cx, cy - size * 0.20 + offset + size * 0.10),
                     (cx + size * 0.34, cy - size * 0.20 + offset)],
                    fill=canvas.accent, width=3, alpha=200)


def icon_queue(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.rect(cx - size * 0.44, cy - size * 0.10, cx + size * 0.44, cy + size * 0.10, radius=8,
                fill=canvas.bg, outline=canvas.accent2, width=3)
    for index in range(5):
        x = cx - size * 0.36 + index * size * 0.17
        colour = canvas.accent2 if index == 4 else canvas.accent
        canvas.circle(x, cy, size * 0.055, fill=colour)
    canvas.line([(cx + size * 0.44, cy), (cx + size * 0.54, cy)], fill=canvas.text, width=3)


def icon_energy(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.polygon([(cx + size * 0.04, cy - size * 0.34), (cx - size * 0.16, cy + size * 0.04),
                    (cx - size * 0.01, cy + size * 0.04), (cx - size * 0.07, cy + size * 0.34),
                    (cx + size * 0.17, cy - size * 0.07), (cx + size * 0.01, cy - size * 0.07)],
                   fill=canvas.accent2)


def icon_cost(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.circle(cx, cy, size * 0.30, fill=canvas.bg, outline=canvas.accent2, width=4)
    face = font(BOLD_CANDIDATES, canvas.px(size * 0.42))
    canvas.draw.text((canvas.px(cx), canvas.px(cy)), "$", font=face, fill=canvas.text, anchor="mm")


def icon_time(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.circle(cx, cy, size * 0.30, fill=canvas.bg, outline=canvas.accent, width=4)
    canvas.line([(cx, cy), (cx, cy - size * 0.18)], fill=canvas.text, width=5)
    canvas.line([(cx, cy), (cx + size * 0.14, cy + size * 0.10)], fill=canvas.text, width=5)
    for index in range(12):
        import math

        angle = index * math.pi / 6
        inner = size * 0.25
        outer = size * 0.29 if index % 3 else size * 0.31
        canvas.line([(cx + math.sin(angle) * inner, cy - math.cos(angle) * inner),
                     (cx + math.sin(angle) * outer, cy - math.cos(angle) * outer)],
                    fill=canvas.accent2, width=2)


def icon_study(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.rect(cx - size * 0.34, cy - size * 0.22, cx + size * 0.34, cy + size * 0.24,
                radius=10, fill=canvas.bg, outline=canvas.accent, width=3)
    canvas.line([(cx, cy - size * 0.22), (cx, cy + size * 0.24)], fill=canvas.accent2, width=3)
    for row in range(3):
        y = cy - size * 0.12 + row * size * 0.12
        for side in (-1, 1):
            canvas.line([(cx + side * size * 0.06, y), (cx + side * size * 0.26, y)],
                        fill=canvas.text, width=2, alpha=150)


def icon_demo(canvas: Canvas, cx: float, cy: float, size: float) -> None:
    canvas.circle(cx, cy - size * 0.20, size * 0.10, fill=canvas.accent)
    canvas.line([(cx, cy - size * 0.10), (cx, cy + size * 0.10)], fill=canvas.accent, width=8)
    canvas.line([(cx, cy + size * 0.10), (cx - size * 0.12, cy + size * 0.28)],
                fill=canvas.accent, width=7)
    canvas.line([(cx, cy + size * 0.10), (cx + size * 0.14, cy + size * 0.26)],
                fill=canvas.accent, width=7)
    canvas.line([(cx, cy - size * 0.06), (cx + size * 0.22, cy - size * 0.14)],
                fill=canvas.accent, width=7)
    canvas.rect(cx + size * 0.18, cy - size * 0.30, cx + size * 0.34, cy - size * 0.20, radius=4,
                fill=canvas.accent2)


ICONS: dict[str, Callable[[Canvas, float, float, float], None]] = {
    "video": icon_video,
    "model": icon_model,
    "action": icon_action,
    "robot": icon_robot,
    "demonstration": icon_demo,
    "data": icon_data,
    "grid": icon_grid,
    "queue": icon_queue,
    "energy": icon_energy,
    "cost": icon_cost,
    "time": icon_time,
    "study": icon_study,
}


def _icon_for(entity: str) -> str:
    return entity if entity in ICONS else "data"


# ---------------------------------------------------------------------------
# stated figures (v1.1)
# ---------------------------------------------------------------------------
_SEQUENCE_CUES = re.compile(
    r"\b(first|then|after|before|finally|last|second|third|"
    r"step\s+(?:\d+|one|two|three|four)|one\s+by\s+one|in\s+order|followed\s+by)\b"
    # "next" is a cue, but "next year" / "next month" is a date, not a sequence.
    r"|\bnext\b(?!\s+(?:year|month|week|day|decade|quarter|time))",
    re.IGNORECASE)


def has_sequence_cue(text: str) -> bool:
    """True only when the sentence states an order, not merely when it mentions time.

    "The future of robot training looks like a video library" mentions the future and states no
    chronology; drawing an axis there asserts an order the narration does not make.
    """

    lowered = f" {text.lower()} "
    lowered = lowered.replace("cannot", " can not ")
    return bool(_SEQUENCE_CUES.search(lowered))


_LABEL_STOPWORDS = {"is", "are", "was", "were", "be", "of", "the", "a", "an", "at", "than", "and",
                    "so", "to", "in", "on", "for", "with", "that", "this", "it", "its", "only",
                    "about", "just", "only", "now", "then", "which", "while", "cost", "costs"}


def figure_labels(narration: str,
                  figures: tuple[tuple[str, float | None, str], ...]) -> tuple[str, ...]:
    """The narration words that name each figure, for chart labels.

    "Human demonstrations are 80 percent of the cost and video is 20 percent" labels its two bars
    "human demonstrations" and "video", so the plate never repeats the number as its own subject.
    """

    text = str(narration or "")
    lowered = text.lower()
    labels: list[str] = []
    for phrase, _, _ in figures:
        position = lowered.find(str(phrase).lower())
        if position <= 0:
            labels.append("")
            continue
        words = [word.strip(".,;:!?") for word in text[:position].split()]
        picked: list[str] = []
        for word in reversed(words):
            cleaned = word.strip(".,;:!?—-").lower()
            if not cleaned or cleaned in _LABEL_STOPWORDS or not cleaned.isalpha():
                if picked:
                    break
                continue
            picked.insert(0, word.strip(".,;:!?"))
            if len(picked) == 3:
                break
        labels.append(" ".join(picked))
    return tuple(labels)


# A percentage can describe a share of a whole ("40 percent of the cost") or a relative change
# ("40 percent cheaper"). Only the first one is drawable as a filled track: filling a track to 40% for
# "cheaper" asserts a whole the sentence never mentions, which is the same invented relationship this
# release exists to remove.
_SHARE_FRAMING = re.compile(
    r"\bof\b|\bshare\b|\bproportion\b|\baccounts?\s+for\b|\bmakes?\s+up\b|\bout\s+of\b",
    re.IGNORECASE)
_RELATIVE_FRAMING = re.compile(
    r"\b(cheaper|costlier|faster|slower|quicker|higher|lower|bigger|smaller|lighter|heavier|"
    r"more|less|fewer|increase[sd]?|decrease[sd]?|reduction|improvement|drop[s]?|rise[s]?|"
    r"grew|grow[s]?|fell|cut|saved|saving[s]?)\b", re.IGNORECASE)

# Categories whose job is a data visual. A scene planned as a photograph or kinetic type must not be
# turned into a chart: the plan is the contract, and a chart where a picture was requested is a
# category the plan never asked for.
_DATA_CATEGORIES = frozenset({"", "dataviz"})


def share_framed(narration: str) -> bool:
    """True when the sentence frames its percentage as a part of a whole."""

    text = str(narration or "")
    return bool(_SHARE_FRAMING.search(text)) and not _RELATIVE_FRAMING.search(text)


def chart_kind(figures: tuple[tuple[str, float | None, str], ...], *,
               narration: str = "", category: str = "") -> str | None:
    """``bars`` for several comparable values, ``ratio`` for one stated share, else None.

    This is the only place that decides whether a chart is drawn. It used to exist twice - here and in
    ``factory/content/figures.py`` - which is how two rules for the same claim drift apart.
    """

    if category not in _DATA_CATEGORIES:
        return None
    numeric = [figure for figure in figures if figure[1] is not None]
    if not numeric:
        return None
    units = {figure[2] for figure in numeric}
    if len(units) != 1:
        return None
    unit = numeric[0][2]
    if len(numeric) == 1:
        if unit != "%":
            return None
        value = float(numeric[0][1])
        # A proportion of a whole is drawable only inside 0..100, and only when the sentence actually
        # says "of" something rather than "40 percent cheaper".
        return "ratio" if 0 < value <= 100 and share_framed(narration) else None
    if unit == "%":
        if not all(0 <= float(figure[1]) <= 100 for figure in numeric):
            return None
        return "bars"
    if len(numeric) > 3:
        return None
    return "bars"


def _figure_rows(spec: DiagramSpec) -> list[tuple[str, float | None, str]]:
    return [tuple(row) for row in spec.figures]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------
def _backdrop(canvas: Canvas) -> None:
    """A quiet plate: panel fill, a fine grid, and a corner rule. Not a text box."""

    canvas.rect(0, 0, canvas.width, canvas.height, radius=24, fill=canvas.panel)
    step = 44
    for x in range(step, canvas.width, step):
        canvas.line([(x, 8), (x, canvas.height - 8)], fill=canvas.text, width=1, alpha=14)
    for y in range(step, canvas.height, step):
        canvas.line([(8, y), (canvas.width - 8, y)], fill=canvas.text, width=1, alpha=14)
    canvas.rect(0, 0, canvas.width, canvas.height, radius=24, outline=canvas.accent, width=2,
                alpha=90)


def _header(canvas: Canvas, spec: DiagramSpec) -> float:
    canvas.rect(30, 34, 36, 78, radius=3, fill=canvas.accent)
    canvas.text_at(50, 38, spec.title.upper()[:34], size=21)
    canvas.line([(30, 96), (canvas.width - 30, 96)], fill=canvas.accent, width=2, alpha=170)
    return 124


def _entity_row(spec: DiagramSpec, count: int) -> list[str]:
    """Up to ``count`` distinct entities.

    Padding a short list by repeating the last entity printed "VIDEO -> MODEL -> MODEL", which reads as
    a claim about two stages that do not exist. A composition adapts to the entities it has.
    """

    return list(dict.fromkeys(spec.entities))[:count]


def _band(canvas: Canvas, top: float) -> tuple[float, float]:
    """The vertical band a composition may use, between the header rule and the footer."""

    return top + 12, canvas.height - 74


def _draw_pipeline(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    entities = _entity_row(spec, 3)
    stages = [entity for entity in entities if entity not in ATTRIBUTE_ENTITIES]
    if stages:
        entities = stages
    upper, lower = _band(canvas, top)
    slot = canvas.width / len(entities)
    cy = (upper + lower) / 2 - 18
    size = min(190, slot * 0.56)
    for index, entity in enumerate(entities):
        cx = slot * (index + 0.5)
        ICONS[_icon_for(entity)](canvas, cx, cy, size * 1.18)
        canvas.text_at(cx, cy + size * 0.86, LEXICON[entity][0].upper(), size=23, anchor="ma")
        if index < len(entities) - 1:
            x0, x1 = cx + size * 0.56, cx + slot - size * 0.56
            canvas.line([(x0, cy), (x1, cy)], fill=canvas.accent2, width=4)
            canvas.polygon([(x1, cy), (x1 - 14, cy - 9), (x1 - 14, cy + 9)], fill=canvas.accent2)
    _footer(canvas, spec, " -> ".join(LEXICON[entity][0] for entity in entities).upper())


def _draw_gap(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    entities = _entity_row(spec, 2)
    if len(entities) < 2:
        # A gap needs two sides. With one subject there is no gap to draw, and indexing the second
        # entity raised IndexError; draw the subject instead of inventing a counterpart.
        _draw_statement(canvas, spec, top)
        return
    upper, lower = _band(canvas, top)
    height = min(310, lower - upper - 16)
    y0 = upper + (lower - upper - height) / 2
    split = canvas.width * 0.5
    for index, entity in enumerate(entities):
        cx = canvas.width * (0.265 if index == 0 else 0.735)
        canvas.rect(cx - 168, y0, cx + 168, y0 + height, radius=16, fill=canvas.bg,
                    outline=canvas.accent2, width=2.5, alpha=235)
        ICONS[_icon_for(entity)](canvas, cx, y0 + height * 0.42, min(150, height * 0.5))
        canvas.text_at(cx, y0 + height - 36, LEXICON[entity][0].upper(), size=22, anchor="ma")
    for index in range(5):
        y = y0 + height * 0.2 + index * 24
        canvas.rect(split - 3, y, split + 3, y + 12, radius=2, fill=canvas.accent)
    canvas.text_at(split, y0 - 22, "MISSING", size=15, anchor="ma", fill=canvas.accent)
    _footer(canvas, spec, (LEXICON[entities[0]][0] + " WITHOUT " +
                           LEXICON[entities[1]][0]).upper())


def _draw_comparison(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """Two options side by side, with no invented magnitude.

    Bars would claim a ratio the narration never states, so the tradeoff is two labelled panels: the
    thing, its pictogram, and the sentence's own words for it.
    """

    entities = _entity_row(spec, 2)
    if len(entities) < 2:
        _draw_statement(canvas, spec, top)
        return
    upper, lower = _band(canvas, top)
    height = min(320, lower - upper - 12)
    y0 = upper + (lower - upper - height) / 2
    half = canvas.width / 2
    for index, entity in enumerate(entities):
        cx = half * (index + 0.5)
        canvas.rect(cx - 176, y0, cx + 176, y0 + height, radius=16, fill=canvas.bg,
                    outline=canvas.accent2, width=2.5, alpha=235)
        ICONS[_icon_for(entity)](canvas, cx, y0 + height * 0.40, min(150, height * 0.46))
        canvas.text_at(cx, y0 + height - 36, LEXICON[entity][0].upper(), size=22, anchor="ma")
    canvas.circle(half, y0 + height * 0.42, 26, fill=canvas.panel, outline=canvas.accent, width=2)
    canvas.text_at(half, y0 + height * 0.42, "vs", size=17, anchor="mm", fill=canvas.accent)
    _footer(canvas, spec, "WHAT THE SENTENCE CONTRASTS")


def _draw_panels(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """Two things the sentence mentions, side by side, and no claim about how they relate.

    A sentence like "a robot arm needs thousands of examples to learn one grasp" mentions two things
    without comparing them, ordering them, or saying one contains the other. Drawing a "vs" badge there
    asserts a contest, and drawing an arrow asserts a direction. Panels assert only co-mention, which
    is the one thing the sentence does guarantee.
    """

    entities = _entity_row(spec, 2)
    if len(entities) < 2:
        _draw_statement(canvas, spec, top)
        return
    upper, lower = _band(canvas, top)
    height = min(320, lower - upper - 12)
    y0 = upper + (lower - upper - height) / 2
    half = canvas.width / 2
    for index, entity in enumerate(entities):
        cx = half * (index + 0.5)
        canvas.rect(cx - 176, y0, cx + 176, y0 + height, radius=16, fill=canvas.bg,
                    outline=canvas.accent2, width=2.5, alpha=235)
        ICONS[_icon_for(entity)](canvas, cx, y0 + height * 0.40, min(150, height * 0.46))
        canvas.text_at(cx, y0 + height - 36, LEXICON[entity][0].upper(), size=22, anchor="ma")
    _footer(canvas, spec, "WHAT THE SENTENCE MENTIONS")


def _draw_topology(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    entities = _entity_row(spec, 2)
    if len(entities) < 2:
        _draw_statement(canvas, spec, top)
        return
    upper, lower = _band(canvas, top)
    cx, cy = canvas.width / 2, (upper + lower) / 2
    ICONS[_icon_for(entities[0])](canvas, cx, cy, 210)
    nodes = [(cx - 196, cy - 74), (cx + 196, cy - 74), (cx - 152, cy + 104), (cx + 152, cy + 104)]
    for x, y in nodes:
        canvas.line([(cx, cy), (x, y)], fill=canvas.accent, width=3, alpha=170)
    for index, (x, y) in enumerate(nodes):
        labelled = index in (1, 3)
        canvas.circle(x, y, 17 if labelled else 11,
                      fill=canvas.bg, outline=canvas.accent2 if labelled else canvas.accent, width=3)
        if labelled:
            role = LEXICON[entities[1 if index == 1 else 0]][0].upper()
            canvas.text_at(x, y + 26, role, size=17, anchor="ma")
    _footer(canvas, spec, (LEXICON[entities[0]][0] + " -> " +
                           LEXICON[entities[1]][0]).upper())


def _draw_components(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    upper, lower = _band(canvas, top)
    cx, cy = canvas.width * 0.32, (upper + lower) / 2
    ICONS["robot"](canvas, cx, cy, 300)
    for y, label in ((cy - 62, "shoulder"), (cy + 10, "elbow"), (cy + 84, "gripper")):
        canvas.line([(cx + 116, y), (cx + 190, y)], fill=canvas.accent2, width=2)
        canvas.circle(cx + 116, y, 5, fill=canvas.accent2)
        canvas.text_at(cx + 200, y - 12, label.upper(), size=15)
    _footer(canvas, spec, "JOINTS, SENSORS AND THE GRIPPER")


def _draw_layers(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    entities = _entity_row(spec, 3)
    upper, lower = _band(canvas, top)
    height = 74
    step = min(height + 16, (lower - upper) / len(entities))
    for index, entity in enumerate(reversed(entities)):
        y = upper + index * step
        inset = 70 + index * 30
        canvas.rect(inset, y, canvas.width - inset, y + height, radius=12,
                    fill=canvas.accent if index == len(entities) - 1 else canvas.bg,
                    outline=canvas.accent2, width=2)
        ICONS[_icon_for(entity)](canvas, inset + 54, y + height / 2, 54)
        canvas.text_at(inset + 100, y + height / 2 - 10, LEXICON[entity][0].upper(), size=18)
    _footer(canvas, spec, "LAYERED, NOT FLAT")


def _draw_timeline(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    entities = _entity_row(spec, 3)
    upper, lower = _band(canvas, top)
    y = (upper + lower) / 2 + 20
    canvas.line([(70, y), (canvas.width - 70, y)], fill=canvas.text, width=3, alpha=190)
    for index, entity in enumerate(entities):
        x = 70 + (canvas.width - 140) * index / max(1, len(entities) - 1)
        ICONS[_icon_for(entity)](canvas, x, y - 96, 96)
        canvas.circle(x, y, 13, fill=canvas.accent2 if index == len(entities) - 1 else canvas.accent,
                      outline=canvas.bg, width=3)
        canvas.text_at(x, y + 30, LEXICON[entity][0].upper(), size=16, anchor="ma")
    _footer(canvas, spec, "WHAT COMES NEXT")



def _label_for(spec: DiagramSpec, index: int) -> str:
    """The narration's own word for the figure at ``index``, upper-cased, or "" when there is none."""

    if index < len(spec.figure_labels):
        return spec.figure_labels[index].upper()
    return ""


def _stated_numbers(spec: DiagramSpec) -> list[tuple[str, float, str]]:
    """Only the figures the sentence actually stated with a number."""

    return [(phrase, float(value), unit) for phrase, value, unit in spec.figures
            if value is not None]


def _draw_bars(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """Comparable stated values, one bar each, on one scale, labelled with the spoken phrase.

    Bars share a scale only when the units match (the spec builder refuses anything else), and no bar
    is ever drawn against an imagined baseline: the empty track behind each bar is a guide, not a
    second value.
    """

    stated = _stated_numbers(spec)[:3]
    if not stated:
        _draw_statement(canvas, spec, top)
        return
    upper, lower = _band(canvas, top)
    height = min(74, (lower - upper) / (len(stated) + 0.5))
    largest = max(value for _, value, _ in stated) or 1.0
    track_x0, track_x1 = 250, canvas.width - 130
    for index, (phrase, value, unit) in enumerate(stated):
        y = upper + 18 + index * (height + 22)
        canvas.rect(track_x0, y, track_x1, y + height, radius=12, fill=canvas.bg,
                    outline=canvas.panel, width=2, alpha=235)
        span = (track_x1 - track_x0) * (value / largest)
        if span > 0:
            canvas.rect(track_x0, y, track_x0 + max(14, span), y + height, radius=12,
                        fill=canvas.accent, outline=canvas.accent, width=0, alpha=235)
        label = f"{value:g}{unit}"
        caption = _label_for(spec, index) or phrase.upper()[:22]
        canvas.text_at(track_x0 - 18, y + height / 2 - 10, caption[:22], size=16, anchor="ra")
        canvas.text_at(track_x0 + max(20, span) + 16, y + height / 2 - 10, label, size=19,
                       fill=canvas.accent2)
    _footer(canvas, spec, "FIGURES THE SENTENCE STATES")


def _draw_ratio(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """One stated proportion of a whole, drawn against a full track and labelled as spoken."""

    stated = _stated_numbers(spec)
    if not stated:
        _draw_statement(canvas, spec, top)
        return
    phrase, value, unit = stated[0]
    fraction = max(0.0, min(1.0, value / 100.0 if unit == "%" else value))
    upper, lower = _band(canvas, top)
    track_x0, track_x1 = 130, canvas.width - 130
    y = (upper + lower) / 2 - 26
    canvas.rect(track_x0, y, track_x1, y + 52, radius=26, fill=canvas.bg,
                outline=canvas.panel, width=2.5, alpha=235)
    filled = track_x0 + (track_x1 - track_x0) * fraction
    if filled - track_x0 > 6:
        canvas.rect(track_x0, y, filled, y + 52, radius=26, fill=canvas.accent,
                    outline=canvas.accent, width=0, alpha=235)
    canvas.text_at(canvas.width / 2, y + 26, f"{value:g}{unit}", size=26, anchor="mm",
                   fill=canvas.text)
    canvas.text_at(canvas.width / 2, y - 34, (_label_for(spec, 0) or phrase.upper())[:40], size=17,
                   anchor="ma", fill=canvas.accent2)
    _footer(canvas, spec, "THE SHARE THE SENTENCE STATES")


def _draw_cta(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """A closing card: concentric rings, an arrow, three beats. No claim, just an invitation."""

    upper, lower = _band(canvas, top)
    cx, cy = canvas.width / 2, (upper + lower) / 2
    for index, radius in enumerate((150, 116, 84)):
        canvas.circle(cx, cy, radius, outline=canvas.accent if index % 2 == 0 else canvas.accent2,
                      width=3, alpha=220 - index * 60)
    canvas.circle(cx, cy, 46, fill=canvas.accent)
    canvas.polygon([(cx - 10, cy + 16), (cx - 10, cy - 18), (cx + 20, cy - 1)],
                   fill=canvas.bg)
    for index in range(3):
        x = cx + 200 + index * 26
        canvas.circle(x, cy, 9, fill=canvas.accent2 if index == 0 else canvas.bg,
                      outline=canvas.accent2, width=2.5)
    canvas.text_at(cx, lower + 6, "MORE LIKE THIS", size=18, anchor="ma", fill=canvas.accent2)
    _footer(canvas, spec, "FOLLOW FOR MORE")



def _draw_statement(canvas: Canvas, spec: DiagramSpec, top: float) -> None:
    """One pictured subject and the properties the sentence actually states about it.

    This exists so a sentence like "human demonstrations are slow and costly" can be shown without
    inventing an order between "demos", "cost" and "data". No number is drawn, no arrow is implied.
    """

    entities = list(dict.fromkeys(spec.entities))
    if not entities:
        # A sentence that names nothing we can draw gets no pictogram and no label. The title and the
        # footer are the whole plate; an invented subject was the defect this replaces.
        upper, lower = _band(canvas, top)
        cx, cy = canvas.width / 2, (upper + lower) / 2 - 22
        canvas.circle(cx, cy, 132, outline=canvas.accent, width=3, alpha=200)
        canvas.circle(cx, cy, 104, outline=canvas.accent2, width=2, alpha=120)
        canvas.circle(cx, cy, 12, fill=canvas.accent, outline=canvas.bg, width=3)
        _footer(canvas, spec, "WHAT THE SENTENCE STATES")
        return
    subject = next((entity for entity in entities if entity not in ATTRIBUTE_ENTITIES), entities[0])
    attributes = [entity for entity in entities if entity in ATTRIBUTE_ENTITIES]
    upper, lower = _band(canvas, top)
    cx, cy = canvas.width / 2, (upper + lower) / 2 - 22

    canvas.circle(cx, cy, 132, outline=canvas.accent, width=3, alpha=200)
    canvas.circle(cx, cy, 104, outline=canvas.accent2, width=2, alpha=120)
    ICONS[_icon_for(subject)](canvas, cx, cy, 160)
    canvas.text_at(cx, cy + 150, LEXICON[subject][0].upper(), size=24, anchor="ma")

    if attributes:
        pill_width, gap = 150, 18
        total = len(attributes) * pill_width + (len(attributes) - 1) * gap
        x = cx - total / 2
        for entity in attributes:
            canvas.rect(x, lower - 74, x + pill_width, lower - 26, radius=13,
                        fill=canvas.bg, outline=canvas.accent2, width=2.5)
            canvas.text_at(x + pill_width / 2, lower - 59, LEXICON[entity][0].upper(), size=18,
                           anchor="ma", fill=canvas.accent2)
            x += pill_width + gap
    _footer(canvas, spec, "WHAT THE SENTENCE STATES")


_DRAWERS = {
    "pipeline": _draw_pipeline,
    "gap": _draw_gap,
    "comparison": _draw_comparison,
    "panels": _draw_panels,
    "topology": _draw_topology,
    "components": _draw_components,
    "layers": _draw_layers,
    "timeline": _draw_timeline,
    "cta": _draw_cta,
    "statement": _draw_statement,
    "bars": _draw_bars,
    "ratio": _draw_ratio,
}

# Matches the visual plate in the Shorts layout: 912 wide is the safe area divided by the maximum
# camera push-in, so the plate cannot drift outside the frame's safe margins.
DEFAULT_SIZE = (912, 600)


def _footer(canvas: Canvas, spec: DiagramSpec, text: str) -> None:
    canvas.line([(30, canvas.height - 52), (canvas.width - 30, canvas.height - 52)],
                fill=canvas.accent2, width=2, alpha=120)
    canvas.text_at(30, canvas.height - 40, text[:52], size=15, fill=canvas.accent2)


def render_diagram(spec: DiagramSpec, *, size: tuple[int, int] = DEFAULT_SIZE) -> Image.Image:
    """Draw the diagram for a spec. Pure function of the spec and the size."""

    canvas = Canvas(size[0], size[1], spec.palette)
    _backdrop(canvas)
    top = _header(canvas, spec)
    drawer = _DRAWERS.get(spec.variant, _draw_pipeline)
    needs_subject = spec.variant not in {"statement", "cta", "bars", "ratio"}
    if needs_subject and not list(dict.fromkeys(spec.entities)):
        # Belt and braces: a forced variant with no subject draws a statement rather than raising or
        # inventing the subject v1.0 used to append.
        drawer = _draw_statement
    drawer(canvas, spec, top)
    return canvas.finish()


def write_diagram(spec: DiagramSpec, destination: str | Path, *,
                  size: tuple[int, int] = DEFAULT_SIZE) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    render_diagram(spec, size=size).save(path, format="PNG", optimize=True)
    return path


def motion_plan(spec: DiagramSpec, duration_s: float) -> dict[str, Any]:
    """How the diagram is treated once it is on the card.

    Data, not code: the renderer stays the only place that draws, and creative QC can state the
    motion a scene actually received.
    """

    return {
        "variant": spec.variant,
        "treatment": "push_in" if spec.variant not in {"timeline", "topology"} else "drift",
        "enter_s": round(min(0.45, max(0.2, duration_s * 0.12)), 3),
        "asset_id": spec.asset_id,
    }
