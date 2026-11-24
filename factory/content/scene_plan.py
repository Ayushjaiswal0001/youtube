"""Semantic scene planning: turn narration into scenes that each have a visual job.

The Shorts renderer used to have exactly one visual unit per script line, so a six-second sentence
got one card and the whole video became a sequence of type. This module adds the layer that was
missing: it decides *what the viewer should see, and when*, using the word timings the TTS pass
already produces.

Four rules shape it:

* Boundaries are semantic. Scenes split at sentence ends and at long pauses inside a sentence, and
  are only forced together or apart when the resulting duration leaves the pacing band.
* The count is derived, never imposed. ``allowed_scene_count`` comes from the real narration length,
  and a plan that cannot be built inside that window records the exception rather than guessing.
* The plan tiles the narration exactly. Each scene starts where the previous ended, so scene time
  and audio time cannot drift apart.
* Every decision is recorded - a merge, a split, or a scene that deliberately runs long - so the
  creative QC report can show judgement instead of a bare number.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

VisualCategory = Literal[
    "footage", "photo", "illustration", "diagram",
    "dataviz", "software_demo", "motion_graphics", "kinetic_type",
]
FallbackKind = Literal["diagram", "motion_graphics", "kinetic_type"]

MIN_SCENE_MS = 2000
MAX_SCENE_MS = 8000

# A scene may break after these; sentence punctuation is strong, a clause mark is weak.
_BREAK_AFTER = re.compile(r"[.!?…][\"')]?\s*$|[;:]\s*$|[,]\s*$")
_STRONG_START = frozenset(
    "but so because instead then now and yet however meanwhile that this where which".split()
)

# Category hints read the narration, not a template: they decide the kind of *visual job* a scene
# has. The resolver then finds the best available way to do that job.
_CATEGORY_HINTS: tuple[tuple[VisualCategory, tuple[str, ...]], ...] = (
    ("dataviz", ("thousand", "percent", "number", "rate", "more than", "less than", "double",
                 "quarter", "half", "cost", "cheaper", "faster", "compare", "versus", "per ")),
    ("diagram", ("how", "works", "because", "flow", "process", "system", "chain", "step",
                 "architecture", "pipeline", "layer", "signal", "gap", "constraint", "needs")),
    ("software_demo", ("model", "training", "dataset", "inference", "code", "api", "run",
                       "pretrain", "finetune", "policy", "network", "learn")),
    ("photo", ("people", "factory", "building", "arm", "camera", "sensor", "robot", "machine",
               "device", "hardware", "physical")),
    ("illustration", ("idea", "imagine", "picture", "looks like", "story", "example")),
)


@dataclass
class ScenePlan:
    """One scene: when it runs, what it says, and what it must show."""

    scene_id: str
    start_ms: int
    end_ms: int
    narration_text: str
    main_concept: str
    visual_objective: str
    visual_category: VisualCategory
    search_query: str = ""
    asset_source: str | None = None
    asset_id: str | None = None
    license: str | None = None
    attribution_text: str | None = None
    on_screen_text: str | None = None
    motion: str = "push_in"
    transition_in: str = "cut"
    transition_out: str = "cut"
    fallback: FallbackKind = "diagram"
    # What was actually rendered. Filled in by the renderer; it is what stops a decorative panel
    # being relabelled as a diagram after the fact.
    coverage_category: VisualCategory | None = None
    visual_variant: str | None = None
    duration_deviation: dict[str, Any] | None = None
    derived_from: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        return data


@dataclass
class ScenePlanSet:
    scenes: list[ScenePlan]
    narration_ms: int
    allowed_scene_count: tuple[int, int]
    decisions: list[dict[str, Any]] = field(default_factory=list)
    min_scene_ms: int = MIN_SCENE_MS
    max_scene_ms: int = MAX_SCENE_MS

    def __len__(self) -> int:
        return len(self.scenes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_count": len(self.scenes),
            "narration_ms": self.narration_ms,
            "allowed_scene_count": list(self.allowed_scene_count),
            "min_scene_ms": self.min_scene_ms,
            "max_scene_ms": self.max_scene_ms,
            "decisions": self.decisions,
            "scenes": [scene.to_dict() for scene in self.scenes],
        }

    def at(self, t: float) -> ScenePlan | None:
        """The scene covering ``t`` seconds, or the last one after the narration ends."""

        if not self.scenes:
            return None
        ms = int(t * 1000)
        for scene in self.scenes:
            if scene.start_ms <= ms < scene.end_ms:
                return scene
        return self.scenes[-1]


def allowed_scene_count(narration_ms: int, *,
                        min_scene_ms: int = MIN_SCENE_MS,
                        max_scene_ms: int = MAX_SCENE_MS) -> tuple[int, int]:
    """The window the scene count has to land in, derived from the narration itself."""

    if narration_ms <= 0:
        raise ValueError("narration_ms must be positive")
    if min_scene_ms <= 0 or max_scene_ms <= min_scene_ms:
        raise ValueError("pacing band must satisfy 0 < min_scene_ms < max_scene_ms")
    low = max(1, math.ceil(narration_ms / max_scene_ms))
    high = max(low, math.floor(narration_ms / min_scene_ms))
    return low, high


def _words(line: Any) -> list[Any]:
    return list(getattr(line, "words", None) or [])


def _line_start(line: Any) -> float:
    words = _words(line)
    return float(getattr(line, "start", 0.0) or (words[0].start if words else 0.0))


def _line_end(line: Any) -> float:
    words = _words(line)
    end = float(getattr(line, "end", 0.0) or 0.0)
    if words:
        end = max(end, float(words[-1].end))
    return end


def _as_ms(piece: dict[str, Any]) -> int:
    return int(round((piece["end"] - piece["start"]) * 1000))


def _punct_tokens(line: Any) -> list[str]:
    """The line's own words *with* punctuation, aligned to the TTS word list.

    TTS word timings are bare tokens: "demonstrations." comes back as "demonstrations". Sentence
    ends therefore cannot be read from the timings at all, which is why punctuation-boundary
    segmentation silently produced one scene per line. The line text still has its punctuation, so
    the two are zipped; when the counts disagree the alignment is abandoned rather than guessed.
    """

    words = _words(line)
    tokens = str(getattr(line, "text", "")).strip().split()
    if not words or len(tokens) != len(words):
        return []
    return tokens


def _candidate_breaks(line: Any) -> list[int]:
    """Indices after which a scene may break inside one line.

    Two signals, both from the narration: sentence/clause punctuation, and a discourse connective
    ("Now", "But", "So") that starts a new idea after a real pause. Pause length alone is not a
    boundary - TTS inserts a short silence every few words, and cutting on those produced
    one-second slivers that the merge pass then collapsed straight back to one scene per line.
    """

    words = _words(line)
    tokens = _punct_tokens(line) or [str(getattr(w, "text", "")) for w in words]
    breaks: list[int] = []
    for index in range(0, len(words) - 1):
        token = tokens[index].strip()
        following = tokens[index + 1].strip().strip(",.;:").lower()
        gap = float(getattr(words[index + 1], "start", 0.0)) - float(getattr(words[index], "end", 0.0))
        punctuated = bool(_BREAK_AFTER.search(token))
        connective = (following in _STRONG_START and gap >= 0.18
                      and index >= max(2, len(words) // 4))
        if punctuated or connective:
            breaks.append(index + 1)
    return breaks


def _segment_bounds(line: Any) -> list[tuple[float, float, int, int]]:
    """Split one line into candidate segments: (start_s, end_s, word_lo, word_hi)."""

    words = _words(line)
    if not words:
        return [(_line_start(line), _line_end(line), 0, 0)]
    bounds: list[tuple[float, float, int, int]] = []
    previous = 0
    for cut in _candidate_breaks(line) + [len(words)]:
        chunk = words[previous:cut]
        if not chunk:
            continue
        bounds.append((float(chunk[0].start), float(chunk[-1].end), previous, cut))
        previous = cut
    return bounds


def _concept_of(text: str) -> str:
    """A short phrase for the scene: the diagram title and the asset query both use it."""

    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"^(and|but|so|then|now|because|instead|not)\s+", "", cleaned, flags=re.I)
    first = re.split(r"(?<=[.!?])\s", cleaned)[0]
    clause = re.split(r"[,;:]\s", first)[0]
    words = clause.split()
    return " ".join(words[:7]).strip(" .,!?:;") or cleaned[:60]


def _objective_of(text: str, category: VisualCategory) -> str:
    if category == "dataviz":
        return "show the comparison or magnitude the sentence asserts"
    if category == "software_demo":
        return "show the system doing the thing being described"
    if category == "diagram":
        return "show the mechanism: what connects to what, and in which order"
    if category == "photo":
        return "show the physical object or place the sentence names"
    if category == "illustration":
        return "illustrate the idea concretely instead of restating the words"
    lowered = text.lower()
    if "gap" in lowered or "not" in lowered:
        return "show the missing link explicitly"
    return "show what the sentence describes"


def _category_of(spec: Any, text: str) -> VisualCategory:
    """Which visual job this sentence calls for, within what the channel will render."""

    lowered = text.lower()
    policy = getattr(spec, "visual_policy", None) or {}
    allowed = set(policy.get("categories") or
                  ("diagram", "dataviz", "motion_graphics", "kinetic_type"))
    for category, hints in _CATEGORY_HINTS:
        if category in allowed and any(hint in lowered for hint in hints):
            return category
    if "diagram" in allowed:
        return "diagram"
    if "motion_graphics" in allowed:
        return "motion_graphics"
    return "kinetic_type"


def _on_screen(headline: str, text: str) -> str:
    words = (headline or _concept_of(text)).split()
    return " ".join(words[:8])


def _segments_of(lines: Sequence[Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for line_index, line in enumerate(lines):
        words = _words(line)
        for start, end, lo, hi in _segment_bounds(line):
            text = " ".join(str(getattr(w, "text", "")) for w in words[lo:hi]).strip()
            segments.append({
                "line_index": line_index, "word_lo": lo, "word_hi": hi,
                "start": start, "end": end, "text": text or str(getattr(line, "text", "")),
                "line": line,
            })
    return segments


def _split_piece(piece: dict[str, Any], cut: int) -> tuple[dict[str, Any], dict[str, Any]]:
    words = _words(piece["line"])[piece["word_lo"]:piece["word_hi"]]
    left_words, right_words = words[:cut], words[cut:]
    left_text = " ".join(str(getattr(w, "text", "")) for w in left_words).strip()
    right_text = " ".join(str(getattr(w, "text", "")) for w in right_words).strip()
    left = dict(piece, end=float(left_words[-1].end), word_hi=piece["word_lo"] + cut,
                text=left_text or piece["text"])
    right = dict(piece, start=float(right_words[0].start), word_lo=piece["word_lo"] + cut,
                 text=right_text or piece["text"])
    return left, right


def _best_cut(piece: dict[str, Any], *, min_ms: int = 0) -> tuple[int | None, float]:
    # A piece merged across a line boundary has no single word-index space: `word_lo`/`word_hi` would
    # index the *first* line while `text` is two concatenated lines. Cutting it produced a wrong slice
    # (and the caller then logged "cannot split without a sliver" for a piece that was simply
    # unsplittable), so a merged piece is reported as uncuttable rather than cut with bad indices.
    """The most natural internal boundary that leaves two usable halves.

    Pauses are scored, but a cut that would leave a one-word sliver is rejected outright: on
    evenly-spaced narration every gap scores the same, and always taking the first maximum turned an
    eleven-second sentence into "cannot split without creating a sliver" instead of two scenes.
    Ties are broken toward the middle, which is where a sentence naturally divides.
    """

    if piece.get("merged_lines"):
        return None, -1.0
    words = _words(piece["line"])[piece["word_lo"]:piece["word_hi"]]
    if len(words) < 2:
        return None, -1.0
    start_s, end_s = float(piece["start"]), float(piece["end"])
    best: tuple[float, int] | None = None
    middle = len(words) / 2.0
    for index in range(1, len(words)):
        gap = float(words[index].start) - float(words[index - 1].end)
        score = gap + (0.45 if _BREAK_AFTER.search(str(getattr(words[index - 1], "text", ""))) else 0.0)
        left_ms = (float(words[index - 1].end) - start_s) * 1000
        right_ms = (end_s - float(words[index].start)) * 1000
        if min_ms and (left_ms < min_ms or right_ms < min_ms):
            continue
        score -= 0.02 * abs(index - middle) / max(1.0, middle)  # tie-break toward the middle
        if best is None or score > best[0]:
            best = (score, index)
    if best is None:
        return None, -1.0
    return best[1], best[0]


def _enforce_max(pieces: list[dict[str, Any]], *, max_scene_ms: int, min_scene_ms: int,
                 decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split anything above the ceiling at its most natural boundary, never into a sliver."""

    queue, out = list(pieces), []
    while queue:
        piece = queue.pop(0)
        if _as_ms(piece) > max_scene_ms:
            cut, score = _best_cut(piece, min_ms=min_scene_ms)
            if cut is not None:
                left, right = _split_piece(piece, cut)
                if _as_ms(left) >= min_scene_ms and _as_ms(right) >= min_scene_ms:
                    decisions.append({"action": "split", "reason": "longer than max_scene_ms",
                                      "line_index": piece["line_index"],
                                      "gap_s": round(score, 3), "duration_ms": _as_ms(piece)})
                    queue = [left, right] + queue
                    continue
            decisions.append({"action": "deviation", "line_index": piece["line_index"],
                              "reason": "cannot split a long scene without creating a sliver",
                              "duration_ms": _as_ms(piece)})
        out.append(piece)
    return out


def plan_scenes(
    spec: Any,
    script: Any,
    *,
    min_scene_ms: int = MIN_SCENE_MS,
    max_scene_ms: int = MAX_SCENE_MS,
    prefix: str = "s",
) -> ScenePlanSet:
    """Build the scene plan for one script."""

    lines = [line for line in getattr(script, "lines", []) if str(getattr(line, "text", "")).strip()]
    if not lines:
        raise ValueError("cannot plan scenes for a script with no narration lines")

    # The span the scenes tile: first spoken word to last spoken word. Using the line objects
    # instead left a 20 ms lip at the end (line.end carries the TTS tail padding past the last word),
    # and "the scenes cover the narration" is a property worth being exact about.
    first_words, last_words = _words(lines[0]), _words(lines[-1])
    span_start = float(first_words[0].start) if first_words else _line_start(lines[0])
    span_end = float(last_words[-1].end) if last_words else _line_end(lines[-1])
    narration_ms = int(round((span_end - span_start) * 1000))
    low, high = allowed_scene_count(narration_ms, min_scene_ms=min_scene_ms, max_scene_ms=max_scene_ms)
    decisions: list[dict[str, Any]] = []

    # 1. Too long: split at the most natural boundary, never into a sliver.
    work = _enforce_max(_segments_of(lines), max_scene_ms=max_scene_ms,
                        min_scene_ms=min_scene_ms, decisions=decisions)

    # 2. Too short: absorb into the previous scene, which is the same idea continuing.
    merged: list[dict[str, Any]] = []
    for piece in work:
        host = merged[-1] if merged else None
        if host is not None and (_as_ms(piece) < min_scene_ms or _as_ms(host) < min_scene_ms):
            combined = _as_ms(host) + _as_ms(piece)
            crosses = host["line_index"] != piece["line_index"]
            # Merging is the right repair for a sliver, but not when the result breaks the ceiling: a
            # nine-second scene with a false "cannot split" justification is worse than a short one
            # that says it is short.
            if combined > max_scene_ms:
                piece["short_reason"] = (
                    "shorter than min_scene_ms, and merging it into the previous scene would exceed "
                    "max_scene_ms")
                decisions.append({"action": "keep_separate",
                                  "reason": "merging would exceed max_scene_ms",
                                  "into_line": host["line_index"], "piece_line": piece["line_index"],
                                  "merged_duration_ms": combined, "crosses_line_break": crosses})
                merged.append(dict(piece))
                continue
            decisions.append({"action": "merge",
                              "reason": ("shorter than min_scene_ms" if _as_ms(piece) < min_scene_ms
                                         else "previous scene was shorter than min_scene_ms"),
                              "into_line": host["line_index"],
                              "absorbed_line": piece["line_index"],
                              "duration_ms": combined,
                              "crosses_line_break": crosses})
            host["end"] = piece["end"]
            host["text"] = f"{host['text']} {piece['text']}".strip()
            if crosses:
                # Two index spaces, so record the span and stop pretending the words are contiguous.
                host["merged_lines"] = [*host.get("merged_lines", [host["line_index"]]),
                                        piece["line_index"]]
            else:
                host["word_hi"] = piece["word_hi"]
            continue
        merged.append(dict(piece))

    # 2b. A merge can push a scene back over the ceiling, so enforce it again.
    merged = _enforce_max(merged, max_scene_ms=max_scene_ms, min_scene_ms=min_scene_ms,
                          decisions=decisions)

    # 3. Below the derived floor: split the longest scene that can be split safely.
    guard = 0
    while len(merged) < low and guard < 64:
        guard += 1
        candidates = []
        for index, piece in enumerate(merged):
            if _as_ms(piece) <= min_scene_ms * 1.5:
                continue
            cut, score = _best_cut(piece, min_ms=min_scene_ms)
            if cut is None:
                continue
            left, right = _split_piece(piece, cut)
            if _as_ms(left) >= min_scene_ms and _as_ms(right) >= min_scene_ms:
                candidates.append((_as_ms(piece), score, index, cut))
        if not candidates:
            break
        _, score, index, cut = max(candidates)
        piece = merged[index]
        left, right = _split_piece(piece, cut)
        merged[index:index + 1] = [left, right]
        decisions.append({"action": "split", "reason": "below derived scene-count floor",
                          "line_index": piece["line_index"], "gap_s": round(score, 3)})

    # 4. Above the derived ceiling: merge the shortest adjacent pair.
    guard = 0
    while len(merged) > high and guard < 64:
        guard += 1
        best = None
        for index in range(len(merged) - 1):
            combined = _as_ms(merged[index]) + _as_ms(merged[index + 1])
            if best is None or combined < best[0]:
                best = (combined, index)
        if best is None:
            break
        _, index = best
        piece, following = merged[index], merged[index + 1]
        decisions.append({"action": "merge", "reason": "above derived scene-count ceiling",
                          "into_line": piece["line_index"],
                          "absorbed_line": following["line_index"],
                          "duration_ms": _as_ms(piece) + _as_ms(following)})
        piece["end"] = following["end"]
        piece["word_hi"] = following["word_hi"]
        piece["text"] = f"{piece['text']} {following['text']}".strip()
        merged[index:index + 1] = [piece]

    if len(merged) < low:
        decisions.append({"action": "exception",
                          "reason": "cannot reach the derived scene-count floor without cutting "
                                    "mid-thought", "achieved": len(merged), "floor": low})

    # 5. Tile the narration exactly: a scene ends where the next one begins.
    scenes: list[ScenePlan] = []
    for index, piece in enumerate(merged):
        start_ms = int(round(piece["start"] * 1000))
        end_ms = (int(round(merged[index + 1]["start"] * 1000)) if index + 1 < len(merged)
                  else int(round(piece["end"] * 1000)))
        duration_ms = end_ms - start_ms
        text = piece["text"]
        # A segment that starts mid-line must not lose its subject: the diagram title comes from the
        # line's own headline, otherwise a clause like "not the exact forces..." becomes the title.
        headline = str(getattr(piece["line"], "headline", "") or "")
        concept = (_concept_of(text) if piece["word_lo"] == 0
                   else (headline.strip() or _concept_of(str(getattr(piece["line"], "text", "")))))
        category = _category_of(spec, text)
        deviation = None
        if duration_ms < min_scene_ms:
            deviation = {"ms": duration_ms, "band": [min_scene_ms, max_scene_ms],
                         "reason": piece.get("short_reason")
                         or "shorter than min_scene_ms with no adjacent scene that could absorb it"}
        elif duration_ms > max_scene_ms:
            deviation = {"ms": duration_ms, "band": [min_scene_ms, max_scene_ms],
                         "reason": piece.get("long_reason")
                         or ("longer than max_scene_ms with no split point that avoids a sliver"
                             if not piece.get("merged_lines")
                             else "merged across a line break, which has no single word index space "
                                  "to split on")}
        scenes.append(ScenePlan(
            scene_id=f"{prefix}{index + 1:02d}",
            start_ms=start_ms,
            end_ms=end_ms,
            narration_text=text,
            main_concept=concept,
            visual_objective=_objective_of(text, category),
            visual_category=category,
            search_query=concept.lower(),
            fallback="diagram" if category != "kinetic_type" else "motion_graphics",
            on_screen_text=_on_screen(str(getattr(piece["line"], "headline", "")), text),
            motion="push_in" if (index + 1) % 2 else "drift_right",
            transition_in="cut" if index == 0 else "crossfade",
            transition_out="cut" if index + 1 == len(merged) else "crossfade",
            duration_deviation=deviation,
            derived_from=({"line_index": piece["line_index"],
                           "lines": list(piece["merged_lines"]),
                           "word_range": None}
                          if piece.get("merged_lines")
                          else {"line_index": piece["line_index"],
                                "word_range": [piece["word_lo"], piece["word_hi"]]}),
        ))

    return ScenePlanSet(
        scenes=scenes,
        narration_ms=narration_ms,
        allowed_scene_count=(low, high),
        decisions=decisions,
        min_scene_ms=min_scene_ms,
        max_scene_ms=max_scene_ms,
    )


def scene_plan_problems(plan: ScenePlanSet) -> list[str]:
    """Structural problems a plan must not have. Used by tests and by creative QC."""

    problems: list[str] = []
    low, high = plan.allowed_scene_count
    if not low <= len(plan.scenes) <= high:
        problems.append(f"scene count {len(plan.scenes)} outside derived window [{low}, {high}]")
    previous_end = None
    for scene in plan.scenes:
        if scene.end_ms <= scene.start_ms:
            problems.append(f"{scene.scene_id}: non-positive duration")
        if previous_end is not None and scene.start_ms < previous_end - 1:
            problems.append(f"{scene.scene_id}: overlaps the previous scene")
        if (scene.duration_ms < plan.min_scene_ms or scene.duration_ms > plan.max_scene_ms) \
                and not scene.duration_deviation:
            problems.append(f"{scene.scene_id}: duration outside band with no recorded reason")
        previous_end = scene.end_ms
    span = sum(scene.duration_ms for scene in plan.scenes)
    if plan.narration_ms and abs(span - plan.narration_ms) > max(400, plan.narration_ms * 0.02):
        problems.append(f"scene span {span}ms does not match narration {plan.narration_ms}ms")
    return problems


def plans_per_line(plan: ScenePlanSet) -> dict[int, int]:
    """How many scenes each narration line produced. One per line is the failure this avoids."""

    counts: dict[int, int] = {}
    for scene in plan.scenes:
        index = int(scene.derived_from.get("line_index", 0))
        counts[index] = counts.get(index, 0) + 1
    return counts
