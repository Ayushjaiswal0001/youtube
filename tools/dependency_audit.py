"""Fail on dependency advisories that have not been reviewed and accepted.

A dependency gate that fails on every known advisory is a gate that gets switched off: this project's
pinned Pillow has four advisories that only clear in a version another local tool forbids. A gate that
ignores all advisories is worse. So the four are written down with a reason, and anything else fails.

Usage:
    python -m tools.dependency_audit                  # audit requirements.txt with pip-audit
    python -m tools.dependency_audit --input report.json   # judge an existing pip-audit JSON report
    python -m tools.dependency_audit --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ACCEPTED = Path("security/accepted-advisories.json")
REQUIREMENTS = Path("requirements.txt")


def ceilings(path: Path = ACCEPTED) -> dict[tuple[str, str], dict]:
    """Accepted package@version pairs, each with the reason and what would clear it."""

    data = json.loads(path.read_text(encoding="utf-8"))
    return {(entry["package"].lower(), entry["version"]): entry
            for entry in data.get("ceilings", [])}


def run_audit(requirements: Path = REQUIREMENTS) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", str(requirements), "--format", "json",
         "--progress-spinner", "off"],
        capture_output=True, text=True, check=False)
    text = result.stdout.strip()
    if not text.startswith("{"):
        raise RuntimeError(f"pip-audit produced no JSON report: {result.stderr.strip()[:400]}")
    return json.loads(text)


def judge(report: dict) -> dict:
    tolerance = ceilings()
    blocking: list[dict] = []
    tolerated: list[dict] = []
    for dependency in report.get("dependencies", []):
        name = str(dependency.get("name", "")).lower()
        version = str(dependency.get("version", ""))
        for advisory in dependency.get("vulns") or []:
            identifier = str(advisory.get("id", ""))
            entry = tolerance.get((name, version))
            # A ceiling only excuses advisories whose published fix lies outside the pinned version.
            if entry and advisory.get("fix_versions"):
                if all(fix <= version for fix in advisory["fix_versions"]):
                    entry = None
            item = {"package": name, "version": version, "id": identifier,
                    "fix": (advisory.get("fix_versions") or [None])[0],
                    "reason": (entry or {}).get("reason", "")}
            (tolerated if entry else blocking).append(item)
    return {"blocking": blocking, "accepted": tolerated,
            "count": len(blocking), "accepted_count": len(tolerated)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=None, help="an existing pip-audit JSON report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = (json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input
              else run_audit())
    verdict = judge(report)

    if args.json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
    else:
        print(f"dependency audit: {verdict['count']} unaccepted, "
              f"{verdict['accepted_count']} reviewed and accepted")
        for item in verdict["blocking"]:
            print(f"  BLOCK {item['package']} {item['version']} {item['id']} "
                  f"(fix: {item['fix'] or 'none published'})")
        for item in verdict["accepted"]:
            print(f"  accept {item['package']} {item['version']} {item['id']} - {item['reason'][:70]}")
    return 1 if verdict["blocking"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
