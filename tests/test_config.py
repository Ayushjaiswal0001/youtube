from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT
from uploader.config import load_channel_configs
from uploader.errors import ConfigError


class ChannelConfigTests(unittest.TestCase):
    def test_loads_the_three_expected_channels(self) -> None:
        configs = load_channel_configs(REPO_ROOT / "channels")
        self.assertEqual(
            set(configs),
            {"nexus-node", "academic-biohacker", "natkhat-toons"},
        )
        self.assertEqual(configs["nexus-node"].expected_channel_id, "UCx9O8VivWkiEylDjs5_Zzag")
        self.assertEqual(
            configs["academic-biohacker"].expected_channel_id,
            "UCr8jSmLa_o2BwNh8HuyZHAQ",
        )
        self.assertEqual(
            configs["natkhat-toons"].expected_channel_id,
            "UC4OCY0qDwQqFnSCZw12sKxA",
        )
        self.assertTrue(configs["natkhat-toons"].requires_made_for_kids_confirmation)
        self.assertTrue(configs["natkhat-toons"].force_made_for_kids)
        self.assertTrue(configs["natkhat-toons"].defaults.made_for_kids)
        self.assertFalse(configs["nexus-node"].allow_public_upload)

    def test_rejects_duplicate_expected_channel_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = {
                "slug": "one",
                "display_name": "One",
                "handle": "@one",
                "expected_channel_id": "UCx9O8VivWkiEylDjs5_Zzag",
            }
            (directory / "one.json").write_text(json.dumps(payload), encoding="utf-8")
            payload["slug"] = "two"
            payload["handle"] = "@two"
            (directory / "two.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_channel_configs(directory)

    def test_rejects_invalid_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = {
                "slug": "one",
                "display_name": "One",
                "handle": "not-a-handle",
                "expected_channel_id": "UCx9O8VivWkiEylDjs5_Zzag",
            }
            (directory / "one.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_channel_configs(directory)
