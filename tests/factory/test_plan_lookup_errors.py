"""A requested plan that does not exist is an error, and an empty composition profile is not a crash.

Cloud acceptance run `45071096194` (nexus-node / `nexus-power-grid`) and `45071125280` (natkhat-toons /
`natkhat-haveli-e4`) failed like this:

    python -m factory.cli resume --channel ... --plan-id ... --json   ->  []
    python -m factory.cli validate ... --json                        ->  []
    IndexError: list index out of range                               (the workflow's QC step)

Three steps of failure for one cause: those plan ids exist only in the local build that named them, never in
`content/`. `resume` treated "matched nothing" as "nothing to do" and exited 0.

Run `45071111024` (academic-biohacker) found the other half: its Short rendered and **passed QC**, then the gate
died with `ValueError: no long plans for channel 'academic-biohacker'` because the gate now iterates both
composition profiles and that channel has no landscape plan at all.

Both are error-reporting defects, not quality-gate changes. Nothing here loosens a threshold: the fixes make
the pipeline refuse to continue instead of reporting an empty success.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from factory import cli, ops
from factory.config import load_channel_specs


@pytest.fixture(scope="module")
def specs():
    return load_channel_specs()


@pytest.fixture()
def build_dir(tmp_path, monkeypatch):
    """Point the build root at an empty directory so no real episode can be picked up."""

    import factory.orchestrator as orchestrator

    root = tmp_path / "build"
    root.mkdir()
    monkeypatch.setattr(orchestrator, "BUILD_ROOT", root)
    monkeypatch.setattr("factory.ops.episode_out_dir",
                        lambda spec, plan: root / spec.slug / str(plan.get("id") or "x"))
    return root


def _run(argv: list[str]) -> int:
    return cli.main(argv)


def test_validate_rejects_a_plan_that_is_not_in_the_repository(build_dir, capsys) -> None:
    code = _run(["validate", "--channel", "nexus-node", "--plan-id", "nexus-power-grid"])
    assert code != 0
    err = capsys.readouterr()
    message = err.err + err.out
    assert "nexus-power-grid" in message
    # the message has to say what does exist, or the operator is still guessing
    assert "nexus-data-wall" in message


def test_resume_rejects_a_plan_that_is_not_in_the_repository(build_dir, capsys) -> None:
    """This used to print `[]` and exit 0, which is why the run failed three steps later."""

    assert _run(["resume", "--channel", "natkhat-toons", "--plan-id", "natkhat-haveli-e4"]) != 0
    assert "natkhat-haveli-e4" in capsys.readouterr().err


def test_manifest_rejects_a_plan_that_is_not_in_the_repository(build_dir, capsys) -> None:
    assert _run(["manifest", "--channel", "nexus-node", "--plan-id", "nexus-power-grid"]) != 0
    assert "not in this repository" in capsys.readouterr().err


def test_gate_rejects_a_plan_that_is_not_in_the_repository(build_dir, capsys) -> None:
    assert _run(["gate", "--channel", "nexus-node", "--plan-id", "nexus-power-grid"]) != 0
    assert "nexus-power-grid" in capsys.readouterr().err


def test_gate_is_happy_with_a_channel_that_has_no_landscape_plan(build_dir, specs, monkeypatch) -> None:
    """The academic Short passed QC and the gate then crashed on the channel's *other* profile."""

    real = ops.load_plans_for

    def fake(spec, *args, **kwargs):
        if spec.format == "long":
            raise ValueError(f"no long plans for channel {spec.slug!r}")
        return real(spec, *args, **kwargs)

    monkeypatch.setattr(ops, "load_plans_for", fake)

    short_plan = next(plan for plan in real(replace(specs["academic-biohacker"], format="shorts"))
                      if str(plan.get("id")) == "academic-post-meal-walk")
    out_dir = ops.episode_out_dir(replace(specs["academic-biohacker"], format="shorts"), short_plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "video.mp4").write_bytes(b"not actually decoded, the gate is stubbed below")

    class _Stub:
        ok = True
        passed = 24
        total = 24
        blockers: list[str] = []
        checks: list = []

        def to_dict(self):
            return {"ok": True, "passed": 24, "total": 24, "blockers": [], "checks": []}

    import factory.ops as ops_module

    monkeypatch.setattr("factory.qa.publish_gate.evaluate_publish_gate",
                        lambda *a, **k: _Stub())
    monkeypatch.setattr(ops_module, "evaluate_publish_gate", lambda *a, **k: _Stub(), raising=False)

    class Args:
        channel = "academic-biohacker"
        plan_id = ""
        json = True

    out: list = []
    code = ops.cmd_gate(Args(), specs=specs, print_fn=out.append,
                        script_for=lambda spec, plan: _FakeScript())
    assert code == 0, out
    assert [item["plan_id"] for item in out[0]] == ["academic-post-meal-walk"]


class _FakeScript:
    """cmd_gate only hands the script to the (stubbed) gate."""

    format = "shorts"


def test_a_plan_walk_without_a_request_covers_every_plan(build_dir) -> None:
    class Args:
        channel = "nexus-node"
        plan_id = ""
        format = ""

    pairs = list(cli._iter_requested_plans(Args()))
    ids = {plan.get("id") for _, plan in pairs}
    assert "nexus-data-wall" in ids
    # Without --format the walk now crosses both composition profiles, because staying on the native one
    # made `validate --plan-id long-...` report "plan not in this repository" for a plan sitting on disk.
    # The change is additive: every plan is still walked, and exactly once.
    assert {spec.format for spec, _ in pairs} == {"shorts", "long"}
    assert len(ids) == len(pairs), "each plan must be walked once"

    class LongArgs(Args):
        format = "long"

    long_ids = {plan.get("id") for _, plan in cli._iter_requested_plans(LongArgs())}
    assert long_ids, "the landscape profile has its own plan and must be reachable with --format long"


def test_a_plan_walk_skips_a_profile_with_no_plans(build_dir) -> None:
    real = cli.load_plans_for

    def fake(spec, *args, **kwargs):
        if spec.format == "long":
            raise ValueError("no long plans")
        return real(spec, *args, **kwargs)

    cli.load_plans_for = fake
    try:
        class Args:
            channel = "academic-biohacker"
            plan_id = "academic-post-meal-walk"
            format = ""

        pairs = list(cli._iter_requested_plans(Args()))
        assert [plan.get("id") for _, plan in pairs] == ["academic-post-meal-walk"]
    finally:
        cli.load_plans_for = real
