"""Scene transition policy.

Scenes were concatenated end to end, so every cut was a hard jump, including a jump between
two different locations. The policy here is the one an editor would use:

* a new location dips to black (a short fade out, a short fade in);
* two consecutive beats in the same location cut directly, because a fade between them would
  read as a time skip that did not happen;
* the episode opens from black and closes to black.
"""

from __future__ import annotations

from typing import Sequence, Tuple

TRANSITION = 0.22   # fade out / fade in at a location change
OPENING = 0.45      # fade up from black at the start
CLOSING = 0.65      # fade down to black at the end


def plan_transitions(scenes: Sequence[dict], transition: float = TRANSITION,
                     opening: float = OPENING, closing: float = CLOSING
                     ) -> list[Tuple[float, float]]:
    """Return ``(fade_in, fade_out)`` seconds for each scene, in order."""

    count = len(scenes)
    if count == 0:
        return []
    backgrounds = [str(scene.get("bg", "")) for scene in scenes]
    plan: list[Tuple[float, float]] = []
    for index in range(count):
        previous_changes = index > 0 and backgrounds[index] != backgrounds[index - 1]
        next_changes = index < count - 1 and backgrounds[index] != backgrounds[index + 1]
        fade_in = transition if previous_changes else 0.0
        fade_out = transition if next_changes else 0.0
        if index == 0:
            fade_in = opening
        if index == count - 1:
            fade_out = closing
        plan.append((fade_in, fade_out))
    return plan


def ffmpeg_fade_filters(fade_in: float, fade_out: float, duration: float) -> list[str]:
    """Video filters for one scene, clamped so the fades can never overlap."""

    filters: list[str] = []
    span = max(0.0, float(duration))
    fade_in = max(0.0, min(float(fade_in), span / 2.0))
    fade_out = max(0.0, min(float(fade_out), span / 2.0))
    if fade_in > 0:
        filters.append(f"fade=t=in:st=0:d={fade_in:.3f}:color=black")
    if fade_out > 0:
        filters.append(
            f"fade=t=out:st={span - fade_out:.3f}:d={fade_out:.3f}:color=black"
        )
    return filters
