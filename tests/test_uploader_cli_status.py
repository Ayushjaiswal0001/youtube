from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from uploader.cli import main
from uploader.ledger import Ledger


class UploaderStatusCliTests(unittest.TestCase):
    def test_text_status_prints_dataclass_entries_and_latest_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ledger = Ledger(root / "state", "nexus-node")
            ledger.start(
                job_id="job-1", video_sha256="hash", metadata_sha256="metadata",
                title="Sample title", privacy_status="private", video_path="video.mp4",
            )
            ledger.mark_uploaded(
                "job-1", video_id="video-1",
                video_url="https://www.youtube.com/watch?v=video-1", attempts=1,
            )
            output = io.StringIO()

            with patch("uploader.cli.setup_logging"), redirect_stdout(output):
                result = main([
                    "status", "--channel", "nexus-node",
                    "--channels-dir", str(Path(__file__).resolve().parents[1] / "channels"),
                    "--state-root", str(root / "state"),
                    "--log-root", str(root / "logs"),
                ])

            self.assertEqual(result, 0)
            self.assertIn("uploaded", output.getvalue())
            self.assertIn("job-1 Sample title", output.getvalue())
            self.assertNotIn("uploading", output.getvalue())
