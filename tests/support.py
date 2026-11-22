from __future__ import annotations

from pathlib import Path
from typing import Any

from uploader.config import ChannelConfig, ChannelDefaults
from uploader.credentials import ChannelCredentials
from uploader.oauth import READONLY_SCOPE, UPLOAD_SCOPE

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_channel(
    slug: str = "nexus-node",
    *,
    display_name: str = "Nexus Node",
    handle: str = "@nexusnode012",
    expected_channel_id: str = "UCx9O8VivWkiEylDjs5_Zzag",
    made_for_kids: bool | None = False,
    requires_made_for_kids_confirmation: bool = False,
    force_made_for_kids: bool = False,
    allow_public_upload: bool = False,
) -> ChannelConfig:
    return ChannelConfig(
        slug=slug,
        display_name=display_name,
        handle=handle,
        expected_channel_id=expected_channel_id,
        defaults=ChannelDefaults(
            tags=("shorts",),
            category_id="27",
            privacy_status="private",
            made_for_kids=made_for_kids,
            notify_subscribers=False,
            description_footer="",
            playlist_id=None,
        ),
        requires_made_for_kids_confirmation=requires_made_for_kids_confirmation,
        force_made_for_kids=force_made_for_kids,
        allow_public_upload=allow_public_upload,
    )


def make_video(directory: Path, name: str = "video.mp4", content: bytes | None = None) -> Path:
    path = directory / name
    path.write_bytes(content if content is not None else b"fake-mp4-bytes")
    return path


class FakeApi:
    def __init__(
        self,
        *,
        channel_id: str = "UCx9O8VivWkiEylDjs5_Zzag",
        title: str = "Nexus Node",
        handle_id: str | None = None,
        handle_title: str | None = None,
        custom_url: str | None = "@nexusnode012",
        upload_error: Exception | None = None,
        upload_response: dict[str, Any] | None = None,
    ) -> None:
        self.channel_id = channel_id
        self.title = title
        self.handle_id = handle_id or channel_id
        self.handle_title = handle_title or title
        self.custom_url = custom_url
        self.upload_error = upload_error
        self.upload_response = upload_response
        self.inserts: list[dict[str, Any]] = []

    def channels_mine(self, parts: str = "snippet,contentDetails") -> list[dict[str, Any]]:
        return [{"id": self.channel_id, "snippet": {"title": self.title}}]

    def channel_for_handle(self, handle: str, parts: str = "snippet") -> list[dict[str, Any]]:
        snippet: dict[str, Any] = {"title": self.handle_title}
        if self.custom_url:
            snippet["customUrl"] = self.custom_url
        return [{"id": self.handle_id, "snippet": snippet}]

    def insert_video(
        self,
        metadata: dict[str, Any],
        video_path: Path,
        *,
        notify_subscribers: bool = False,
        chunk_size: int | None = None,
    ) -> dict[str, Any]:
        if self.upload_error:
            raise self.upload_error
        self.inserts.append(
            {
                "metadata": metadata,
                "video_path": str(video_path),
                "notify_subscribers": notify_subscribers,
            }
        )
        if self.upload_response is not None:
            return self.upload_response
        return {
            "id": "vid-123",
            "snippet": {"channelId": self.channel_id},
            "status": {"privacyStatus": metadata["status"]["privacyStatus"]},
        }


class FakeOAuthHttp:
    def __init__(
        self,
        *,
        scopes: tuple[str, ...] = (UPLOAD_SCOPE, READONLY_SCOPE),
        access_token: str = "access-token",
    ) -> None:
        self.scopes = scopes
        self.access_token = access_token
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "data": data,
            }
        )
        return {
            "access_token": self.access_token,
            "expires_in": 3600,
            "scope": " ".join(self.scopes),
            "token_type": "Bearer",
        }


class FakeCredentials:
    def __init__(self, source: str = "secret_file") -> None:
        self.source_name = source

    def get(self, slug: str) -> ChannelCredentials:
        return ChannelCredentials(
            channel_slug=slug,
            client_id="client-id",
            client_secret="client-secret",  # pragma: allowlist secret - fixture, not a credential
            refresh_token="refresh-token",  # pragma: allowlist secret
            source=self.source_name,
        )

    def source(self, slug: str) -> str:
        return self.source_name
