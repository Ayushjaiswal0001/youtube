"""The production workflows are load-bearing, so their shape is asserted here.

The long-form bottleneck was not a bug in Python: it was one job with a 60-minute timeout rendering
whichever format the channel asked for, while a measured long-form episode took 50 minutes 8 seconds. That
left ten minutes of headroom on a developer machine and none on a slower hosted runner, and it made the
3-minute Short queue behind the 50-minute render.

These tests pin the shape that fixes it, because a workflow is not covered by the render tests: nothing
else in this repository would fail if someone merged the two jobs back together, raised one timeout and
deleted the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(".github/workflows")
CHANNELS = {
    "nexus-node": ("NEXUS_NODE", "30 14 * * *"),
    "academic-biohacker": ("ACADEMIC_BIOHACKER", "30 6 * * *"),
    "natkhat-toons": ("NATKHAT_TOONS", "30 12 * * *"),
}

#: Measured on a developer machine: `long-nexus-power-grid` rendered 223.1 s of video in 3,008 s.
LONG_RENDER_SECONDS = 3_008
LONG_TIMEOUT_MINIMUM_MINUTES = 120


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def raw(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def trigger(workflow: dict) -> dict:
    """The `on:` block. PyYAML reads the bare key `on` as the boolean True (YAML 1.1)."""

    return workflow.get("on") or workflow.get(True) or {}


class TestChannelWorkflows:
    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_each_channel_has_a_short_job_and_a_long_job(self, channel: str) -> None:
        jobs = load(f"produce-{channel}.yml")["jobs"]
        assert set(jobs) == {"short", "long"}, f"{channel} jobs: {sorted(jobs)}"
        for name, job in jobs.items():
            assert job["uses"] == "./.github/workflows/produce.yml"

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_the_short_job_asks_for_the_short_format(self, channel: str) -> None:
        short = load(f"produce-{channel}.yml")["jobs"]["short"]
        assert short["with"]["format"] == "shorts"
        assert short["with"]["channel"] == channel
        assert short["with"]["secret_prefix"] == CHANNELS[channel][0]

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_the_long_job_asks_for_the_long_format(self, channel: str) -> None:
        long = load(f"produce-{channel}.yml")["jobs"]["long"]
        assert long["with"]["format"] == "long"
        assert long["with"]["channel"] == channel

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_the_long_job_has_headroom_over_the_measured_render(self, channel: str) -> None:
        long = load(f"produce-{channel}.yml")["jobs"]["long"]
        minimum = LONG_RENDER_SECONDS / 60 * 2  # twice the measured render
        assert int(long["with"]["timeout_minutes"]) >= LONG_TIMEOUT_MINIMUM_MINUTES
        assert int(long["with"]["timeout_minutes"]) >= minimum

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_the_two_jobs_are_independent(self, channel: str) -> None:
        jobs = load(f"produce-{channel}.yml")["jobs"]
        # `needs: long` would make the Short wait for the long render, which is the bottleneck this
        # split removes. Neither job may depend on the other.
        for name, job in jobs.items():
            assert "needs" not in job, f"{channel}:{name} depends on another job"

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_each_job_receives_only_its_own_credentials(self, channel: str) -> None:
        prefix = CHANNELS[channel][0]
        jobs = load(f"produce-{channel}.yml")["jobs"]
        for name, job in jobs.items():
            passed = set((job.get("secrets") or {}))
            assert passed == {
                f"YT_{prefix}_CLIENT_ID",
                f"YT_{prefix}_CLIENT_SECRET",
                f"YT_{prefix}_REFRESH_TOKEN",
            }, f"{channel}:{name} received {sorted(passed)}"

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_the_schedule_and_publish_time_are_unchanged(self, channel: str) -> None:
        cron = trigger(load(f"produce-{channel}.yml"))["schedule"][0]["cron"]
        assert cron == CHANNELS[channel][1]

    @pytest.mark.parametrize("channel", sorted(CHANNELS))
    def test_uploads_default_to_off(self, channel: str) -> None:
        workflow = load(f"produce-{channel}.yml")
        assert trigger(workflow)["workflow_dispatch"]["inputs"]["upload"]["default"] is False
        # A manual run uploads only when asked; a scheduled run asks, and `produce.yml` then requires the
        # channel's publishing policy to agree before it exports a credential. The conjunction is longer,
        # not looser: `produce.yml` gates every upload step on that policy output as well.
        for job in workflow["jobs"].values():
            assert str(job["with"]["upload"]) == (
                "${{ inputs.upload || github.event_name == 'schedule' }}")

    def test_no_workflow_inherits_every_secret(self) -> None:
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.strip().startswith("#"):
                    continue
                assert "secrets: inherit" not in line, f"{path.name} passes every secret"


class TestProduceWorkflow:
    def test_the_timeout_is_an_input_with_a_safe_default(self) -> None:
        produce = load("produce.yml")
        spec = trigger(produce)["workflow_call"]["inputs"]["timeout_minutes"]
        assert spec["default"] == 60
        job = produce["jobs"]["produce"]
        assert job["timeout-minutes"] == "${{ inputs.timeout_minutes }}"

    def test_the_concurrency_group_separates_the_two_formats(self) -> None:
        produce = load("produce.yml")
        group = produce["concurrency"]["group"]
        # Same group for both formats would serialise a 3-minute Short behind a 50-minute render.
        assert "inputs.format" in group
        assert produce["concurrency"]["cancel-in-progress"] is False

    def test_the_state_cache_key_includes_the_format(self) -> None:
        text = raw("produce.yml")
        # Two jobs of one run share `github.run_id`; without the format in the key the second save
        # overwrites the first job's pipeline state.
        assert "state-${{ inputs.channel }}-${{ inputs.format || 'native' }}-${{ github.run_id }}" in text

    def test_planning_is_told_which_format_to_select(self) -> None:
        text = raw("produce.yml")
        assert 'EXTRA+=(--format "$FORMAT")' in text

    def test_the_publishing_switches_stay_off_by_default(self) -> None:
        env = load("produce.yml")["env"]
        assert str(env["UPLOAD_ENABLED"]).lower() == "false"
        assert str(env["SCHEDULED_PUBLISHING_ENABLED"]).lower() == "false"
        assert str(env["PUBLICATION_APPROVAL_REQUIRED"]).lower() == "true"

    def test_the_upload_step_is_gated_on_the_gate_and_credentials(self) -> None:
        job = load("produce.yml")["jobs"]["produce"]
        upload = next(step for step in job["steps"] if step.get("name") == "Upload (private, gated)")
        assert upload["if"] == ("${{ inputs.upload && steps.policy.outputs.ready == '1' && "
                               "steps.creds.outputs.ready == '1' && steps.gate.outputs.ok == '1' }}")

    def test_the_manifest_is_rebuilt_after_qc(self) -> None:
        job = load("produce.yml")["jobs"]["produce"]
        names = [step.get("name") for step in job["steps"]]
        assert names.index("Quality assurance") < names.index("Rebuild manifest after QC")
        assert names.index("Rebuild manifest after QC") < names.index("Publishing gate")


class TestManualWorkflow:
    def test_each_channel_is_its_own_job_with_its_own_secrets(self) -> None:
        workflow = load("production.yml")
        assert set(workflow["jobs"]) == set(CHANNELS)
        for channel, (prefix, _cron) in CHANNELS.items():
            job = workflow["jobs"][channel]
            assert job["with"]["channel"] == channel
            assert job["with"]["secret_prefix"] == prefix
            assert set(job["secrets"]) == {
                f"YT_{prefix}_CLIENT_ID", f"YT_{prefix}_CLIENT_SECRET",
                f"YT_{prefix}_REFRESH_TOKEN",
            }

    def test_only_the_requested_channel_job_runs(self) -> None:
        workflow = load("production.yml")
        for channel in CHANNELS:
            assert workflow["jobs"][channel]["if"] == f"${{{{ inputs.channel == '{channel}' }}}}"

    def test_a_long_form_manual_run_gets_the_long_budget(self) -> None:
        workflow = load("production.yml")
        for channel in CHANNELS:
            expression = workflow["jobs"][channel]["with"]["timeout_minutes"]
            assert "120" in expression and "60" in expression
