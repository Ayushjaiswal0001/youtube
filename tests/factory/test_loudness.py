"""Tests for loudness measurement, normalisation and the QC tolerance."""

from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from studio.audio.loudness import (
    ACCEPTED_RANGE,
    LOUDNESS_TARGET,
    _decode_summary,
    measure,
    measure_with_diagnostics,
    normalize_file,
    within_tolerance,
)

# A relative scratch directory, never an absolute path: an absolute Windows path such as
# "C:/Users/..." makes ffmpeg on Linux read "C:" as a protocol, so the measurement silently
# returned nothing on CI while passing locally.
WORK = Path(tempfile.mkdtemp(prefix="loudness-test-"))


def _write_tone(path: Path, amplitude: float, duration: float = 3.0,
                frequency: float = 440.0, sample_rate: int = 44100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(int(sample_rate * duration)):
            value = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames += struct.pack("<hh", value, value)
        handle.writeframes(bytes(frames))
    return path


class SummaryParsingTests(unittest.TestCase):
    """The ffmpeg summary is embedded in stderr, so parsing it must be defensive."""

    def test_a_clean_summary_decodes(self):
        raw = _decode_summary('{"input_i" : "-14.10", "input_tp" : "-1.24"}')
        self.assertEqual(raw["input_i"], "-14.10")

    def test_a_trailing_brace_does_not_break_the_parse(self):
        # The previous implementation sliced from the last "{" to the last "}", so any later
        # brace made the whole block unparseable and the measurement silently vanished.
        newline = chr(10)
        text = ("noise {not json}" + newline + '{"input_i" : "-24.30"}' + newline
                + "Conversion failed }")
        self.assertEqual(_decode_summary(text)["input_i"], "-24.30")

    def test_a_summary_without_input_i_is_not_accepted(self):
        self.assertIsNone(_decode_summary('{"something" : "else"}'))

    def test_no_json_at_all_returns_none(self):
        self.assertIsNone(_decode_summary("ffmpeg: protocol not found"))

    def test_a_missing_file_explains_itself(self):
        stats, error = measure_with_diagnostics(WORK / "does-not-exist.wav")
        self.assertEqual(stats, {})
        self.assertTrue(error, "a failed measurement must say why")

    def test_a_good_file_reports_no_error(self):
        path = _write_tone(WORK / "diag.wav", 0.2)
        stats, error = measure_with_diagnostics(path)
        self.assertEqual(error, "")
        self.assertIn("integrated_lufs", stats)


class MeasurementTests(unittest.TestCase):
    def test_quiet_tone_measures_far_below_reference(self):
        path = _write_tone(WORK / "quiet.wav", 0.03)
        stats = measure(path)
        self.assertIn("integrated_lufs", stats)
        self.assertLess(stats["integrated_lufs"], -25.0)
        self.assertLess(stats["true_peak_dbtp"], -25.0)

    def test_missing_file_reports_nothing_instead_of_raising(self):
        self.assertEqual(measure(WORK / "nope.wav"), {})


class NormalisationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _write_tone(WORK / "mix.wav", 0.03, duration=3.0)

    def test_quiet_mix_is_lifted_to_reference(self):
        target = WORK / "mix_norm.wav"
        report = normalize_file(self.source, output=target)
        self.assertTrue(report["applied"], report)
        after = report["after"]
        self.assertAlmostEqual(after["integrated_lufs"], LOUDNESS_TARGET["I"], delta=1.5)
        self.assertLessEqual(after["true_peak_dbtp"], -1.0)
        self.assertLess(report["before"]["integrated_lufs"], -25.0)

    def test_duration_is_preserved_so_sync_cannot_drift(self):
        target = WORK / "mix_norm_duration.wav"
        report = normalize_file(self.source, output=target, keep_duration=3.0)
        self.assertTrue(report["applied"], report)
        self.assertAlmostEqual(report["duration_after"], 3.0, delta=0.02)
        self.assertAlmostEqual(report["duration_delta"], 0.0, delta=0.02)

    def test_normalising_in_place_replaces_the_file(self):
        working = _write_tone(WORK / "inplace.wav", 0.02)
        before = measure(working)["integrated_lufs"]
        report = normalize_file(working)
        self.assertTrue(report["applied"], report)
        after = measure(working)["integrated_lufs"]
        self.assertGreater(after, before + 10.0)
        self.assertAlmostEqual(after, LOUDNESS_TARGET["I"], delta=1.5)

    def test_a_loud_mix_is_turned_down(self):
        loud = _write_tone(WORK / "loud.wav", 0.9, duration=2.0)
        report = normalize_file(loud, output=WORK / "loud_norm.wav")
        self.assertTrue(report["applied"], report)
        self.assertLess(report["after"]["integrated_lufs"],
                        report["before"]["integrated_lufs"])
        self.assertLessEqual(report["after"]["true_peak_dbtp"], -1.0)


class ToleranceTests(unittest.TestCase):
    def test_the_measured_old_output_would_fail(self):
        ok, detail = within_tolerance({"integrated_lufs": -24.3, "true_peak_dbtp": -11.0})
        self.assertFalse(ok)
        self.assertIn("outside", detail)

    def test_a_reference_level_mix_passes(self):
        ok, detail = within_tolerance({"integrated_lufs": -14.1, "true_peak_dbtp": -1.4})
        self.assertTrue(ok, detail)

    def test_clipping_true_peak_fails_even_at_the_right_level(self):
        ok, detail = within_tolerance({"integrated_lufs": -14.0, "true_peak_dbtp": -0.2})
        self.assertFalse(ok)
        self.assertIn("true peak", detail)

    def test_unmeasurable_audio_fails_rather_than_passing(self):
        self.assertFalse(within_tolerance({})[0])

    def test_the_accepted_window_brackets_the_target(self):
        low, high = ACCEPTED_RANGE
        self.assertLess(low, LOUDNESS_TARGET["I"])
        self.assertGreater(high, LOUDNESS_TARGET["I"])


if __name__ == "__main__":
    unittest.main()
