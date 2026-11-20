from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from .errors import ApiError, UploaderError
from .http import HttpClient

API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
_RANGE_RE = re.compile(r"bytes=0-(\d+)")


class YouTubeApi:
    def __init__(self, access_token: str, *, http: HttpClient | None = None) -> None:
        if not access_token:
            raise ValueError("access token is required")
        self.access_token = access_token
        self.http = http or HttpClient()

    def _auth_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if extra:
            headers.update(extra)
        return headers

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{API_BASE}/{path}?{urllib.parse.urlencode(params)}"
        payload = self.http.request_json("GET", url, headers=self._auth_headers())
        if not isinstance(payload, dict):
            raise ApiError(None, "invalid_response", "YouTube API returned an invalid response")
        return payload

    @staticmethod
    def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise ApiError(None, "invalid_response", "YouTube API items were invalid")
        return [item for item in items if isinstance(item, dict)]

    def channels_mine(self, parts: str = "snippet,contentDetails") -> list[dict[str, Any]]:
        return self._items(self._get("channels", {"part": parts, "mine": "true"}))

    def channel_for_handle(self, handle: str, parts: str = "snippet") -> list[dict[str, Any]]:
        clean_handle = handle[1:] if handle.startswith("@") else handle
        return self._items(
            self._get("channels", {"part": parts, "forHandle": clean_handle})
        )

    def get_video(self, video_id: str, parts: str = "snippet,status") -> dict[str, Any]:
        payload = self._get("videos", {"part": parts, "id": video_id})
        items = self._items(payload)
        if len(items) != 1:
            raise UploaderError(f"video lookup returned {len(items)} items for {video_id}")
        return items[0]

    def list_uploads(self, playlist_id: str, max_results: int = 10) -> list[dict[str, Any]]:
        return self._items(
            self._get(
                "playlistItems",
                {
                    "part": "contentDetails,snippet",
                    "playlistId": playlist_id,
                    "maxResults": str(max(1, min(max_results, 50))),
                },
            )
        )

    @staticmethod
    def uploads_playlist_id(channel_item: dict[str, Any]) -> str | None:
        content_details = channel_item.get("contentDetails", {})
        related = content_details.get("relatedPlaylists", {}) if isinstance(content_details, dict) else {}
        uploads = related.get("uploads") if isinstance(related, dict) else None
        return str(uploads) if uploads else None

    def initiate_resumable(
        self,
        metadata: dict[str, Any],
        content_length: int,
        *,
        content_type: str = "video/mp4",
        notify_subscribers: bool = False,
    ) -> str:
        if content_length <= 0:
            raise UploaderError("video file is empty")
        query = urllib.parse.urlencode(
            {
                "uploadType": "resumable",
                "part": "snippet,status",
                "notifySubscribers": "true" if notify_subscribers else "false",
            }
        )
        body = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers(
            {
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(content_length),
                "X-Upload-Content-Type": content_type,
            }
        )
        response = self.http.request(
            "POST",
            f"{UPLOAD_URL}?{query}",
            headers=headers,
            data=body,
            timeout=60,
        )
        location = response.header("Location")
        if not location:
            raise ApiError(
                response.status,
                "missing_upload_location",
                "resumable upload did not return a Location header",
            )
        return location

    def upload_resumable(
        self,
        upload_url: str,
        video_path: Path | str,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        timeout: float = 600,
    ) -> dict[str, Any]:
        path = Path(video_path)
        total = path.stat().st_size
        if total <= 0:
            raise UploaderError("video file is empty")
        if chunk_size <= 0:
            raise UploaderError("chunk size must be positive")
        offset = 0
        with path.open("rb") as handle:
            while offset < total:
                chunk = handle.read(min(chunk_size, total - offset))
                if not chunk:
                    raise UploaderError("unexpected end of video file")
                end = offset + len(chunk) - 1
                response = self.http.request(
                    "PUT",
                    upload_url,
                    headers=self._auth_headers(
                        {
                            "Content-Length": str(len(chunk)),
                            "Content-Type": "video/mp4",
                            "Content-Range": f"bytes {offset}-{end}/{total}",
                        }
                    ),
                    data=chunk,
                    timeout=timeout,
                )
                if response.status in (200, 201):
                    payload = response.json()
                    if not isinstance(payload, dict) or not payload.get("id"):
                        raise ApiError(
                            response.status,
                            "invalid_upload_response",
                            "upload completed without a video id",
                        )
                    return payload
                if response.status == 308:
                    range_header = response.header("Range")
                    match = _RANGE_RE.search(range_header or "")
                    if match:
                        offset = int(match.group(1)) + 1
                    else:
                        offset = end + 1
                    continue
                raise ApiError(
                    response.status,
                    "unexpected_upload_status",
                    f"unexpected status during resumable upload: {response.status}",
                    retryable=response.status == 429 or response.status >= 500,
                )
        raise UploaderError("resumable upload ended without a completion response")

    def insert_video(
        self,
        metadata: dict[str, Any],
        video_path: Path | str,
        *,
        notify_subscribers: bool = False,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> dict[str, Any]:
        path = Path(video_path)
        upload_url = self.initiate_resumable(
            metadata,
            path.stat().st_size,
            notify_subscribers=notify_subscribers,
        )
        return self.upload_resumable(upload_url, path, chunk_size=chunk_size)
