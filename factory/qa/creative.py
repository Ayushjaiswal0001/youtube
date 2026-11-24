"""Creative quality control: does the video actually tell the story?

Technical QC answers "does it play". This answers "does it show the thing" - and unlike a taste
judgement it is measured, from the scene plan and the resolved assets, with published thresholds.

The checks are deliberately conservative about what they can know. Nothing here inspects a PNG for
"interesting"; it verifies the properties that separate a planned video from a wall of type:

* every scene covers narration time, and the scenes tile it with no gaps;
* the scene count sits inside the window derived from the narration length;
* scenes that leave the pacing band carry a written reason;
* the visuals are not one composition repeated - distinct assets and distinct compositions;
* every scene has a visual, and its category is what was actually rendered;
* the plate on screen does not collide with the caption or leave the safe area;
* on-screen text is short enough to read at a glance.

Thresholds live in ``content/creative_qc.json`` when present, with the same values as defaults here,
so a channel can tune pacing without a code change - and the file cannot silently disable a check.

Version 1.1 adds five checks: ``figure_is_stated`` (a plate may only show digits the narration
speaks, in figures or in words), ``dataviz_delivered`` (a dataviz scene that drew a diagram says so),
``visual_diversity_pixels`` (distinct plates measured by fingerprint, not by asset id),
``provenance_recorded`` and ``attribution_present``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..media.assets.metadata import REQUIRES_ATTRIBUTION

CONFIG_PATH = Path("content") / "creative_qc.json"


def default_config_path() -> Path:
    """The threshold file, resolved from the repository rather than from the working directory."""

    from ..media.assets.paths import thresholds_path as _thresholds_path

    return _thresholds_path()

# Words that carry no subject matter. Used only by the "does the plate title belong to this sentence"
# check, which is a warning: it must not reject a legitimate paraphrase.
STOPWORDS = frozenset(
    "the a an and or but so then now that this these those it its is are was were be been being to of "
    "in on at for with from by as not no more most less than very much many few into over under about "
    "after before while when where which who whom what how why can could would should will may might "
    "must do does did done has have had they them their we our you your he she his her i me my us one "
    "two three also just only even still because instead there here let lets look looks like get gets "
    "make makes made use used uses need needs turn turns keep keeps".split()
)


def content_words(text: str) -> set[str]:
    """The words in a phrase that carry meaning, lowercased, with a crude plural fold."""

    words: set[str] = set()
    for raw in str(text or "").replace("-", " ").split():
        word = raw.strip(".,;:!?\"'()").lower()
        if len(word) <= 3 or word in STOPWORDS:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and len(word) > 4:
            word = word[:-1]
        words.add(word)
    return words

DEFAULTS: dict[str, Any] = {
    "min_scene_ms": 2000,
    "max_scene_ms": 8000,
    "min_distinct_assets_ratio": 0.6,     # distinct visuals / scenes
    "min_distinct_variants": 2,
    "max_consecutive_same_variant": 2,
    "max_title_chars": 30,
    "max_on_screen_words": 8,
    "max_caption_collision_frames": 0,
    "require_visual_every_scene": True,
    "min_scenes_per_10s": 1.5,
    "min_distinct_pixel_ratio": 0.5,      # distinct plate fingerprints / scenes
    "max_fingerprint_distance": 6,        # Hamming distance that still counts as "the same picture"
}


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}


def _hamming(first: str, second: str) -> int:
    """Bit distance between two hex fingerprints, used to cluster near-identical plates."""

    try:
        return bin(int(first[:16], 16) ^ int(second[:16], 16)).count("1")
    except (TypeError, ValueError):
        return 64


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"              # "error" fails the video, "warn" is reported

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "severity": self.severity}


@dataclass
class CreativeReport:
    channel: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks if check.severity == "error")

    @property
    def failures(self) -> list[str]:
        return [check.name for check in self.checks
                if not check.ok and check.severity == "error"]

    @property
    def warnings(self) -> list[str]:
        return [check.name for check in self.checks
                if not check.ok and check.severity == "warn"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "creative-qc/1",
            "channel": self.channel,
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "failures": self.failures,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
        }

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        return destination


def load_thresholds(path: str | Path | None = None) -> dict[str, Any]:
    """Code defaults, overridden by a channel file - but never emptied by it."""

    thresholds = dict(DEFAULTS)
    config = Path(path) if path else CONFIG_PATH
    if not config.is_file():
        return thresholds
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return thresholds
    if not isinstance(data, dict):
        return thresholds
    for key, value in data.items():
        if key in DEFAULTS and isinstance(value, (int, float, bool)):
            thresholds[key] = value
    return thresholds


def evaluate(
    *,
    channel: str,
    scene_plan: dict[str, Any],
    framing: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> CreativeReport:
    """Judge the creative properties of one rendered video from its own artefacts."""

    limits = dict(DEFAULTS)
    limits.update(thresholds or {})

    # The plan states the band it was built against. Judging it against different numbers made a
    # tightened channel band unenforced: four scenes of 2.5-7.0 s passed a 3000-6000 ms plan.
    declared_min = scene_plan.get("min_scene_ms")
    declared_max = scene_plan.get("max_scene_ms")
    band_source = "config"
    if isinstance(declared_min, (int, float)) and isinstance(declared_max, (int, float)) \
            and 0 < declared_min < declared_max:
        limits["min_scene_ms"] = int(declared_min)
        limits["max_scene_ms"] = int(declared_max)
        band_source = "plan"
    report = CreativeReport(channel=channel, thresholds=limits)
    report.metrics["band_source"] = band_source
    scenes = scene_plan.get("scenes") or []
    narration_ms = int(scene_plan.get("narration_ms") or 0)
    allowed = scene_plan.get("allowed_scene_count") or [0, 0]

    # -- 1. continuity of the reel ------------------------------------------
    tiles = all(
        int(scenes[index]["end_ms"]) == int(scenes[index + 1]["start_ms"])
        for index in range(len(scenes) - 1)
    ) if len(scenes) > 1 else bool(scenes)
    covered = sum(int(scene.get("duration_ms") or 0) for scene in scenes)
    report.checks.append(Check(
        "scenes_tile_narration", tiles and (not scenes or covered == narration_ms),
        f"{len(scenes)} scenes covering {covered} ms of {narration_ms} ms narration",
    ))
    report.checks.append(Check(
        "scene_count_in_derived_window", bool(scenes) and allowed[0] <= len(scenes) <= allowed[1],
        f"{len(scenes)} scenes, window {allowed[0]}-{allowed[1]} derived from {narration_ms} ms",
    ))

    # -- 2. pacing -----------------------------------------------------------
    short = [scene["scene_id"] for scene in scenes
             if int(scene["duration_ms"]) < limits["min_scene_ms"]
             and not scene.get("duration_deviation")]
    long = [scene["scene_id"] for scene in scenes
            if int(scene["duration_ms"]) > limits["max_scene_ms"]
            and not scene.get("duration_deviation")]
    report.checks.append(Check(
        "pacing_inside_band", not short and not long,
        f"unexplained deviations: short={short} long={long}",
    ))
    per_ten = (len(scenes) / (narration_ms / 1000.0) * 10.0) if narration_ms else 0.0
    report.checks.append(Check(
        "scene_rate", per_ten >= limits["min_scenes_per_10s"],
        f"{per_ten:.2f} scenes per 10 s (minimum {limits['min_scenes_per_10s']})",
    ))

    # -- 3. breadth of visuals ----------------------------------------------
    asset_ids = [scene.get("asset_id") for scene in scenes if scene.get("asset_id")]
    variants = [(scene.get("resolution") or {}).get("variant") for scene in scenes]
    distinct_ratio = (len(set(asset_ids)) / len(scenes)) if scenes else 0.0
    report.checks.append(Check(
        "distinct_visuals", distinct_ratio >= limits["min_distinct_assets_ratio"],
        f"{len(set(asset_ids))} distinct visuals over {len(scenes)} scenes "
        f"({distinct_ratio:.2f} < {limits['min_distinct_assets_ratio']})"
        if distinct_ratio < limits["min_distinct_assets_ratio"]
        else f"{len(set(asset_ids))} distinct visuals over {len(scenes)} scenes",
    ))
    distinct_variants = {variant for variant in variants if variant}
    report.checks.append(Check(
        "composition_variety", len(distinct_variants) >= limits["min_distinct_variants"],
        f"compositions used: {sorted(distinct_variants)}",
    ))

    run_length, longest, previous = 0, 0, None
    for variant in variants:
        if variant and variant == previous:
            run_length += 1
        else:
            run_length = 1
            previous = variant
        longest = max(longest, run_length)
    report.checks.append(Check(
        "no_repeated_composition_runs", longest <= limits["max_consecutive_same_variant"],
        f"longest run of the same composition: {longest}",
    ))

    # -- 4. every scene shows something, and says what it rendered -----------
    empty = [scene["scene_id"] for scene in scenes
             if not (scene.get("resolution") or {}).get("asset_id")]
    report.checks.append(Check(
        "every_scene_has_a_visual", not empty or not limits["require_visual_every_scene"],
        f"scenes without a visual: {empty}",
    ))
    mislabelled = [scene["scene_id"] for scene in scenes
                   if not scene.get("coverage_category")]
    report.checks.append(Check(
        "rendered_category_recorded", not mislabelled,
        f"scenes missing a rendered category: {mislabelled}",
    ))

    # -- 4b. does the plate agree with the sentence? -------------------------
    #
    # Warnings, not failures: a legitimate paraphrase ("what sets the date" for a sentence about
    # timelines) has no shared word, and a check that cannot tell paraphrase from mismatch must not
    # claim the video is wrong. It is still worth surfacing - the audited render shipped a plate
    # labelled STUDY for a sentence about videos, and nothing in the pipeline said so.
    # A plate title may paraphrase its sentence; what it may not do is name something the episode
    # never mentions. The audited failure was a plate labelled STUDY on a sentence about videos, and
    # that word appears nowhere in the narration - which is what this measures.
    episode_vocabulary: set[str] = set()
    for scene in scenes:
        episode_vocabulary |= content_words(str(scene.get("narration_text") or ""))
        episode_vocabulary |= content_words(str(scene.get("main_concept") or ""))
    mismatched_titles = []
    for scene in scenes:
        title = str((scene.get("resolution") or {}).get("spec_title")
                    or scene.get("main_concept") or "")
        words = content_words(title)
        if not words:
            continue
        if not words & episode_vocabulary:
            mismatched_titles.append(scene["scene_id"])
    report.checks.append(Check(
        "title_matches_narration", not mismatched_titles,
        f"plates whose title shares no content word with the episode's narration: {mismatched_titles} "
        f"- a paraphrase is fine, an unmentioned subject is not", severity="warn",
    ))

    agreement = scene_plan.get("line_agreement") or {}
    if agreement.get("checked"):
        report.checks.append(Check(
            "headline_matches_active_line", not agreement.get("mismatches"),
            f"{agreement.get('checked')} scenes checked; cards whose headline line differs from the "
            f"scene's line: {agreement.get('mismatches') or 'none'}", severity="warn",
        ))

    # -- 4b. stated figures and provenance (v1.1) ----------------------------
    #
    # A chart is the most authoritative object on a card, so a number that the narration never says is
    # the worst thing this engine could put on screen. `figure_is_stated` compares every digit the
    # plate shows with the digits the sentence speaks.
    unsupported: list[str] = []
    for scene in scenes:
        resolution = scene.get("resolution") or {}
        shown = " ".join(str(value) for value in (resolution.get("visible_text") or []))
        shown += " " + str(resolution.get("spec_title") or "")
        spoken = str(scene.get("narration_text") or "")
        spoken_digits = {token.replace(",", "") for token in re.findall(r"\d[\d,]*", spoken)}
        # "Two years later" states the number 2; a digit-only comparison would call the plate's
        # "STEP 2" an invention. Number words count as stating the number.
        spoken_digits |= {str(_NUMBER_WORDS[word]) for word in re.findall(r"[a-z]+", spoken.lower())
                          if word in _NUMBER_WORDS}
        for token in re.findall(r"\d[\d,]*", shown):
            digits = token.replace(",", "")
            if digits not in spoken_digits:
                unsupported.append(f"{scene['scene_id']}:{token}")
    report.checks.append(Check(
        "figure_is_stated", not unsupported,
        f"numbers shown on a plate that the narration does not state: {unsupported}"
        if unsupported else "every number on screen is stated in the narration",
    ))

    undelivered = [scene["scene_id"] for scene in scenes
                   if scene.get("visual_category") == "dataviz"
                   and (scene.get("coverage_category") or scene.get("resolution", {}).get("category"))
                   != "dataviz"]
    report.checks.append(Check(
        "dataviz_delivered", not undelivered,
        f"dataviz scenes rendered as a non-chart visual: {undelivered} "
        f"(correct when the sentence states no comparable figure)"
        if undelivered else "every dataviz scene rendered a chart",
        severity="warn",
    ))

    fingerprints = [str((scene.get("resolution") or {}).get("plate_fingerprint") or "")
                    for scene in scenes]
    measured = [value for value in fingerprints if value]
    if len(measured) != len(scenes) or not measured:
        report.checks.append(Check(
            "visual_diversity_pixels", False,
            f"{len(measured)} of {len(scenes)} plates carry a fingerprint: pixel diversity unmeasured "
            f"(the renderer writes these; a hand-made scenes.json does not)", severity="warn",
        ))
    else:
        clusters: list[list[str]] = []
        for fingerprint in measured:
            for cluster in clusters:
                if _hamming(fingerprint, cluster[0]) <= int(limits["max_fingerprint_distance"]):
                    cluster.append(fingerprint)
                    break
            else:
                clusters.append([fingerprint])
        ratio = len(clusters) / len(measured)
        report.checks.append(Check(
            "visual_diversity_pixels", ratio >= float(limits["min_distinct_pixel_ratio"]),
            f"{len(clusters)} distinct pictures over {len(measured)} plates ({ratio:.2f}, minimum "
            f"{limits['min_distinct_pixel_ratio']})",
        ))

    missing_provenance = []
    unattributed = []
    for scene in scenes:
        resolution = scene.get("resolution") or {}
        for key, value in (("asset_id", scene.get("asset_id")),
                           ("asset_source", scene.get("asset_source")),
                           ("license", scene.get("license")),
                           ("entities", resolution.get("entities"))):
            if value in (None, ""):
                missing_provenance.append(f"{scene['scene_id']}:{key}")
        licence = scene.get("license")
        if licence in REQUIRES_ATTRIBUTION and not (scene.get("attribution_text")
                                                    or resolution.get("attribution")):
            unattributed.append(f"{scene['scene_id']}:{licence}")
    report.checks.append(Check(
        "provenance_recorded", not missing_provenance,
        f"scenes missing provenance: {missing_provenance}" if missing_provenance
        else "every scene records asset id, source, licence and entities",
    ))
    report.checks.append(Check(
        "attribution_present", not unattributed,
        f"scenes whose licence requires attribution and none was recorded: {unattributed}"
        if unattributed else "attribution recorded wherever the licence requires it",
    ))

    # -- 5. legibility ------------------------------------------------------
    long_titles = [scene["scene_id"] for scene in scenes
                   if len(str((scene.get("resolution") or {}).get("spec_title")
                              or scene.get("main_concept") or "")) > limits["max_title_chars"]]
    report.checks.append(Check(
        "titles_fit_the_plate", not long_titles,
        f"titles over {limits['max_title_chars']} characters: {long_titles}", severity="warn",
    ))
    wordy = [scene["scene_id"] for scene in scenes
             if len(str(scene.get("on_screen_text") or "").split()) > limits["max_on_screen_words"]]
    report.checks.append(Check(
        "on_screen_text_short", not wordy, f"on-screen text too long in: {wordy}", severity="warn",
    ))

    # -- 6. composition on the real frames ----------------------------------
    if framing is not None:
        collisions = int(framing.get("subtitle_collision_frames") or 0)
        overflow = int((framing.get("elements", {}).get("caption", {}) or {}).get("max_overflow_px") or 0)
        headline_overflow = int((framing.get("elements", {}).get("headline", {}) or {})
                                .get("max_overflow_px") or 0)
        report.checks.append(Check(
            "no_caption_collisions", collisions <= limits["max_caption_collision_frames"],
            f"{collisions} sampled frames had a caption collision",
        ))
        report.checks.append(Check(
            "captions_inside_safe_area", overflow == 0 and headline_overflow == 0,
            f"caption overflow {overflow}px, headline overflow {headline_overflow}px",
        ))
        visual = framing.get("elements", {}).get("visual") or {}
        if visual:
            report.checks.append(Check(
                "visual_inside_safe_area", int(visual.get("max_overflow_px") or 0) == 0,
                f"visual plate overflow {visual.get('max_overflow_px')} px, "
                f"painted on {visual.get('painted_frames')} sampled frames",
            ))

    categories: dict[str, int] = {}
    for scene in scenes:
        key = str(scene.get("coverage_category") or "unresolved")
        categories[key] = categories.get(key, 0) + 1
    report.metrics = {
        "scenes": len(scenes),
        "narration_ms": narration_ms,
        "mean_scene_ms": int(covered / len(scenes)) if scenes else 0,
        "categories_rendered": categories,
        "distinct_assets": len(set(asset_ids)),
        "distinct_asset_ratio": round(distinct_ratio, 3),
        "compositions": sorted(distinct_variants),
        "longest_composition_run": longest,
        "scene_rate_per_10s": round(per_ten, 2),
    }
    return report


def evaluate_scenes_file(
    scenes_path: str | Path,
    *,
    framing_path: str | Path | None = None,
    thresholds: dict[str, Any] | None = None,
) -> CreativeReport:
    """Convenience entry point for the CLI and the publishing gate."""

    scenes = json.loads(Path(scenes_path).read_text(encoding="utf-8"))
    framing = None
    if framing_path and Path(framing_path).is_file():
        framing = json.loads(Path(framing_path).read_text(encoding="utf-8"))
    thresholds = thresholds or load_thresholds()
    # The plan's own band is applied inside `evaluate`, where the plan is available.
    return evaluate(channel=str(scenes.get("channel") or ""), scene_plan=scenes,
                    framing=framing, thresholds=thresholds)
