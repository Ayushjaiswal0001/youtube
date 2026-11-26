from __future__ import annotations

from pathlib import Path

from factory.config import load_channel_specs
from factory.controls import pause_state


def test_activation_order_enables_nexus_and_academic_but_holds_natkhat(tmp_path: Path) -> None:
    specs = load_channel_specs()

    assert specs["nexus-node"].production_enabled is True
    assert specs["academic-biohacker"].production_enabled is True
    assert specs["natkhat-toons"].production_enabled is False

    assert pause_state("nexus-node", environ={}, root=tmp_path).paused is False
    assert pause_state("academic-biohacker", environ={}, root=tmp_path).paused is False
    natkhat = pause_state("natkhat-toons", environ={}, root=tmp_path)
    assert natkhat.paused is True
    assert natkhat.scope == "channel"
    assert "production_enabled is false" in natkhat.reason


def test_disabled_channel_cannot_become_ready_for_scheduled_publishing(capsys) -> None:
    from factory.cli import main

    result = main(["publishing", "--channel", "natkhat-toons", "--json"])

    assert result == 0
    output = capsys.readouterr().out
    assert '"production_enabled": false' in output
    assert '"may_upload_on_schedule": false' in output
    assert '"ready": false' in output
