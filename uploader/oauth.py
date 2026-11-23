from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .config import ChannelConfig
from .credentials import SecretStore
from .errors import OAuthError, ScopeError
from .http import HttpClient

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
SCOPES = (UPLOAD_SCOPE, READONLY_SCOPE)
ALLOWED_SCOPES = frozenset(SCOPES)


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scope: str
    token_type: str

    def __repr__(self) -> str:
        return (
            "TokenResponse(access_token=<redacted>, "
            "refresh_token=<redacted>, "
            f"expires_in={self.expires_in!r}, scope={self.scope!r}, "
            f"token_type={self.token_type!r})"
        )

    def scopes(self) -> tuple[str, ...]:
        return tuple(part for part in self.scope.split() if part)


CLIENT_JSON_KINDS = ("installed", "web")


def load_client_json(path: Any) -> tuple[str, str]:
    """Read a downloaded Google OAuth client JSON and return ``(client_id, client_secret)``.

    Only a Desktop ("installed") client can drive this flow: the redirect is
    ``http://127.0.0.1:<port>/oauth2callback`` and the port is chosen at runtime, so it cannot be
    pre-registered - which is precisely what a Web application client requires. Refusing a Web
    client here is friendlier than letting Google return ``redirect_uri_mismatch`` after the user
    has already picked an account.

    Neither value is ever printed or included in an exception message.
    """

    import json
    from pathlib import Path as _Path

    file_path = _Path(path)
    if not file_path.is_file():
        raise OAuthError(f"OAuth client JSON not found: {file_path}")
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthError("OAuth client JSON could not be read as JSON") from exc
    if not isinstance(payload, dict):
        raise OAuthError("OAuth client JSON must be a JSON object")
    kinds = [kind for kind in CLIENT_JSON_KINDS if kind in payload]
    if not kinds:
        raise OAuthError(
            "OAuth client JSON has neither an 'installed' nor a 'web' section; "
            "download it from the Google Cloud console with 'Download JSON'"
        )
    kind = kinds[0]
    if kind != "installed":
        raise OAuthError(
            "this is a Web application OAuth client; the uploader completes the flow on a "
            "loopback redirect whose port is chosen at runtime, which a Web client cannot "
            "pre-register. Use the Desktop application client"
        )
    section = payload.get("installed")
    if not isinstance(section, dict):
        raise OAuthError("OAuth client JSON 'installed' section is malformed")
    client_id = str(section.get("client_id") or "").strip()
    client_secret = str(section.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise OAuthError(
            "OAuth client JSON is missing client_id or client_secret; the Desktop client type "
            "always includes both"
        )
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise OAuthError("OAuth client JSON client_id is not a Google client ID")
    return client_id, client_secret


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class OAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        http: HttpClient | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise OAuthError("OAuth client credentials are incomplete")
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http or HttpClient()

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        payload = urllib.parse.urlencode(data).encode("ascii")
        response = self.http.request_json(
            "POST",
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            timeout=60,
        )
        if not isinstance(response, dict):
            raise OAuthError("token endpoint returned an invalid response")
        return response

    def _token_from_payload(
        self, payload: dict[str, Any], require_refresh_token: bool
    ) -> TokenResponse:
        # The token endpoint reports failures as a 200 with an `error` body. Without this the caller
        # saw "token endpoint did not return an access token" for a revoked refresh token, which
        # names neither the cause nor the remedy. Only the error code and description are carried -
        # they are Google's text, never the request - so nothing secret reaches a log.
        error = payload.get("error")
        if error:
            description = str(payload.get("error_description") or "").strip()
            raise OAuthError(
                f"token endpoint refused the request: {error}"
                + (f" ({description})" if description else "")
                + (
                    "; a revoked or expired refresh token needs a new consent run"
                    if str(error) in ("invalid_grant", "invalid_client")
                    else ""
                )
            )
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        if not access_token:
            raise OAuthError("token endpoint did not return an access token")
        if require_refresh_token and not refresh_token:
            raise OAuthError("token endpoint did not return a refresh token")
        try:
            expires_in = int(payload["expires_in"]) if payload.get("expires_in") else None
        except (TypeError, ValueError):
            expires_in = None
        return TokenResponse(
            access_token=str(access_token),
            refresh_token=str(refresh_token) if refresh_token else None,
            expires_in=expires_in,
            scope=str(payload.get("scope") or ""),
            token_type=str(payload.get("token_type") or "Bearer"),
        )

    def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> TokenResponse:
        payload = self._post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        )
        token = self._token_from_payload(payload, require_refresh_token=True)
        self.validate_scopes(token.scope)
        return token

    def refresh(self, refresh_token: str) -> TokenResponse:
        payload = self._post_token(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        token = self._token_from_payload(payload, require_refresh_token=False)
        self.validate_scopes(token.scope)
        return token

    def build_consent_url(
        self,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        *,
        scopes: tuple[str, ...] = SCOPES,
    ) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "false",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return AUTHORIZATION_URL + "?" + urllib.parse.urlencode(params)

    @staticmethod
    def validate_scopes(scope: str) -> tuple[str, ...]:
        provided = {part for part in scope.split() if part}
        if UPLOAD_SCOPE not in provided:
            raise ScopeError("token is missing the youtube.upload scope")
        if READONLY_SCOPE not in provided:
            raise ScopeError(
                "token is missing youtube.readonly; "
                "re-consent is required before identity verification"
            )
        extra = provided - ALLOWED_SCOPES
        if extra:
            raise ScopeError(
                "token has unexpected OAuth scopes: "
                + " ".join(sorted(extra))
                + "; re-consent with only the approved upload and readonly scopes"
            )
        return tuple(sorted(provided))


class OAuthCallbackServer:
    def __init__(self) -> None:
        self.result: dict[str, str] | None = None
        self._event = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/oauth2callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = urllib.parse.parse_qs(parsed.query)
                outer.result = {
                    key: values[0] if values else ""
                    for key, values in query.items()
                }
                body = (
                    "<html><body><h1>Authorization received</h1>"
                    "<p>You can close this window and return to the terminal.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer._event.set()
                threading.Thread(target=outer.server.shutdown, daemon=True).start()

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.handler = Handler
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.server.server_address[1])
        self.redirect_uri = f"http://127.0.0.1:{self.port}/oauth2callback"
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self._started = True

    def wait(self, timeout: float) -> dict[str, str] | None:
        if not self._event.wait(timeout):
            return None
        return self.result

    def close(self) -> None:
        if self._started:
            self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._started = False


def run_consent(
    channel: ChannelConfig,
    client_id: str,
    client_secret: str,
    store: SecretStore,
    *,
    open_browser: bool = True,
    timeout: float = 300.0,
    force: bool = False,
) -> dict[str, Any]:
    if store.exists(channel.slug) and not force:
        raise OAuthError(
            f"credentials already exist for {channel.slug}; pass --force to replace"
        )
    client = OAuthClient(client_id, client_secret)
    verifier = generate_code_verifier()
    challenge = code_challenge_for(verifier)
    state = secrets.token_urlsafe(32)
    server = OAuthCallbackServer()
    try:
        server.start()
        url = client.build_consent_url(server.redirect_uri, state, challenge)
        print(f"Channel: {channel.display_name} ({channel.slug})")
        print(f"Expected channel ID: {channel.expected_channel_id}")
        print("Open this URL and choose that channel's Google account:")
        print(url)
        print("Waiting for the browser callback...", flush=True)
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                print("Could not open a browser automatically; open the URL above.")
        result = server.wait(timeout)
        if result is None:
            raise OAuthError("timed out waiting for OAuth callback")
        if result.get("error"):
            raise OAuthError(
                f"OAuth authorization failed: {result.get('error')} "
                f"{result.get('error_description', '')}".strip()
            )
        if result.get("state") != state:
            raise OAuthError("OAuth state mismatch; aborting")
        code = result.get("code")
        if not code:
            raise OAuthError("OAuth callback did not include an authorization code")
        token = client.exchange_code(code, server.redirect_uri, verifier)
        if not token.refresh_token:
            raise OAuthError("OAuth response did not include a refresh token")
        from .identity import verify_access_token

        evidence = verify_access_token(token.access_token, channel)
        store.save(
            channel.slug,
            client_id,
            client_secret,
            token.refresh_token,
            scopes=token.scopes(),
            channel_id=evidence["token_channel_id"],
            channel_title=evidence["token_channel_title"],
            handle=channel.handle,
            force=force,
        )
        return {
            "channel_slug": channel.slug,
            "display_name": channel.display_name,
            "redirect_uri": server.redirect_uri,
            "scopes": list(token.scopes()),
            "evidence": evidence,
        }
    finally:
        server.close()
