"""The encoded true peak is measured, not assumed, and the limiter is tightened only when needed.

Real failure this replaces: `nexus-robot-video` encoded to -0.46 dBTP at limiter 0.74 while
`nexus-small-models` encoded to -2.33 dBTP with the same settings, so one constant did not hold the
-1.0 dBTP gate for every narration take (TTS output varies between renders). The episode was blocked
by its own QC, correctly.
"""

from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from factory.media import music

WORK = Path(tempfile.mkdtemp(prefix="peak-guard-test-"))


def _write_tone(path: Path, amplitude: float, duration: float = 2.0,
                frequency: float = 220.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        frames = bytearray()
        for index in range(int(44100 * duration)):
            # A hard-edged square wave is the worst case for inter-sample overshoot after encoding.
            value = int(amplitude * 32767) * (1 if math.sin(2 * math.pi * frequency * index / 44100) >= 0 else -1)
            frames += struct.pack("<h", max(-32768, min(32767, value)))
        handle.writeframes(bytes(frames))
    return path


class TruePeakGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.narration = _write_tone(WORK / "narration.wav", 0.98)
        self.bed = music.make_bed(2.0, "nexus", [0.4, 1.2], WORK / "bed.wav")
        self.out = WORK / "mixed.m4a"

    def test_a_hot_narration_still_encodes_below_the_gate(self) -> None:
        music.mix_narration(self.narration, self.bed, self.out, 2.0)
        measured = music.measure_loudness(self.out)
        self.assertIsNotNone(measured)
        self.assertLessEqual(measured["true_peak_dbtp"], -1.0,
                             f"encoded true peak {measured['true_peak_dbtp']} dBTP exceeds the gate")
        # Normalisation still targets the reference loudness, not a much quieter file.
        self.assertLess(abs(measured["integrated_lufs"] + 14.0), 3.0)

    @staticmethod
    def _encodes(calls: list[str]) -> list[str]:
        """The `-af` chain of each encode pass, not the mix pass (which also runs ffmpeg)."""

        chains: list[str] = []
        for call in calls:
            parts = call.split()
            if "-af" in parts:
                chains.append(parts[parts.index("-af") + 1])
        return chains

    def test_the_limiter_is_tightened_only_when_the_encoded_peak_is_hot(self) -> None:
        hot = {"integrated_lufs": -14.0, "true_peak_dbtp": -0.4, "lra_lu": 3.0,
               "threshold_lufs": -25.0}
        ok = {"integrated_lufs": -14.0, "true_peak_dbtp": -1.6, "lra_lu": 3.0,
              "threshold_lufs": -25.0}
        calls: list[str] = []

        def fake_run(args, **kwargs):  # noqa: ANN001, ANN401
            calls.append(" ".join(args))
            Path(args[-1]).write_bytes(b"encoded")
            return None

        with mock.patch("factory.util.run", side_effect=fake_run):
            # The first call measures the pre-encode mix (to feed loudnorm's linear pass), then one
            # measurement per encode attempt.
            with mock.patch.object(music, "measure_loudness", side_effect=[ok, hot, ok]):
                music.mix_narration(self.narration, self.bed, self.out, 2.0)

        chains = self._encodes(calls)
        self.assertEqual(len(chains), 2, "a hot encode must be re-encoded")
        self.assertIn("limit=0.7400", chains[0])
        tightened = float(chains[1].rsplit("limit=", 1)[1].split(":")[0])
        self.assertLess(tightened, 0.74)

    def test_a_clean_encode_is_not_re_encoded(self) -> None:
        calls: list[str] = []

        def fake_run(args, **kwargs):  # noqa: ANN001, ANN401
            calls.append(" ".join(args))
            Path(args[-1]).write_bytes(b"encoded")
            return None

        clean = {"integrated_lufs": -14.2, "true_peak_dbtp": -2.3, "lra_lu": 3.0,
                 "threshold_lufs": -25.0}
        with mock.patch("factory.util.run", side_effect=fake_run):
            with mock.patch.object(music, "measure_loudness", side_effect=[clean, clean]):
                music.mix_narration(self.narration, self.bed, self.out, 2.0)
        self.assertEqual(len(self._encodes(calls)), 1)

    def test_an_unmeasurable_encode_is_not_retried_forever(self) -> None:
        calls: list[str] = []

        def fake_run(args, **kwargs):  # noqa: ANN001, ANN401
            calls.append(" ".join(args))
            Path(args[-1]).write_bytes(b"encoded")
            return None

        reference = {"integrated_lufs": -14.0, "true_peak_dbtp": -2.0, "lra_lu": 3.0,
                     "threshold_lufs": -25.0}
        with mock.patch("factory.util.run", side_effect=fake_run):
            with mock.patch.object(music, "measure_loudness", side_effect=[reference, None]):
                music.mix_narration(self.narration, self.bed, self.out, 2.0)
        # Nothing to compare against, so the loop must stop rather than re-encode blindly.
        self.assertEqual(len(self._encodes(calls)), 1)


if __name__ == "__main__":
    unittest.main()
