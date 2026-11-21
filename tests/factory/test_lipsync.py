"""Lip-sync tests: the mouth must follow the narration, not a fixed sine wave."""

from __future__ import annotations

import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from studio.characters.lipsync import SILENCE_FLOOR, VisemeTrack, viseme_for
from studio.characters.rig_base import Viseme

RATE = 16000


def _write_bursts(path: Path, pattern: list[tuple[float, float]], rate: int = RATE) -> Path:
    """Write a WAV with (duration, amplitude) segments so speech/silence is unambiguous."""

    frames = bytearray()
    for seconds, amplitude in pattern:
        count = int(seconds * rate)
        for index in range(count):
            value = int(amplitude * 30000 * math.sin(2 * math.pi * 180 * index / rate))
            frames += struct.pack("<h", max(-32768, min(32767, value)))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


class VisemeMappingTests(unittest.TestCase):
    def test_closed_below_floor(self) -> None:
        self.assertEqual(viseme_for(0.0), Viseme.CLOSED)
        self.assertEqual(viseme_for(SILENCE_FLOOR / 2), Viseme.CLOSED)

    def test_openness_ordering(self) -> None:
        states = [viseme_for(value) for value in (0.1, 0.3, 0.65, 0.95)]
        self.assertEqual(states, [Viseme.SMILE, Viseme.OPEN_SMALL, Viseme.OPEN_WIDE, Viseme.SURPRISED])


class VisemeTrackTests(unittest.TestCase):
    def _track(self) -> VisemeTrack:
        samples = []
        for index in range(RATE * 2):
            loud = (index // (RATE // 4)) % 2 == 0  # 250 ms on, 250 ms off
            amplitude = 0.6 if loud else 0.0
            samples.append(amplitude * math.sin(2 * math.pi * 190 * index / RATE))
        return VisemeTrack.from_samples(samples, fps=30, sample_rate=RATE)

    def test_frames_in_word_are_open_and_gaps_closed(self) -> None:
        track = self._track()
        self.assertGreaterEqual(len(track), 55)
        for index, value in enumerate(track.openness):
            t = index / track.fps
            in_word = ((int(t * 4)) % 2) == 0
            if in_word and 0.12 < (t % 0.5) < 0.40:
                self.assertGreater(value, SILENCE_FLOOR, f"frame {index} inside a word stayed closed")
            # allow ~80 ms of natural release before demanding a closed mouth
            if not in_word and 0.33 < (t % 0.5) < 0.47:
                self.assertLess(value, 0.25, f"frame {index} in silence opened too far")

    def test_silence_only_audio_is_all_closed(self) -> None:
        track = VisemeTrack.from_samples([0.0] * RATE, fps=30, sample_rate=RATE)
        self.assertIn(len(track), (30, 31))
        self.assertTrue(all(value == 0.0 for value in track.openness))
        self.assertFalse(any(track.speaking_at(index / 30) for index in range(len(track))))

    def test_interpolation_and_bounds(self) -> None:
        track = VisemeTrack(fps=2.0, openness=[0.0, 1.0])
        self.assertEqual(track.at(-1.0), 0.0)
        self.assertAlmostEqual(track.at(0.25), 0.5, places=6)
        self.assertAlmostEqual(track.at(0.0), 0.0, places=6)
        # past the end the mouth closes again rather than sticking open
        self.assertEqual(track.at(10.0), 0.0)

    def test_empty_track_is_safe(self) -> None:
        track = VisemeTrack(fps=30, openness=[])
        self.assertEqual(len(track), 0)
        self.assertEqual(track.at(1.0), 0.0)
        self.assertEqual(track.viseme_at(1.0), Viseme.CLOSED)


class RigIntegrationTests(unittest.TestCase):
    def test_rig_uses_track_instead_of_sine(self) -> None:
        from studio.characters.chiku import ChikuRig

        rig = ChikuRig()
        track = VisemeTrack(fps=30, openness=[0.0] * 30 + [0.9] * 30)
        sine_samples = []
        for frame in range(0, 60, 5):
            rig.update_pose("idle", frame / 30, is_talking=True, phoneme_intensity=1.0)
            sine_samples.append(rig.mouth_open)
        driven = []
        for frame in range(0, 60, 5):
            rig.update_pose("idle", frame / 30, is_talking=True, phoneme_intensity=1.0, lipsync=track)
            driven.append(rig.mouth_open)
        self.assertTrue(any(value > 0.0 for value in sine_samples))
        self.assertEqual(driven[:6], [0.0] * 6, "mouth must stay shut while the track is silent")
        self.assertTrue(all(value > 0.5 for value in driven[6:]), "mouth must open during speech frames")
        self.assertNotEqual(sine_samples, driven)

    def test_rig_ignores_track_when_not_talking(self) -> None:
        from studio.characters.chiku import ChikuRig

        rig = ChikuRig()
        track = VisemeTrack(fps=30, openness=[1.0] * 30)
        rig.update_pose("idle", 0.5, is_talking=False, lipsync=track)
        self.assertEqual(rig.mouth_open, 0.0)
        self.assertEqual(rig.viseme, Viseme.SMILE)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not available")
class FromAudioTests(unittest.TestCase):
    def test_real_audio_file_produces_a_track(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_bursts(
                Path(tmp) / "voice.wav",
                [(0.5, 0.5), (0.5, 0.0), (0.5, 0.5), (0.5, 0.0)],
            )
            track = VisemeTrack.from_audio(path, fps=30)
            self.assertGreaterEqual(len(track), 55)
            self.assertGreater(track.at(0.2), SILENCE_FLOOR)
            self.assertLess(track.at(0.75), 0.25)
            self.assertGreater(track.at(1.2), SILENCE_FLOOR)

    def test_missing_file_returns_empty_track(self) -> None:
        track = VisemeTrack.from_audio("does/not/exist.mp3", fps=30)
        self.assertEqual(len(track), 0)
        self.assertTrue(track.source.startswith("missing"))


if __name__ == "__main__":
    unittest.main()
