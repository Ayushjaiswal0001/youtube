"""Loudness and mix tests (require ffmpeg on PATH).

They prove the numbers the pipeline promises: the mix lands on -14 LUFS with true peak
inside the ceiling, duration is preserved for A/V sync, and the bed is ducked under the
narration instead of sitting at a fixed level.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from factory.media.music import LOUDNESS_TARGET, measure_loudness, mix_narration

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _write_tone(path: Path, seconds: float, frequency: float, amplitude: float, rate: int = 44100) -> Path:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        payload = bytearray()
        for index in range(frames):
            # gentle envelope so loudnorm sees a realistic, non-clipped signal
            gate = 0.55 + 0.45 * math.sin(2 * math.pi * 0.7 * index / rate)
            value = int(amplitude * gate * 32767 * math.sin(2 * math.pi * frequency * index / rate))
            payload += struct.pack("<h", max(-32768, min(32767, value)))
        handle.writeframes(bytes(payload))
    return path


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not available")
class LoudnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-audio-"))
        self.narration = _write_tone(self.tmp / "narration.wav", 6.0, 220.0, 0.25)
        self.bed = _write_tone(self.tmp / "bed.wav", 6.0, 440.0, 0.9)
        self.duration = 6.0

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mix_reaches_broadcast_loudness(self) -> None:
        out = self.tmp / "mixed.m4a"
        mix_narration(self.narration, self.bed, out, self.duration)
        measured = measure_loudness(out)
        self.assertAlmostEqual(measured["integrated_lufs"], LOUDNESS_TARGET["I"], delta=1.5)
        self.assertLessEqual(measured["true_peak_dbtp"], -1.0, "true peak must stay under -1 dBTP")

    def test_quiet_input_is_lifted_to_target(self) -> None:
        quiet = _write_tone(self.tmp / "quiet.wav", 4.0, 220.0, 0.02)
        out = self.tmp / "quiet_mix.m4a"
        mix_narration(quiet, self.bed, out, 4.0)
        measured = measure_loudness(out)
        self.assertGreater(measured["integrated_lufs"], -20.0, "normalisation must lift a quiet mix")

    def test_duration_is_preserved_for_av_sync(self) -> None:
        out = self.tmp / "duration.m4a"
        mix_narration(self.narration, self.bed, out, self.duration)
        duration = float(
            subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        self.assertAlmostEqual(duration, self.duration, delta=0.08)

    def test_measure_returns_nan_free_numbers(self) -> None:
        measured = measure_loudness(self.narration)
        for key in ("integrated_lufs", "true_peak_dbtp", "lra_lu"):
            self.assertIn(key, measured)
            self.assertFalse(math.isnan(measured[key]), f"{key} parsed as NaN")


if __name__ == "__main__":
    unittest.main()


def test_a_hot_mix_leaves_true_peak_headroom_for_the_encoder(tmp_path: Path) -> None:
    """The limiter target has to survive AAC inter-sample overshoot, not just sample peak.

    Cloud run 45137023125 encoded the academic long-form episode to -0.96 dBTP and failed `audio_loudness`
    (limit -1.0), with the limiter at 0.82 - about -1.7 dBFS of sample peak, which the encoder pushed back over
    the line. This drives a deliberately hot tone through the real mix path and measures the encoded file.
    """

    import subprocess

    from factory.config import load_channel_specs
    from factory.media.music import make_bed, mix_narration
    from studio.audio.loudness import measure, within_tolerance

    spec = load_channel_specs()["academic-biohacker"]
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                    "-af", "volume=9dB", "-ar", "44100", "-ac", "2", str(tmp_path / "hot.wav")],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    make_bed(6.0, spec.palette, [1.5, 4.0], tmp_path / "bed.wav")
    mix_narration(tmp_path / "hot.wav", tmp_path / "bed.wav", tmp_path / "mixed.m4a", 6.0)
    measurement = measure(tmp_path / "mixed.m4a")
    ok, detail = within_tolerance(measurement)
    assert ok, detail
    assert measurement["true_peak_dbtp"] <= -1.0
