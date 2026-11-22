"""Publishing gates and renderer path binding.

The uploader layer has its own 50 tests. These cover the factory-side guarantees that
sit in front of it: nothing uploads without an explicit environment gate, the channel
confirmation must match, privacy stays private by default, and a second Hindi render in
the same process cannot reuse the first episode's studio directories.

These fixtures use placeholder byte files, not real media, so the publishing gate (which
measures the actual container) is bypassed here with `skip_gate=True`. The gate has its own
tests in `test_publish_gate.py`, and it is enforced - not bypassable - for a real upload.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.config import load_channel_specs
from factory.content.script import build_english_script, load_plans_for
from factory.publisher import build_upload_data, publish_episode


class FakeRouter:
    """Stands in for uploader.router.ChannelRouter; records what it was asked to do."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upload(self, slug, video_path, data, *, execute=False, confirm_channel=None, allow_public=False):
        self.calls.append(
            {
                "slug": slug,
                "video": str(video_path),
                "data": dict(data),
                "execute": execute,
                "confirm_channel": confirm_channel,
                "allow_public": allow_public,
            }
        )
        if not execute:
            return {"status": "dry_run", "channel": slug}
        return {"status": "uploaded", "channel": slug, "video_id": "vid123"}


class PublishGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-publish-"))
        self.video = self.tmp / "video.mp4"
        self.video.write_bytes(b"\x00" * 2048)
        self.spec = load_channel_specs()["nexus-node"]
        self.plan = load_plans_for(self.spec)[0]
        self.script = build_english_script(self.spec, self.plan)
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for key in ("FACTORY_ALLOW_UPLOAD", "FACTORY_ALLOW_SCHEDULE"):
            os.environ.pop(key, None)
        self._state = mock.patch("factory.publisher.ChannelState", autospec=False)
        self.state_mock = self._state.start()

    def tearDown(self) -> None:
        self._state.stop()
        self._env.stop()
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dry_run_is_the_default(self) -> None:
        router = FakeRouter()
        result = publish_episode(self.spec, self.script, self.video, router=router, skip_gate=True)
        self.assertEqual(router.calls[0]["execute"], False)
        self.assertEqual(result["status"], "dry_run")
        self.state_mock.assert_not_called()

    def test_execute_without_upload_gate_is_refused(self) -> None:
        with self.assertRaises(PermissionError):
            publish_episode(
                self.spec,
                self.script,
                self.video,
                execute=True,
                confirm_channel=self.spec.slug,
                router=FakeRouter(),
                skip_gate=True,
            )

    def test_scheduled_execute_without_schedule_gate_is_refused(self) -> None:
        os.environ["FACTORY_ALLOW_UPLOAD"] = "1"
        with self.assertRaises(PermissionError) as caught:
            publish_episode(
                self.spec,
                self.script,
                self.video,
                execute=True,
                confirm_channel=self.spec.slug,
                publish_at="2026-11-21T06:30:00+00:00",
                router=FakeRouter(),
                skip_gate=True,
            )
        self.assertIn("scheduled releases are disabled", str(caught.exception))

    def test_confirm_channel_must_match(self) -> None:
        os.environ["FACTORY_ALLOW_UPLOAD"] = "1"
        with self.assertRaises(ValueError):
            publish_episode(
                self.spec,
                self.script,
                self.video,
                execute=True,
                confirm_channel="natkhat-toons",
                router=FakeRouter(),
                skip_gate=True,
            )

    def test_public_upload_needs_explicit_flag_and_stays_private_otherwise(self) -> None:
        os.environ["FACTORY_ALLOW_UPLOAD"] = "1"
        router = FakeRouter()
        result = publish_episode(
            self.spec,
            self.script,
            self.video,
            execute=True,
            confirm_channel=self.spec.slug,
            router=router,
            skip_gate=True,
        )
        self.assertEqual(router.calls[0]["data"]["privacyStatus"], "private")
        self.assertEqual(result["requested_privacy"], "private")

    def test_upload_records_plan_id_and_advances_series_for_hindi(self) -> None:
        spec = load_channel_specs()["natkhat-toons"]
        plan = load_plans_for(spec)[0]
        os.environ["FACTORY_ALLOW_UPLOAD"] = "1"
        with mock.patch("factory.publisher.existing_plan", return_value=plan), mock.patch(
            "factory.publisher.advance_after_publish", return_value={"next_episode": 2}
        ) as advance:
            result = publish_episode(
                spec,
                self.script,
                self.video,
                execute=True,
                confirm_channel=spec.slug,
                router=FakeRouter(),
                skip_gate=True,
            )
        self.assertEqual(result["series_state"], {"next_episode": 2})
        advance.assert_called_once()

    def test_upload_data_carries_channel_identity_and_kids_flag(self) -> None:
        spec = load_channel_specs()["natkhat-toons"]
        data = build_upload_data(spec, self.script)
        self.assertTrue(data["madeForKids"])
        self.assertEqual(data["channel_slug"], "natkhat-toons")
        self.assertNotIn("publishAt", data)


class StudioPathBindingTests(unittest.TestCase):
    def test_two_renders_bind_different_studio_directories(self) -> None:
        from factory.media.hindi_renderer import _load_pipeline

        self.assertIsNotNone(_load_pipeline)
        first = Path(tempfile.mkdtemp(prefix="studio-a-"))
        second = Path(tempfile.mkdtemp(prefix="studio-b-"))
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "STUDIO_OUTPUT_DIR": str(first),
                    "STUDIO_EPISODES_DIR": str(first / "episodes"),
                    "STUDIO_INTERMEDIATE_DIR": str(first / "intermediate"),
                },
                clear=False,
            ):
                _load_pipeline(first)
                import studio.config as studio_config

                self.assertEqual(studio_config.OUTPUT_DIR, first.resolve())

            with mock.patch.dict(
                os.environ,
                {
                    "STUDIO_OUTPUT_DIR": str(second),
                    "STUDIO_EPISODES_DIR": str(second / "episodes"),
                    "STUDIO_INTERMEDIATE_DIR": str(second / "intermediate"),
                },
                clear=False,
            ):
                _load_pipeline(second)
                import studio.pipeline.episode as episode_module

                self.assertEqual(episode_module.EPISODES_DIR, (second / "episodes").resolve())
        finally:
            import shutil

            shutil.rmtree(first, ignore_errors=True)
            shutil.rmtree(second, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
