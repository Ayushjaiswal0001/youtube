"""The publishing gate (T49 / Part 7).

The gate's job is a decision, so these tests drive the decision: with complete evidence it passes,
and with each kind of missing or wrong evidence it blocks. The media measurements are stubbed here so
the tests are about the gate's logic; the gate itself was also run against a real 32 s artifact, where
it went from 22/23 (missing manifest) to 24/24 once the manifest existed.
"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from factory.config import load_channel_specs
from factory.content.models import Script, ScriptLine
from factory.qa import publish_gate as gate_mod
from factory.qa.publish_gate import _rate, _srt_is_valid, evaluate_publish_gate

SPEC = replace(load_channel_specs()["natkhat-toons"], format="shorts")


def _script():
    return Script(
        channel="natkhat-toons", language="hi", format="shorts",
        topic="t", title="हवेली की चाबी", hook="h", moral="m",
        description="desc", tags=["a", "b"],
        lines=[ScriptLine(text="x", start=0.0, end=4.0)],
        style="toon", metadata={"plan_id": "p"},
    )


class SrtTests(unittest.TestCase):
    def test_a_valid_file_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,500\nपहला\n\n"
                            "2\n00:00:01,600 --> 00:00:03,000\nदूसरा\n", encoding="utf-8")
            ok, detail = _srt_is_valid(path)
        self.assertTrue(ok, detail)
        self.assertIn("2 cues", detail)

    def test_an_overlapping_cue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:02,000\nअ\n\n"
                            "2\n00:00:01,000 --> 00:00:03,000\nब\n", encoding="utf-8")
            ok, detail = _srt_is_valid(path)
        self.assertFalse(ok)
        self.assertIn("overlapping", detail)

    def test_an_empty_cue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.srt"
            path.write_text("1\n00:00:02,000 --> 00:00:02,000\nअ\n", encoding="utf-8")
            ok, _ = _srt_is_valid(path)
        self.assertFalse(ok)

    def test_a_missing_file_is_rejected(self):
        ok, detail = _srt_is_valid(Path("/nope/c.srt"))
        self.assertFalse(ok)
        self.assertEqual(detail, "missing")


class RateTests(unittest.TestCase):
    def test_a_fraction_is_parsed(self):
        self.assertEqual(_rate("30/1"), 30.0)

    def test_ntsc_is_not_thirty(self):
        self.assertAlmostEqual(_rate("30000/1001"), 29.97, places=2)

    def test_garbage_is_zero(self):
        self.assertEqual(_rate(None), 0.0)


class GateDecisionTests(unittest.TestCase):
    """Every check is fed a plausible-but-wrong value in turn and must block."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.video = self.out / "video.mp4"
        self.video.write_bytes(b"\0" * 200_000)
        for name, payload in (
            ("qc.json", {"ok": True, "checks": [
                {"name": "frozen_frames", "ok": True, "detail": "none"},
                {"name": "audio_loudness", "ok": True, "detail": ""}]}),
            ("framing.json", {"cropped_required_frames": 0, "subtitle_collision_frames": 0}),
            ("shot_plan.json", {"decisions": [{}] * 4, "warnings": []}),
            ("timeline.json", {"scenes": []}),
            ("script.json", {}),
            ("story.json", {}),
            ("captions.srt", "1\n00:00:00,000 --> 00:00:01,000\nअ\n"),
        ):
            (self.out / name).write_text(
                json.dumps(payload, ensure_ascii=False) if name.endswith(".json") else payload,
                encoding="utf-8")
        from PIL import Image

        Image.new("RGB", (1280, 720), (10, 10, 30)).save(self.out / "thumbnail.jpg", "JPEG")
        # The manifest is built by the same routine production uses, over every artifact this fixture writes.
        # It used to be a hand-written one-entry manifest, which the gate accepted because it only checked the
        # entries it was given; a package with seven unlisted artifacts was "complete". The gate now verifies
        # the whole package, so the fixture has to be a real one.
        from factory import manifesting

        manifesting.rebuild(self.out, channel=SPEC.slug, plan_id="fixture", format=SPEC.format)
        self.manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))

        self.patches = [
            mock.patch.object(gate_mod, "ffprobe_streams", return_value={"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                 "avg_frame_rate": "30/1", "start_time": "0.000000", "duration": "30.0"},
                {"codec_type": "audio", "codec_name": "aac", "start_time": "0.000000",
                 "duration": "30.0"}]}),
            mock.patch.object(gate_mod, "ffprobe_duration", return_value=30.0),
            mock.patch.object(gate_mod, "_decode_errors", return_value=None),
            mock.patch.object(gate_mod, "_measure_loudness",
                              return_value={"integrated_lufs": -14.1, "true_peak_dbtp": -1.4}),
            mock.patch.object(gate_mod, "_silence_seconds", return_value=1.0),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def _gate(self, **kwargs):
        return evaluate_publish_gate(SPEC, _script(), self.video, out_dir=self.out, **kwargs)

    def test_a_complete_package_passes(self):
        gate = self._gate()
        self.assertTrue(gate.ok, gate.to_dict())
        self.assertGreaterEqual(gate.to_dict()["total"], 20)

    def test_the_check_names_match_what_the_render_emits(self):
        names = {check.name for check in self._gate().checks}
        for expected in ("mp4_container", "video_stream", "audio_stream", "resolution",
                         "frame_rate", "duration", "decode_clean", "av_sync", "loudness",
                         "silence_policy", "subtitles", "framing", "caption_clearance",
                         "shot_continuity", "thumbnail", "metadata_title", "manifest"):
            self.assertIn(expected, names)

    def test_a_wrong_resolution_blocks(self):
        with mock.patch.object(gate_mod, "ffprobe_streams", return_value={"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                 "avg_frame_rate": "30/1", "start_time": "0", "duration": "30.0"},
                {"codec_type": "audio", "codec_name": "aac", "start_time": "0",
                 "duration": "30.0"}]}):
            gate = self._gate()
        self.assertIn("resolution", gate.blockers)

    def test_a_wrong_frame_rate_blocks(self):
        with mock.patch.object(gate_mod, "ffprobe_streams", return_value={"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                 "avg_frame_rate": "30000/1001", "start_time": "0", "duration": "30.0"},
                {"codec_type": "audio", "codec_name": "aac", "start_time": "0",
                 "duration": "30.0"}]}):
            gate = self._gate()
        self.assertIn("frame_rate", gate.blockers)

    def test_a_short_video_blocks(self):
        with mock.patch.object(gate_mod, "ffprobe_duration", return_value=5.0):
            gate = self._gate()
        self.assertIn("duration", gate.blockers)

    def test_decode_errors_block(self):
        with mock.patch.object(gate_mod, "_decode_errors", return_value="Invalid NAL unit"):
            gate = self._gate()
        self.assertIn("decode_clean", gate.blockers)

    def test_missing_audio_blocks(self):
        with mock.patch.object(gate_mod, "ffprobe_streams", return_value={"streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920,
                 "avg_frame_rate": "30/1", "start_time": "0", "duration": "30.0"}]}):
            gate = self._gate()
        self.assertIn("audio_stream", gate.blockers)

    def test_a_loud_track_blocks(self):
        with mock.patch.object(gate_mod, "_measure_loudness",
                               return_value={"integrated_lufs": -8.0, "true_peak_dbtp": 0.4}):
            gate = self._gate()
        self.assertIn("loudness", gate.blockers)

    def test_excessive_silence_blocks(self):
        with mock.patch.object(gate_mod, "_silence_seconds", return_value=29.0):
            gate = self._gate()
        self.assertIn("silence_policy", gate.blockers)

    def test_a_missing_manifest_blocks(self):
        (self.out / "manifest.json").unlink()
        gate = self._gate()
        self.assertIn("manifest", gate.blockers)

    def test_a_tampered_artifact_blocks(self):
        with (self.out / "video.mp4").open("ab") as handle:
            handle.write(b"tampered")
        gate = self._gate()
        self.assertIn("manifest", gate.blockers)

    def test_missing_framing_evidence_blocks(self):
        (self.out / "framing.json").unlink()
        gate = self._gate()
        self.assertIn("framing", gate.blockers)

    def test_a_cropped_character_blocks(self):
        (self.out / "framing.json").write_text(
            json.dumps({"cropped_required_frames": 12, "subtitle_collision_frames": 0}),
            encoding="utf-8")
        gate = self._gate()
        self.assertIn("framing", gate.blockers)

    def test_a_face_under_the_caption_blocks(self):
        (self.out / "framing.json").write_text(
            json.dumps({"cropped_required_frames": 0, "subtitle_collision_frames": 40}),
            encoding="utf-8")
        gate = self._gate()
        self.assertIn("caption_clearance", gate.blockers)

    def test_a_shot_continuity_violation_blocks(self):
        (self.out / "shot_plan.json").write_text(
            json.dumps({"decisions": [{}] * 4,
                        "warnings": ["scene 3: medium_chiku frames gappu while gappu speaks"]}),
            encoding="utf-8")
        gate = self._gate()
        self.assertIn("shot_continuity", gate.blockers)

    def test_an_overlong_title_blocks(self):
        script = _script()
        script.title = "x" * 101
        gate = evaluate_publish_gate(SPEC, script, self.video, out_dir=self.out)
        self.assertIn("metadata_title", gate.blockers)

    def test_a_missing_thumbnail_blocks(self):
        (self.out / "thumbnail.jpg").unlink()
        gate = self._gate()
        self.assertIn("thumbnail", gate.blockers)

    def test_the_report_is_machine_readable(self):
        payload = self._gate().to_dict()
        self.assertEqual(set(payload) >= {"ok", "checks", "blockers", "passed", "total"}, True)
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
