"""Both 1080p profiles this factory renders must be uploadable.

The uploader was written when every episode was a Short, and ``probe_media`` hard-coded 1080x1920. A 16:9
episode could be rendered, QC'd and gated - and then refused at the last step with "video must be
1080x1920, got 1920x1080", which would have made the long-form half of the nightly cadence unpublishable.
The geometry guard still exists; it now knows the two profiles the factory actually produces.

This module is ``unittest`` rather than ``pytest`` on purpose: the uploader CI job runs
``python -m unittest discover -s tests`` with no third-party packages installed, and a pytest import here
would fail the whole job at collection.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_channel, make_video
from uploader.errors import ValidationError
from uploader.metadata import ALLOWED_GEOMETRIES, UploadRequest


def probe(width: int, height: int, *, video_streams: int = 1, audio_streams: int = 1) -> dict:
    streams = [{"codec_type": "video", "width": width, "height": height}] * video_streams
    streams += [{"codec_type": "audio"}] * audio_streams
    return {"streams": streams, "format": {"duration": "38.0"}}


def probe_in(directory: Path, payload: dict) -> UploadRequest:
    video = make_video(directory)
    request = UploadRequest.from_data(make_channel(), video, {"title": "T", "description": "D"})
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload))
    # The uploader CI job installs no system packages, so ffprobe is absent there. Both the availability
    # check and the probe itself are stubbed: what is under test is the geometry rule, not the tool.
    with mock.patch("uploader.metadata._find_ffprobe", return_value="ffprobe"),             mock.patch("uploader.metadata.subprocess.run", return_value=completed):
        request.probe_media()
    return request


class UploadGeometryTests(unittest.TestCase):
    def test_the_portrait_profile_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            probe_in(Path(temporary), probe(1080, 1920))

    def test_the_landscape_profile_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            probe_in(Path(temporary), probe(1920, 1080))

    def test_anything_else_is_still_refused(self) -> None:
        for width, height in ((720, 1280), (1080, 1080), (3840, 2160), (1080, 1919), (1920, 1919)):
            with self.subTest(size=f"{width}x{height}"):
                with tempfile.TemporaryDirectory() as temporary:
                    with self.assertRaises(ValidationError) as caught:
                        probe_in(Path(temporary), probe(width, height))
                    message = str(caught.exception)
                    self.assertIn(f"{width}x{height}", message)
                    self.assertIn("1080x1920", message)
                    self.assertIn("1920x1080", message)

    def test_the_allowed_set_is_exactly_the_two_profiles(self) -> None:
        self.assertEqual(ALLOWED_GEOMETRIES, frozenset({(1080, 1920), (1920, 1080)}))

    def test_a_video_without_audio_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValidationError) as caught:
                probe_in(Path(temporary), probe(1920, 1080, audio_streams=0))
            self.assertIn("audio stream", str(caught.exception))

    def test_a_video_with_two_video_streams_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValidationError) as caught:
                probe_in(Path(temporary), probe(1920, 1080, video_streams=2))
            self.assertIn("exactly one video stream", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
