from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from uploader.credentials import (
    CredentialManager,
    SecretStore,
    map_legacy_label,
    parse_legacy_credentials,
)
from uploader.errors import CredentialsError


LEGACY_TEXT = """\
for nexus node
YT_CLIENT_ID: cid-nexus
YT_CLIENT_SECRET: secret-nexus
YT_REFRESH_TOKEN: refresh-nexus

for academic biohacker
YT_CLIENT_ID: cid-academic
YT_CLIENT_SECRET: secret-academic
YT_REFRESH_TOKEN: refresh-academic

for kids channel - natkhat toons
YT_CLIENT_ID: cid-natkhat
YT_CLIENT_SECRET: secret-natkhat
YT_REFRESH_TOKEN: refresh-natkhat
"""


class CredentialParsingTests(unittest.TestCase):
    def test_maps_labels(self) -> None:
        self.assertEqual(map_legacy_label("for nexus node"), "nexus-node")
        self.assertEqual(map_legacy_label("for academic biohacker"), "academic-biohacker")
        self.assertEqual(
            map_legacy_label("for kids channel - natkhat toons"), "natkhat-toons"
        )
        self.assertIsNone(map_legacy_label("unknown"))

    def test_parses_three_sets_without_exposing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.txt"
            path.write_text(LEGACY_TEXT, encoding="utf-8")
            parsed = parse_legacy_credentials(path)
            self.assertEqual(
                set(parsed),
                {"nexus-node", "academic-biohacker", "natkhat-toons"},
            )
            self.assertEqual(parsed["nexus-node"].client_id, "cid-nexus")
            self.assertEqual(parsed["academic-biohacker"].refresh_token, "refresh-academic")
            self.assertNotIn("secret-nexus", repr(parsed["nexus-node"]))
            self.assertNotIn("refresh-nexus", repr(parsed["nexus-node"]))
            self.assertNotIn("secret-nexus", parsed["nexus-node"].public_dict())

    def test_rejects_unknown_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.txt"
            path.write_text(
                "for unknown channel\n"
                "YT_CLIENT_ID: cid\n"
                "YT_CLIENT_SECRET: secret\n"
                "YT_REFRESH_TOKEN: refresh\n",
                encoding="utf-8",
            )
            with self.assertRaises(CredentialsError):
                parse_legacy_credentials(path)

    def test_rejects_incomplete_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "credentials.txt"
            path.write_text(
                "for nexus node\n"
                "YT_CLIENT_ID: cid\n"
                "YT_CLIENT_SECRET: secret\n",
                encoding="utf-8",
            )
            with self.assertRaises(CredentialsError):
                parse_legacy_credentials(path)


class SecretStoreTests(unittest.TestCase):
    def test_save_and_load_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(Path(temporary))
            path = store.save(
                "nexus-node",
                "client-id",
                "client-secret",
                "refresh-token",
                scopes=("scope-a", "scope-b"),
                channel_id="UCx9O8VivWkiEylDjs5_Zzag",
                channel_title="Nexus Node",
                handle="@nexusnode012",
            )
            self.assertTrue(path.is_file())
            loaded = store.load("nexus-node")
            self.assertEqual(loaded.client_id, "client-id")
            self.assertEqual(loaded.scopes, ("scope-a", "scope-b"))
            self.assertNotIn("client-secret", repr(loaded))
            with self.assertRaises(CredentialsError):
                store.save(
                    "nexus-node",
                    "other-id",
                    "other-secret",
                    "other-refresh",
                    scopes=("scope-a",),
                    channel_id="UCx9O8VivWkiEylDjs5_Zzag",
                    channel_title="Nexus Node",
                    handle="@nexusnode012",
                )

    def test_environment_credentials_take_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = CredentialManager(
                Path(temporary),
                env={
                    "YT_NEXUS_NODE_CLIENT_ID": "env-id",
                    "YT_NEXUS_NODE_CLIENT_SECRET": "env-secret",
                    "YT_NEXUS_NODE_REFRESH_TOKEN": "env-refresh",
                },
            )
            credentials = manager.get("nexus-node")
            self.assertEqual(credentials.source, "environment")
            self.assertEqual(credentials.client_id, "env-id")
            self.assertEqual(manager.source("nexus-node"), "environment")

    def test_legacy_file_is_last_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "credentials.txt"
            legacy.write_text(LEGACY_TEXT, encoding="utf-8")
            manager = CredentialManager(root / "secrets", legacy, env={})
            credentials = manager.get("natkhat-toons")
            self.assertEqual(credentials.source, "legacy_file")
            self.assertEqual(manager.source("natkhat-toons"), "legacy_file")
