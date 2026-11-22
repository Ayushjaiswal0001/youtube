"""Orchestration, idempotency and interrupted-render recovery (T46).

These tests drive the real code paths with a stubbed renderer: what is under test is *when* work
happens, not what the frames look like. Two properties matter and both were broken before T46:

* a re-run of an unchanged plan must not re-render anything, and must not produce a second episode;
* a run that died part-way must resume by re-rendering only what is missing, and the reassembled
  video must be byte-identical to an uninterrupted run.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.config import BUILD_ROOT, load_channel_specs
from factory.content.script import load_plans_for
from factory.media import landscape_stage
from factory.media.landscape_stage import (
    plan_scenes,
    scene_is_current,
    scene_signature,
    stage_story_id,
)
from factory.orchestrator import episode_out_dir, plan_identifier, resolve_engine

NATKHAT = load_channel_specs()["natkhat-toons"]


def _long_spec():
    from dataclasses import replace

    return replace(NATKHAT, format="long")


def _stage_plan():
    spec = _long_spec()
    for plan in load_plans_for(spec):
        if plan.get("id") == "natkhat-haveli-stage-e1":
            return plan
    raise AssertionError("the stage plan disappeared from the series fixtures")


class EngineResolutionTests(unittest.TestCase):
    def test_a_plan_with_engine_stage_uses_the_stage(self):
        self.assertEqual(resolve_engine(_long_spec(), _stage_plan()), "stage")

    def test_an_english_long_plan_uses_the_card_renderer(self):
        spec = _long_spec().__class__(**{**_long_spec().__dict__, "slug": "nexus-node"})
        self.assertEqual(resolve_engine(spec, {"id": "x"}), "cards")

    def test_a_shorts_plan_uses_the_character_engine(self):
        from dataclasses import replace

        spec = replace(NATKHAT, format="shorts")
        plan = next(p for p in load_plans_for(spec) if p.get("id") == "natkhat-haveli-e1")
        self.assertEqual(resolve_engine(spec, plan), "shorts")

    def test_an_unknown_engine_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            resolve_engine(_long_spec(), {"id": "x", "engine": "magic"})

    def test_the_engine_is_not_inferred_from_a_scenes_key(self):
        # The existing Shorts plans carry a `scenes` key too; inferring from it routed a 9:16 Short
        # through the landscape stage.
        plan = dict(_stage_plan())
        plan.pop("engine")
        self.assertNotEqual(resolve_engine(_long_spec(), plan), "stage")


class OutputDirectoryTests(unittest.TestCase):
    def test_the_stage_renderer_and_the_orchestrator_name_the_same_directory(self):
        spec, plan = _long_spec(), _stage_plan()
        self.assertEqual(episode_out_dir(spec, plan).name, stage_story_id(spec, plan))
        self.assertEqual(episode_out_dir(spec, plan).parent, BUILD_ROOT / spec.slug)

    def test_the_directory_does_not_contain_a_render_stage_prefix(self):
        # `..._render-stage-<plan>` is what the two modules used to compute differently.
        self.assertNotIn("render-stage", stage_story_id(_long_spec(), _stage_plan()))


class SceneSignatureTests(unittest.TestCase):
    def setUp(self):
        self.scene = plan_scenes(_stage_plan())[0]

    def _signature(self, scene_overrides=None, *, audio="a", stage="s",
                   fade_in=0.0, fade_out=0.0):
        scene = dict(self.scene, **(scene_overrides or {}))
        return scene_signature(scene, fade_in, fade_out, stage_signature=stage,
                               audio_digest=audio)

    def test_the_same_scene_signs_the_same(self):
        self.assertEqual(self._signature(), self._signature())

    def test_dialogue_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature({"dialogue": "कुछ और"}))

    def test_speaker_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature({"speaker": "chiku"}))

    def test_camera_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature({"camera": "close_up_chiku"}))

    def test_a_pose_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature({"chiku_pose": "shocked_freeze"}))

    def test_a_fade_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature(fade_in=0.5))

    def test_a_new_narration_take_changes_the_signature(self):
        # Visemes come from the audio envelope, so a fresh dub with identical text must invalidate.
        self.assertNotEqual(self._signature(), self._signature(audio="b"))

    def test_the_stage_changes_the_signature(self):
        self.assertNotEqual(self._signature(), self._signature(stage="s2"))


class SceneCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / "scene_001.mp4"
        self.video.write_bytes(b"\0" * 20_000)

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, signature="abc"):
        self.video.with_suffix(".json").write_text(
            json.dumps({"signature": signature, "duration": 4.0}), encoding="utf-8")

    def test_a_scene_without_state_is_not_current(self):
        with mock.patch.object(landscape_stage, "_ffprobe_duration", return_value=4.0):
            self.assertFalse(scene_is_current(self.video, "abc"))

    def test_a_matching_signature_and_a_probe_is_current(self):
        self._record()
        with mock.patch.object(landscape_stage, "_ffprobe_duration", return_value=4.0):
            self.assertTrue(scene_is_current(self.video, "abc"))

    def test_a_changed_signature_is_not_current(self):
        self._record("abc")
        with mock.patch.object(landscape_stage, "_ffprobe_duration", return_value=4.0):
            self.assertFalse(scene_is_current(self.video, "def"))

    def test_a_truncated_scene_is_not_current_even_with_matching_state(self):
        self._record()
        self.video.write_bytes(b"\0" * 100)
        with mock.patch.object(landscape_stage, "_ffprobe_duration", return_value=4.0):
            self.assertFalse(scene_is_current(self.video, "abc"))

    def test_a_scene_that_does_not_decode_is_not_current(self):
        # The state file is written after the encode returns, but an MP4 truncated by a kill can
        # still carry its moov box; the probe is the independent gate.
        self._record()
        with mock.patch.object(landscape_stage, "_ffprobe_duration", return_value=0.0):
            self.assertFalse(scene_is_current(self.video, "abc"))


class AtomicConcatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.scenes = []
        for index in (1, 2):
            path = self.dir / f"scene_00{index}.mp4"
            path.write_bytes(b"\0" * 20_000)
            self.scenes.append(path)
        self.target = self.dir / "video.mp4"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_failed_join_leaves_the_previous_artifact_untouched(self):
        self.target.write_bytes(b"verified")
        finished = mock.Mock(returncode=1, stderr="boom", stdout="")
        with mock.patch.object(landscape_stage.subprocess, "run", return_value=finished):
            with self.assertRaises(RuntimeError):
                landscape_stage._concat(self.scenes, self.target)
        self.assertEqual(self.target.read_bytes(), b"verified")
        self.assertEqual(list(self.dir.glob("*.partial.mp4")), [])

    def test_the_join_is_written_beside_the_target_and_renamed(self):
        written = {}

        def fake_run(command, **kwargs):
            written["command"] = command
            Path(command[-1]).write_bytes(b"new")
            return mock.Mock(returncode=0, stderr="", stdout="")

        with mock.patch.object(landscape_stage.subprocess, "run", side_effect=fake_run):
            landscape_stage._concat(self.scenes, self.target)
        self.assertTrue(written["command"][-1].endswith(".partial.mp4"))
        self.assertEqual(self.target.read_bytes(), b"new")
        self.assertEqual(list(self.dir.glob("*.partial.mp4")), [])

    def test_the_partial_file_keeps_the_mp4_extension(self):
        # ".mp4.partial" has no muxer ffmpeg can name, and the join failed with "Invalid argument"
        # after every scene had already rendered.
        seen = []

        def fake_run(command, **kwargs):
            seen.append(command[-1])
            Path(command[-1]).write_bytes(b"x")
            return mock.Mock(returncode=0, stderr="", stdout="")

        with mock.patch.object(landscape_stage.subprocess, "run", side_effect=fake_run):
            landscape_stage._concat(self.scenes, self.target)
        self.assertTrue(seen[0].endswith(".mp4"))


class StageSceneStateTests(unittest.TestCase):
    def test_the_scene_numbers_come_from_the_plan_schema(self):
        from factory.cli import _stage_scene_state

        spec, plan = _long_spec(), _stage_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / stage_story_id(spec, plan)
            scene_dir = out_dir / "studio" / "intermediate" / stage_story_id(spec, plan)
            scene_dir.mkdir(parents=True)
            for scene in plan_scenes(plan):
                (scene_dir / f"scene_{scene['scene_num']:03d}.mp4").write_bytes(b"\0" * 20_000)
            counts = _stage_scene_state(out_dir, spec, plan)
        self.assertEqual(counts["scenes"], len(plan_scenes(plan)))
        self.assertEqual(counts["missing"], 0)

    def test_a_plan_whose_scenes_key_is_not_scene_still_counts(self):
        # The authored key is "n"; reading `scene["scene"]` reported 12 missing scenes for an
        # episode that was entirely on disk.
        self.assertIsNone(plan_scenes(_stage_plan())[0].get("scene"))


class RenderLoopTests(unittest.TestCase):
    """The scene loop with a stub studio: proves reuse, resume and re-render decisions."""

    class FakeTTSEngine:
        def __init__(self):
            self.calls = []

        def generate_dialogue(self, text, speaker="narrator", tag="dialogue"):
            self.calls.append(tag)
            path = Path(tempfile.gettempdir()) / "t46-audio" / f"{tag}.mp3"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(tag.encode("utf-8") * 100)
            return {"audio_path": str(path), "duration": 4.0, "boundaries": [], "speaker": speaker}

    class FakeRenderer:
        def __init__(self):
            self.scenes = []

        def render_scene(self, scene, audio, target, sfx_delay_ms=0):
            self.scenes.append(scene["scene_num"])
            Path(target).write_bytes(b"\0" * 30_000)

    def _run(self, *, plan, force=False, only_scenes=None, renderer=None, tts=None, out_root=None):
        renderer = renderer or self.FakeRenderer()
        tts = tts or self.FakeTTSEngine()
        studio = {
            "TTSEngine": lambda: tts,
            "LANDSCAPE": mock.Mock(ground_y=788.0, eye_y=470.0, slots={}),
            "LandscapeEnvironment": lambda *a, **k: mock.Mock(),
            "ForegroundLayer": lambda *a, **k: mock.Mock(),
            "SceneRenderer": lambda *a, **k: renderer,
            "plan_transitions": lambda scenes: [(0.0, 0.0)] * len(scenes),
            # The stub mirrors load_studio, so a new studio binding has to appear here too.
            "plan_conversation": lambda *a, **k: mock.Mock(
                decisions=[], warnings=[], to_dict=lambda: {"decisions": [], "warnings": []}),
            "apply_shot_plan": lambda scenes, plan: scenes,
        }
        spec = _long_spec()
        with mock.patch.object(landscape_stage, "load_studio", return_value=studio):
            with mock.patch.object(landscape_stage, "title_overlay",
                                   side_effect=lambda *a, **k: Path("/dev/null")), \
                 mock.patch.object(landscape_stage, "caption_overlay",
                                   side_effect=lambda *a, **k: Path("/dev/null")):
                if out_root:
                    with mock.patch.object(landscape_stage, "BUILD_ROOT", out_root):
                        return landscape_stage.render_stage_episode(
                            spec, plan, force=force, only_scenes=only_scenes)
                return landscape_stage.render_stage_episode(
                    spec, plan, force=force, only_scenes=only_scenes)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan = _stage_plan()
        patches = [
            mock.patch.object(landscape_stage, "BUILD_ROOT", self.root),
            mock.patch.object(landscape_stage, "_ffprobe_duration",
                              side_effect=lambda path: 4.0 if Path(path).is_file() else 0.0),
            mock.patch.object(landscape_stage, "_concat",
                              side_effect=lambda scenes, target: (
                                  Path(target).write_bytes(b"\0" * 50_000) or target)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _episode_dir(self):
        return self.root / _long_spec().slug / stage_story_id(_long_spec(), self.plan)

    def test_the_first_run_renders_every_scene(self):
        renderer = self.FakeRenderer()
        result = self._run(plan=self.plan, renderer=renderer)
        self.assertEqual(result["rendered_scenes"], len(plan_scenes(self.plan)))
        self.assertEqual(result["reused_scenes"], 0)
        self.assertFalse(result["skipped_render"])

    def test_a_second_run_renders_nothing(self):
        first = self.FakeRenderer()
        self._run(plan=self.plan, renderer=first)
        second = self.FakeRenderer()
        result = self._run(plan=self.plan, renderer=second)
        self.assertEqual(result["rendered_scenes"], 0)
        self.assertEqual(second.scenes, [])
        self.assertTrue(result["skipped_render"])

    def test_a_changed_line_re_renders_only_that_scene(self):
        self._run(plan=self.plan)
        plan = json.loads(json.dumps(self.plan))
        plan["scenes"][2]["line"] = "एक अलग पंक्ति"
        renderer = self.FakeRenderer()
        result = self._run(plan=plan, renderer=renderer)
        self.assertEqual(result["rendered_scenes"], 1)
        self.assertEqual(renderer.scenes, [plan_scenes(plan)[2]["scene_num"]])

    def test_force_re_renders_everything(self):
        self._run(plan=self.plan)
        renderer = self.FakeRenderer()
        result = self._run(plan=self.plan, force=True, renderer=renderer)
        self.assertEqual(result["rendered_scenes"], len(plan_scenes(self.plan)))

    def test_a_missing_scene_is_the_only_one_re_rendered(self):
        self._run(plan=self.plan)
        target = self._episode_dir() / "studio" / "intermediate" / stage_story_id(
            _long_spec(), self.plan) / "scene_003.mp4"
        target.unlink()
        target.with_suffix(".json").unlink()
        renderer = self.FakeRenderer()
        result = self._run(plan=self.plan, renderer=renderer)
        self.assertEqual(result["rendered_scenes"], 1)
        self.assertEqual(len(renderer.scenes), 1)

    def test_a_scene_whose_state_is_missing_is_re_rendered(self):
        self._run(plan=self.plan)
        target = self._episode_dir() / "studio" / "intermediate" / stage_story_id(
            _long_spec(), self.plan) / "scene_002.mp4"
        target.with_suffix(".json").write_text("{}", encoding="utf-8")
        renderer = self.FakeRenderer()
        result = self._run(plan=self.plan, renderer=renderer)
        self.assertEqual(result["rendered_scenes"], 1)

    def test_the_episode_video_is_not_rebuilt_when_every_scene_is_current(self):
        self._run(plan=self.plan)
        video = self._episode_dir() / "video.mp4"
        before = video.stat().st_mtime_ns
        self._run(plan=self.plan)
        self.assertEqual(video.stat().st_mtime_ns, before)


class ResumeContractTests(unittest.TestCase):
    def test_resume_skips_an_episode_whose_artifact_passed_qc(self):
        from factory.cli import cmd_resume

        spec, plan = _long_spec(), _stage_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / stage_story_id(spec, plan)
            out_dir.mkdir(parents=True)
            (out_dir / "video.mp4").write_bytes(b"\0" * 50_000)
            (out_dir / "qc.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            with mock.patch("factory.cli.load_plans_for", return_value=[plan]), \
                 mock.patch("factory.cli.episode_out_dir", return_value=out_dir), \
                 mock.patch("factory.cli.render_episode") as render:
                code = cmd_resume(mock.Mock(channel=spec.slug, plan_id=None,
                                            format="long", force=False, json=True))
        self.assertEqual(code, 0)
        render.assert_not_called()

    def test_resume_renders_an_episode_without_a_verified_artifact(self):
        from factory.cli import cmd_resume

        spec, plan = _long_spec(), _stage_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / stage_story_id(spec, plan)
            out_dir.mkdir(parents=True)
            with mock.patch("factory.cli.load_plans_for", return_value=[plan]), \
                 mock.patch("factory.cli.episode_out_dir", return_value=out_dir), \
                 mock.patch("factory.cli.render_episode",
                            return_value={"qc_ok": True, "channel": spec.slug,
                                          "plan_id": plan_identifier(plan)}) as render:
                code = cmd_resume(mock.Mock(channel=spec.slug, plan_id=None,
                                            format="long", force=False, json=True))
        self.assertEqual(code, 0)
        render.assert_called_once()


if __name__ == "__main__":
    unittest.main()
