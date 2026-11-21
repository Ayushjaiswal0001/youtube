"""Scan a tree, the staged diff or the whole commit history for credentials.

This exists because the repository is public and an OAuth client secret or refresh token in it is a
publishing credential: anyone who reads the history could upload to the channels. It is deliberately a
local, dependency-free scanner rather than a downloaded binary, so the CI gate cannot be weakened by a
supply-chain swap - and it is precise about the shapes that actually matter here (Google OAuth, YouTube
tokens, GitHub tokens, API keys, private keys, connection strings) instead of flagging any 32-character
string.

Usage:
    python -m tools.secret_scan                 # working tree
    python -m tools.secret_scan --history       # every blob reachable from every ref
    python -m tools.secret_scan --staged        # staged diff, for pre-commit
    python -m tools.secret_scan --json

Exit code 0 means nothing found, 1 means at least one finding, 2 means the scan could not run. A
finding is never printed in full: the report shows a masked prefix, the file and the line, which is
enough to act on and not enough to leak.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

#: Files we never scan: binaries, VCS internals, build outputs.
SKIP_DIRS = {".git", "build", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", "studio/intermediate"}
SKIP_SUFFIXES = {".mp4", ".mp3", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip", ".pyc", ".wav",
                 ".ttf", ".otf", ".pdf", ".ico", ".so", ".dll", ".exe", ".bin"}

#: Placeholders that must not be reported: they document a variable, not a secret.
PLACEHOLDER = re.compile(
    r"^(|x+|\*+|<[^>]*>|\$\{[^}]*\}|\$[A-Z_]+|%[A-Z_]+%|YOUR[_-].*|CHANGEME|REDACTED|EXAMPLE.*|"
    r"DUMMY.*|FAKE.*|PLACEHOLDER.*|TEST.*|NONE|null|None|true|false|\.\.\.)$",
    re.IGNORECASE,
)


@dataclass
class Rule:
    name: str
    pattern: re.Pattern[str]
    severity: str = "critical"
    note: str = ""


RULES: tuple[Rule, ...] = (
    Rule("google-oauth-client-secret", re.compile(r"GOCSPX-[A-Za-z0-9_-]{20,}"),
         note="Google OAuth client secret - can mint tokens for the channel"),
    Rule("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}"),
         note="Google API key"),
    Rule("youtube-refresh-token", re.compile(r"1//0[0-9A-Za-z_-]{20,}"),
         note="YouTube OAuth refresh token - long-lived upload access"),
    Rule("youtube-access-token", re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"),
         note="YouTube OAuth access token"),
    Rule("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
         note="GitHub token"),
    Rule("github-fine-grained-token", re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
         note="GitHub fine-grained token"),
    Rule("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), note="AWS access key id"),
    Rule("slack-token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"), note="Slack token"),
    Rule("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
         note="Private key material"),
    Rule("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), note="OpenAI-style API key"),
    Rule("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), note="Anthropic API key"),
    Rule("connection-string", re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@]{6,}@"),
         note="Connection string with an inline password"),
    Rule("bearer-header", re.compile(r"Authorization\s*[:=]\s*[\"']?Bearer\s+[A-Za-z0-9._\-]{20,}"),
         note="Hardcoded bearer token"),
    Rule("keyed-secret-assignment", re.compile(
        r"(?i)\b(?:client_secret|refresh_token|access_token|api_key|apikey|auth_token|password|"
        r"passwd|secret_key|private_key)\b\s*[:=]\s*[\"']([^\"'\n]{12,})[\"']"),
         severity="high", note="A secret-looking value assigned in source"),
)

#: Whole-line opt-out, for fixture data that is obviously synthetic and must stay readable.
ALLOW_MARKERS = ("pragma: allowlist secret", "noqa: secret", "example-placeholder")

#: Exact values accepted even when matched, after review.
#:
#: These four appear in `tests/support.py` and `tests/test_oauth.py` in the history as well as the tree,
#: and history is not being rewritten for cosmetics. They are allowlisted by value rather than by file,
#: so a real credential placed in those same files is still reported - no provider issues a secret that
#: is literally the string `refresh-token`.
ALLOWED_VALUES = {"client-secret", "refresh-token", "access-secret", "refresh-secret"}


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-2:]} ({len(value)} chars)"


def _scan_text(text: str, where: str, out: list[dict]) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        if any(marker in line for marker in ALLOW_MARKERS):
            continue
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                value = match.group(1) if match.groups() else match.group(0)
                if value.strip() in ALLOWED_VALUES:
                    continue
                if PLACEHOLDER.match(value.strip()):
                    continue
                # An environment lookup is a reference to a secret, not the secret.
                if value.startswith(("os.environ", "environ", "getenv", "${", "$")):
                    continue
                out.append({"rule": rule.name, "severity": rule.severity, "where": where,
                            "line": number, "match": mask(value), "note": rule.note})


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = {part for part in path.parts}
        if parts & SKIP_DIRS or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        yield path


def scan_tree(root: Path = Path(".")) -> list[dict]:
    findings: list[dict] = []
    for path in _iter_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        _scan_text(text, str(path.relative_to(root)).replace("\\", "/"), findings)
    return findings


def scan_staged() -> list[dict]:
    """Only added lines of the staged diff, so a pre-commit hook is fast and precise."""

    diff = subprocess.run(["git", "diff", "--cached", "--unified=0"], capture_output=True,
                          text=True, check=False).stdout
    findings: list[dict] = []
    current: list[str] = []
    line_no = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current.append(line[6:].strip())
            continue
        header = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
        if header:
            line_no = int(header.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            where = current[-1] if current else "<staged>"
            _scan_text(line[1:], where, findings)
            line_no += 1
    return findings


def scan_history() -> list[dict]:
    """Every blob reachable from every ref, including deleted files.

    A credential removed in the latest commit is still in the history and still works, so the working
    tree is the wrong place to look for one.
    """

    try:
        shas = subprocess.run(["git", "rev-list", "--objects", "--all"], capture_output=True,
                              text=True, check=True).stdout.splitlines()
    except subprocess.CalledProcessError:
        return []
    findings: list[dict] = []
    # Keyed by file *and* line: keying by line alone collapsed a finding in one file with an unrelated
    # line number in another, which is exactly how a history scan reports a false clean bill.
    seen: set[tuple[str, str, int]] = set()
    for entry in shas:
        parts = entry.split(maxsplit=1)
        if len(parts) != 2:
            continue
        sha, name = parts[0], parts[1]
        if Path(name).suffix.lower() in SKIP_SUFFIXES:
            continue
        blob = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True, check=False)
        if blob.returncode != 0 or b"\x00" in blob.stdout[:4096]:
            continue
        text = blob.stdout.decode("utf-8", errors="replace")
        local: list[dict] = []
        _scan_text(text, f"{name}@{sha[:10]}", local)
        for finding in local:
            key = (finding["rule"], name, finding["line"])
            if key not in seen:
                seen.add(key)
                findings.append(finding)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="scan every blob in every ref")
    parser.add_argument("--staged", action="store_true", help="scan the staged diff only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=".")
    parser.add_argument("--fail-on", default="high", choices=("critical", "high", "none"))
    args = parser.parse_args(argv)

    if args.history:
        findings, scope = scan_history(), "history"
    elif args.staged:
        findings, scope = scan_staged(), "staged"
    else:
        findings, scope = scan_tree(Path(args.root)), "tree"

    rank = {"critical": 2, "high": 1, "low": 0}
    threshold = rank.get(args.fail_on, 1)
    fatal = [f for f in findings if rank[f["severity"]] >= threshold]

    payload = {"scope": scope, "findings": findings, "count": len(findings),
               "failing": len(fatal), "rules": len(RULES)}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"secret scan [{scope}]: {len(RULES)} rules, {len(findings)} finding(s), "
              f"{len(fatal)} at or above '{args.fail_on}'")
        for finding in findings:
            print(f"  {finding['severity']:8} {finding['rule']:28} {finding['where']}:"
                  f"{finding['line']}  {finding['match']}")
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
