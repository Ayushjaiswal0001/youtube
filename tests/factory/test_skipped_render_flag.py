"""`skipped_render` has to describe what happened, not what the filesystem looks like afterwards.

Found while running the three-channel batch on the merged build: all three episodes rendered from an
empty build directory and all three reported `skipped_render: true`, because the flag was computed after
the render, when `video.mp4` exists by definition. The field an operator reads first said the opposite of
the truth, which is the worst possible failure for a "did anything happen?" field.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.content.plans import load_longform_plans
from factory.orchestrator import episode_out_dir, render_episode


@pytest.fixture()
def scratch(tmp_path, monkeypatch):
    """A build/state tree that belongs to the test, never to the repository."""

    build = tmp_path / "build"
    state = tmp_path / "state"
    build.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FACTORY_BUILD_DIR", str(build))
    monkeypatch.setenv("FACTORY_STATE_DIR", str(state))
    monkeypatch.setenv("FACTORY_ASSET_CACHE", str(tmp_path / "cache"))

    import factory.config as config

    monkeypatch.setattr(config, "BUILD_ROOT", build, raising=False)
    monkeypatch.setattr(config, "STATE_ROOT", state, raising=False)
    import factory.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "BUILD_ROOT", build, raising=False)
    return build


def _plan(slug: str = "nexus-node") -> dict:
    """The next Short plan for a channel, without writing anything into content/."""

    from factory.content.plans import generate_plan

    return generate_plan(load_channel_specs()[slug], write=False)["plan"]


class TestSkippedRenderFlag:
    def test_the_flag_is_read_before_the_render_runs(self) -> None:
        """The defect, stated as a property of the source: the capture must precede the render."""

        source = Path("factory/orchestrator.py").read_text(encoding="utf-8")
        assert '"skipped_render": reused_build' in source
        assert '"skipped_render": bool(timeline' not in source
        assert source.index("reused_build = ") < source.index('job.transition("GENERATING"')
        # It must be derived from the build directory and `force`, not from a post-render fact, and it must
        # ask whether the build is *complete*: a truncated video from an interrupted encode is not a build
        # to skip (see tests/factory/test_interrupted_render_recovery.py).
        assert "reused_build = build_is_complete(expected_out_dir) and not force" in source
        assert 'reused_build = (expected_out_dir / "video.mp4").is_file() and not force' not in source

    def test_a_real_idempotent_rerun_reports_the_second_run_as_skipped(
        self, scratch, monkeypatch
    ) -> None:
        """End to end on the cheapest real episode: render once, then render again without force."""

        specs = load_channel_specs()
        spec = replace(specs["academic-biohacker"], production_enabled=True)
        specs["academic-biohacker"] = spec
        monkeypatch.setattr("factory.controls.load_channel_specs", lambda: specs)
        plan = _plan("academic-biohacker")
        first = render_episode(spec, plan=plan, force=True)
        assert first["qc_ok"], first.get("qc_errors")
        assert first["skipped_render"] is False

        second = render_episode(spec, plan=plan, force=False)
        assert second["skipped_render"] is True, "an idempotent re-run must report that it skipped"
        assert second["sha256"] == first["sha256"], "the re-run must not re-encode the video"
