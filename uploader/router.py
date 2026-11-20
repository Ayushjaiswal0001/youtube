from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import ChannelConfig
from .credentials import CredentialManager
from .errors import (
    ApiError,
    SafetyError,
    UploadStateUnknown,
    UploaderError,
    WrongChannelError,
)
from .identity import verify_identity, verify_upload_response
from .ledger import Ledger
from .metadata import UploadRequest
from .oauth import OAuthClient
from .retry import retry_call
from .youtube import YouTubeApi

logger = logging.getLogger("uploader")


@dataclass
class PreparedUpload:
    channel: ChannelConfig
    request: UploadRequest
    credential_source: str
    scopes: tuple[str, ...]
    identity: dict[str, Any]
    video_sha256: str
    metadata_sha256: str
    prior_status: str | None
    ledger: Ledger = field(repr=False)
    api: Any = field(repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "channel_slug": self.channel.slug,
            "display_name": self.channel.display_name,
            "expected_channel_id": self.channel.expected_channel_id,
            "handle": self.channel.handle,
            "title": self.request.title,
            "privacy_status": self.request.privacy_status,
            "made_for_kids": self.request.made_for_kids,
            "notify_subscribers": self.request.notify_subscribers,
            "playlist_id": self.request.playlist_id,
            "publish_at": self.request.publish_at,
            "thumbnail": (
                str(self.request.thumbnail_path)
                if self.request.thumbnail_path
                else None
            ),
            "default_language": self.request.default_language,
            "default_audio_language": self.request.default_audio_language,
            "video_file": self.request.video_path.name,
            "video_size": self.request.video_path.stat().st_size,
            "video_sha256": self.video_sha256,
            "metadata_sha256": self.metadata_sha256,
            "credential_source": self.credential_source,
            "scopes": list(self.scopes),
            "identity": self.identity,
            "duplicate_check": "clear",
            "prior_status": self.prior_status,
        }


class ChannelRouter:
    def __init__(
        self,
        configs: Mapping[str, ChannelConfig],
        credentials: CredentialManager,
        ledger_root: Path | str,
        *,
        http: Any = None,
        api_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not configs:
            raise ValueError("at least one channel config is required")
        self.configs = dict(configs)
        self.credentials = credentials
        self.ledger_root = Path(ledger_root)
        self.http = http
        self.api_factory = api_factory or (
            lambda token: YouTubeApi(token, http=self.http)
        )

    def channel(self, slug: str) -> ChannelConfig:
        try:
            return self.configs[slug]
        except KeyError as exc:
            raise UploaderError(f"unknown channel: {slug}") from exc

    def source_for(self, slug: str) -> str:
        self.channel(slug)
        return self.credentials.source(slug)

    def _refresh(self, slug: str) -> tuple[Any, Any, tuple[str, ...]]:
        credentials = self.credentials.get(slug)
        client = OAuthClient(
            credentials.client_id,
            credentials.client_secret,
            http=self.http,
        )
        token = retry_call(lambda: client.refresh(credentials.refresh_token))
        api = self.api_factory(token.access_token)
        return credentials, api, token.scopes()

    def refresh_scopes(self, slug: str) -> list[str]:
        self.channel(slug)
        _, _, scopes = self._refresh(slug)
        return list(scopes)

    def refresh_api(self, slug: str) -> Any:
        self.channel(slug)
        _, api, _ = self._refresh(slug)
        return api

    def verify_channel(self, slug: str) -> dict[str, Any]:
        channel = self.channel(slug)
        credentials, api, scopes = self._refresh(slug)
        evidence = verify_identity(api, channel)
        return {
            "channel_slug": channel.slug,
            "display_name": channel.display_name,
            "expected_channel_id": channel.expected_channel_id,
            "handle": channel.handle,
            "credential_source": credentials.source,
            "scopes": list(scopes),
            "identity": evidence.to_dict(),
            "verified": True,
        }

    def verify_all(self) -> list[dict[str, Any]]:
        return [self.verify_channel(slug) for slug in self.configs]

    def prepare(
        self,
        slug: str,
        video_path: Path | str,
        data: Mapping[str, Any],
        *,
        allow_public: bool = False,
        validate_media: bool = True,
    ) -> PreparedUpload:
        channel = self.channel(slug)
        request = UploadRequest.from_data(channel, video_path, data)
        effective_allow_public = bool(allow_public and channel.allow_public_upload)
        request.validate(allow_public=effective_allow_public)
        if validate_media:
            request.probe_media()
        video_sha256 = request.video_sha256()
        metadata_sha256 = request.metadata_sha256()
        ledger = Ledger(self.ledger_root, channel.slug)
        prior = ledger.assert_no_duplicate(video_sha256)
        credentials, api, scopes = self._refresh(slug)
        evidence = verify_identity(api, channel)
        return PreparedUpload(
            channel=channel,
            request=request,
            credential_source=credentials.source,
            scopes=scopes,
            identity=evidence.to_dict(),
            video_sha256=video_sha256,
            metadata_sha256=metadata_sha256,
            prior_status=prior.status if prior else None,
            ledger=ledger,
            api=api,
        )

    def dry_run(
        self,
        slug: str,
        video_path: Path | str,
        data: Mapping[str, Any],
        *,
        allow_public: bool = False,
        validate_media: bool = True,
    ) -> dict[str, Any]:
        prepared = self.prepare(
            slug,
            video_path,
            data,
            allow_public=allow_public,
            validate_media=validate_media,
        )
        result = prepared.public_dict()
        result.update(
            {
                "status": "dry_run_ok",
                "upload_performed": False,
            }
        )
        return result

    def upload(
        self,
        slug: str,
        video_path: Path | str,
        data: Mapping[str, Any],
        *,
        execute: bool = False,
        confirm_channel: str | None = None,
        allow_public: bool = False,
        validate_media: bool = True,
    ) -> dict[str, Any]:
        if execute and confirm_channel != slug:
            raise SafetyError(
                "--confirm-channel must exactly match the selected channel slug"
            )
        prepared = self.prepare(
            slug,
            video_path,
            data,
            allow_public=allow_public,
            validate_media=validate_media,
        )
        if not execute:
            result = prepared.public_dict()
            result.update({"status": "dry_run_ok", "upload_performed": False})
            return result
        final_evidence = verify_identity(prepared.api, prepared.channel)
        if (
            final_evidence.token_channel_id
            != prepared.identity.get("token_channel_id")
            or final_evidence.token_channel_title
            != prepared.identity.get("token_channel_title")
        ):
            raise WrongChannelError("channel changed between preflight and upload")
        job_id = uuid.uuid4().hex
        prepared.ledger.start(
            job_id=job_id,
            video_sha256=prepared.video_sha256,
            metadata_sha256=prepared.metadata_sha256,
            title=prepared.request.title,
            privacy_status=prepared.request.privacy_status,
            video_path=str(prepared.request.video_path),
            attempts=1,
        )
        try:
            response = prepared.api.insert_video(
                prepared.request.to_api_body(),
                prepared.request.video_path,
                notify_subscribers=prepared.request.notify_subscribers,
            )
            verify_upload_response(response, prepared.channel)
            video_id = str(response.get("id"))
            entry = prepared.ledger.mark_uploaded(
                job_id,
                video_id=video_id,
                video_url=f"https://www.youtube.com/watch?v={video_id}",
                attempts=1,
            )
            thumbnail_applied = False
            thumbnail_error = None
            if prepared.request.thumbnail_path is not None:
                try:
                    prepared.api.set_thumbnail(
                        video_id, prepared.request.thumbnail_path
                    )
                    thumbnail_applied = True
                except Exception as exc:  # noqa: BLE001 - upload already succeeded
                    thumbnail_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "video %s uploaded but thumbnail failed: %s",
                        video_id,
                        thumbnail_error,
                    )
            result = prepared.public_dict()
            result.update(
                {
                    "status": "uploaded",
                    "upload_performed": True,
                    "job_id": job_id,
                    "video_id": entry.video_id,
                    "video_url": entry.video_url,
                    "playlist_applied": False,
                    "thumbnail_applied": thumbnail_applied,
                    "thumbnail_error": thumbnail_error,
                }
            )
            return result
        except ApiError as exc:
            code = f"http_{exc.status}_{exc.reason}"
            if exc.retryable:
                prepared.ledger.mark_unknown(
                    job_id,
                    error_code=code,
                    error_message=str(exc),
                    attempts=1,
                )
                raise UploadStateUnknown(
                    "upload result is unknown; reconcile the channel uploads "
                    "playlist before retrying"
                ) from exc
            prepared.ledger.mark_failed(
                job_id,
                error_code=code,
                error_message=str(exc),
                attempts=1,
            )
            raise
        except WrongChannelError as exc:
            prepared.ledger.mark_unknown(
                job_id,
                error_code="wrong_channel",
                error_message=str(exc),
                attempts=1,
            )
            raise
        except Exception as exc:
            prepared.ledger.mark_unknown(
                job_id,
                error_code="unexpected_error",
                error_message=f"{type(exc).__name__}: {exc}",
                attempts=1,
            )
            raise UploadStateUnknown(
                "unexpected upload error; state is unknown and requires reconciliation"
            ) from exc
