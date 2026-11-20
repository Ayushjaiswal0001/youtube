from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.support import (
    FakeApi,
    FakeCredentials,
    FakeOAuthHttp,
    make_channel,
    make_video,
)
from uploader.errors import (
    ApiError,
    DuplicateUploadError,
    IdentityError,
    SafetyError,
    ScopeError,
    UploadStateUnknown,
    ValidationError,
)
from uploader.ledger import Ledger
from uploader.metadata import UploadRequest
from uploader.oauth import UPLOAD_SCOPE
from uploader.router import ChannelRouter


class RouterTests(unittest.TestCase):
    def _router(
        self,
        root: Path,
        *,
        api: FakeApi | None = None,
        scopes: tuple[str, ...] | None = None,
        channel=None,
    ) -> tuple[ChannelRouter, FakeApi, FakeOAuthHttp]:
        channel = channel or make_channel()
        fake_api = api or FakeApi()
        http = FakeOAuthHttp(scopes=scopes) if scopes else FakeOAuthHttp()
        router = ChannelRouter(
            {channel.slug: channel},
            FakeCredentials(),
            root / "state",
            http=http,
            api_factory=lambda token: fake_api,
        )
        return router, fake_api, http

    def test_dry_run_verifies_and_does_not_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            router, api, _ = self._router(root)
            result = router.dry_run(
                "nexus-node",
                video,
                {"title": "Test"},
                validate_media=False,
            )
            self.assertEqual(result["status"], "dry_run_ok")
            self.assertFalse(result["upload_performed"])
            self.assertEqual(result["identity"]["token_channel_id"], "UCx9O8VivWkiEylDjs5_Zzag")
            self.assertEqual(api.inserts, [])

    def test_wrong_channel_aborts_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            api = FakeApi(channel_id="UCwrongwrongwrongwrongwrong")
            router, _, _ = self._router(root, api=api)
            with self.assertRaises(IdentityError):
                router.dry_run(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    validate_media=False,
                )
            self.assertEqual(api.inserts, [])

    def test_public_upload_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            router, api, _ = self._router(root)
            with self.assertRaises(SafetyError):
                router.dry_run(
                    "nexus-node",
                    video,
                    {"title": "Test", "privacyStatus": "public"},
                    validate_media=False,
                )
            self.assertEqual(api.inserts, [])

    def test_natkhat_requires_made_for_kids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            channel = make_channel(
                slug="natkhat-toons",
                display_name="Natkhat Toons",
                handle="@NatkhatToons-n5",
                expected_channel_id="UC4OCY0qDwQqFnSCZw12sKxA",
                made_for_kids=None,
                requires_made_for_kids_confirmation=True,
            )
            router, api, _ = self._router(root, channel=channel)
            with self.assertRaises(ValidationError):
                router.dry_run(
                    "natkhat-toons",
                    video,
                    {"title": "Kids"},
                    validate_media=False,
                )
            self.assertEqual(api.inserts, [])

    def test_duplicate_hash_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            channel = make_channel()
            request = UploadRequest.from_data(channel, video, {"title": "Test"})
            ledger = Ledger(root / "state", "nexus-node")
            ledger.start(
                job_id="job-1",
                video_sha256=request.video_sha256(),
                metadata_sha256=request.metadata_sha256(),
                title=request.title,
                privacy_status=request.privacy_status,
                video_path=str(video),
                attempts=1,
            )
            ledger.mark_uploaded(
                "job-1",
                video_id="video-1",
                video_url="https://www.youtube.com/watch?v=video-1",
                attempts=1,
            )
            router, api, _ = self._router(root)
            with self.assertRaises(DuplicateUploadError):
                router.dry_run(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    validate_media=False,
                )
            self.assertEqual(api.inserts, [])

    def test_missing_readonly_scope_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            router, _, _ = self._router(root, scopes=(UPLOAD_SCOPE,))
            with self.assertRaises(ScopeError):
                router.dry_run(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    validate_media=False,
                )

    def test_execute_requires_exact_confirm_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            router, api, _ = self._router(root)
            with self.assertRaises(SafetyError):
                router.upload(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    execute=True,
                    confirm_channel=None,
                    validate_media=False,
                )
            self.assertEqual(api.inserts, [])

    def test_simulated_execute_upload_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            router, api, _ = self._router(root)
            result = router.upload(
                "nexus-node",
                video,
                {"title": "Test"},
                execute=True,
                confirm_channel="nexus-node",
                validate_media=False,
            )
            self.assertEqual(result["status"], "uploaded")
            self.assertTrue(result["upload_performed"])
            self.assertEqual(result["video_id"], "vid-123")
            self.assertEqual(len(api.inserts), 1)
            self.assertEqual(api.inserts[0]["notify_subscribers"], False)
            history = Ledger(root / "state", "nexus-node").history()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].video_id, "vid-123")

    def test_retryable_api_error_marks_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            api = FakeApi(
                upload_error=ApiError(None, "network_error", "timeout", retryable=True)
            )
            router, _, _ = self._router(root, api=api)
            with self.assertRaises(UploadStateUnknown):
                router.upload(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    execute=True,
                    confirm_channel="nexus-node",
                    validate_media=False,
                )
            entries = Ledger(root / "state", "nexus-node").entries()
            self.assertEqual(entries[-1].status, "unknown")

    def test_nonretryable_api_error_marks_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            api = FakeApi(
                upload_error=ApiError(403, "forbidden", "denied", retryable=False)
            )
            router, _, _ = self._router(root, api=api)
            with self.assertRaises(ApiError):
                router.upload(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    execute=True,
                    confirm_channel="nexus-node",
                    validate_media=False,
                )
            entries = Ledger(root / "state", "nexus-node").entries()
            self.assertEqual(entries[-1].status, "failed")

    def test_upload_response_wrong_channel_marks_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = make_video(root)
            api = FakeApi(
                upload_response={
                    "id": "video-id",
                    "snippet": {"channelId": "UCwrongwrongwrongwrongwrong"},
                }
            )
            router, _, _ = self._router(root, api=api)
            with self.assertRaises(Exception):
                router.upload(
                    "nexus-node",
                    video,
                    {"title": "Test"},
                    execute=True,
                    confirm_channel="nexus-node",
                    validate_media=False,
                )
            entries = Ledger(root / "state", "nexus-node").entries()
            self.assertEqual(entries[-1].status, "unknown")
