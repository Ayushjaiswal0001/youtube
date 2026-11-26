"""Stop buttons, because a production system needs one that works without a developer.

Two levels, both checked before any work starts and before any upload:

* **global** - ``FACTORY_PAUSED=1`` or a ``PAUSED`` file in the state directory stops every channel;
* **per channel** - a channel's ``production_enabled: false`` setting, the
  ``FACTORY_PAUSED_CHANNELS`` variable, or a ``PAUSED_<channel>`` file.

The environment variable is what CI uses (a repository variable is one click to set), and the file is
what a person uses on a machine at 2 a.m. Both are read fresh on every call, so a pause takes effect on
the next job rather than on the next deploy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from factory.config import STATE_ROOT, load_channel_specs


class ProductionPaused(RuntimeError):
    """Raised when a run is not allowed to start. Never caught to "continue anyway"."""


@dataclass
class PauseState:
    paused: bool
    reason: str
    scope: str  # "global", "channel" or "none"

    def as_dict(self) -> dict:
        return {"paused": self.paused, "reason": self.reason, "scope": self.scope}


def _state_root(root: Optional[Path | str] = None) -> Path:
    return Path(root or STATE_ROOT)


def pause_state(channel: Optional[str] = None, *, environ: Optional[Mapping[str, str]] = None,
                root: Optional[Path | str] = None) -> PauseState:
    env = os.environ if environ is None else environ
    state = _state_root(root)

    if str(env.get("FACTORY_PAUSED", "")).strip().lower() in ("1", "true", "yes", "on"):
        return PauseState(True, "FACTORY_PAUSED is set", "global")
    if (state / "PAUSED").is_file():
        return PauseState(True, f"{state / 'PAUSED'} exists", "global")

    if channel:
        spec = load_channel_specs().get(channel)
        if spec is not None and not spec.production_enabled:
            return PauseState(
                True, "production_enabled is false in channel configuration", "channel"
            )
        listed = {part.strip() for part in str(env.get("FACTORY_PAUSED_CHANNELS", "")).split(",")
                  if part.strip()}
        if channel in listed:
            return PauseState(True, f"FACTORY_PAUSED_CHANNELS lists {channel}", "channel")
        flag = state / f"PAUSED_{channel}"
        if flag.is_file():
            return PauseState(True, f"{flag} exists", "channel")

    return PauseState(False, "", "none")


def ensure_allowed(channel: Optional[str] = None, *, environ: Optional[Mapping[str, str]] = None,
                   root: Optional[Path | str] = None, action: str = "production") -> None:
    state = pause_state(channel, environ=environ, root=root)
    if state.paused:
        who = f"channel {channel}" if state.scope == "channel" else "all channels"
        raise ProductionPaused(f"{action} is paused for {who}: {state.reason}")


def pause(channel: Optional[str] = None, *, root: Optional[Path | str] = None) -> Path:
    """Create the flag file. Returns the path so a caller can report it."""

    state = _state_root(root)
    state.mkdir(parents=True, exist_ok=True)
    path = state / (f"PAUSED_{channel}" if channel else "PAUSED")
    path.write_text("paused\n", encoding="utf-8")
    return path


def resume(channel: Optional[str] = None, *, root: Optional[Path | str] = None) -> bool:
    path = _state_root(root) / (f"PAUSED_{channel}" if channel else "PAUSED")
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return existed
