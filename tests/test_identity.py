from __future__ import annotations

import unittest

from tests.support import FakeApi, make_channel
from uploader.errors import IdentityError, WrongChannelError
from uploader.identity import verify_identity, verify_upload_response


class IdentityTests(unittest.TestCase):
    def test_verified_identity(self) -> None:
        evidence = verify_identity(FakeApi(), make_channel())
        self.assertTrue(evidence.verified)
        self.assertEqual(evidence.token_channel_id, "UCx9O8VivWkiEylDjs5_Zzag")
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
