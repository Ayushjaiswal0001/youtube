from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from uploader.http import HttpResponse
from uploader.youtube import YouTubeApi


class FakeUploadHttp:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers=None,
        data=None,
        timeout=None,
    ) -> HttpResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "data": data,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)

    def request_json(self, method, url, *, headers=None, data=None, timeout=None):
        response = self.request(method, url, headers=headers, data=data, timeout=timeout)
        return response.json()


class YouTubeTests(unittest.TestCase):
    def test_uploads_playlist_id(self) -> None:
        item = {"contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}
        self.assertEqual(YouTubeApi.uploads_playlist_id(item), "UU123")
        self.assertIsNone(YouTubeApi.uploads_playlist_id({}))

    def test_insert_video_sends_metadata_and_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "video.mp4"
            video.write_bytes(b"0123456789")
            responses = [
                HttpResponse(200, {"Location": "https://upload.example/resumable"}, b"{}"),
                HttpResponse(
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "video-id",
                            "snippet": {"channelId": "UCx9O8VivWkiEylDjs5_Zzag"},
                        }
                    ).encode(),
                ),
            ]
            http = FakeUploadHttp(responses)
            api = YouTubeApi("access-token", http=http)
            result = api.insert_video(
                {"snippet": {"title": "Test"}, "status": {"privacyStatus": "private"}},
                video,
                notify_subscribers=False,
                chunk_size=4,
            )
            self.assertEqual(result["id"], "video-id")
            self.assertEqual(http.requests[0]["method"], "POST")
            self.assertTrue(
                http.requests[0]["url"].startswith(
                    "https://www.googleapis.com/upload/youtube/v3/videos?"
                )
            )
            self.assertIn("uploadType=resumable", http.requests[0]["url"])
            self.assertIn("notifySubscribers=false", http.requests[0]["url"])
            self.assertEqual(http.requests[1]["method"], "PUT")
            self.assertIn("bytes 0-3/10", http.requests[1]["headers"]["Content-Range"])

    def test_resumable_upload_handles_308_range(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "video.mp4"
            video.write_bytes(b"0123456789")
            responses = [
                HttpResponse(200, {"Location": "https://upload.example/resumable"}, b"{}"),
                HttpResponse(308, {"Range": "bytes=0-3"}, b""),
                HttpResponse(
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "video-id",
                            "snippet": {"channelId": "UCx9O8VivWkiEylDjs5_Zzag"},
                        }
                    ).encode(),
                ),
            ]
            http = FakeUploadHttp(responses)
            api = YouTubeApi("access-token", http=http)
            result = api.insert_video(
                {"snippet": {"title": "Test"}, "status": {"privacyStatus": "private"}},
                video,
                chunk_size=4,
            )
            self.assertEqual(result["id"], "video-id")
            self.assertIn("bytes 4-7/10", http.requests[2]["headers"]["Content-Range"])
