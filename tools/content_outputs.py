"""Turn ``factory.cli plan available --json`` into GitHub Actions step outputs.

Kept as a script rather than inline shell so the same parsing is used on a runner and by the tests, and so the
workflow step stays readable.
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
    item = json.loads(raw[start:])[0]
    reasons = " ".join(str(entry.get("reason") or "") for entry in [item]).strip()
    return {
        "available": "1" if item.get("available") else "0",
        "kind": str(item.get("kind") or ""),
        "plan_id": str(item.get("plan_id") or ""),
        "reason": reasons.replace("\n", " ")[:300],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: content_outputs.py <available.json>")
    for key, value in outputs(Path(argv[1])).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
