"""Housekeeping deletes only what is released, valid, idle and old — and says why for the rest.

The failure mode this prevents is the one-line `find build -mtime +14 -delete`: it removes the only copy of
an episode that was rendered but never uploaded, or the artifact that explains a QC failure. Each rule
below is a separate test because each one is a way to lose work.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.housekeeping import apply, classify, scan, summary
from factory.state import ChannelState


@pytest.fixture()
def world(tmp_path, monkeypatch):
    build = tmp_path / "build"
    state = tmp_path / "state"
    (build / "nexus-node").mkdir(parents=True)
    state.mkdir()
    monkeypatch.setenv("FACTORY_STATE_DIR", str(state))
    return build, state


def make_episode(build: Path, plan_id: str, *, channel: str = "nexus-node", qc: bool = True,
                 manifest: bool = True, gate: bool = True, age_days: float = 30.0,
                 video: bool = True) -> Path:
    out = build / channel / plan_id
    out.mkdir(parents=True, exist_ok=True)
    if video:
        (out / "video.mp4").write_bytes(b"x" * 2048)
    if qc:
        (out / "qc.json").write_text(json.dumps({"ok": True, "checks": []}), encoding="utf-8")
    if manifest:
        payload = {"artifacts": [{"name": "video", "complete": True, "bytes": 2048,
                                  "sha256": "0" * 64}]}
        (out / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    if gate:
        (out / "publish_gate.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    stamp = (datetime.now(timezone.utc) - timedelta(days=age_days)).timestamp()
    for item in out.rglob("*"):
        os.utime(item, (stamp, stamp))
    os.utime(out, (stamp, stamp))
    return out


def record_upload(state: Path, channel: str, plan_id: str) -> None:
    ChannelState(channel, root=state).record(topic=f"topic-{plan_id}", title="T",
                                             status="uploaded", plan_id=plan_id)


def test_a_released_valid_old_episode_is_deletable(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-old")
    record_upload(state, "nexus-node", "nexus-old")
    entry = classify(build, "nexus-node", out, keep_days=14, state_root=state)
    assert entry.action == "delete"
    assert "released" in entry.reason


def test_a_recent_released_episode_is_kept(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-new", age_days=1)
    record_upload(state, "nexus-node", "nexus-new")
    entry = classify(build, "nexus-node", out, keep_days=14, state_root=state)
    assert entry.action == "keep"
    assert "keep window" in entry.reason


def test_an_unuploaded_episode_is_never_deleted(world) -> None:
    """A rendered video that was never uploaded is the most expensive thing on disk."""

    build, state = world
    out = make_episode(build, "nexus-unreleased")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "not released" in entry.reason


def test_a_qc_failure_is_kept_as_evidence(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-bad", qc=False)
    (out / "qc.json").write_text(json.dumps({"ok": False, "checks": []}), encoding="utf-8")
    record_upload(state, "nexus-node", "nexus-bad")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "QC failed" in entry.reason


def test_a_blocked_publishing_gate_is_kept(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-blocked", gate=False)
    (out / "publish_gate.json").write_text(json.dumps({"ok": False}), encoding="utf-8")
    record_upload(state, "nexus-node", "nexus-blocked")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "gate blocked" in entry.reason


def test_a_missing_manifest_is_kept(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-nomanifest", manifest=False)
    record_upload(state, "nexus-node", "nexus-nomanifest")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "never verified" in entry.reason


def test_an_incomplete_manifest_is_kept(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-incomplete")
    (out / "manifest.json").write_text(
        json.dumps({"artifacts": [{"name": "video", "complete": False}]}), encoding="utf-8")
    record_upload(state, "nexus-node", "nexus-incomplete")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "incomplete" in entry.reason


def test_a_running_job_protects_its_directory(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-running")
    record_upload(state, "nexus-node", "nexus-running")
    job_dir = state / "jobs" / "nexus-node_nexus-running_20261125"
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(json.dumps({"state": "RENDERING"}), encoding="utf-8")
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "still writing" in entry.reason


def test_a_partial_build_without_a_video_is_kept(world) -> None:
    build, state = world
    out = make_episode(build, "nexus-partial", video=False)
    entry = classify(build, "nexus-node", out, keep_days=1, state_root=state)
    assert entry.action == "keep"
    assert "no video.mp4" in entry.reason


def test_a_dry_run_deletes_nothing(world) -> None:
    build, state = world
    make_episode(build, "nexus-old")
    record_upload(state, "nexus-node", "nexus-old")
    entries = scan([load_channel_specs()["nexus-node"]], build_root=build, state_root=state,
                   keep_days=1)
    assert [entry.action for entry in entries] == ["delete"]
    assert (build / "nexus-node" / "nexus-old" / "video.mp4").is_file()
    report = summary(entries, keep_days=1)
    assert report["deletable"] == 1
    assert report["reclaimable_bytes"] > 0


def test_apply_removes_only_the_deletable_entries(world) -> None:
    build, state = world
    old = make_episode(build, "nexus-old")
    fresh = make_episode(build, "nexus-fresh", age_days=0)
    record_upload(state, "nexus-node", "nexus-old")
    record_upload(state, "nexus-node", "nexus-fresh")
    entries = scan([load_channel_specs()["nexus-node"]], build_root=build, state_root=state,
                   keep_days=14)
    result = apply(entries)
    assert not old.exists()
    assert fresh.exists()
    assert len(result["deleted"]) == 1
    assert result["freed_bytes"] > 0


def test_scan_ignores_other_channels(world) -> None:
    build, state = world
    make_episode(build, "academic-old", channel="academic-biohacker")
    record_upload(state, "academic-biohacker", "academic-old")
    entries = scan([load_channel_specs()["nexus-node"]], build_root=build, state_root=state,
                   keep_days=1)
    assert entries == []
