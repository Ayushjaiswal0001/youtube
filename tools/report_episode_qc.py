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

def discover(build: Path) -> list[tuple[str, str, Path]]:
    """Every episode directory in the build tree, in channel then plan order.

    The list used to be hard-coded, which meant a report could silently omit an episode that was rendered
    in a different session. Discovery keeps the report a description of the artifacts rather than of
    someone's memory.
    """

    found: list[tuple[str, str, Path]] = []
    for channel_dir in sorted(p for p in build.iterdir() if p.is_dir()) if build.is_dir() else []:
        for out_dir in sorted(p for p in channel_dir.iterdir() if p.is_dir()):
            if (out_dir / "video.mp4").is_file():
                found.append((channel_dir.name, out_dir.name, out_dir))
    longform = os.environ.get("FACTORY_LONGFORM_BUILD_DIR")
    if longform:
        extra = Path(longform)
        for channel_dir in sorted(p for p in extra.iterdir() if p.is_dir()) if extra.is_dir() else []:
            for out_dir in sorted(p for p in channel_dir.iterdir() if p.is_dir()):
                if (out_dir / "video.mp4").is_file():
                    found.append((channel_dir.name, f"{out_dir.name} (16:9)", out_dir))
    return found


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
    episodes = discover(BUILD)
    if not episodes:
        out.extend(["No rendered episodes were found in the build directory.", ""])
    for channel, plan_id, root in episodes:
        out.extend(section(channel, plan_id, root))
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} lines)")


if __name__ == "__main__":
    main()
