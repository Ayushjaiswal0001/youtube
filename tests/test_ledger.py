from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from uploader.errors import DuplicateUploadError
from uploader.ledger import Ledger


class LedgerTests(unittest.TestCase):
    def test_upload_lifecycle_and_duplicate_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Ledger(Path(temporary), "nexus-node")
            ledger.start(
                job_id="job-1",
                video_sha256="video-hash",
                metadata_sha256="metadata-hash",
                title="Title",
                privacy_status="private",
                video_path="video.mp4",
                attempts=1,
            )
            with self.assertRaises(DuplicateUploadError):
                ledger.assert_no_duplicate("video-hash")
            uploaded = ledger.mark_uploaded(
                "job-1",
                video_id="video-1",
                video_url="https://www.youtube.com/watch?v=video-1",
                attempts=1,
            )
            self.assertEqual(uploaded.status, "uploaded")
            self.assertEqual(len(ledger.history()), 1)
            self.assertEqual(ledger.summary().get("uploaded"), 1)
            with self.assertRaises(DuplicateUploadError):
                ledger.assert_no_duplicate("video-hash")

    def test_failed_upload_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Ledger(Path(temporary), "nexus-node")
            ledger.start(
                job_id="job-1",
                video_sha256="video-hash",
                metadata_sha256="metadata-hash",
                title="Title",
                privacy_status="private",
                video_path="video.mp4",
                attempts=1,
            )
            ledger.mark_failed(
                "job-1",
                error_code="http_403_forbidden",
                error_message="forbidden",
                attempts=1,
            )
            prior = ledger.assert_no_duplicate("video-hash")
            self.assertIsNotNone(prior)
            self.assertEqual(prior.status, "failed")
            ledger.start(
                job_id="job-2",
                video_sha256="video-hash",
                metadata_sha256="metadata-hash",
                title="Title",
                privacy_status="private",
                video_path="video.mp4",
                attempts=2,
            )
            with self.assertRaises(DuplicateUploadError):
                ledger.assert_no_duplicate("video-hash")

    def test_unknown_is_not_retried_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Ledger(Path(temporary), "nexus-node")
            ledger.start(
                job_id="job-1",
                video_sha256="video-hash",
                metadata_sha256="metadata-hash",
                title="Title",
                privacy_status="private",
                video_path="video.mp4",
                attempts=1,
            )
            ledger.mark_unknown(
                "job-1",
                error_code="network_error",
                error_message="timeout",
                attempts=1,
            )
            with self.assertRaises(DuplicateUploadError):
                ledger.assert_no_duplicate("video-hash")
