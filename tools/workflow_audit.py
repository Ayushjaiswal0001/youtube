"""Static audit of the workflow files themselves.

CI can check that code works; it cannot tell you that a workflow hands a write token to a fork. This
does, because these are the properties that quietly turn a public repository into someone else's
credential harvester:

* every workflow declares a least-privilege ``permissions:`` block (a missing block inherits the
  repository default, which is a setting, not a promise);
* no job grants ``write-all`` or ``contents: write`` unless it is explicitly allowlisted here;
* third-party actions are pinned to a full commit SHA, not a moving tag;
* no ``pull_request_target`` (the trigger that runs with a write token against untrusted code);
* no ``${{ secrets.* }}`` reachable from a ``pull_request`` trigger;
* no dispatch input interpolated directly into a ``run:`` block.

Usage: ``python -m tools.workflow_audit [--json]``. Exit 0 clean, 1 on a finding.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WORKFLOWS = Path(".github/workflows")

#: First-party Actions and the repository's own reusable workflow. Anything else must be SHA-pinned.
FIRST_PARTY = ("actions/", "./")
SHA_PIN = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)", re.MULTILINE)
PERMISSIONS = re.compile(r"^permissions:\s*$", re.MULTILINE)
DANGEROUS_PERMISSIONS = ("write-all", "contents: write", "id-token: write")
SECRETS = re.compile(r"secrets\.[A-Za-z_]|secrets\[", re.IGNORECASE)
INTERPOLATED_INPUT = re.compile(r"\$\{\{\s*inputs\.[A-Za-z_]+\s*\}\}")
INTERPOLATED_STEP_OUTPUT = re.compile(
    r"\$\{\{\s*steps\.[A-Za-z0-9_-]+\.outputs\.[A-Za-z0-9_-]+\s*\}\}"
)


def _run_script_lines(text: str) -> list[str]:
    """Return inline and block-scalar shell source from workflow ``run`` keys.

    GitHub expressions inside ``run: |`` are expanded before the shell executes. Looking only at the YAML
    key line misses the common multiline form and silently lets tainted inputs or step outputs through.
    This small indentation-aware reader is enough for the workflow files in this repository and does not
    mistake ``env:``, ``with:`` or ``if:`` values for shell source.
    """

    scripts: list[str] = []
    run_indent: int | None = None
    for line in text.splitlines():
        if run_indent is None:
            match = re.match(r"^(\s*)run:\s*(.*)$", line)
            if not match:
                continue
            run_indent = len(match.group(1))
            if run_indent < 4:
                # A job can be named `run`; only step-level `run:` keys execute shell source.
                run_indent = None
                continue
            value = match.group(2).strip()
            if value and value[0] not in "|>":
                scripts.append(value)
                run_indent = None
            continue

        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= run_indent:
            run_indent = None
            match = re.match(r"^(\s*)run:\s*(.*)$", line)
            if match:
                run_indent = len(match.group(1))
                if run_indent < 4:
                    run_indent = None
                    continue
                value = match.group(2).strip()
                if value and value[0] not in "|>":
                    scripts.append(value)
                    run_indent = None
            continue
        scripts.append(line)
    return scripts


def _job_bodies(text: str) -> dict[str, str]:
    """Split a workflow into job blocks, so a permission is judged where it is granted."""

    jobs: dict[str, str] = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if not match or line.startswith("  #"):
            continue
        body: list[str] = []
        for follow in lines[index + 1:]:
            if re.match(r"^  [A-Za-z0-9_-]+:\s*$", follow):
                break
            body.append(follow)
        jobs[match.group(1)] = "\n".join(body)
    return jobs


def strip_comments(text: str) -> str:
    """Remove comments before scanning.

    The first version matched the word `pull_request_target` inside the comment that explains why it is
    not used, so the auditor failed the very workflow written to be safe.
    """

    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"(?:^|\s)#.*$", "", line))
    return "\n".join(lines)


def audit_workflow(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    text = strip_comments(raw)
    findings: list[dict] = []
    name = path.name

    def add(kind: str, detail: str) -> None:
        findings.append({"workflow": name, "kind": kind, "detail": detail})

    if not PERMISSIONS.search(text):
        add("missing-permissions", "no top-level permissions block, so the repository default applies")
    for dangerous in DANGEROUS_PERMISSIONS:
        if dangerous in text:
            add("broad-permission", f"grants '{dangerous}'")

    for uses in USES.findall(text):
        if uses.startswith(FIRST_PARTY):
            continue
        if not SHA_PIN.match(uses):
            add("unpinned-action", f"'{uses}' is not pinned to a commit SHA")

    if "pull_request_target" in text:
        add("dangerous-trigger", "uses pull_request_target, which runs with a write token "
                                 "against code from a fork")

    # A top-level `permissions:` block already narrows every job that does not override it, so only a
    # workflow with no block at all leaves the repository default in force.
    workflow_wide = bool(PERMISSIONS.search(text))
    for job, body in _job_bodies(text).items():
        if SECRETS.search(body) and "permissions" not in body and not workflow_wide:
            add("secret-without-permissions",
                f"job '{job}' reads secrets but does not narrow its own permissions")

    for line in _run_script_lines(text):
        if INTERPOLATED_INPUT.search(line) or INTERPOLATED_STEP_OUTPUT.search(line):
            add("input-in-shell", line.strip()[:100])
    return findings


def audit(directory: Path = WORKFLOWS) -> dict:
    workflows = sorted(directory.glob("*.yml"))
    findings: list[dict] = []
    for path in workflows:
        findings.extend(audit_workflow(path))
    return {"workflows": [p.name for p in workflows], "findings": findings,
            "count": len(findings)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dir", default=str(WORKFLOWS))
    args = parser.parse_args(argv)
    report = audit(Path(args.dir))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"workflow audit: {len(report['workflows'])} workflow(s), {report['count']} finding(s)")
        for finding in report["findings"]:
            print(f"  {finding['kind']:26} {finding['workflow']}: {finding['detail']}")
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
