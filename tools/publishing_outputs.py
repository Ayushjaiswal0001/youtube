"""Turn ``factory.cli publishing --json`` output into GitHub Actions step outputs.

The CLI may print log lines before its JSON payload, so the payload is located rather than assumed. Kept as
a script instead of inline shell so the same parsing is used on a runner and by the tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def outputs(path: Path) -> dict[str, str]:
    raw = path.read_text(encoding="utf-8")
    start = raw.find("[")
    if start < 0:
        raise SystemExit(f"no JSON payload in {path}")
    data = json.loads(raw[start:])
    item = data[0]
    policy = item["policy"]
    release = item["next_release"]
    return {
        "ready": "1" if item["ready"] else "0",
        "mode": str(policy["mode"]),
        "scheduled_upload": "1" if policy["scheduled_upload"] else "0",
        "next_release": str(release["publish_at"] or ""),
        "release_reason": str(release["reason"]),
        # informational only: another plan of this channel already has a release pending. It does not block
        # this run - the Short and the long-form share one release instant by design - but an operator
        # reading the summary should know a second video is queued for the same channel.
        "pending_release": str(item.get("pending_release") or ""),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: publishing_outputs.py <publishing.json>")
    for key, value in outputs(Path(argv[1])).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
