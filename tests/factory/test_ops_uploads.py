from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from factory.ops import _upload_snapshot
from uploader.ledger import Ledger


class OpsUploadSnapshotTests(unittest.TestCase):
    def test_snapshot_reads_current_ledger_state_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = Ledger(root, "nexus-node")
            started = ledger.start(
                job_id="job-1", video_sha256="0123456789abcdef-extra",
                metadata_sha256="metadata", title="Sample", privacy_status="private",
                video_path="video.mp4",
            )
            ledger.mark_uploaded(
                "job-1", video_id="video-1",
                video_url="https://www.youtube.com/watch?v=video-1", attempts=1,
            )

            snapshot = _upload_snapshot(root, "nexus-node")

            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0]["status"], "uploaded")
            self.assertEqual(snapshot[0]["video_id"], "video-1")
            self.assertEqual(snapshot[0]["sha256"], "0123456789abcdef")
            self.assertNotEqual(snapshot[0]["at"], started.updated_at)

    def test_snapshot_with_zero_limit_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(_upload_snapshot(Path(temporary), "nexus-node", limit=0), [])
