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


class ConsentBootstrapTests(unittest.TestCase):
    """`consent` creates the first refresh token, so it cannot require one.

    `CredentialManager.get()` demands a complete credential set, which made the documented runbook
    impossible: with only CLIENT_ID and CLIENT_SECRET present it raised "environment credentials
    ... are incomplete: refresh_token", and with nothing set, "no credentials available".
    """

    def test_a_client_pair_in_the_environment_is_enough(self) -> None:
        manager = CredentialManager(
            "/nonexistent-secrets",
            env={"YT_NEXUS_NODE_CLIENT_ID": "cid", "YT_NEXUS_NODE_CLIENT_SECRET": "secret"},
        )
        self.assertEqual(manager.client_pair_for_consent("nexus-node"), ("cid", "secret"))
        # and the strict accessor still refuses, which is what keeps the upload path honest
        with self.assertRaises(CredentialsError):
            manager.client_pair("nexus-node")

    def test_a_half_configured_pair_names_the_missing_value(self) -> None:
        manager = CredentialManager(
            "/nonexistent-secrets", env={"YT_NEXUS_NODE_CLIENT_ID": "cid"}
        )
        with self.assertRaises(CredentialsError) as caught:
            manager.client_pair_for_consent("nexus-node")
        self.assertIn("YT_NEXUS_NODE_CLIENT_SECRET", str(caught.exception))

    def test_nothing_configured_explains_the_two_ways_to_start(self) -> None:
        manager = CredentialManager("/nonexistent-secrets", env={})
        with self.assertRaises(CredentialsError) as caught:
            manager.client_pair_for_consent("nexus-node")
        message = str(caught.exception)
        self.assertIn("YT_NEXUS_NODE_CLIENT_ID", message)
        self.assertIn("--client-json", message)

    def test_a_stored_secret_file_supplies_the_pair_for_re_consent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(temporary)
            store.save("nexus-node", "cid-stored", "secret-stored", "refresh",
                       scopes=["s"], channel_id="UCx9O8VivWkiEylDjs5_Zzag",
                       channel_title="Nexus Node", handle="@nexusnode012", force=False)
            manager = CredentialManager(temporary, env={})
            self.assertEqual(
                manager.client_pair_for_consent("nexus-node"),
                ("cid-stored", "secret-stored"),
            )

    def test_the_environment_pair_wins_over_the_stored_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SecretStore(temporary)
            store.save("nexus-node", "cid-stored", "secret-stored", "refresh",
                       scopes=["s"], channel_id="UCx9O8VivWkiEylDjs5_Zzag",
                       channel_title="Nexus Node", handle="@nexusnode012", force=False)
            manager = CredentialManager(
                temporary,
                env={"YT_NEXUS_NODE_CLIENT_ID": "cid-env",
                     "YT_NEXUS_NODE_CLIENT_SECRET": "secret-env"},
            )
            self.assertEqual(
                manager.client_pair_for_consent("nexus-node"), ("cid-env", "secret-env")
            )

