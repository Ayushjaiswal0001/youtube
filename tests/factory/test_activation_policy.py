from __future__ import annotations

from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.controls import pause_state


def test_activation_order_enables_only_verified_nexus(tmp_path: Path) -> None:
    specs = load_channel_specs()

    assert specs["nexus-node"].production_enabled is True
    assert specs["academic-biohacker"].production_enabled is False
    assert specs["natkhat-toons"].production_enabled is False

    assert pause_state("nexus-node", environ={}, root=tmp_path).paused is False
    academic = pause_state("academic-biohacker", environ={}, root=tmp_path)
    assert academic.paused is True
    assert academic.scope == "channel"
    assert "production_enabled is false" in academic.reason
    natkhat = pause_state("natkhat-toons", environ={}, root=tmp_path)
    assert natkhat.paused is True
    assert natkhat.scope == "channel"
    assert "production_enabled is false" in natkhat.reason


@pytest.mark.parametrize("channel", ["academic-biohacker", "natkhat-toons"])
def test_disabled_channel_cannot_become_ready_for_scheduled_publishing(channel, capsys) -> None:
    from factory.cli import main

    result = main(["publishing", "--channel", channel, "--json"])

    assert result == 0
    output = capsys.readouterr().out
    assert '"production_enabled": false' in output
    assert '"may_upload_on_schedule": false' in output
    assert '"ready": false' in output
