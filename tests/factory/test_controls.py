"""The stop buttons, tested the way an operator would use them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory.controls import ProductionPaused, ensure_allowed, pause, pause_state, resume


def test_nothing_is_paused_by_default(tmp_path: Path) -> None:
    assert pause_state("nexus-node", environ={}, root=tmp_path).paused is False


def test_the_global_environment_flag_stops_every_channel(tmp_path: Path) -> None:
    for slug in ("nexus-node", "academic-biohacker", "natkhat-toons"):
        state = pause_state(slug, environ={"FACTORY_PAUSED": "1"}, root=tmp_path)
        assert state.paused and state.scope == "global"
    with pytest.raises(ProductionPaused):
        ensure_allowed("nexus-node", environ={"FACTORY_PAUSED": "true"}, root=tmp_path)


def test_a_per_channel_variable_stops_only_that_channel(tmp_path: Path) -> None:
    env = {"FACTORY_PAUSED_CHANNELS": "natkhat-toons, nexus-node"}
    assert pause_state("natkhat-toons", environ=env, root=tmp_path).paused
    assert pause_state("academic-biohacker", environ=env, root=tmp_path).paused is False


def test_the_flag_file_works_without_an_operator_present(tmp_path: Path) -> None:
    pause("natkhat-toons", root=tmp_path)
    with pytest.raises(ProductionPaused) as caught:
        ensure_allowed("natkhat-toons", environ={}, root=tmp_path)
    assert "paused" in str(caught.value)
    assert resume("natkhat-toons", root=tmp_path) is True
    ensure_allowed("natkhat-toons", environ={}, root=tmp_path)


def test_a_global_flag_file_stops_and_clears(tmp_path: Path) -> None:
    path = pause(root=tmp_path)
    assert path.name == "PAUSED"
    assert pause_state(environ={}, root=tmp_path).scope == "global"
    resume(root=tmp_path)
    assert pause_state(environ={}, root=tmp_path).paused is False


def test_the_error_names_the_channel_and_the_action(tmp_path: Path) -> None:
    pause("academic-biohacker", root=tmp_path)
    with pytest.raises(ProductionPaused) as caught:
        ensure_allowed("academic-biohacker", environ={}, root=tmp_path, action="upload")
    message = str(caught.value)
    assert "academic-biohacker" in message and "upload" in message


def test_pause_state_is_json_safe(tmp_path: Path) -> None:
    pause("nexus-node", root=tmp_path)
    json.dumps(pause_state("nexus-node", environ={}, root=tmp_path).as_dict())


def test_a_pause_never_looks_like_success(tmp_path: Path) -> None:
    """The guard raises; it does not return a falsy value a caller might ignore."""

    pause(root=tmp_path)
    with pytest.raises(ProductionPaused):
        ensure_allowed("nexus-node", environ={}, root=tmp_path)


def test_a_paused_channel_cannot_reach_the_publish_shell(monkeypatch) -> None:
    """`publish` must refuse before it looks at any artifact, exactly like `render`."""

    from factory import cli

    pause("nexus-node")
    try:
        code = cli.main(["publish", "--channel", "nexus-node", "--plan-id", "x", "--execute",
                         "--confirm-channel", "nexus-node"])
    finally:
        resume("nexus-node")
    assert code != 0
