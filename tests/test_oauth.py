from __future__ import annotations

import json
import unittest
import urllib.parse

from uploader.errors import ScopeError
from uploader.oauth import (
    READONLY_SCOPE,
    UPLOAD_SCOPE,
    OAuthClient,
    TokenResponse,
    code_challenge_for,
    generate_code_verifier,
)


class StubTokenHttp:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def request_json(self, method, url, *, headers=None, data=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data})
        return self.payload


class OAuthTests(unittest.TestCase):
    def test_pkce_challenge_is_deterministic(self) -> None:
        verifier = "fixed-verifier"
        self.assertEqual(code_challenge_for(verifier), code_challenge_for(verifier))
        self.assertNotEqual(code_challenge_for(verifier), verifier)
        self.assertGreaterEqual(len(generate_code_verifier()), 40)

    def test_consent_url_has_required_parameters(self) -> None:
        client = OAuthClient("client-id", "client-secret")
        url = client.build_consent_url(
            "http://127.0.0.1:1234/oauth2callback",
            "state-value",
            "challenge-value",
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent select_account"])
        self.assertEqual(query["include_granted_scopes"], ["false"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(set(query["scope"][0].split()), {UPLOAD_SCOPE, READONLY_SCOPE})
        self.assertNotIn("client-secret", url)

    def test_scope_validation_requires_exact_approved_scopes(self) -> None:
        with self.assertRaises(ScopeError):
            OAuthClient.validate_scopes(UPLOAD_SCOPE)
        with self.assertRaises(ScopeError):
            OAuthClient.validate_scopes(
                f"{UPLOAD_SCOPE} "
                "https://www.googleapis.com/auth/youtube "
                "https://www.googleapis.com/auth/drive"
            )
        scopes = OAuthClient.validate_scopes(f"{UPLOAD_SCOPE} {READONLY_SCOPE}")
        self.assertEqual(scopes, tuple(sorted((UPLOAD_SCOPE, READONLY_SCOPE))))

    def test_token_response_repr_redacts_secrets(self) -> None:
        token = TokenResponse(
            access_token="access-secret",
            refresh_token="refresh-secret",
            expires_in=3600,
            scope=f"{UPLOAD_SCOPE} {READONLY_SCOPE}",
            token_type="Bearer",
        )
        self.assertNotIn("access-secret", repr(token))
        self.assertNotIn("refresh-secret", repr(token))

    def test_exchange_code_sends_verifier_and_requires_refresh_token(self) -> None:
        payload = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "scope": f"{UPLOAD_SCOPE} {READONLY_SCOPE}",
            "token_type": "Bearer",
        }
        http = StubTokenHttp(payload)
        client = OAuthClient("client-id", "client-secret", http=http)
        token = client.exchange_code("auth-code", "http://localhost/callback", "verifier")
        self.assertEqual(token.refresh_token, "refresh")
        self.assertIn(b"code_verifier=verifier", http.calls[0]["data"])

    def test_exchange_code_rejects_missing_refresh_token(self) -> None:
        http = StubTokenHttp(
            {
                "access_token": "access",
                "expires_in": 3600,
                "scope": f"{UPLOAD_SCOPE} {READONLY_SCOPE}",
                "token_type": "Bearer",
            }
        )
        client = OAuthClient("client-id", "client-secret", http=http)
        with self.assertRaises(Exception):
            client.exchange_code("auth-code", "http://localhost/callback", "verifier")
