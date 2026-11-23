from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ChannelConfig
from .errors import IdentityError, WrongChannelError


@dataclass(frozen=True)
class IdentityEvidence:
    channel_slug: str
    expected_channel_id: str
    expected_title: str
    expected_handle: str
    token_channel_id: str | None
    token_channel_title: str | None
    handle_channel_id: str | None
    handle_channel_title: str | None
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_slug": self.channel_slug,
            "expected_channel_id": self.expected_channel_id,
            "expected_title": self.expected_title,
            "expected_handle": self.expected_handle,
            "token_channel_id": self.token_channel_id,
            "token_channel_title": self.token_channel_title,
            "handle_channel_id": self.handle_channel_id,
            "handle_channel_title": self.handle_channel_title,
            "verified": self.verified,
        }


def _snippet(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet", {})
    return snippet if isinstance(snippet, dict) else {}


def _describe(items: list[dict[str, Any]]) -> str:
    return ", ".join(
        f"{item.get('id') or '<missing>'} ({_snippet(item).get('title') or '?'})"
        for item in items
    )


def verify_identity(api: Any, channel: ChannelConfig) -> IdentityEvidence:
    mine = api.channels_mine("snippet,contentDetails")
    if len(mine) != 1:
        # A token bound to one channel is the whole premise of channel routing: `videos.insert` has
        # no "upload to channel X" parameter, so it publishes to whatever channel the token belongs
        # to. If `mine=true` returns several, the token is not bound to one channel and this check
        # cannot prove where an upload would land. Refusing is the only honest answer - matching one
        # of several IDs would say "the expected channel is in the list", which is not the same
        # claim. The remedy is a token per channel (choose the channel's own identity in the account
        # picker), and the message names what the token currently sees so that is actionable.
        seen = f"; returned: {_describe(mine)}" if mine else ""
        raise IdentityError(
            f"channels.list(mine=true) returned {len(mine)} channels; expected exactly 1 "
            f"({channel.slug} = {channel.expected_channel_id}). A token must be bound to a single "
            f"channel; re-run consent and choose {channel.display_name!r} itself in the account "
            f"picker rather than the Google Account that owns it{seen}"
        )
    mine_item = mine[0]
    mine_id = str(mine_item.get("id") or "")
    mine_title = str(_snippet(mine_item).get("title") or "")

    handle_items = api.channel_for_handle(channel.handle, "snippet")
    if len(handle_items) != 1:
        raise IdentityError(
            f"handle lookup for {channel.handle} returned {len(handle_items)} channels"
        )
    handle_item = handle_items[0]
    handle_id = str(handle_item.get("id") or "")
    handle_title = str(_snippet(handle_item).get("title") or "")

    evidence = IdentityEvidence(
        channel_slug=channel.slug,
        expected_channel_id=channel.expected_channel_id,
        expected_title=channel.display_name,
        expected_handle=channel.handle,
        token_channel_id=mine_id or None,
        token_channel_title=mine_title or None,
        handle_channel_id=handle_id or None,
        handle_channel_title=handle_title or None,
        verified=False,
    )
    if mine_id != channel.expected_channel_id:
        raise IdentityError(
            f"token channel ID mismatch for {channel.slug}: "
            f"expected {channel.expected_channel_id}, got {mine_id or '<missing>'}"
        )
    if mine_title != channel.display_name:
        raise IdentityError(
            f"token channel title mismatch for {channel.slug}: "
            f"expected {channel.display_name!r}, got {mine_title!r}"
        )
    if handle_id != channel.expected_channel_id:
        raise IdentityError(
            f"handle channel ID mismatch for {channel.slug}: "
            f"expected {channel.expected_channel_id}, got {handle_id or '<missing>'}"
        )
    if handle_title != channel.display_name:
        raise IdentityError(
            f"handle channel title mismatch for {channel.slug}: "
            f"expected {channel.display_name!r}, got {handle_title!r}"
        )
    custom_url = str(_snippet(handle_item).get("customUrl") or "")
    if custom_url and custom_url.lower() != channel.handle.lower():
        raise IdentityError(
            f"handle customUrl mismatch for {channel.slug}: "
            f"expected {channel.handle!r}, got {custom_url!r}"
        )
    return IdentityEvidence(
        channel_slug=evidence.channel_slug,
        expected_channel_id=evidence.expected_channel_id,
        expected_title=evidence.expected_title,
        expected_handle=evidence.expected_handle,
        token_channel_id=evidence.token_channel_id,
        token_channel_title=evidence.token_channel_title,
        handle_channel_id=evidence.handle_channel_id,
        handle_channel_title=evidence.handle_channel_title,
        verified=True,
    )


def verify_access_token(
    access_token: str,
    channel: ChannelConfig,
    *,
    http: Any = None,
) -> dict[str, Any]:
    from .youtube import YouTubeApi

    api = YouTubeApi(access_token, http=http)
    return verify_identity(api, channel).to_dict()


def verify_upload_response(
    response: dict[str, Any],
    channel: ChannelConfig,
) -> None:
    snippet = response.get("snippet", {})
    channel_id = snippet.get("channelId") if isinstance(snippet, dict) else None
    if channel_id != channel.expected_channel_id:
        raise WrongChannelError(
            f"upload response channel ID mismatch for {channel.slug}: "
            f"expected {channel.expected_channel_id}, got {channel_id or '<missing>'}"
        )
