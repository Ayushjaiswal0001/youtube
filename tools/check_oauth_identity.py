"""Report what a channel's refresh token can actually see, without printing it.

The interesting question when one Google account owns several YouTube channels is what
``channels.list(mine=true)`` returns: one channel or three. This answers it with the real API and the
real stored credential, then runs the same ``verify_identity`` the upload path runs, so the verdict
here is the verdict production will reach.

Read-only: it uses the readonly scope, never uploads, and never prints a token, a client secret or a
refresh token. IDs and titles are printed because they are the thing being checked.

Usage:
    python -m tools.check_oauth_identity --channel nexus-node
    python -m tools.check_oauth_identity --channel all --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from uploader.config import load_channel_configs
from uploader.credentials import CredentialManager
from uploader.errors import UploaderError
from uploader.identity import verify_identity
from uploader.router import ChannelRouter


def _summarise(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for item in items:
        snippet = item.get("snippet")
        snippet = snippet if isinstance(snippet, dict) else {}
        out.append({"id": str(item.get("id") or ""), "title": str(snippet.get("title") or "")})
    return out


def inspect_channel(slug: str, router: ChannelRouter) -> dict[str, Any]:
    """Everything the token sees, and whether the exact-channel check passes."""

    channel = router.channel(slug)
    report: dict[str, Any] = {
        "channel_slug": slug,
        "expected_channel_id": channel.expected_channel_id,
        "expected_title": channel.display_name,
        "expected_handle": channel.handle,
        "credential_source": router.credentials.source(slug),
        "authorized": False,
        "mine_count": None,
        "mine": [],
        "handle_lookup": [],
        "verified": False,
        "error": None,
    }
    if report["credential_source"] == "missing":
        report["error"] = (
            "no credentials for this channel; run `python -m uploader.cli consent "
            f"--channel {slug}` first"
        )
        return report
    try:
        api = router.refresh_api(slug)
        mine = api.channels_mine("snippet,contentDetails")
        report["authorized"] = True
        report["mine"] = _summarise(list(mine))
        report["mine_count"] = len(mine)
        report["handle_lookup"] = _summarise(
            list(api.channel_for_handle(channel.handle, "snippet"))
        )
        evidence = verify_identity(api, channel)
        report["verified"] = evidence.verified
        report["token_channel_id"] = evidence.token_channel_id
        report["token_channel_title"] = evidence.token_channel_title
    except UploaderError as exc:
        # A refresh or API failure is a real answer, not a crash: the caller wants to see which
        # channel is not usable and why.
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def render(report: dict[str, Any]) -> str:
    lines = [f"{report['channel_slug']}", f"  expected id   {report['expected_channel_id']}"]
    lines.append(f"  expected name {report['expected_title']!r}  handle {report['expected_handle']!r}")
    lines.append(f"  credentials   {report['credential_source']}")
    if not report["authorized"]:
        lines.append(f"  NOT AUTHORIZED: {report['error']}")
        return "\n".join(lines)
    lines.append(f"  channels.list(mine=true) returned {report['mine_count']}")
    for item in report["mine"]:
        marker = "  <- expected" if item["id"] == report["expected_channel_id"] else ""
        lines.append(f"    {item['id']}  {item['title']!r}{marker}")
    for item in report["handle_lookup"]:
        lines.append(f"  handle {report['expected_handle']} -> {item['id']}  {item['title']!r}")
    if report["verified"]:
        lines.append("  identity      VERIFIED (id, title and handle all match)")
    else:
        lines.append(f"  identity      NOT VERIFIED: {report['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="all", help="channel slug, or 'all'")
    parser.add_argument("--channels-dir", default="channels")
    parser.add_argument("--secrets-root", default=".secrets/youtube")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    configs = load_channel_configs(Path(args.channels_dir))
    slugs = list(configs) if args.channel == "all" else [args.channel]
    unknown = [slug for slug in slugs if slug not in configs]
    if unknown:
        parser.error(f"unknown channel(s): {', '.join(unknown)}")

    router = ChannelRouter(
        configs,
        CredentialManager(args.secrets_root),
        Path(".state/youtube"),
    )
    reports = [inspect_channel(slug, router) for slug in slugs]
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for report in reports:
            print(render(report))
            print()
    return 0 if all(report["verified"] for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
