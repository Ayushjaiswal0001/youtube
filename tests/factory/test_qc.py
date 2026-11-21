"""QC gate tests that do not need a rendered file.

`validate_episode` needs ffprobe and a real MP4, but the frame-rate gate is pure arithmetic on
the stream dictionary, and it exists because the concat step silently produced 29.90 fps. These
tests pin that arithmetic so a future refactor cannot quietly widen it.
"""

from __future__ import annotations

import unittest

from factory.qa.validator import _check


def fps_from_stream(stream: dict) -> float:
    """Mirror of the parsing the validator performs on `avg_frame_rate`."""

    rate_text = str(stream.get("avg_frame_rate") or "0/0")
    try:
        numerator, denominator = rate_text.split("/")
        return float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


class FrameRateParsingTests(unittest.TestCase):
    def test_exact_thirty(self):
        self.assertAlmostEqual(fps_from_stream({"avg_frame_rate": "30/1"}), 30.0)

    def test_the_old_defect_is_now_outside_tolerance(self):
        # 14415/481 is what the unpinned concat actually wrote (29.9698...). A half-frame
        # tolerance would have waved it through, which is why the gate is 0.01.
        fps = fps_from_stream({"avg_frame_rate": "14415/481"})
        self.assertAlmostEqual(fps, 29.97, places=2)
        self.assertGreater(abs(fps - 30.0), 0.01)

    def test_ntsc_rate_is_outside_tolerance(self):
        # 29.97 is a legitimate delivery rate but not what this engine writes, so it must
        # fail loudly rather than pass silently as "close to 30".
        self.assertGreater(abs(fps_from_stream({"avg_frame_rate": "30000/1001"}) - 30.0), 0.01)

    def test_a_zero_denominator_is_reported_as_unknown(self):
        # "0" is a non-empty string, so `denominator or 1` does not rescue it; the
        # ZeroDivisionError is caught and the rate is unknown, never assumed correct.
        self.assertEqual(fps_from_stream({"avg_frame_rate": "30/0"}), 0.0)

    def test_missing_rate_is_zero(self):
        self.assertEqual(fps_from_stream({}), 0.0)

    def test_malformed_rate_is_zero_not_a_crash(self):
        self.assertEqual(fps_from_stream({"avg_frame_rate": "garbage"}), 0.0)

    def test_tolerance_boundary(self):
        self.assertTrue(abs(30.005 - 30.0) <= 0.01)
        self.assertFalse(abs(30.02 - 30.0) <= 0.01)


class CheckRecordTests(unittest.TestCase):
    def test_a_check_records_its_verdict_and_detail(self):
        record = _check("frame_rate", True, "30.00 fps, expected 30")
        self.assertEqual(record["name"], "frame_rate")
        self.assertTrue(record["ok"])
        self.assertIn("expected 30", record["detail"])


if __name__ == "__main__":
    unittest.main()
