"""The security checks that protect a public repository.

Three separate promises are tested here:

1. the secret scanner still detects each credential shape it claims to detect, and still stays quiet
   about placeholders, environment lookups and explicitly allowlisted fixtures - a scanner that has
   silently stopped matching is worse than none, because its green check is believed;
2. the run journal cannot publish the machine it ran on (CI uploads it as an artifact);
3. the three channels cannot borrow each other's credentials or publish to each other's channel.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from factory.state import ChannelState, portable_path, _scrub
from tools.secret_scan import RULES, mask, scan_tree
from uploader.config import load_channel_configs
from uploader.credentials import ChannelCredentials, CredentialManager, CredentialsError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake(prefix: str, body: str, length: int = 32) -> str:
    """Build a synthetic token at runtime.

    Written as a concatenation on purpose: this file must not trip the history scan while proving the
    scan works.
    """

    return prefix + (body * (length // len(body) + 1))[:length]


# --------------------------------------------------------------------------- scanner behaviour

def test_every_rule_detects_its_own_shape(tmp_path: Path) -> None:
    samples = {
        "google-oauth-client-secret": _fake("GOCSPX-", "aB3dE"),
        "google-api-key": _fake("AIza", "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q", 35),
        "youtube-refresh-token": _fake("1//0", "gA1b2C3d4E5f6G7h8", 24),
        "youtube-access-token": _fake("ya29.", "a0AfB1c2D3e4F5g6H7i8", 22),
        "github-token": _fake("ghp_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", 36),
        "aws-access-key": "AKIA" + "Q1W2E3R4T5Y6U7I8",
        "slack-token": "xoxb-" + "1234567890-abcdefghij",  # gitleaks:allow
        "private-key": "-----BEGIN RSA PRIVATE KEY-----",  # pragma: allowlist secret - header only
        "connection-string": "postgres://user:sup3rs3cret@db.internal:5432/app",  # pragma: allowlist secret
    }
    assert set(samples) <= {rule.name for rule in RULES}
    for rule_name, value in samples.items():
        path = tmp_path / f"{rule_name}.txt"
        path.write_text(f"value = {value}\n", encoding="utf-8")
        findings = scan_tree(tmp_path)
        tmp_path.joinpath(path.name).unlink()
        assert any(f["rule"] == rule_name for f in findings), f"{rule_name} was not detected"


def test_placeholders_are_not_reported(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text(
        'client_secret = "YOUR_CLIENT_SECRET"\n'
        'refresh_token = "<refresh-token>"\n'
        'api_key = "CHANGEME"\n'
        'password = "xxxxxxxxxxxx"\n',
        encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_environment_lookup_is_not_a_secret(tmp_path: Path) -> None:
    (tmp_path / "cfg.py").write_text(
        'client_secret = os.environ["CLIENT_SECRET"]\n'
        'refresh_token = "${REFRESH_TOKEN}"\n'
        'api_key = os.getenv("API_KEY")\n',
        encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_allowlist_marker_suppresses_a_reviewed_fixture(tmp_path: Path) -> None:
    (tmp_path / "fixture.py").write_text(
        'client_secret = "client-secret"  # pragma: allowlist secret\n', encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_the_same_value_without_the_marker_is_reported(tmp_path: Path) -> None:
    # Built at runtime so the probe string is not itself a literal in this file.
    value = "hidden" + "-value-9"  # pragma: allowlist secret
    (tmp_path / "fixture.py").write_text(
        f'client_secret = "{value}"\n', encoding="utf-8")
    findings = scan_tree(tmp_path)
    assert [f["rule"] for f in findings] == ["keyed-secret-assignment"]


def test_documented_fixture_values_are_allowlisted_by_value() -> None:
    """The four fixture strings are fake and sit in history; the allowlist is by value, not by file."""

    from tools.secret_scan import ALLOWED_VALUES

    assert "client-secret" in ALLOWED_VALUES
    assert all(len(v) < 20 for v in ALLOWED_VALUES)  # no provider issues a secret this short


def test_a_finding_never_carries_the_full_value() -> None:
    full = _fake("GOCSPX-", "s3cr3tV4lue")
    masked = mask(full)
    assert full not in masked
    assert masked.startswith(full[:4])
    assert "chars" in masked


def test_the_repository_itself_is_clean() -> None:
    findings = scan_tree(REPO_ROOT)
    assert findings == [], findings


# --------------------------------------------------------------------------- journal hygiene

def test_portable_path_keeps_project_paths_relative() -> None:
    assert portable_path(r"C:\Users\someone\clone\build\chan\ep\video.mp4") == \
        "build/chan/ep/video.mp4"
    assert portable_path("/home/someone/clone/build/chan/ep.mp4") == "build/chan/ep.mp4"


def test_portable_path_drops_a_path_outside_the_project() -> None:
    assert portable_path(r"D:\private\notes.txt") == "notes.txt"
    assert portable_path("/Users/someone/Desktop/x.png") == "x.png"


def test_journal_entry_cannot_publish_the_machine(tmp_path: Path) -> None:
    state = ChannelState("natkhat-toons", root=tmp_path)
    state.log_run({
        "kind": "render",
        "video_path": r"C:\Users\someone\clone\build\c\e\video.mp4",
        "thumbnail": {"thumbnail_path": r"C:\Users\someone\clone\build\c\e\t.jpg"},
        "title": "ok",
    })
    line = state.runs_path.read_text(encoding="utf-8")
    assert "someone" not in line
    assert "C:\\" not in line
    assert "build/c/e/video.mp4" in line
    assert json.loads(line)["title"] == "ok"


def test_scrub_leaves_ordinary_text_alone() -> None:
    payload = {"title": r"a title with a \ backslash", "duration": 32.1, "done": True}
    assert _scrub(payload) == payload


# --------------------------------------------------------------------------- channel isolation

def test_the_three_channels_have_distinct_identities() -> None:
    configs = load_channel_configs(REPO_ROOT / "channels")
    assert set(configs) == {"nexus-node", "academic-biohacker", "natkhat-toons"}
    ids = {slug: config.expected_channel_id for slug, config in configs.items()}
    assert len(set(ids.values())) == 3, ids
    handles = {slug: config.handle for slug, config in configs.items()}
    assert len(set(handles.values())) == 3, handles


def test_credentials_are_read_from_the_channel_own_prefix(tmp_path: Path) -> None:
    env = {
        "YT_NEXUS_NODE_CLIENT_ID": "id-n", "YT_NEXUS_NODE_CLIENT_SECRET": "s-n",
        "YT_NEXUS_NODE_REFRESH_TOKEN": "r-n",
        "YT_NATKHAT_TOONS_CLIENT_ID": "id-t", "YT_NATKHAT_TOONS_CLIENT_SECRET": "s-t",
        "YT_NATKHAT_TOONS_REFRESH_TOKEN": "r-t",
    }
    manager = CredentialManager(tmp_path, env=env)
    nexus = manager.get("nexus-node")
    natkhat = manager.get("natkhat-toons")
    assert (nexus.client_id, natkhat.client_id) == ("id-n", "id-t")
    assert nexus.refresh_token != natkhat.refresh_token


def test_a_channel_without_credentials_fails_closed(tmp_path: Path) -> None:
    manager = CredentialManager(tmp_path, env={})
    with pytest.raises(CredentialsError) as absent:
        manager.get("academic-biohacker")
    assert "no credentials available" in str(absent.value)

    partial = CredentialManager(tmp_path, env={"YT_NEXUS_NODE_CLIENT_ID": "id-n"})
    with pytest.raises(CredentialsError) as incomplete:
        partial.get("nexus-node")
    assert "incomplete" in str(incomplete.value)
    # The error names the missing key and never the value that was supplied.
    assert "id-n" not in str(incomplete.value)


def test_credentials_never_print_their_secrets() -> None:
    creds = ChannelCredentials(channel_slug="natkhat-toons", client_id="cid",
                               client_secret="shhh-secret", refresh_token="r3fresh",
                               source="environment")
    for rendered in (repr(creds), str(creds), json.dumps(creds.public_dict())):
        assert "shhh-secret" not in rendered
        assert "r3fresh" not in rendered
    assert creds.public_dict()["channel_slug"] == "natkhat-toons"


def test_verification_rejects_a_token_that_belongs_to_another_channel() -> None:
    """A valid token for the wrong channel must abort, not publish to whatever it does own."""

    from uploader.config import load_channel_configs
    from uploader.identity import IdentityError, verify_identity

    configs = load_channel_configs(REPO_ROOT / "channels")
    natkhat = configs["natkhat-toons"]
    other = configs["nexus-node"]

    class WrongChannelApi:
        """A token that works, but answers as the other channel."""

        def channels_mine(self, part: str) -> list[dict]:
            return [{"id": other.expected_channel_id,
                     "snippet": {"title": other.display_name}}]

        def channel_for_handle(self, handle: str, part: str) -> list[dict]:
            return [{"id": natkhat.expected_channel_id,
                     "snippet": {"title": natkhat.display_name}}]

    with pytest.raises(IdentityError) as caught:
        verify_identity(WrongChannelApi(), natkhat)
    assert "mismatch" in str(caught.value)
    assert other.expected_channel_id in str(caught.value)


def test_verification_rejects_more_than_one_channel_on_a_token() -> None:
    from uploader.config import load_channel_configs
    from uploader.identity import IdentityError, verify_identity

    configs = load_channel_configs(REPO_ROOT / "channels")
    target = configs["nexus-node"]

    class SharedTokenApi:
        def channels_mine(self, part: str) -> list[dict]:
            return [{"id": target.expected_channel_id},
                    {"id": configs["academic-biohacker"].expected_channel_id}]

        def channel_for_handle(self, handle: str, part: str) -> list[dict]:
            return []

    with pytest.raises(IdentityError) as caught:
        verify_identity(SharedTokenApi(), target)
    assert "expected exactly 1" in str(caught.value)


def test_gitignore_covers_credential_files() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("ytcredentials", "ytcredetials", ".env", "secrets/"):
        assert pattern in ignored, f".gitignore no longer covers {pattern}"
    assert not (REPO_ROOT / "ytcredentials.txt").exists()
    assert not (REPO_ROOT / "ytcredetials.txt").exists()
