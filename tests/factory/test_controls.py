"""The stop buttons, tested the way an operator would use them."""

from __future__ import annotations

import json
from dataclasses import replace
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


def test_a_per_channel_variable_stops_only_that_channel(monkeypatch, tmp_path: Path) -> None:
    from factory.config import load_channel_specs

    specs = load_channel_specs()
    specs["academic-biohacker"] = replace(specs["academic-biohacker"], production_enabled=True)
    monkeypatch.setattr("factory.controls.load_channel_specs", lambda: specs)
    env = {"FACTORY_PAUSED_CHANNELS": "natkhat-toons, nexus-node"}
    assert pause_state("natkhat-toons", environ=env, root=tmp_path).paused
    assert pause_state("academic-biohacker", environ=env, root=tmp_path).paused is False


def test_the_flag_file_works_without_an_operator_present(tmp_path: Path) -> None:
    pause("nexus-node", root=tmp_path)
    with pytest.raises(ProductionPaused) as caught:
        ensure_allowed("nexus-node", environ={}, root=tmp_path)
    assert "paused" in str(caught.value)
    assert resume("nexus-node", root=tmp_path) is True
    ensure_allowed("nexus-node", environ={}, root=tmp_path)


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


# ------------------------------------------------------------------ the guard has to be in the choke point

def test_resume_is_stopped_by_the_pause_and_says_so(monkeypatch, tmp_path: Path, capsys) -> None:
    """`resume` is the verb the workflow calls to render, and it was not guarded.

    With `FACTORY_PAUSED=1` it started TTS and created a build directory: the emergency stop stopped the local
    `render` verb and nothing else. A guard living in individual CLI verbs is a guard someone routes around.
    """

    from factory import cli
    import factory.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "BUILD_ROOT", tmp_path / "build")
    monkeypatch.setenv("FACTORY_PAUSED", "1")
    code = cli.main(["resume", "--channel", "nexus-node", "--plan-id", "nexus-data-wall"])
    assert code != 0
    assert "paused" in capsys.readouterr().err.lower()
    assert not (tmp_path / "build" / "nexus-node").exists()


def test_the_orchestrator_refuses_to_render_while_paused(monkeypatch, tmp_path: Path) -> None:
    """Every producing path goes through `render_episode`, so the guard belongs there, not in the callers."""

    import factory.orchestrator as orchestrator
    from factory.config import load_channel_specs

    monkeypatch.setattr(orchestrator, "BUILD_ROOT", tmp_path / "build")
    spec = load_channel_specs()["nexus-node"]
    monkeypatch.setenv("FACTORY_PAUSED_CHANNELS", "nexus-node")
    with pytest.raises(ProductionPaused):
        orchestrator.render_episode(spec, {"id": "nexus-data-wall", "format": "shorts", "scenes": []})
    assert not (tmp_path / "build").exists()


def test_the_orchestrator_asks_about_the_channel_it_is_about_to_render(monkeypatch) -> None:
    """The guard must name the episode's own channel, not "all", or a narrow pause becomes a wide one."""

    import factory.controls as controls
    import factory.orchestrator as orchestrator
    from factory.config import load_channel_specs

    asked: list[tuple] = []

    def record(channel=None, **kwargs):
        asked.append((channel, kwargs.get("action")))

    def boom(spec, plan_id):
        raise RuntimeError("stop after the guard")

    monkeypatch.setattr(controls, "ensure_allowed", record)
    monkeypatch.setattr(orchestrator, "find_plan", boom)
    spec = load_channel_specs()["nexus-node"]
    with pytest.raises(RuntimeError):
        orchestrator.render_episode(spec, None, plan_id="nexus-data-wall")
    assert asked == [("nexus-node", "render")]


# ------------------------------------------------------------------ a re-run of a finished episode

def test_a_rerun_rewinds_a_finished_journal_instead_of_crashing(monkeypatch, tmp_path: Path) -> None:
    """`pipeline_state` is cached across workflow runs, `build/` is not.

    Cloud run 45073494545 restored a journal that said READY_TO_PUBLISH, had no artefact, and died with
    `READY_TO_PUBLISH -> QUEUED is not a legal transition` before rendering a single frame.
    """

    import factory.orchestrator as orchestrator
    from factory import reliability
    from factory.config import load_channel_specs

    monkeypatch.setattr(orchestrator, "BUILD_ROOT", tmp_path / "build")
    monkeypatch.setattr(reliability, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(orchestrator, "STATE_ROOT", tmp_path / "state", raising=False)
    monkeypatch.delenv("FACTORY_PAUSED", raising=False)
    monkeypatch.delenv("FACTORY_PAUSED_CHANNELS", raising=False)

    spec = load_channel_specs()["nexus-node"]
    plan = {"id": "nexus-data-wall", "format": "shorts",
            "scenes": [{"n": 1, "text": "One sentence here."}]}
    job_id = reliability.job_id_for(spec.slug, "nexus-data-wall")
    journal = reliability.JobJournal(job_id)
    for state in ("QUEUED", "PREFLIGHT", "GENERATING", "RENDERING", "VALIDATING",
                  "PACKAGING", "READY_TO_PUBLISH"):
        journal.transition(state)

    seen: list[str] = []
    monkeypatch.setattr(orchestrator, "find_plan", lambda spec, plan_id: plan)
    monkeypatch.setattr(orchestrator, "_render_tracked",
                        lambda *a, **k: seen.append("rendered") or {"ok": True})
    monkeypatch.setattr(orchestrator, "JobLock", _NoLock)

    assert orchestrator.render_episode(spec, plan) == {"ok": True}
    assert seen == ["rendered"]
    states = [record["state"] for record in journal.records()]
    assert states[-1] == "QUEUED" and "RECOVERABLE" in states[-2:]


def test_a_contended_job_lock_does_not_mutate_the_owner_journal_or_render(
    monkeypatch, tmp_path: Path,
) -> None:
    import factory.orchestrator as orchestrator
    from factory import reliability
    from factory.config import load_channel_specs

    monkeypatch.setattr(reliability, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(orchestrator, "LOCK_ROOT", tmp_path / "locks")
    monkeypatch.delenv("FACTORY_PAUSED", raising=False)
    monkeypatch.delenv("FACTORY_PAUSED_CHANNELS", raising=False)

    spec = load_channel_specs()["nexus-node"]
    plan = {"id": "nexus-data-wall", "format": "shorts",
            "scenes": [{"n": 1, "text": "One sentence here."}]}
    job_id = reliability.job_id_for(spec.slug, "nexus-data-wall")
    journal = reliability.JobJournal(job_id)
    for state in ("QUEUED", "PREFLIGHT", "GENERATING", "RENDERING"):
        journal.transition(state)
    before = journal.records()

    class BusyLock:
        def __init__(self, *args, **kwargs):
            pass

        def acquire(self):
            return False

    rendered: list[bool] = []
    monkeypatch.setattr(orchestrator, "find_plan", lambda spec, plan_id: plan)
    monkeypatch.setattr(orchestrator, "JobLock", BusyLock)
    monkeypatch.setattr(orchestrator, "_render_tracked",
                        lambda *a, **k: rendered.append(True))

    with pytest.raises(reliability.LockBusy):
        orchestrator.render_episode(spec, plan)

    assert journal.records() == before
    assert rendered == []


def test_a_contended_new_job_does_not_create_a_journal_directory_or_render(
    monkeypatch, tmp_path: Path,
) -> None:
    import factory.orchestrator as orchestrator
    from factory import reliability
    from factory.config import load_channel_specs

    state_root = tmp_path / "state"
    monkeypatch.setattr(reliability, "STATE_ROOT", state_root)
    monkeypatch.setattr(orchestrator, "LOCK_ROOT", tmp_path / "locks")
    monkeypatch.delenv("FACTORY_PAUSED", raising=False)
    monkeypatch.delenv("FACTORY_PAUSED_CHANNELS", raising=False)

    spec = load_channel_specs()["nexus-node"]
    plan = {"id": "nexus-data-wall", "format": "shorts",
            "scenes": [{"n": 1, "text": "One sentence here."}]}
    job_id = reliability.job_id_for(spec.slug, "nexus-data-wall")

    class BusyLock:
        def __init__(self, *args, **kwargs):
            pass

        def acquire(self):
            return False

    rendered: list[bool] = []
    monkeypatch.setattr(orchestrator, "find_plan", lambda spec, plan_id: plan)
    monkeypatch.setattr(orchestrator, "JobLock", BusyLock)
    monkeypatch.setattr(orchestrator, "_render_tracked",
                        lambda *a, **k: rendered.append(True))

    with pytest.raises(reliability.LockBusy):
        orchestrator.render_episode(spec, plan)

    assert not (state_root / "jobs" / job_id).exists()
    assert rendered == []


def test_render_episode_renews_lock_during_tracked_render(monkeypatch, tmp_path: Path) -> None:
    import time

    import factory.orchestrator as orchestrator
    from factory import reliability
    from factory.config import load_channel_specs

    monkeypatch.setattr(reliability, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(orchestrator, "LOCK_ROOT", tmp_path / "locks")
    monkeypatch.delenv("FACTORY_PAUSED", raising=False)
    monkeypatch.delenv("FACTORY_PAUSED_CHANNELS", raising=False)
    spec = load_channel_specs()["nexus-node"]
    plan = {"id": "nexus-data-wall", "format": "shorts",
            "scenes": [{"n": 1, "text": "One sentence here."}]}

    def short_lock(path, *, job_id, ttl):
        return reliability.JobLock(
            path, job_id=job_id, ttl=0.04, heartbeat_interval=0.01,
        )

    observed = {}

    def tracked(*args, **kwargs):
        lock = args[4]
        first = lock.read().heartbeat
        time.sleep(0.12)
        lock.assert_healthy()
        observed["first"] = first
        observed["last"] = lock.read().heartbeat
        return {"ok": True}

    monkeypatch.setattr(orchestrator, "JobLock", short_lock)
    monkeypatch.setattr(orchestrator, "_render_tracked", tracked)

    assert orchestrator.render_episode(spec, plan) == {"ok": True}
    assert observed["last"] > observed["first"]


def test_a_published_episode_is_not_reproduced_without_force(monkeypatch, tmp_path: Path) -> None:
    import factory.orchestrator as orchestrator
    from factory import reliability
    from factory.config import load_channel_specs

    monkeypatch.setattr(orchestrator, "BUILD_ROOT", tmp_path / "build")
    monkeypatch.setattr(reliability, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(orchestrator, "STATE_ROOT", tmp_path / "state", raising=False)
    spec = load_channel_specs()["nexus-node"]
    plan = {"id": "nexus-data-wall", "format": "shorts", "scenes": [{"n": 1, "text": "x"}]}
    journal = reliability.JobJournal(reliability.job_id_for(spec.slug, "nexus-data-wall"))
    for state in ("QUEUED", "PREFLIGHT", "GENERATING", "RENDERING", "VALIDATING",
                  "PACKAGING", "READY_TO_PUBLISH", "PUBLISHING", "PUBLISHED"):
        journal.transition(state)
    monkeypatch.setattr(orchestrator, "find_plan", lambda spec, plan_id: plan)
    monkeypatch.setattr(orchestrator, "_render_tracked", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(orchestrator, "JobLock", _NoLock)

    with pytest.raises(ValueError) as caught:
        orchestrator.render_episode(spec, plan)
    assert "--force" in str(caught.value)


class _NoLock:
    def __init__(self, *args, **kwargs):
        pass

    def acquire(self):
        return True

    def read(self):
        return None

    def assert_healthy(self):
        return None

    def release(self):
        return None
