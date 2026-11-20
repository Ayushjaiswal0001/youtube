from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import make_channel, make_video
from uploader.errors import SafetyError, ValidationError
from uploader.metadata import UploadRequest, load_metadata_file


class MetadataTests(unittest.TestCase):
    def test_defaults_merge_channel_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            request = UploadRequest.from_data(
                make_channel(),
                video,
                {
                    "title": "Test title",
                    "description": "Description",
                    "tags": ["extra"],
                },
            )
            request.validate()
            self.assertEqual(request.tags, ("shorts", "extra"))
            self.assertEqual(request.privacy_status, "private")
            self.assertFalse(request.made_for_kids)
            self.assertFalse(request.notify_subscribers)

    def test_public_upload_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            request = UploadRequest.from_data(
                make_channel(),
                video,
                {"title": "Test", "privacyStatus": "public"},
            )
            with self.assertRaises(SafetyError):
                request.validate()

    def test_public_upload_can_be_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            request = UploadRequest.from_data(
                make_channel(),
                video,
                {"title": "Test", "privacyStatus": "public"},
            )
            request.validate(allow_public=True)
            self.assertEqual(request.privacy_status, "public")

    def test_natkhat_defaults_made_for_kids_true_and_rejects_false(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            channel = make_channel(
                slug="natkhat-toons",
                display_name="Natkhat Toons",
                handle="@NatkhatToons-n5",
                expected_channel_id="UC4OCY0qDwQqFnSCZw12sKxA",
                made_for_kids=True,
                requires_made_for_kids_confirmation=True,
                force_made_for_kids=True,
            )
            request = UploadRequest.from_data(channel, video, {"title": "Kids"})
            request.validate()
            self.assertTrue(request.made_for_kids)
            request = UploadRequest.from_data(
                channel, video, {"title": "Kids", "madeForKids": False}
            )
            with self.assertRaises(ValidationError):
                request.validate()

    def test_rejects_non_mp4_and_empty_video(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.webm"
            video.write_bytes(b"data")
            request = UploadRequest.from_data(make_channel(), video, {"title": "Test"})
            with self.assertRaises(ValidationError):
                request.validate()
            empty = root / "empty.mp4"
            empty.write_bytes(b"")
            request = UploadRequest.from_data(make_channel(), empty, {"title": "Test"})
            with self.assertRaises(ValidationError):
                request.validate()

    def test_rejects_string_boolean_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            with self.assertRaises(ValidationError):
                UploadRequest.from_data(
                    make_channel(),
                    video,
                    {"title": "Test", "notifySubscribers": "false"},
                )

    def test_api_body_contains_required_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary))
            request = UploadRequest.from_data(
                make_channel(),
                video,
                {"title": "Test", "madeForKids": True, "tags": ["a", "b"]},
            )
            body = request.to_api_body()
            self.assertEqual(body["snippet"]["title"], "Test")
            self.assertEqual(body["snippet"]["tags"], ["shorts", "a", "b"])
            self.assertTrue(body["status"]["selfDeclaredMadeForKids"])
            self.assertEqual(body["status"]["privacyStatus"], "private")

    def test_hashes_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = make_video(Path(temporary), content=b"same-bytes")
            first = UploadRequest.from_data(make_channel(), video, {"title": "A"})
            second = UploadRequest.from_data(make_channel(), video, {"title": "A"})
            self.assertEqual(first.video_sha256(), second.video_sha256())
            self.assertEqual(first.metadata_sha256(), second.metadata_sha256())
            third = UploadRequest.from_data(make_channel(), video, {"title": "B"})
            self.assertNotEqual(first.metadata_sha256(), third.metadata_sha256())

    def test_load_metadata_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "metadata.json"
            path.write_text(json.dumps({"title": "Test"}), encoding="utf-8")
            self.assertEqual(load_metadata_file(path), {"title": "Test"})
