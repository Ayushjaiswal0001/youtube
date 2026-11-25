"""Collect the per-episode QC evidence from the artifacts actually produced in this mission.

Every number in the generated report is read from the build directory, not typed by hand: a report that
restates a log by memory is how a "passed" claim gets made about a run that never happened.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

BUILD = Path(os.environ.get("FACTORY_BUILD_DIR", "build").split(os.pathsep)[0])
#: Accept several trees at once, so a report can cover the Shorts build, the long-form build and a
#: recovery build in one file instead of three fragments. `os.pathsep` is ; on Windows and : elsewhere.
TREES = [Path(part) for part in os.environ.get("FACTORY_BUILD_DIR", "build").split(os.pathsep) if part]
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


def sha256_of(path: Path) -> str:
    """The hash of the file that would be uploaded, read from the bytes rather than a manifest."""

    if not path.is_file():
        return "n/a"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    if not path.is_file():
        return {}
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def loudness(path: Path) -> tuple[float | None, float | None]:
    """Integrated LUFS and true peak, measured on the file that would be uploaded."""

    if not path.is_file():
        return None, None
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    integrated = peak = None
    for line in result.stderr.splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                integrated = float(line.split("I:")[1].split("LUFS")[0].strip())
            except ValueError:
                pass
        if "Peak:" in line and "dBFS" in line:
            try:
                peak = float(line.split("Peak:")[1].split("dBFS")[0].strip())
            except ValueError:
                pass
    return integrated, peak


def srt_cues(path: Path) -> str:
    """Count subtitle cues from the file, since not every engine records the count in render.json."""

    if not path.is_file():
        return "0"
    text = path.read_text(encoding="utf-8", errors="replace")
    return str(sum(1 for line in text.splitlines() if line.strip().isdigit()))


def job_for(plan_id: str) -> dict:
    """The job record for this episode, if the state directory is pointed at it."""

    state = os.environ.get("FACTORY_STATE_DIR")
    if not state:
        return {}
    for path in sorted(Path(state).glob("jobs/*/job.json")):
        record = load(path)
        if record.get("job_id", "").split("_")[1] == plan_id:
            return record
    return {}


def upload_for(channel: str, sha256: str) -> dict:
    root = os.environ.get("YT_STATE_ROOT")
    if not root or not sha256:
        return {}
    ledger = Path(root) / channel / "ledger.jsonl"
    if not ledger.is_file():
        return {}
    latest: dict = {}
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("video_sha256") == sha256:
            latest = entry
    return latest


def section(channel: str, plan_id: str, root: Path) -> list[str]:
    render = load(root / "render.json")
    qc = load(root / "qc.json")
    creative = load(root / "creative.json")
    manifest = load(root / "manifest.json")
    meta = probe(root / "video.mp4")
    streams = meta.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    digest = sha256_of(root / "video.mp4")
    integrated, peak = loudness(root / "video.mp4")
    job = job_for(plan_id)
    gate = load(root / "publish_gate.json")
    lines = [f"## {channel} / {plan_id}", ""]
    lines.append("| field | value |")
    lines.append("| --- | --- |")
    lines.append(f"| channel | `{channel}` |")
    lines.append(f"| episode id | `{plan_id}` |")
    lines.append(f"| job id | `{job.get('job_id', 'not recorded')}` |")
    lines.append(f"| job state | `{job.get('state', 'not recorded')}` |")
    lines.append(f"| uploads attempted | {job.get('attempts', 0)} |")
    if render.get("rendered_at"):
        lines.append(f"| rendered at | `{render['rendered_at']}` |")
    lines.append(f"| artifact | `{root.name}/video.mp4` |")
    lines.append(f"| sha256 | `{digest}` |")
    lines.append(f"| bytes | {root.joinpath('video.mp4').stat().st_size if root.joinpath('video.mp4').is_file() else 'n/a'} |")
    lines.append(f"| duration | {render.get('duration')} s |")
    lines.append(f"| resolution | {video_stream.get('width')}×{video_stream.get('height')} |")
    lines.append(f"| frame rate | {video_stream.get('r_frame_rate')} |")
    lines.append(f"| codecs | {video_stream.get('codec_name')} / {audio_stream.get('codec_name') or 'none'} |")
    lines.append(f"| loudness | {integrated} LUFS (target −14) |")
    lines.append(f"| true peak | {peak} dBTP (gate −1.0) |")
    captions = root / "captions.srt"
    cues = render.get("cue_count") or srt_cues(captions)
    lines.append(f"| subtitles | {'present' if captions.is_file() else 'MISSING'}, "
                 f"{captions.stat().st_size if captions.is_file() else 0} B, {cues} cues |")
    lines.append(f"| creative QC | {'see below' if creative else 'not run (no scene plan for this engine)'} |")
    lines.append(f"| publishing gate | {gate.get('passed')}/{gate.get('total')} ok={gate.get('ok')} |"
                 if gate else "| publishing gate | not recorded |")
    upload = upload_for(channel, digest)
    lines.append(f"| upload state | {upload.get('status', 'never uploaded')}"
                 f"{(' (' + str(upload.get('video_id')) + ')') if upload.get('video_id') else ''} |")
    lines.append(f"| retry state | {job.get('attempts', 0)} attempt(s), error: {job.get('error') or 'none'} |")
    lines.append("")
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
    episodes = []
    for tree in TREES:
        for channel, plan_id, root in discover(tree):
            if all(existing[1] != plan_id or existing[0] != channel for existing in episodes):
                episodes.append((channel, plan_id, root))
    if not episodes:
        out.extend(["No rendered episodes were found in the build directory.", ""])
    for channel, plan_id, root in episodes:
        out.extend(section(channel, plan_id, root))
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(out)} lines)")


if __name__ == "__main__":
    main()
