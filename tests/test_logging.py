from __future__ import annotations

import unittest

from uploader.logging import redact


class LoggingTests(unittest.TestCase):
    def test_redacts_common_secret_shapes(self) -> None:
        text = (
            "client_secret=super-secret "
            "refresh_token: refresh-secret "
            "Authorization=Bearer abc.def.ghi "
            "ya29.access-token "
            "1//refresh-token "
            "GOCSPX-client-secret"
        )
        redacted = redact(text)
        for secret in (
            "super-secret",
            "refresh-secret",
            "abc.def.ghi",
            "ya29.access-token",
            "1//refresh-token",
            "GOCSPX-client-secret",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("<redacted>", redacted)
