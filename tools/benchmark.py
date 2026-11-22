"""Measure a production render: wall time, peak memory, disk delta, frames per second.

Run: python -m tools.benchmark --channel natkhat-toons --format short [--label short-32s]

The harness drives the *real* CLI entry point in this process (rather than re-implementing the
pipeline) so the numbers describe the production path, and samples resident memory from the OS while
it runs so the peak is measured rather than estimated from the output. Whatever it cannot measure it
does not invent: a projected figure is reported with ``"kind": "projection"`` and the measured rate it
was derived from.
"""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import time
from pathlib import Path

from factory.observability import process_rss_mb
from factory.orchestrator import BUILD_ROOT, episode_out_dir
from factory.config import load_channel_specs


def _sample_memory(stop: threading.Event, out: dict, interval: float = 0.4) -> None:
    peak = 0.0
    while not stop.is_set():
        value = process_rss_mb()
        if value:
            peak = max(peak, value)
        stop.wait(interval)
    out["peak_rss_mb"] = round(peak, 1) or None


def measure(argv: list[str], label: str, *, output_dir: Path | None = None) -> dict:
    from factory import cli

    memory: dict = {}
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_memory, args=(stop, memory), daemon=True)
    before_free = shutil.disk_usage(str(BUILD_ROOT)).free
    sampler.start()
    started = time.time()
    try:
        code = cli.main(argv)
    finally:
        stop.set()
        sampler.join(timeout=5.0)
        wall = time.time() - started
    after_free = shutil.disk_usage(str(BUILD_ROOT)).free

    report = {"label": label, "kind": "measured", "command": " ".join(argv),
              "exit_code": code, "wall_seconds": round(wall, 2),
              "peak_rss_mb": memory.get("peak_rss_mb"),
              "disk_delta_mb": round((before_free - after_free) / (1024 * 1024), 1),
              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if output_dir is not None:
        video = Path(output_dir) / "video.mp4"
        if video.is_file():
            report["size_mb"] = round(video.stat().st_size / (1024 * 1024), 2)
            report["sha256_prefix"] = _sha_prefix(video)
            report["video_path"] = str(video)
    return report


def _sha_prefix(path: Path, chars: int = 16) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:chars]


def project(measured: dict, seconds: float, *, frames_at_30fps: float) -> dict:
    """Extrapolate a longer render from a measured one, and say so in the payload."""

    wall = measured.get("wall_seconds") or 0.0
    duration = measured.get("duration_seconds") or 0.0
    if not wall or not duration:
        return {"kind": "unavailable", "reason": "no measured baseline"}
    rate = duration / wall
    return {"kind": "projection",
            "label": f"{seconds:.0f}s episode",
            "from": measured["label"],
            "measured_rate": round(rate, 4),
            "wall_seconds": round(seconds / rate, 1),
            "peak_rss_mb": measured.get("peak_rss_mb"),
            "frames": int(seconds * 30),
            "note": "extrapolated from a measured render; not itself measured"}


def _video_seconds(path: Path) -> float:
    import subprocess

    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", str(path)],
                            capture_output=True, text=True, check=False)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="natkhat-toons")
    parser.add_argument("--format", default="short")
    parser.add_argument("--label", default="")
    parser.add_argument("--out", default="build/benchmarks")
    args = parser.parse_args(argv)

    specs = load_channel_specs()
    spec = specs[args.channel]
    from dataclasses import replace

    target = replace(spec, format=args.format)
    label = args.label or f"{args.channel}-{args.format}"

    command = ["render", "--channel", args.channel, "--format", args.format]
    report = measure(command, label)
    out_dir = episode_out_dir(target, _selected_plan(target))
    report["duration_seconds"] = _video_seconds(Path(out_dir) / "video.mp4")
    if report["duration_seconds"] and report["wall_seconds"]:
        report["realtime_factor"] = round(report["wall_seconds"] / report["duration_seconds"], 2)
        report["fps"] = round(report["duration_seconds"] * 30 / report["wall_seconds"], 2)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    for seconds in (60.0, 300.0, 600.0):
        projection = project(report, seconds, frames_at_30fps=30.0)
        (out / f"projection-{int(seconds)}s.json").write_text(
            json.dumps(projection, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{int(seconds):>4}s projection: {projection.get('wall_seconds')} s wall")
    return 0


def _selected_plan(spec):
    """The plan the CLI would pick with no --plan-id, so the output directory matches it."""

    from factory.content.script import load_plans_for

    plans = load_plans_for(spec)
    if not plans:
        return {}
    return plans[0]


if __name__ == "__main__":
    raise SystemExit(main())
