"""Per-channel publishing policy and the release-time resolver.

Two failures motivated these tests.

**Nothing published, and nothing said so.** Three daily workflows were disabled and, even if enabled, a
`schedule` event cannot supply `workflow_dispatch` inputs, so `upload` was always false. The upload step also
called `publish` without `--schedule`, so an upload carried no `publishAt` and the video stayed private for
ever. Publishing is now a per-channel decision that a scheduled run can reach, and the tests below pin each
of the three separate authorizations.

**A late cron published a day late.** `_next_ist_date` rolled to tomorrow as soon as the release time had
passed, so a cron at 20:00 IST that reached the upload step at 20:00:04 scheduled the episode 24 hours late.
The resolver instead schedules today, a few minutes out, within a grace window, and refuses beyond it rather
than publishing quietly.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from factory.config import ChannelSpec, load_channel_specs
from factory.publishing import (
    PublishingPolicy,
    intended_release,
    parse_publishing_policy,
    resolve_release,
)

IST = timezone(timedelta(hours=5, minutes=30))
WORKFLOWS = Path(".github/workflows")


def spec(**kwargs) -> ChannelSpec:
    """A channel spec with only the fields publishing cares about."""

    base = dict(
        slug="nexus-node",
        display_name="Nexus Node",
        handle="@nexusnode012",
        channel_id="UCx9O8VivWkiEylDjs5_Zzag",
        language="en",
        format="shorts",
        style="deep-dive",
        voice="en-US-AndrewNeural",
        rate="+10%",
        pitch="+0Hz",
        palette="nexus",
        niche="technology",
        publish_time_ist="20:00",
        publishing=PublishingPolicy(mode="scheduled", scheduled_upload=True),
    )
    base.update(kwargs)
    return ChannelSpec(**base)


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


# --------------------------------------------------------------------------------------- policy parsing


def test_a_channel_with_no_publishing_block_stays_manual():
    policy = parse_publishing_policy(None, slug="nexus-node", release_time_ist="20:00")
    assert policy.mode == "manual"
    assert policy.may_schedule is False


def test_the_shipped_channels_have_opted_into_scheduled_publishing():
    specs = load_channel_specs()
    assert set(specs) == {"nexus-node", "academic-biohacker", "natkhat-toons"}
    for slug, channel in specs.items():
        assert channel.publishing.mode == "scheduled", slug
        assert channel.publishing.may_schedule is True, slug
        assert channel.publish_time_ist, f"{slug} needs a release time to schedule one"


def test_an_unknown_mode_fails_closed():
    policy = parse_publishing_policy({"mode": "automatic"}, slug="x", release_time_ist="20:00")
    assert policy.mode == "manual"
    assert policy.scheduled_upload is False
    assert any("unknown publishing mode" in warning for warning in policy.warnings)


def test_an_unknown_late_run_policy_fails_closed():
    policy = parse_publishing_policy(
        {"mode": "scheduled", "late_run_policy": "publish-anyway"},
        slug="x",
        release_time_ist="20:00",
    )
    assert policy.late_run_policy == "skip"
    assert any("unknown late_run_policy" in warning for warning in policy.warnings)


def test_scheduled_upload_without_scheduled_mode_is_coerced_off():
    policy = parse_publishing_policy(
        {"mode": "manual", "scheduled_upload": True}, slug="x", release_time_ist="20:00")
    assert policy.mode == "manual"
    assert policy.scheduled_upload is False
    assert policy.may_schedule is False


def test_scheduled_mode_without_a_release_time_falls_back_to_manual():
    policy = parse_publishing_policy({"mode": "scheduled"}, slug="x", release_time_ist="")
    assert policy.mode == "manual"
    assert policy.may_schedule is False
    assert any("needs publish_time_ist" in warning for warning in policy.warnings)


def test_a_non_object_block_fails_closed():
    policy = parse_publishing_policy("scheduled", slug="x", release_time_ist="20:00")
    assert policy.mode == "manual"


def test_numbers_are_clamped_and_junk_is_ignored():
    policy = parse_publishing_policy(
        {
            "mode": "scheduled",
            "late_grace_minutes": 100_000,
            "minimum_lead_minutes": "soon",
        },
        slug="x",
        release_time_ist="20:00",
    )
    assert policy.late_grace_minutes == 24 * 60
    assert policy.minimum_lead_minutes == 15
    assert any("non-numeric" in warning for warning in policy.warnings)


def test_the_policy_is_reportable():
    payload = parse_publishing_policy(
        {"mode": "scheduled"}, slug="x", release_time_ist="20:00").as_dict()
    assert payload["may_schedule"] is True
    assert json.dumps(payload)  # serialisable for the workflow and the reports


# ------------------------------------------------------------------------------------ release resolution


def test_an_on_time_run_schedules_the_channels_release_instant():
    release = resolve_release(
        spec(), now=at("2026-11-25T13:55:00Z"), run_started=at("2026-11-25T13:50:00Z"))
    assert release.reason == "on_time"
    assert release.iso() == "2026-11-25T14:30:00Z"  # 20:00 IST


def test_a_late_run_does_not_jump_forward_a_day():
    """The defect: a cron at 20:00 IST that uploads at 20:04 used to schedule tomorrow's 20:00."""

    release = resolve_release(
        spec(), now=at("2026-11-25T14:34:00Z"), run_started=at("2026-11-25T14:30:00Z"))
    assert release.scheduled is True
    assert release.iso() == "2026-11-25T14:49:00Z"  # now + the 15 minute minimum lead, today
    assert release.reason.startswith("late_run_shifted")
    # and provably not the old behaviour
    assert release.publish_at < at("2026-11-26T14:30:00Z")


def test_a_release_only_seconds_away_is_pushed_out_rather_than_raced():
    release = resolve_release(spec(), now=at("2026-11-25T14:27:00Z"))
    assert release.reason == "too_close_to_release"
    assert release.iso() == "2026-11-25T14:42:00Z"


def test_a_run_late_beyond_the_grace_window_refuses_to_schedule():
    release = resolve_release(spec(), now=at("2026-11-25T16:31:00Z"))  # 2h01m late
    assert release.scheduled is False
    assert release.publish_at is None
    assert release.reason.startswith("release_window_missed")


def test_the_skip_policy_refuses_even_inside_the_grace_window():
    channel = spec(publishing=PublishingPolicy(
        mode="scheduled", scheduled_upload=True, late_run_policy="skip"))
    release = resolve_release(channel, now=at("2026-11-25T14:34:00Z"))
    assert release.scheduled is False
    assert release.reason.startswith("release_window_missed")


def test_an_existing_release_is_never_overwritten():
    release = resolve_release(
        spec(),
        now=at("2026-11-25T14:34:00Z"),
        existing_scheduled=at("2026-11-26T14:30:00Z"),
    )
    assert release.scheduled is False
    assert release.reason.startswith("release_already_scheduled")


class FakeState:
    """Stands in for ChannelState: the resolver only reads `history()`."""

    entries: list = []

    def __init__(self, channel, root=None):
        self.channel = channel

    def history(self):
        return list(FakeState.entries)


def test_one_release_per_plan_per_ist_day():
    from factory import publishing

    FakeState.entries = [{
        "status": "uploaded",
        "plan_id": "nexus-data-wall",
        "publish_at": "2026-11-25T14:49:00Z",
    }]
    original = publishing.ChannelState if hasattr(publishing, "ChannelState") else None
    import factory.state as state_module

    saved = state_module.ChannelState
    state_module.ChannelState = FakeState
    try:
        same = publishing.scheduled_plan_at(
            spec(), "nexus-data-wall", at("2026-11-25T15:00:00Z"))
        assert same == at("2026-11-25T14:49:00Z")
        # the other format of the same day is a different plan and must still be free to schedule
        assert publishing.scheduled_plan_at(
            spec(), "long-nexus-power-grid", at("2026-11-25T15:00:00Z")) is None
        # and yesterday's release does not block today
        assert publishing.scheduled_plan_at(
            spec(), "nexus-data-wall", at("2026-11-26T15:00:00Z")) is None
    finally:
        state_module.ChannelState = saved


def test_a_failed_entry_does_not_count_as_a_release():
    from factory import publishing
    import factory.state as state_module

    FakeState.entries = [{
        "status": "failed", "plan_id": "nexus-data-wall", "publish_at": "2026-11-25T14:49:00Z"}]
    saved = state_module.ChannelState
    state_module.ChannelState = FakeState
    try:
        assert publishing.scheduled_plan_at(
            spec(), "nexus-data-wall", at("2026-11-25T15:00:00Z")) is None
    finally:
        state_module.ChannelState = saved


def test_no_moment_in_a_day_produces_a_past_release():
    channel = spec()
    start = at("2026-11-25T00:00:00Z")
    for minute in range(0, 24 * 60, 7):
        now = start + timedelta(minutes=minute)
        release = resolve_release(channel, now=now, run_started=now)
        if release.publish_at is not None:
            assert release.publish_at > now, f"past release at {now.isoformat()}"
            assert release.publish_at - now >= timedelta(minutes=5)


def test_the_intended_instant_follows_the_runs_ist_date_not_utc():
    """00:30 UTC on the 26th is 06:00 IST on the 26th, so the intended release is the 26th's 20:00 IST."""

    intended = intended_release(spec(), at("2026-11-26T00:30:00Z"))
    assert intended.isoformat() == "2026-11-26T14:30:00.000000+00:00".replace(".000000", "")


def test_the_release_is_self_describing_for_the_reports():
    payload = resolve_release(spec(), now=at("2026-11-25T13:55:00Z")).describe()
    assert payload["publish_at"] == "2026-11-25T14:30:00Z"
    assert payload["publish_at_ist"].startswith("2026-11-25T20:00:00")
    assert payload["reason"] == "on_time"


# --------------------------------------------------------------------------------------------- the CLI


def run_cli(*args: str) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "factory.cli", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    return completed.returncode, completed.stdout + completed.stderr


def payload(text: str):
    return json.loads(text[text.index("["):])


def test_the_cli_reports_the_policy_and_the_release_it_would_schedule():
    code, output = run_cli("publishing", "--channel", "nexus-node", "--json")
    assert code == 0
    item = payload(output)[0]
    assert item["policy"]["mode"] == "scheduled"
    assert item["may_upload_on_schedule"] is True
    assert item["release_time_ist"] == "20:00"
    assert item["next_release"]["reason"]


def test_the_cli_reports_a_manual_channel_as_not_ready(monkeypatch):
    """A channel that has not opted in must not be able to reach an automatic upload.

    `ready` is the output the workflow gates on, so this asserts the whole chain: policy -> resolver ->
    what `produce.yml` would read, not just the dataclass default.
    """

    import argparse

    from factory import cli

    manual = spec(publishing=PublishingPolicy(mode="manual", scheduled_upload=False))
    seen: list = []
    monkeypatch.setattr(cli, "_specs", lambda name: [manual])
    monkeypatch.setattr(cli, "_print", lambda payload, as_json: seen.append(payload))

    assert cli.cmd_publishing(argparse.Namespace(channel="nexus-node", json=True)) == 0
    item = seen[0][0]
    assert item["policy"]["mode"] == "manual"
    assert item["may_upload_on_schedule"] is False
    assert item["ready"] is False


def test_publish_refuses_to_schedule_an_explicitly_past_date():
    code, output = run_cli(
        "publish", "--channel", "nexus-node", "--plan-id", "nexus-data-wall",
        "--schedule", "--publish-date", "2020-01-01", "--json")
    assert code == 2
    item = payload(output)[0]
    assert item["status"] == "not_scheduled"
    assert "not in the future" in item["reason"]


def _publish_args(**overrides):
    import argparse

    values = dict(
        channel="nexus-node",
        plan_id="nexus-data-wall",
        execute=True,
        confirm_channel="nexus-node",
        schedule=True,
        publish_date=None,
        allow_public=False,
        skip_gate=False,
        json=True,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def test_publish_hands_the_resolvers_decision_to_the_uploader(monkeypatch):
    """The uploader must receive the resolved instant, not a date re-derived after the upload started."""

    from factory import cli
    from factory.publishing import Release

    seen: dict = {}

    def fake_publish(channel, script, video, **kwargs):
        seen.update(kwargs)
        return {"channel": channel.slug, "status": "uploaded"}

    monkeypatch.setattr(cli, "publish_episode", fake_publish)
    monkeypatch.setattr(
        cli, "resolve_release",
        lambda *a, **k: Release(at("2026-11-25T14:49:00Z"), "late_run_shifted"))
    assert cli.cmd_publish(_publish_args()) == 0
    assert seen["publish_at"] == "2026-11-25T14:49:00Z"


def test_publish_uploads_nothing_when_the_release_window_is_missed(monkeypatch):
    from factory import cli
    from factory.publishing import Release

    calls: list = []
    monkeypatch.setattr(cli, "publish_episode", lambda *a, **k: calls.append(1) or {})
    monkeypatch.setattr(
        cli, "resolve_release",
        lambda *a, **k: Release(None, "release_window_missed (late by 7200s)"))
    assert cli.cmd_publish(_publish_args()) == 2
    assert calls == []


def test_publish_does_not_upload_a_plan_that_already_has_a_release_today(monkeypatch):
    from factory import cli

    calls: list = []
    monkeypatch.setattr(cli, "_specs", lambda name: [spec()])
    monkeypatch.setattr(cli, "_rendered_plan", lambda channel, plan_id: {"id": "nexus-data-wall"})
    monkeypatch.setattr(cli, "_profile_for", lambda channel, plan: channel)
    monkeypatch.setattr(cli, "_script_for", lambda channel, plan: None)
    monkeypatch.setattr(cli, "episode_out_dir", lambda channel, plan: Path("/tmp/none"))
    monkeypatch.setattr(cli, "latest_scheduled_release", lambda channel: None)
    monkeypatch.setattr(cli, "publish_episode", lambda *a, **k: calls.append(1) or {})
    monkeypatch.setattr(
        cli, "scheduled_plan_at",
        lambda channel, plan_id, when: at("2026-11-25T14:49:00Z"))

    assert cli.cmd_publish(_publish_args(execute=False)) == 2
    assert calls == []


def test_a_five_minute_late_run_publishes_today_not_tomorrow(monkeypatch):
    """The regression that matters: the old helper returned tomorrow's date once the time had passed."""

    from factory import cli

    now_ist = datetime.now(timezone.utc).astimezone(IST)
    late_time = (now_ist - timedelta(minutes=5)).strftime("%H:%M")
    channel = spec(publish_time_ist=late_time)
    monkeypatch.setattr(cli, "_specs", lambda name: [channel])
    monkeypatch.setattr(cli, "_rendered_plan", lambda channel, plan_id: {"id": "nexus-data-wall"})
    monkeypatch.setattr(cli, "_profile_for", lambda channel, plan: channel)
    monkeypatch.setattr(cli, "_script_for", lambda channel, plan: None)
    monkeypatch.setattr(cli, "episode_out_dir", lambda channel, plan: Path("/tmp/none"))

    seen: dict = {}
    monkeypatch.setattr(
        cli, "publish_episode",
        lambda c, s, v, **kw: seen.update(kw) or {"channel": c.slug, "status": "uploaded"})
    monkeypatch.setattr(cli, "latest_scheduled_release", lambda channel: None)

    assert cli.cmd_publish(_publish_args(execute=False)) == 0
    scheduled = at(seen["publish_at"].replace("Z", "+00:00"))
    assert scheduled - datetime.now(timezone.utc) <= timedelta(minutes=20)
    assert scheduled - datetime.now(timezone.utc) > timedelta(0)
    assert scheduled.astimezone(IST).date() == datetime.now(timezone.utc).astimezone(IST).date()


# ----------------------------------------------------------------------------------- workflow wiring


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def raw(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_the_reusable_workflow_can_be_asked_for_a_release_time():
    inputs = load("produce.yml")[True]["workflow_call"]["inputs"]
    assert inputs["release"]["default"] == ""
    assert "auto" in inputs["release"]["description"]


def test_a_scheduled_run_asks_for_an_upload_and_a_release_but_the_policy_decides():
    for name in ("nexus-node", "academic-biohacker", "natkhat-toons"):
        text = raw(f"produce-{name}.yml")
        assert "upload: ${{ inputs.upload || github.event_name == 'schedule' }}" in text, name
        assert "release: ${{ github.event_name == 'schedule' && 'auto' || '' }}" in text, name


def test_the_upload_steps_are_gated_on_the_channel_policy():
    text = raw("produce.yml")
    assert "id: policy" in text
    assert "steps.policy.outputs.ready == '1'" in text
    # credentials, identity verification and the upload itself all consult the policy
    assert text.count("steps.policy.outputs.ready == '1'") >= 3
    # and the global default is still "no uploads"
    assert 'UPLOAD_ENABLED: "false"' in text


def test_the_scheduled_flag_is_only_passed_when_the_release_is_auto():
    text = raw("produce.yml")
    assert "FACTORY_ALLOW_SCHEDULE: ${{ inputs.release == 'auto' && '1' || '0' }}" in text
    assert 'if [ "$RELEASE_MODE" = "auto" ]; then' in text
    assert "ARGS+=(--schedule)" in text


def test_the_manual_workflow_can_exercise_the_scheduled_path_on_hosted_hardware():
    inputs = load("production.yml")[True]["workflow_dispatch"]["inputs"]
    assert inputs["release"]["options"] == ["", "auto"]
    for job in ("nexus-node", "academic-biohacker", "natkhat-toons"):
        assert load("production.yml")["jobs"][job]["with"]["release"] == "${{ inputs.release }}"


def test_the_step_output_helper_reads_a_log_prefixed_payload(tmp_path: Path):
    document = [{
        "channel": "nexus-node",
        "policy": {"mode": "scheduled", "scheduled_upload": True},
        "next_release": {"publish_at": "2026-11-25T14:30:00Z", "reason": "on_time"},
        "ready": True,
    }]
    path = tmp_path / "publishing.json"
    path.write_text("INFO some log line\n" + json.dumps(document), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "tools/publishing_outputs.py", str(path)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    lines = dict(line.split("=", 1) for line in completed.stdout.strip().splitlines())
    assert lines["ready"] == "1"
    assert lines["mode"] == "scheduled"
    assert lines["next_release"] == "2026-11-25T14:30:00Z"
    assert lines["release_reason"] == "on_time"
