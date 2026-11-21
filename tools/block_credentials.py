"""Refuse to commit files that hold credentials.

``.gitignore`` is advisory: ``git add -f`` ignores it, and a file named ``ytcredetials.txt`` (a real
misspelling in this project's history) is exactly what a tired commit looks like. This runs on the file
names a commit is about to include and fails on the names that mean a credential, and on any small text
file whose content is a downloaded OAuth secret JSON.

Usage: ``python -m tools.block_credentials <file> ...`` (pre-commit passes them), or with no arguments
it checks the staged file names. Exit 0 clean, 1 on a blocked file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

#: Name shapes that mean "credentials live here".
NAME_PATTERNS = (
    re.compile(r"(?i)(^|[/_-])ytcrede?n?t?ials?\.(txt|json)$"),
    re.compile(r"(?i)^client_secret.*\.json$"),
    re.compile(r"(?i)(^|/)\.env(\..+)?$"),
    re.compile(r"(?i)token\.json$"),
    re.compile(r"(?i)service[-_]?account.*\.json$"),
    re.compile(r"(?i)\.(pem|p12|pfx|key)$"),
)

#: Content shapes: a JSON object carrying the OAuth fields together.
SECRET_JSON_KEYS = {"client_secret", "refresh_token", "installed", "web", "access_token"}


def staged_names() -> list[str]:
    result = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                            capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def blocks(name: str, path: Path | None = None) -> str | None:
    for pattern in NAME_PATTERNS:
        if pattern.search(name):
            return f"'{name}' looks like a credential file"
    if path is not None and path.is_file() and path.suffix == ".json" and path.stat().st_size < 64_000:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, dict) and SECRET_JSON_KEYS & set(data):
            return f"'{name}' is a JSON document containing OAuth fields"
    return None


def main(argv: list[str] | None = None) -> int:
    names = list(argv[1:] if argv is not None else sys.argv[1:]) or staged_names()
    blocked = []
    for name in names:
        reason = blocks(name, Path(name))
        if reason:
            blocked.append(reason)
    for reason in blocked:
        print(f"blocked: {reason}", file=sys.stderr)
    if blocked:
        print("Remove the file or add it to .gitignore. Never commit credentials.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
