from __future__ import annotations

import unittest

from tools.check_oauth_identity import inspect_channel, render
from uploader.config import ChannelConfig


class FakeCredentials:
    def __init__(self, source: str) -> None:
        self._source = source

    def source(self, slug: str) -> str:
        return self._source


class FakeApi:
    def __init__(self, items, handle_items, token: str = "ya29.SECRET-TOKEN") -> None:
        self.items = items
        self.handle_items = handle_items
        self.token = token

    def channels_mine(self, parts: str = "snippet,contentDetails"):
        return self.items

    def channel_for_handle(self, handle: str, parts: str = "snippet"):
        return self.handle_items


class FakeRouter:
    def __init__(self, channel: ChannelConfig, api, source: str = "environment") -> None:
        self._channel = channel
        self._api = api
        self.credentials = FakeCredentials(source)

    def channel(self, slug: str) -> ChannelConfig:
        return self._channel

    def refresh_api(self, slug: str):
        return self._api


def _channel() -> ChannelConfig:
    return ChannelConfig.from_dict(
        {
            "slug": "nexus-node",
            "display_name": "Nexus Node",
            "handle": "@nexusnode012",
            "expected_channel_id": "UCx9O8VivWkiEylDjs5_Zzag",
            "requires_made_for_kids_confirmation": False,
            "force_made_for_kids": False,
            "default_category_id": "27",
        }
    )


class DiagnosticTests(unittest.TestCase):
    """The diagnostic must answer "what does this token see" without ever showing the token."""

    def test_a_three_channel_response_is_reported_in_full(self) -> None:
        api = FakeApi(
            [
                {"id": "UCx9O8VivWkiEylDjs5_Zzag", "snippet": {"title": "Nexus Node"}},
                {"id": "UCr8jSmLa_o2BwNh8HuyZHAQ", "snippet": {"title": "Academic Biohacker"}},
                {"id": "UC4OCY0qDwQqFnSCZw12sKxA", "snippet": {"title": "Natkhat Toons"}},
            ],
            [{"id": "UCx9O8VivWkiEylDjs5_Zzag",
              "snippet": {"title": "Nexus Node", "customUrl": "@nexusnode012"}}],
        )
        report = inspect_channel("nexus-node", FakeRouter(_channel(), api))
        # Three channels is a refusal, not a verification: the token is not bound to one channel,
        # so nothing here can prove where an upload would land. The diagnostic's job is to show
        # that plainly, with every channel the token sees.
        self.assertEqual(report["mine_count"], 3)
        self.assertFalse(report["verified"])
        self.assertIn("expected exactly 1", report["error"])
        text = render(report)
        self.assertIn("returned 3", text)
        self.assertIn("UCr8jSmLa_o2BwNh8HuyZHAQ", text)
        self.assertIn("NOT VERIFIED", text)
        self.assertNotIn("ya29", text)
        self.assertNotIn("SECRET", text)

    def test_a_token_for_the_wrong_channel_is_reported_as_not_verified(self) -> None:
        api = FakeApi(
            [{"id": "UC4OCY0qDwQqFnSCZw12sKxA", "snippet": {"title": "Natkhat Toons"}}],
            [{"id": "UC4OCY0qDwQqFnSCZw12sKxA", "snippet": {"title": "Natkhat Toons"}}],
        )
        report = inspect_channel("nexus-node", FakeRouter(_channel(), api))
        self.assertFalse(report["verified"])
        self.assertIn("identity", render(report).lower())

    def test_missing_credentials_are_reported_without_a_network_call(self) -> None:
        class ExplodingRouter(FakeRouter):
            def refresh_api(self, slug: str):
                raise AssertionError("must not refresh without credentials")

        report = inspect_channel(
            "nexus-node", ExplodingRouter(_channel(), FakeApi([], []), source="missing")
        )
        self.assertFalse(report["authorized"])
        self.assertIn("consent", report["error"])

    def test_the_json_report_contains_no_token_material(self) -> None:
        import json

        api = FakeApi(
            [{"id": "UCx9O8VivWkiEylDjs5_Zzag", "snippet": {"title": "Nexus Node"}}],
            [{"id": "UCx9O8VivWkiEylDjs5_Zzag",
              "snippet": {"title": "Nexus Node", "customUrl": "@nexusnode012"}}],
        )
        report = inspect_channel("nexus-node", FakeRouter(_channel(), api))
        payload = json.dumps(report)
        self.assertNotIn("ya29", payload)
        self.assertNotIn("refresh_token", payload)
        self.assertNotIn("client_secret", payload)
