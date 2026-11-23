from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from .config import load_channel_configs
from .credentials import CredentialManager
from .errors import SafetyError, UploaderError
from .ledger import Ledger
from .logging import redact, setup_logging
from .metadata import load_metadata_file
from .oauth import run_consent
from .router import ChannelRouter

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CHANNEL_DIR = PACKAGE_DIR.parent / "channels"
DEFAULT_SECRETS_ROOT = Path.home() / ".faceless-shorts" / "secrets" / "youtube"
DEFAULT_STATE_ROOT = Path.home() / ".faceless-shorts" / "state" / "youtube"
DEFAULT_LOG_ROOT = Path.home() / ".faceless-shorts" / "logs" / "youtube"


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--channels-dir", type=Path, default=DEFAULT_CHANNEL_DIR)
    parser.add_argument("--legacy-credentials", type=Path, default=None)
    parser.add_argument("--secrets-root", type=Path, default=DEFAULT_SECRETS_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--log-root", type=Path, default=DEFAULT_LOG_ROOT)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    parser.add_argument("--json", action="store_true")
    return parser


def _add_upload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channel", required=True)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--tags", default=None, help="comma-separated tags")
    parser.add_argument("--category", default=None)
    parser.add_argument("--privacy", choices=("private", "unlisted", "public"), default=None)
    kids = parser.add_mutually_exclusive_group()
    kids.add_argument("--made-for-kids", dest="made_for_kids", action="store_true")
    kids.add_argument("--not-made-for-kids", dest="made_for_kids", action="store_false")
    parser.set_defaults(made_for_kids=None)
    parser.add_argument(
        "--notify-subscribers", dest="notify_subscribers", action="store_true", default=None
    )
    parser.add_argument("--playlist", default=None)
    parser.add_argument("--allow-public", action="store_true")
    parser.add_argument("--skip-media-check", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    common = _common_parser()
    parser = argparse.ArgumentParser(
        prog="python -m uploader.cli",
        description="Three-channel YouTube uploader with strict identity checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sources = subparsers.add_parser("sources", parents=[common])
    sources.set_defaults(func=cmd_sources)

    scope_check = subparsers.add_parser("scope-check", parents=[common])
    scope_check.add_argument("--channel", default="all")
    scope_check.set_defaults(func=cmd_scope_check)

    verify = subparsers.add_parser("verify", parents=[common])
    verify.add_argument("--channel", default="all")
    verify.set_defaults(func=cmd_verify)

    consent = subparsers.add_parser("consent", parents=[common])
    consent.add_argument("--channel", required=True)
    consent.add_argument("--force", action="store_true")
    consent.add_argument("--no-open", action="store_true")
    consent.add_argument(
        "--client-json",
        help="path to the downloaded Desktop OAuth client JSON; avoids putting the client "
             "secret in the environment",
    )
    consent.add_argument("--timeout", type=float, default=300.0)
    consent.set_defaults(func=cmd_consent)

    dry_run = subparsers.add_parser("dry-run", parents=[common])
    _add_upload_arguments(dry_run)
    dry_run.set_defaults(func=cmd_dry_run)

    upload = subparsers.add_parser("upload", parents=[common])
    _add_upload_arguments(upload)
    upload.add_argument("--execute", action="store_true")
    upload.add_argument("--confirm-channel", default=None)
    upload.set_defaults(func=cmd_upload)

    status = subparsers.add_parser("status", parents=[common])
    status.add_argument("--channel", required=True)
    status.add_argument("--limit", type=int, default=10)
    status.set_defaults(func=cmd_status)

    history = subparsers.add_parser("history", parents=[common])
    history.add_argument("--channel", required=True)
    history.add_argument("--limit", type=int, default=50)
    history.set_defaults(func=cmd_history)

    return parser


def _level(value: str) -> int:
    return getattr(logging, value.upper())


def _context(args: argparse.Namespace) -> tuple[Any, ChannelRouter]:
    configs = load_channel_configs(args.channels_dir)
    credentials = CredentialManager(args.secrets_root, args.legacy_credentials)
    router = ChannelRouter(configs, credentials, args.state_root)
    return configs, router


def _selected(configs: Any, value: str) -> list[str]:
    if value == "all":
        return list(configs)
    if value not in configs:
        raise UploaderError(f"unknown channel: {value}")
    return [value]


def _setup(args: argparse.Namespace, channel: str) -> None:
    setup_logging(
        args.log_root,
        channel,
        level=_level(args.log_level),
        console=not args.json,
    )


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _print_text(lines: list[str]) -> None:
    for line in lines:
        print(line)


def _build_data(args: argparse.Namespace) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if args.metadata:
        data.update(load_metadata_file(args.metadata))
    if args.title is not None:
        data["title"] = args.title
    if args.description is not None:
        data["description"] = args.description
    if args.tags is not None:
        data["tags"] = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
    if args.category is not None:
        data["categoryId"] = args.category
    if args.privacy is not None:
        data["privacyStatus"] = args.privacy
    if args.made_for_kids is not None:
        data["madeForKids"] = args.made_for_kids
    if args.notify_subscribers is not None:
        data["notifySubscribers"] = args.notify_subscribers
    if args.playlist is not None:
        data["playlistId"] = args.playlist
    return data


def _run_batch(
    args: argparse.Namespace,
    operation: Callable[[str], dict[str, Any]],
) -> int:
    configs, _ = _context(args)
    slugs = _selected(configs, args.channel)
    _setup(args, args.channel if len(slugs) == 1 else "all")
    results: list[dict[str, Any]] = []
    failed = False
    for slug in slugs:
        try:
            result = operation(slug)
            result.setdefault("ok", True)
            results.append(result)
        except UploaderError as exc:
            failed = True
            results.append(
                {
                    "channel_slug": slug,
                    "ok": False,
                    "error": redact(str(exc)),
                }
            )
    if args.json:
        _print_json(results)
    else:
        for result in results:
            if not result.get("ok"):
                print(f"{result['channel_slug']}: ERROR {result['error']}")
                continue
            identity = result.get("identity", {})
            print(
                f"{result['channel_slug']}: OK "
                f"id={identity.get('token_channel_id')} "
                f"title={identity.get('token_channel_title')!r}"
            )
    return 1 if failed else 0


def cmd_sources(args: argparse.Namespace) -> int:
    configs, router = _context(args)
    _setup(args, "all")
    results = [
        {
            "channel_slug": config.slug,
            "display_name": config.display_name,
            "handle": config.handle,
            "expected_channel_id": config.expected_channel_id,
            "credential_source": router.source_for(config.slug),
        }
        for config in configs.values()
    ]
    if args.json:
        _print_json(results)
    else:
        for result in results:
            print(
                f"{result['channel_slug']}: {result['credential_source']} "
                f"({result['expected_channel_id']}, {result['handle']})"
            )
    return 0


def cmd_scope_check(args: argparse.Namespace) -> int:
    def operation(slug: str) -> dict[str, Any]:
        scopes = router.refresh_scopes(slug)
        return {"channel_slug": slug, "scopes": scopes}

    configs, router = _context(args)
    return _run_batch(args, operation)


def cmd_verify(args: argparse.Namespace) -> int:
    configs, router = _context(args)
    return _run_batch(args, router.verify_channel)


def cmd_consent(args: argparse.Namespace) -> int:
    configs, router = _context(args)
    if args.channel not in configs:
        raise UploaderError(f"unknown channel: {args.channel}")
    _setup(args, args.channel)
    if args.client_json:
        from .oauth import load_client_json

        client_id, client_secret = load_client_json(args.client_json)
    else:
        client_id, client_secret = router.credentials.client_pair_for_consent(args.channel)
    result = run_consent(
        configs[args.channel],
        client_id,
        client_secret,
        router.credentials.secret_store,
        open_browser=not args.no_open,
        timeout=args.timeout,
        force=args.force,
    )
    result["credential_path"] = str(
        router.credentials.secret_store.path_for(args.channel)
    )
    if args.json:
        _print_json(result)
    else:
        print(
            f"Consent complete for {result['channel_slug']}: "
            f"id={result['evidence']['token_channel_id']}"
        )
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    configs, router = _context(args)
    if args.channel not in configs:
        raise UploaderError(f"unknown channel: {args.channel}")
    _setup(args, args.channel)
    result = router.dry_run(
        args.channel,
        args.video,
        _build_data(args),
        allow_public=args.allow_public,
        validate_media=not args.skip_media_check,
    )
    if args.json:
        _print_json(result)
    else:
        print(
            f"DRY RUN OK: {result['channel_slug']} "
            f"{result['identity']['token_channel_id']} "
            f"video={result['video_sha256'][:12]}"
        )
        print("No upload was performed.")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    configs, router = _context(args)
    if args.channel not in configs:
        raise UploaderError(f"unknown channel: {args.channel}")
    if args.execute and args.confirm_channel != args.channel:
        raise SafetyError(
            "--execute requires --confirm-channel with the exact channel slug"
        )
    _setup(args, args.channel)
    result = router.upload(
        args.channel,
        args.video,
        _build_data(args),
        execute=args.execute,
        confirm_channel=args.confirm_channel,
        allow_public=args.allow_public,
        validate_media=not args.skip_media_check,
    )
    if args.json:
        _print_json(result)
    else:
        print(f"{result['status']}: {result['channel_slug']}")
        print(f"upload_performed={result['upload_performed']}")
        if result.get("video_url"):
            print(result["video_url"])
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    configs, _ = _context(args)
    if args.channel not in configs:
        raise UploaderError(f"unknown channel: {args.channel}")
    _setup(args, args.channel)
    ledger = Ledger(args.state_root, args.channel)
    entries = list(reversed(ledger.entries()))[: max(0, args.limit)]
    result = {
        "channel_slug": args.channel,
        "summary": ledger.summary(),
        "entries": [entry.to_dict() for entry in entries],
    }
    if args.json:
        _print_json(result)
    else:
        print(f"{args.channel}: {result['summary']}")
        for entry in entries:
            print(
                f"{entry['updated_at']} {entry['status']} "
                f"{entry['job_id']} {entry['title']}"
            )
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    configs, _ = _context(args)
    if args.channel not in configs:
        raise UploaderError(f"unknown channel: {args.channel}")
    _setup(args, args.channel)
    ledger = Ledger(args.state_root, args.channel)
    entries = list(reversed(ledger.history()))[: max(0, args.limit)]
    result = {
        "channel_slug": args.channel,
        "uploads": [entry.to_dict() for entry in entries],
    }
    if args.json:
        _print_json(result)
    else:
        for entry in entries:
            print(f"{entry.updated_at} {entry.video_id} {entry.video_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except UploaderError as exc:
        print(f"error: {redact(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
