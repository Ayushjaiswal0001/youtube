"""Conversational cinematography: which shot, of whom, and why (T42).

The authored plans named a camera per scene, and some of them named the wrong character: scene 11 of
the Haveli episode has Gappu speaking over a `medium_chiku`, a medium shot of the listener while the
speaker's mouth is off screen. Five consecutive scenes in the middle of the same conversation were
all `two_shot`, so the middle of a two-hander had no reverse coverage at all.

This module derives the shot from the *conversation* instead of from the scene index:

* who owns the line,
* who is listening,
* whether the location just changed,
* what was framed on the previous cut.

It is deliberately not a timer. Nothing here counts scenes or alternates on a parity bit: the shot
follows the dialogue, so re-ordering two lines re-orders the shots and inserting a narrator beat
changes the coverage of the lines around it.

The vocabulary is the camera's existing one (`medium_<name>`, `reaction_<name>`, `close_up_<name>`,
`two_shot`, `wide_establishing`); this module chooses among the styles that already exist rather than
inventing a parallel set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# A shot naming one character. `medium_` and `reaction_` are single-subject framings; `close_up_`
# is the tightest and is the one that has to be earned.
SUBJECT_PREFIXES: Tuple[str, ...] = ("medium_", "reaction_", "close_up_")

# A line ends on a beat only when it is a question or an exclamation. The Devanagari danda is an
# ordinary full stop - Hindi dialogue ends almost every sentence with one - so treating it as a beat
# made every single turn "punctuated" and turned the episode into a wall of close-ups.
HARD_STOPS: Tuple[str, ...] = ("?", "!")

# A close-up is the tightest frame available; spending one every other line flattens the edit.
MIN_TURNS_BETWEEN_CLOSE_UPS = 2

DEFAULT_PARTICIPANTS: Tuple[str, ...] = ("chiku", "gappu")

# More than one cut every two seconds reads as a nervous edit, not as coverage.
MIN_SECONDS_PER_CUT = 2.0


@dataclass(frozen=True)
class ShotDecision:
    """One scene's framing, with the reason it was chosen."""

    scene_num: int
    camera: str
    subject: Optional[str]
    reason: str
    speaker: str = "narrator"
    listener: Optional[str] = None
    location: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scene": self.scene_num,
            "camera": self.camera,
            "subject": self.subject,
            "reason": self.reason,
            "speaker": self.speaker,
            "listener": self.listener,
            "location": self.location,
        }


@dataclass
class ShotPlan:
    """A whole episode's shot decisions plus the spatial facts they depend on."""

    decisions: List[ShotDecision] = field(default_factory=list)
    screen_side: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    participants: Tuple[str, ...] = DEFAULT_PARTICIPANTS

    def by_scene(self) -> Dict[int, ShotDecision]:
        return {decision.scene_num: decision for decision in self.decisions}

    def cameras(self) -> List[str]:
        return [decision.camera for decision in self.decisions]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decisions": [decision.to_dict() for decision in self.decisions],
            "screen_side": dict(self.screen_side),
            "warnings": list(self.warnings),
            "participants": list(self.participants),
        }


def _subject_of(camera: str, participants: Sequence[str]) -> Optional[str]:
    for prefix in SUBJECT_PREFIXES:
        if camera.startswith(prefix):
            name = camera[len(prefix):]
            return name if name in participants else None
    return None


def _is_hard_stop(line: str) -> bool:
    """Does this line land on a beat?

    Either it ends on one, or it opens with an interjection ("अरे!", "देखा?") - Hindi dialogue puts
    the emotional emphasis first and then explains it, so checking only the last character missed
    every line like "अरे! खिड़की की सील पर कुछ चमक रहा है।"
    """

    stripped = line.strip()
    if not stripped:
        return False
    if stripped.endswith(HARD_STOPS):
        return True
    return stripped.split()[0].endswith(HARD_STOPS)


def screen_sides(anchors: Iterable[Tuple[str, float]]) -> Dict[str, str]:
    """Which half of the frame each character occupies, from where the stage put them.

    This is the axis of action for a two-hander: Chiku on the left always looks right, Gappu on the
    right always looks left, and no cut may quietly swap them.
    """

    ordered = sorted(anchors, key=lambda item: float(item[1]))
    if len(ordered) == 1:
        return {ordered[0][0]: "centre"}
    return {
        name: ("left" if index < len(ordered) / 2 else "right")
        for index, (name, _) in enumerate(ordered)
    }


def _resolve_speaker_shot(speaker: str, listener: Optional[str], previous: Optional[ShotDecision],
                          line: str, turn_counts: Dict[str, int],
                          close_up_turn: int = -99) -> Tuple[str, str]:
    """The shot for a line delivered by a character."""

    previous_camera = previous.camera if previous else ""
    same_subject_twice = previous_camera in (
        f"medium_{speaker}", f"close_up_{speaker}", f"reaction_{speaker}")

    if same_subject_twice:
        # Two identical framings back to back is a jump cut, not coverage. Borrow the partner's
        # frame for this line and let the reverse shot carry the answer.
        if listener and previous_camera != f"reaction_{listener}":
            return f"reaction_{listener}", "same_subject_twice"
        return "two_shot", "same_subject_twice"

    turn = turn_counts.get(speaker, 0)
    if (_is_hard_stop(line) and turn >= 2 and listener
            and turn - close_up_turn >= MIN_TURNS_BETWEEN_CLOSE_UPS):
        # A character who has had several turns and lands a question or an exclamation earns the
        # tight frame - provided the last close-up is not too recent.
        return f"close_up_{speaker}", "punctuated_turn"

    return f"medium_{speaker}", "speaker_medium"


def _resolve_narrator_shot(previous: Optional[ShotDecision]) -> Tuple[str, str]:
    previous_camera = previous.camera if previous else ""
    if previous_camera == "two_shot":
        # The narrator already held both of them; hold the pair again only after a single frame.
        return "wide_establishing", "narrator_after_two_shot"
    return "two_shot", "narrator_watching_both"


def plan_conversation(
    scenes: Sequence[Dict[str, Any]],
    *,
    anchors: Iterable[Tuple[str, float]],
    participants: Sequence[str] = DEFAULT_PARTICIPANTS,
) -> ShotPlan:
    """Plan the shots for a dialogue sequence.

    `scenes` is the story packet's scene list (speaker, dialogue, bg, scene_num). `anchors` is
    (name, world_x) for the cast, which fixes the axis of action.
    """

    present = tuple(participants)
    plan = ShotPlan(screen_side=screen_sides(anchors), participants=present)
    turn_counts: Dict[str, int] = {name: 0 for name in present}
    close_up_turn = -99
    previous: Optional[ShotDecision] = None
    previous_location = ""

    for scene in scenes:
        line = str(scene.get("dialogue") or "")
        speaker = str(scene.get("speaker") or "narrator")
        location = str(scene.get("bg") or scene.get("location") or "")
        listener = next((name for name in present if name != speaker), None) \
            if speaker in present else None

        if speaker in present:
            turn_counts[speaker] = turn_counts.get(speaker, 0) + 1

        if previous is None:
            # An episode opens on the space, not on a face.
            camera, reason = "wide_establishing", "episode_open"
        elif location and previous_location and location != previous_location:
            camera, reason = "wide_establishing", "location_change"
        elif speaker in present:
            camera, reason = _resolve_speaker_shot(
                speaker, listener, previous, line, turn_counts, close_up_turn)
        else:
            camera, reason = _resolve_narrator_shot(previous)

        # A repeat is only a repeat in the same space: two wides either side of a location change are
        # two different photographs, and collapsing them was how a scene lost its own wide.
        if (previous is not None and camera == previous.camera
                and location == previous.location):
            camera, reason = "wide_establishing", "repeat_avoided"

        decision = ShotDecision(
            scene_num=int(scene.get("scene_num") or scene.get("scene") or 0),
            camera=camera,
            subject=_subject_of(camera, present),
            reason=reason,
            speaker=speaker,
            listener=listener,
            location=location,
        )
        plan.decisions.append(decision)
        if camera.startswith("close_up_"):
            close_up_turn = turn_counts.get(speaker, 0)
        previous = decision
        if location:
            previous_location = location

    plan.warnings.extend(validate_plan(plan))
    return plan


def validate_plan(plan: ShotPlan) -> List[str]:
    """Continuity and coverage violations. Returns readable strings, never raises."""

    violations: List[str] = []
    decisions = plan.decisions

    for decision in decisions:
        subject = decision.subject
        if subject is not None and subject not in plan.participants:
            violations.append(
                f"scene {decision.scene_num}: shot {decision.camera!r} names {subject!r}, "
                "who is not in this scene")

        # A single-subject shot of the listener while the speaker is delivering the line leaves the
        # line without a mouth. This is the defect that motivated the module.
        if subject is not None and decision.speaker in plan.participants:
            if subject != decision.speaker:
                violations.append(
                    f"scene {decision.scene_num}: {decision.camera!r} frames "
                    f"{subject!r} while {decision.speaker!r} is speaking")

    for previous, current in zip(decisions, decisions[1:]):
        if previous.camera == current.camera:
            violations.append(
                f"scenes {previous.scene_num}->{current.scene_num}: identical framing "
                f"{current.camera!r} either side of a cut")

        # Axis of action: a sign flip between two shots of the same pair reads as a jump in space.
        if previous.subject and current.subject and previous.location == current.location:
            left, right = plan.screen_side.get(previous.subject), \
                plan.screen_side.get(current.subject)
            if left and right and left == right and previous.subject != current.subject:
                violations.append(
                    f"scenes {previous.scene_num}->{current.scene_num}: "
                    f"{previous.subject!r} and {current.subject!r} share the {left} side")

    # Coverage: a run of one speaker's turns with no shot of the other side at all.
    run: List[ShotDecision] = []
    for decision in decisions + [None]:  # type: ignore[list-item]
        if decision is not None and decision.speaker in plan.participants:
            run.append(decision)
            continue
        if len(run) >= 3 and len({item.subject for item in run}) == 1:
            violations.append(
                f"scenes {run[0].scene_num}-{run[-1].scene_num}: {len(run)} lines with no "
                f"reverse coverage (every shot framed {run[0].subject!r})")
        run = []

    for decision in decisions:
        if decision.reason == "punctuated_turn" and decision.speaker not in plan.participants:
            violations.append(
                f"scene {decision.scene_num}: a close-up was earned by a non-participant")

    return violations


def apply_plan(scenes: Sequence[Dict[str, Any]], plan: ShotPlan, *,
               respect_authored: bool = True) -> List[Dict[str, Any]]:
    """Return new scene dicts with the planned camera, leaving authored cameras alone if asked."""

    replacements = plan.by_scene()
    out: List[Dict[str, Any]] = []
    for scene in scenes:
        number = int(scene.get("scene_num") or scene.get("scene") or 0)
        decision = replacements.get(number)
        if decision is None:
            out.append(dict(scene))
            continue
        authored = str(scene.get("camera") or "").lower()
        keep = respect_authored and authored not in ("", "auto", "director")
        updated = dict(scene)
        if not keep:
            updated["camera"] = decision.camera
            updated["camera_reason"] = decision.reason
        out.append(updated)
    return out


def cut_rate_violations(scenes: Sequence[Dict[str, Any]], plan: ShotPlan,
                        durations: Optional[Sequence[float]] = None) -> List[str]:
    """Flag an edit that cuts faster than an audience can follow."""

    if not durations or len(durations) != len(plan.decisions):
        return []
    violations: List[str] = []
    for index in range(1, len(plan.decisions)):
        if plan.decisions[index].camera == plan.decisions[index - 1].camera:
            continue
        if float(durations[index]) < MIN_SECONDS_PER_CUT:
            violations.append(
                f"scene {plan.decisions[index].scene_num}: cut after "
                f"{float(durations[index]):.2f}s, under the {MIN_SECONDS_PER_CUT:.1f}s floor")
    return violations
