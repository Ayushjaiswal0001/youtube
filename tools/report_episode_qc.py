"""Collect the per-episode QC evidence from the artifacts actually produced in this mission.

Every number in the generated report is read from the build directory, not typed by hand: a report that
restates a log by memory is how a "passed" claim gets made about a run that never happened.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BUILD = Path(os.environ.get("FACTORY_BUILD_DIR", "build"))
OUT = Path(os.environ.get("FACTORY_QC_REPORT", "X100_EPISODE_QC_REPORTS.md"))

EPISODES = [
    ("nexus-node", "nexus-small-models", BUILD / "nexus-node/nexus-small-models"),
    ("nexus-node", "nexus-robot-video", BUILD / "nexus-node/nexus-robot-video"),
    ("academic-biohacker", "academic-morning-light",
     BUILD / "academic-biohacker/academic-morning-light"),
    ("academic-biohacker", "academic-slow-breathing",
     BUILD / "academic-biohacker/academic-slow-breathing"),
    ("natkhat-toons", "natkhat-haveli-e1",
     BUILD / "natkhat-toons/natkhat-toons_natkhat-haveli-e1"),
    ("nexus-node", "long-nexus-power-grid (16:9)",
     Path(os.environ.get("FACTORY_LONGFORM_BUILD_DIR", BUILD))
     / "nexus-node/long-nexus-power-grid"),
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def section(channel: str, plan_id: str, root: Path) -> list[str]:
    render = load(root / "render.json")
    qc = load(root / "qc.json")
    creative = load(root / "creative.json")
    manifest = load(root / "manifest.json")
    lines = [f"## {channel} / {plan_id}", ""]
    lines.append(f"- build directory: `{root.name}`")
    if render:
        lines.append(f"- video: {render.get('duration')} s, "
                     f"{render.get('size') or render.get('size_bytes')} bytes")
    if qc:
        checks = qc.get("checks") or qc.get("results") or []
        failed = [c for c in checks if isinstance(c, dict) and not c.get("ok", True)]
        lines.append(f"- technical QC: ok={qc.get('ok')} checks={len(checks)} failed={len(failed)}")
        for check in failed:
            lines.append(f"  - FAIL `{check.get('name')}`: {str(check.get('detail'))[:160]}")
    else:
        lines.append("- technical QC: **not recorded** for this episode")
    if creative:
        checks = creative.get("checks") or []
        warnings = [c["name"] for c in checks if not c.get("ok")]
        lines.append(f"- creative QC: ok={creative.get('ok')} checks={len(checks)} "
                     f"not-ok={warnings}")
        for name in ("visual_diversity_pixels", "no_repeated_composition_runs",
                     "figure_is_stated", "provenance_recorded", "attribution_present"):
            detail = next((c.get("detail") for c in checks if c.get("name") == name), None)
            if detail:
                lines.append(f"  - `{name}`: {detail}")
    else:
        lines.append("- creative QC: not run (no scene plan for this engine)")
    if manifest:
        paths = manifest.get("artifacts") or manifest.get("files") or []
        lines.append(f"- manifest: {len(paths) if isinstance(paths, list) else 'n/a'} artifacts, "
                     f"root `{(manifest.get('root') or '')[-40:]}`")
    lines.append("")
    return lines


def main() -> None:
    out = ["# X100 per-episode QC reports", "",
           "Generated from the artifacts in the acceptance build directory. Values are read from "
           "`render.json`, `qc.json`, `creative.json` and `manifest.json`; nothing here is transcribed "
           "by hand.", ""]
    for channel, plan_id, root in EPISODES:
        if root.exists():
            out.extend(section(channel, plan_id, root))
        else:
            out.extend([f"## {channel} / {plan_id}", "", "- **not rendered** in this mission", ""])
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} lines)")


if __name__ == "__main__":
    main()
