from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import CredentialsError

LEGACY_KEYS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def normalize_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def map_legacy_label(label: str) -> str | None:
    lowered = label.strip().lower()
    if "nexus" in lowered:
        return "nexus-node"
    if "academic" in lowered:
        return "academic-biohacker"
    if "natkhat" in lowered or "kids" in lowered:
        return "natkhat-toons"
    return None


@dataclass(frozen=True)
class ChannelCredentials:
    channel_slug: str
    client_id: str
    client_secret: str
    refresh_token: str
    source: str
    scopes: tuple[str, ...] = ()
    channel_id: str | None = None
    channel_title: str | None = None
    handle: str | None = None
    obtained_at: str | None = None

    def __repr__(self) -> str:
        return (
            f"ChannelCredentials(channel_slug={self.channel_slug!r}, "
            f"source={self.source!r}, client_id=<redacted>, "
            f"client_secret=<redacted>, refresh_token=<redacted>)"
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "channel_slug": self.channel_slug,
            "source": self.source,
            "scopes": list(self.scopes),
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "handle": self.handle,
            "obtained_at": self.obtained_at,
        }


def parse_legacy_credentials(path: Path | str) -> dict[str, ChannelCredentials]:
    file_path = Path(path)
    if not file_path.is_file():
        raise CredentialsError(f"legacy credential file not found: {file_path}")
    try:
        lines = file_path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise CredentialsError(f"cannot read legacy credential file: {exc}") from exc

    pending_label: str | None = None
    current: dict[str, Any] | None = None
    raw_sets: list[dict[str, Any]] = []

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*[:=]\s*(.*)$", line)
        if not match:
            pending_label = line
            continue
        key, value = match.group(1), match.group(2)
        if key == "YT_CLIENT_ID":
            if current is not None:
                raw_sets.append(current)
            current = {
                "label": pending_label,
                "line": line_number,
                "YT_CLIENT_ID": value,
            }
            pending_label = None
        elif current is not None and key in LEGACY_KEYS:
            current[key] = value
    if current is not None:
        raw_sets.append(current)

    if len(raw_sets) != 3:
        raise CredentialsError(
            f"expected exactly 3 credential sets in legacy file, found {len(raw_sets)}"
        )

    parsed: dict[str, ChannelCredentials] = {}
    for item in raw_sets:
        label = item.get("label")
        if not label:
            raise CredentialsError(
                f"credential set at line {item.get('line')} has no channel label"
            )
        slug = map_legacy_label(str(label))
        if not slug:
            raise CredentialsError(
                f"credential label at line {item.get('line')} cannot be mapped: {label}"
            )
        missing = [key for key in LEGACY_KEYS if not item.get(key)]
        if missing:
            raise CredentialsError(
                f"credential set for {slug} is missing fields: {', '.join(missing)}"
            )
        if slug in parsed:
            raise CredentialsError(f"duplicate legacy credential set for {slug}")
        parsed[slug] = ChannelCredentials(
            channel_slug=slug,
            client_id=str(item["YT_CLIENT_ID"]),
            client_secret=str(item["YT_CLIENT_SECRET"]),
            refresh_token=str(item["YT_REFRESH_TOKEN"]),
            source="legacy_file",
        )
    return parsed


class SecretStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path_for(self, slug: str) -> Path:
        if not SLUG_RE.match(slug):
            raise CredentialsError("invalid channel slug for secret storage")
        return self.root / f"{slug}.json"

    def exists(self, slug: str) -> bool:
        return self.path_for(slug).is_file()

    def load(self, slug: str) -> ChannelCredentials:
        path = self.path_for(slug)
        if not path.is_file():
            raise CredentialsError(f"no stored credentials for channel {slug}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CredentialsError(f"cannot read credentials for channel {slug}") from exc
        required = ("client_id", "client_secret", "refresh_token")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise CredentialsError(
                f"stored credentials for {slug} are missing fields: {', '.join(missing)}"
            )
        scopes = data.get("scopes", [])
        if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
            raise CredentialsError(f"stored scopes for {slug} are invalid")
        return ChannelCredentials(
            channel_slug=slug,
            client_id=str(data["client_id"]),
            client_secret=str(data["client_secret"]),
            refresh_token=str(data["refresh_token"]),
            source="secret_file",
            scopes=tuple(scopes),
            channel_id=data.get("channel_id"),
            channel_title=data.get("channel_title"),
            handle=data.get("handle"),
            obtained_at=data.get("obtained_at"),
        )

    def save(
        self,
        slug: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        scopes: tuple[str, ...],
        channel_id: str,
        channel_title: str,
        handle: str,
        force: bool = False,
    ) -> Path:
        path = self.path_for(slug)
        if path.exists() and not force:
            raise CredentialsError(
                f"credentials already exist for channel {slug}; refusing to overwrite"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "channel_slug": slug,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "scopes": list(scopes),
            "channel_id": channel_id,
            "channel_title": channel_title,
            "handle": handle,
            "obtained_at": datetime.now(timezone.utc).isoformat(),
        }
        fd, temporary = tempfile.mkstemp(
            prefix=f".{slug}.", suffix=".tmp", dir=str(self.root)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle_file:
                json.dump(payload, handle_file, ensure_ascii=False, indent=2)
                handle_file.flush()
                os.fsync(handle_file.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return path


class CredentialManager:
    def __init__(
        self,
        secrets_root: Path | str,
        legacy_path: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.secret_store = SecretStore(secrets_root)
        self.legacy_path = Path(legacy_path) if legacy_path else None
        self.env = env if env is not None else os.environ
        self._legacy_cache: dict[str, ChannelCredentials] | None = None

    def _env_credentials(self, slug: str) -> ChannelCredentials | None:
        prefix = "YT_" + slug.upper().replace("-", "_") + "_"
        values = {
            "client_id": self.env.get(prefix + "CLIENT_ID"),
            "client_secret": self.env.get(prefix + "CLIENT_SECRET"),
            "refresh_token": self.env.get(prefix + "REFRESH_TOKEN"),
        }
        if not any(values.values()):
            return None
        missing = [key for key, value in values.items() if not value]
        if missing:
            raise CredentialsError(
                f"environment credentials for {slug} are incomplete: {', '.join(missing)}"
            )
        return ChannelCredentials(
            channel_slug=slug,
            client_id=str(values["client_id"]),
            client_secret=str(values["client_secret"]),
            refresh_token=str(values["refresh_token"]),
            source="environment",
        )

    def _legacy_credentials(self, slug: str) -> ChannelCredentials | None:
        if self._legacy_cache is None:
            if self.legacy_path is None:
                return None
            self._legacy_cache = parse_legacy_credentials(self.legacy_path)
        return self._legacy_cache.get(slug)

    def get(self, slug: str) -> ChannelCredentials:
        env_creds = self._env_credentials(slug)
        if env_creds:
            return env_creds
        if self.secret_store.exists(slug):
            return self.secret_store.load(slug)
        legacy = self._legacy_credentials(slug)
        if legacy:
            return legacy
        raise CredentialsError(f"no credentials available for channel {slug}")

    def source(self, slug: str) -> str:
        if self._env_credentials(slug):
            return "environment"
        if self.secret_store.exists(slug):
            return "secret_file"
        if self._legacy_credentials(slug):
            return "legacy_file"
        return "missing"

    def client_pair(self, slug: str) -> tuple[str, str]:
        credentials = self.get(slug)
        return credentials.client_id, credentials.client_secret

    def client_pair_for_consent(self, slug: str) -> tuple[str, str]:
        """The client pair, for the one operation that runs *before* a refresh token exists.

        ``consent`` is what creates the first refresh token, so it cannot be gated on one being
        present: ``get()`` requires a complete credential set and this used to make the first run
        of ``consent`` impossible - "environment credentials ... are incomplete: refresh_token"
        with only CLIENT_ID and CLIENT_SECRET set, and "no credentials available" with nothing.

        The pair is read from the environment first (both values together), then from a stored
        secret file, then from the legacy file. A refresh token is never consulted, and nothing
        here is trusted for any purpose except starting a consent flow: the token that comes back
        is still verified against the exact channel ID before it is stored.
        """

        prefix = "YT_" + slug.upper().replace("-", "_") + "_"
        client_id = self.env.get(prefix + "CLIENT_ID")
        client_secret = self.env.get(prefix + "CLIENT_SECRET")
        if client_id and client_secret:
            return client_id, client_secret
        partial = [name for name, value in (("CLIENT_ID", client_id), ("CLIENT_SECRET", client_secret)) if value]
        if partial:
            missing = "CLIENT_SECRET" if partial == ["CLIENT_ID"] else "CLIENT_ID"
            raise CredentialsError(
                f"{prefix}{missing} is missing; set both {prefix}CLIENT_ID and "
                f"{prefix}CLIENT_SECRET (or pass --client-json) to run consent for {slug}"
            )
        if self.secret_store.exists(slug):
            stored = self.secret_store.load(slug)
            return stored.client_id, stored.client_secret
        legacy = self._legacy_credentials(slug)
        if legacy:
            return legacy.client_id, legacy.client_secret
        raise CredentialsError(
            f"no OAuth client configured for {slug}; set {prefix}CLIENT_ID and "
            f"{prefix}CLIENT_SECRET, or pass --client-json with the downloaded Desktop client "
            "JSON, to run consent"
        )

    def public_sources(self, slugs: list[str]) -> dict[str, str]:
        return {slug: self.source(slug) for slug in slugs}
