"""Automated Quality Assurance Module for Animated Episodes.
Performs comprehensive multi-point checks: resolution, aspect ratio, duration,
audio presence, silence detection, black frame detection, and file integrity.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List

class QualityAssurance:
    """Runs automated broadcast QA checks on rendered episodes."""

    def __init__(self, target_w: int = 1080, target_h: int = 1920,
                 min_dur: float = 20.0, max_dur: float = 65.0):
        self.target_w = target_w
        self.target_h = target_h
        self.min_dur = min_dur
        self.max_dur = max_dur

    def validate_episode(self, video_path: Path) -> Dict[str, Any]:
        """Runs full suite of QA tests and returns pass/fail report."""
        report = {
            "file": str(video_path),
            "passed": True,
            "errors": [],
            "warnings": [],
            "metrics": {}
        }

        if not video_path.exists():
            report["passed"] = False
            report["errors"].append("Video file does not exist.")
            return report

        # 1. Probe Video & Audio Streams
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(video_path)
        ]
        res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            report["passed"] = False
            report["errors"].append(f"ffprobe failed: {res.stderr}")
            return report

        info = json.loads(res.stdout)
        streams = info.get("streams", [])
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        # 2. Check Video Stream
        if not v_stream:
            report["passed"] = False
            report["errors"].append("Missing video stream.")
        else:
            w = int(v_stream.get("width", 0))
            h = int(v_stream.get("height", 0))
            report["metrics"]["width"] = w
            report["metrics"]["height"] = h

            if w != self.target_w or h != self.target_h:
                report["passed"] = False
                report["errors"].append(f"Resolution mismatch: expected {self.target_w}x{self.target_h}, got {w}x{h}.")

            codec = v_stream.get("codec_name", "")
            report["metrics"]["video_codec"] = codec
            if codec != "h264":
                report["warnings"].append(f"Expected h264, found {codec}.")

        # 3. Check Audio Stream
        if not a_stream:
            report["passed"] = False
            report["errors"].append("Missing audio stream.")
        else:
            sample_rate = int(a_stream.get("sample_rate", 0))
            channels = int(a_stream.get("channels", 0))
            report["metrics"]["audio_sample_rate"] = sample_rate
            report["metrics"]["audio_channels"] = channels
            if sample_rate < 44100:
                report["warnings"].append(f"Low audio sample rate: {sample_rate} Hz.")

        # 4. Check Duration
        dur = float(info.get("format", {}).get("duration", 0.0))
        report["metrics"]["duration_seconds"] = dur
        if dur < self.min_dur:
            report["passed"] = False
            report["errors"].append(f"Episode too short ({dur:.2f}s < {self.min_dur}s).")
        elif dur > self.max_dur:
            report["warnings"].append(f"Episode duration ({dur:.2f}s) exceeds optimal Shorts limit ({self.max_dur}s).")

        # 5. Check Audio Volume (Silence Check)
        vol_cmd = [
            "ffmpeg", "-i", str(video_path),
            "-af", "volumedetect",
            "-vn", "-sn", "-dn",
            "-f", "null", os.devnull
        ]
        vol_res = subprocess.run(vol_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        mean_vol = None
        for line in vol_res.stderr.splitlines():
            if "mean_volume:" in line:
                try:
                    mean_vol = float(line.split("mean_volume:")[1].split("dB")[0].strip())
                    report["metrics"]["mean_volume_db"] = mean_vol
                except Exception:
                    pass

        if mean_vol is not None and mean_vol < -50.0:
            report["passed"] = False
            report["errors"].append(f"Audio is nearly silent (mean volume {mean_vol} dB).")

        # 6. Black Frame Detection
        black_cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", "blackdetect=d=2.0:pix_th=0.10",
            "-an", "-f", "null", os.devnull
        ]
        black_res = subprocess.run(black_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        has_black_freeze = any("black_start" in line for line in black_res.stderr.splitlines())
        if has_black_freeze:
            report["warnings"].append("Potential black frame freeze detected.")

        return report
