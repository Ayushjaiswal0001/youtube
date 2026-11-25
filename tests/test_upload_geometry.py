"""Both 1080p profiles this factory renders must be uploadable.

The uploader was written when every episode was a Short, and `probe_media` hard-coded 1080x1920. A 16:9
episode could be rendered, QC'd and gated — and then refused at the last step with "video must be
1080x1920, got 1920x1080", which would have made the long-form half of the nightly cadence unpublishable.
The geometry guard still exists; it now knows the two profiles the factory actually produces.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from tests.support import make_channel, make_video
from uploader.errors import ValidationError
from uploader.metadata import ALLOWED_GEOMETRIES, UploadRequest


def probe(width: int, height: int, *, video_streams: int = 1, audio_streams: int = 1) -> dict:
    streams = [{"codec_type": "video", "width": width, "height": height}] * video_streams
    streams += [{"codec_type": "audio"}] * audio_streams
    return {"streams": streams, "format": {"duration": "38.0"}}


def request_for(tmp_path: Path, payload: dict) -> UploadRequest:
    video = make_video(tmp_path)
    request = UploadRequest.from_data(make_channel(), video, {"title": "T", "description": "D"})
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload))
    with mock.patch("uploader.metadata.subprocess.run", return_value=completed):
        request.probe_media()
    return request


def test_the_portrait_profile_is_accepted(tmp_path: Path) -> None:
    request_for(tmp_path, probe(1080, 1920))


def test_the_landscape_profile_is_accepted(tmp_path: Path) -> None:
    request_for(tmp_path, probe(1920, 1080))


@pytest.mark.parametrize("width,height", [(720, 1280), (1080, 1080), (3840, 2160), (1080, 1919)])
def test_anything_else_is_still_refused(tmp_path: Path, width: int, height: int) -> None:
    with pytest.raises(ValidationError) as excinfo:
        request_for(tmp_path, probe(width, height))
    message = str(excinfo.value)
    assert f"{width}x{height}" in message
    assert "1080x1920" in message and "1920x1080" in message, "the error must say what is allowed"


def test_the_allowed_set_is_exactly_the_two_profiles() -> None:
    assert ALLOWED_GEOMETRIES == frozenset({(1080, 1920), (1920, 1080)})


def test_a_video_without_audio_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="audio stream"):
        request_for(tmp_path, probe(1920, 1080, audio_streams=0))
