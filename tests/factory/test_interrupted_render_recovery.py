"""A run killed mid-encode must be resumable, not permanently broken.

Found by actually killing one: `render --plan-id academic-cool-to-sleep` was interrupted 40 seconds in,
while FFmpeg was writing `video.mp4`. The build directory then held a 524 KB truncated video and no
`timeline.json`. `resume` printed

    RuntimeError: missing timeline for .../academic-cool-to-sleep/video.mp4

and would print it forever, because `_render_english` treated "a file called video.mp4 exists" as "this
episode is finished" and returned without rendering. `--force` was the only way out, and it throws away
every completed scene. That is exactly the state a cancelled GitHub Actions job leaves behind, so the
recovery path the mission exists to prove was broken for the most likely interruption there is.

A build is finished when its video *and* the timeline it was rendered against are both there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory.config import load_channel_specs
from factory.orchestrator import _render_english

SPEC = load_channel_specs()["academic-biohacker"]


@pytest.fixture()
def out_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "build" / "academic-biohacker" / "academic-cool-to-sleep"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture()
def render_calls(monkeypatch) -> list[dict]:
    """Replace TTS and the renderer, so the test measures the decision rather than the pixels."""

    import factory.orchestrator as orchestrator

    calls: list[dict] = []
    monkeypatch.setattr(orchestrator, "synthesize_script", lambda *a, **k: object())

    def fake_render(script, narration, spec, path, *, force=False):
        calls.append({"path": Path(path), "force": force})
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"freshly-rendered")
        Path(path).with_name("timeline.json").write_text('{"duration": 38.0}', encoding="utf-8")
        return {"video_path": str(path), "duration": 38.0, "skipped": False}

    monkeypatch.setattr(orchestrator, "render_english", fake_render)
    return calls


class TestInterruptedRenderRecovery:
    def test_a_finished_build_is_skipped(self, out_dir: Path, render_calls: list[dict]) -> None:
        (out_dir / "video.mp4").write_bytes(b"complete")
        (out_dir / "timeline.json").write_text('{"duration": 38.0}', encoding="utf-8")

        result = _render_english(SPEC, object(), out_dir, force=False)

        assert result["skipped"] is True
        assert result["duration"] == 38.0
        assert render_calls == [], "a finished build must not be re-rendered"

    def test_a_truncated_video_is_re_rendered(self, out_dir: Path, render_calls: list[dict]) -> None:
        """The defect: video.mp4 exists, timeline.json does not, so the run was killed mid-encode."""

        (out_dir / "video.mp4").write_bytes(b"\x00" * 524288)

        result = _render_english(SPEC, object(), out_dir, force=False)

        assert result["skipped"] is False, "a truncated video is not a finished build"
        assert len(render_calls) == 1, "the episode must be rendered again"
        assert (out_dir / "video.mp4").read_bytes() == b"freshly-rendered"
        assert (out_dir / "timeline.json").is_file()

    def test_the_fragment_is_removed_before_the_renderer_runs(
        self, out_dir: Path, render_calls: list[dict]
    ) -> None:
        """The renderer refuses to overwrite an existing file, so the fragment must go first."""

        (out_dir / "video.mp4").write_bytes(b"\x00" * 524288)

        _render_english(SPEC, object(), out_dir, force=False)

        # The stub saw a directory whose video had already been removed; that is what lets the real
        # renderer write instead of raising FileExistsError.
        assert not any(call["path"].with_suffix(".fragment").exists() for call in render_calls)
        assert render_calls[0]["force"] is False, "scene reuse must not be thrown away"

    def test_an_empty_directory_renders(self, out_dir: Path, render_calls: list[dict]) -> None:
        result = _render_english(SPEC, object(), out_dir, force=False)
        assert result["skipped"] is False
        assert len(render_calls) == 1

    def test_the_landscape_profile_takes_the_same_path(self, out_dir: Path, monkeypatch) -> None:
        """A 16:9 episode goes through the same guard, with the card renderer instead."""

        from dataclasses import replace

        import factory.orchestrator as orchestrator

        calls: list[Path] = []

        def fake_landscape(script, narration, spec, path, *, force=False):
            calls.append(Path(path))
            Path(path).write_bytes(b"landscape")
            Path(path).with_name("timeline.json").write_text('{"duration": 214.0}', encoding="utf-8")
            return {"video_path": str(path), "duration": 214.0, "skipped": False}

        monkeypatch.setattr(orchestrator, "synthesize_script", lambda *a, **k: object())
        monkeypatch.setattr(orchestrator, "render_landscape", fake_landscape)
        long_spec = replace(SPEC, format="long")
        (out_dir / "video.mp4").write_bytes(b"" * 4096)  # interrupted encode, no timeline

        result = _render_english(long_spec, object(), out_dir, force=False)

        assert result["skipped"] is False
        assert calls, "the card renderer must run for the 16:9 profile"
        assert (out_dir / "video.mp4").read_bytes() == b"landscape"
