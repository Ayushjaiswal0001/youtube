"""Content availability: a bank with nothing left is a warning, a blocked run is a failure.

Three defects found by running the merged code on 2026-11-25, all in this area:

* each channel ships exactly **one** long-form plan, so from day two the long job raised "every long-form plan
  has been uploaded" and went red every night for a reason engineering cannot fix;
* `natkhat-haveli` starts at episode 4 and the ordering guard demanded episode 3 be uploaded first - an episode
  this repository has never produced - so the channel could not start at all;
* a run with no content still reached the render steps, because nothing asked the question first.

These tests pin the answer: the planner says whether there is anything to make, the workflow warns and skips
when the bank is empty, and it still fails hard when the run is blocked rather than empty.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from factory.config import load_channel_specs

WORKFLOWS = Path(".github/workflows")


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """A private state root, so the real pipeline_state is never read or written."""

    import factory.state as state_module

    monkeypatch.setattr(state_module, "STATE_ROOT", tmp_path)
    return tmp_path


def history(root: Path, channel: str) -> Path:
    return root / channel / "history.json"


def record(root: Path, channel: str, **entry) -> None:
    path = history(root, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    items.append(entry)
    path.write_text(json.dumps(items), encoding="utf-8")


def run_cli(state_root: Path, *args: str) -> tuple[int, str]:
    """Run the real CLI against a private state root: `FACTORY_STATE_DIR` is read at import time."""

    import os

    env = dict(os.environ)
    env["FACTORY_STATE_DIR"] = str(state_root)
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "factory.cli", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300, env=env,
    )
    return completed.returncode, completed.stdout + completed.stderr


def payload(text: str):
    return json.loads(text[text.index("["):])


# ------------------------------------------------------------------------------ the planner's exception


def test_an_empty_long_form_bank_is_exhaustion_not_a_fault(state):
    from factory.content.plans import PlanGenerationError, generate_plan

    spec = load_channel_specs()["nexus-node"]
    plan = generate_plan(spec, write=False, format="long")
    assert plan["plan_id"] == "long-nexus-power-grid"

    # once it has been uploaded there is nothing left, and that is a content gap
    record(state, "nexus-node", status="uploaded", plan_id="long-nexus-power-grid")
    with pytest.raises(PlanGenerationError) as excinfo:
        generate_plan(spec, write=False, format="long")
    assert excinfo.value.kind == "exhausted"
    assert "author the next long-form episode" in str(excinfo.value)


def test_a_fresh_series_channel_can_start(state):
    """`start_episode: 4` means 1-3 belong to an earlier batch; requiring them blocked the channel for ever."""

    from factory.content.plans import generate_plan

    spec = load_channel_specs()["natkhat-toons"]
    plan = generate_plan(spec, write=False)
    assert plan["plan_id"] == "natkhat-haveli-e4"


def test_next_haveli_short_has_character_actions_and_a_rooftop_cut(state):
    from factory.content.plans import generate_plan

    plan = generate_plan(load_channel_specs()["natkhat-toons"], write=False)["plan"]
    assert plan["scenes"][0]["prop"] == "brass_key"
    assert plan["scenes"][0]["chiku_motion"] == "turn"
    assert plan["scenes"][2]["gappu_motion"] == "point"
    assert plan["scenes"][3]["bg"] == "village_night"
    assert plan["scenes"][4]["chiku_motion"] == "wave"


def test_an_episode_the_factory_rendered_but_did_not_publish_still_blocks(state):
    """The guard must keep working for episodes the factory *did* produce."""

    from factory.content.plans import PlanGenerationError, generate_plan

    spec = load_channel_specs()["natkhat-toons"]
    (state / "natkhat-toons").mkdir(parents=True, exist_ok=True)
    (state / "natkhat-toons" / "series.json").write_text(
        json.dumps({"active_series": "natkhat-haveli", "next_episode": 5}), encoding="utf-8")
    record(state, "natkhat-toons", status="rendered", plan_id="natkhat-haveli-e4")

    with pytest.raises(PlanGenerationError) as excinfo:
        generate_plan(spec, write=False)
    assert excinfo.value.kind == "blocked"
    assert "out of order" in str(excinfo.value)


# -------------------------------------------------------------------------------------- the CLI verb


def test_the_cli_reports_an_exhausted_bank_as_available_false_and_exits_zero(state):
    record(state, "nexus-node", status="uploaded", plan_id="long-nexus-power-grid")
    code, output = run_cli(state, "plan", "available", "--channel", "nexus-node", "--format", "long", "--json")
    assert code == 0, output  # a content gap is not a failure
    item = payload(output)[0]
    assert item["available"] is False
    assert item["kind"] == "exhausted"


def test_the_cli_reports_a_blocked_run_and_exits_non_zero(state):
    code, output = run_cli(state, "plan", "available", "--channel", "natkhat-toons", "--format", "long", "--json")
    # the long-form bank is present and unused, so this is available; make it blocked by consuming it
    assert code == 0
    assert payload(output)[0]["available"] is True

    (state / "natkhat-toons").mkdir(parents=True, exist_ok=True)
    (state / "natkhat-toons" / "series.json").write_text(
        json.dumps({"active_series": "natkhat-haveli", "next_episode": 5}), encoding="utf-8")
    record(state, "natkhat-toons", status="rendered", plan_id="natkhat-haveli-e4")
    code, output = run_cli(state, "plan", "available", "--channel", "natkhat-toons", "--json")
    assert code == 2, output
    item = payload(output)[0]
    assert item["available"] is False
    assert item["kind"] == "blocked"


def test_the_step_output_helper_reads_a_log_prefixed_payload(tmp_path: Path):
    document = [{
        "channel": "nexus-node", "format": "long", "available": False,
        "kind": "exhausted", "reason": "every long-form plan has been uploaded",
    }]
    path = tmp_path / "available.json"
    path.write_text("INFO some log line\n" + json.dumps(document), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/content_outputs.py", str(path)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    lines = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert lines["available"] == "0"
    assert lines["kind"] == "exhausted"
    assert "every long-form plan" in lines["reason"]


# ------------------------------------------------------------------------------------ workflow wiring


def steps() -> list[dict]:
    workflow = yaml.safe_load((WORKFLOWS / "produce.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["produce"]["steps"]


def step_named(name: str) -> dict:
    return next(s for s in steps() if s.get("name") == name)


def test_the_workflow_asks_whether_there_is_content_before_it_renders():
    names = [s.get("name") for s in steps()]
    assert names.index("Content availability") < names.index("Resolve the plan")
    assert names.index("Content availability") < names.index("Resume or render")


@pytest.mark.parametrize("name", [
    "Resolve the plan", "Resume or render", "Quality assurance",
    "Rebuild manifest after QC", "Publishing gate", "Package manifest",
])
def test_no_production_step_runs_without_content(name: str):
    assert "steps.content.outputs.available == '1'" in str(step_named(name).get("if"))


@pytest.mark.parametrize("name", [
    "Export channel credentials", "Verify channel identity before upload", "Upload (private, gated)",
])
def test_a_skipped_day_cannot_reach_a_credential(name: str) -> None:
    condition = str(step_named(name).get("if"))
    assert "steps.content.outputs.available == '1'" in condition
    assert condition.startswith("${{ inputs.upload")
