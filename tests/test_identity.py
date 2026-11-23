from __future__ import annotations

import unittest

from tests.support import FakeApi, make_channel
from uploader.errors import IdentityError, WrongChannelError
from uploader.identity import verify_identity, verify_upload_response


class IdentityTests(unittest.TestCase):
    def test_verified_identity(self) -> None:
        evidence = verify_identity(FakeApi(), make_channel())
        self.assertTrue(evidence.verified)
        # Public channel identifier, not a credential.  
        self.assertEqual(evidence.token_channel_id, "UCx9O8VivWkiEylDjs5_Zzag")  # gitleaks:allow
        self.assertEqual(evidence.handle_channel_id, "UCx9O8VivWkiEylDjs5_Zzag")

    def test_wrong_token_channel_id_aborts(self) -> None:
        api = FakeApi(channel_id="UCwrongwrongwrongwrongwrong")
        with self.assertRaises(IdentityError):
            verify_identity(api, make_channel())

    def test_wrong_title_aborts(self) -> None:
        api = FakeApi(title="Other Channel")
        with self.assertRaises(IdentityError):
            verify_identity(api, make_channel())

    def test_wrong_handle_channel_aborts(self) -> None:
        api = FakeApi(
            handle_id="UCwrongwrongwrongwrongwrong",
            handle_title="Nexus Node",
        )
        with self.assertRaises(IdentityError):
            verify_identity(api, make_channel())

    def test_wrong_handle_title_aborts(self) -> None:
        api = FakeApi(handle_title="Other Channel")
        with self.assertRaises(IdentityError):
            verify_identity(api, make_channel())

    def test_wrong_custom_url_aborts(self) -> None:
        api = FakeApi(custom_url="@not-nexus")
        with self.assertRaises(IdentityError):
            verify_identity(api, make_channel())

    def test_upload_response_channel_mismatch_aborts(self) -> None:
        with self.assertRaises(WrongChannelError):
            verify_upload_response(
                {"id": "video", "snippet": {"channelId": "UCwrongwrongwrongwrongwrong"}},
                make_channel(),
            )


class MultiChannelResponseTests(unittest.TestCase):
    """One Google account can own several channels, so `mine=true` may return more than one.

    This refuses rather than selecting the expected ID out of the list, and that is deliberate:
    `videos.insert` has no "publish to channel X" parameter, so an upload goes to whichever channel
    the token belongs to. If a token can see three channels it is not bound to one of them, and
    matching the expected ID inside the list would prove only that the channel is in the list - not
    that an upload would land there. The remedy is a token per channel, and the message says so.
    """

    IDS = (
        "UCx9O8VivWkiEylDjs5_Zzag",
        "UCr8jSmLa_o2BwNh8HuyZHAQ",
        "UC4OCY0qDwQqFnSCZw12sKxA",
    )
    TITLES = ("Nexus Node", "Academic Biohacker", "Natkhat Toons")

    class MultiApi:
        def __init__(self, items, handle_item=None):
            self.items = items
            self.handle_item = handle_item

        def channels_mine(self, parts="snippet,contentDetails"):
            return self.items

        def channel_for_handle(self, handle, parts="snippet"):
            if self.handle_item is not None:
                return self.handle_item
            return [{"id": "UCx9O8VivWkiEylDjs5_Zzag",
                     "snippet": {"title": "Nexus Node", "customUrl": "@nexusnode012"}}]

    def _items(self):
        return [
            {"id": channel_id, "snippet": {"title": title}}
            for channel_id, title in zip(self.IDS, self.TITLES)
        ]

    def test_three_channels_are_refused_even_when_the_expected_one_is_among_them(self) -> None:
        with self.assertRaises(IdentityError) as caught:
            verify_identity(self.MultiApi(self._items()), make_channel())
        self.assertIn("expected exactly 1", str(caught.exception))

    def test_the_refusal_names_every_channel_the_token_sees(self) -> None:
        with self.assertRaises(IdentityError) as caught:
            verify_identity(self.MultiApi(self._items()), make_channel())
        message = str(caught.exception)
        for channel_id in self.IDS:
            self.assertIn(channel_id, message)
        self.assertIn("re-run consent", message)

    def test_no_channels_is_refused_with_the_count(self) -> None:
        with self.assertRaises(IdentityError) as caught:
            verify_identity(self.MultiApi([]), make_channel())
        self.assertIn("returned 0 channels", str(caught.exception))

    def test_a_single_channel_with_the_wrong_title_still_aborts(self) -> None:
        api = self.MultiApi([{"id": self.IDS[0], "snippet": {"title": "Something Else"}}])
        with self.assertRaises(IdentityError) as caught:
            verify_identity(api, make_channel())
        self.assertIn("title mismatch", str(caught.exception))
