"""The audio that ships must be the audio that was measured.

Found when the suite failed on a fresh render with

    audio_loudness: EBU R128: true peak -0.23 dBTP above -1.0

`mix_narration` measures the true peak of the AAC file it writes and tightens its limiter until that file
passes the -1.0 dBTP gate. The renderers then muxed that file into the video with `-c:a aac -b:a 192k` - a
second encode of an already-encoded file. Decoding and re-encoding AAC adds inter-sample overshoot *after*
the measurement, so the guard approved a file that was not the one delivered, and the delivered episode
could sit above the gate by around a decibel depending on the material.

The renderers now copy the audio, so the measured file is the delivered file and the second generation of
loss is gone as well.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from factory.media.music import measure_loudness

RENDERERS = {
    "english_renderer": Path("factory/media/english_renderer.py"),
    "landscape_renderer": Path("factory/media/landscape_renderer.py"),
}


def mux_command_source(path: Path) -> str:
    """The ffmpeg invocation that writes the episode video, as text."""

    text = path.read_text(encoding="utf-8")
    start = text.index("mixed_audio")
    return text[start:start + 1200]


class TestDeliveredAudio:
    def test_the_renderers_copy_the_measured_audio(self) -> None:
        for name, path in RENDERERS.items():
            source = mux_command_source(path)
            assert '"-c:a", "copy"' in source or '"-c:a", "aac"' not in source, name
            assert '"aac"' not in source.split('"-c:a"', 1)[-1][:40], (
                f"{name} re-encodes the audio it just measured")

    def test_copying_preserves_the_measured_true_peak(self, tmp_path: Path) -> None:
        """The mechanism, on real audio: a copy measures the same as its source."""

        source = tmp_path / "source.m4a"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2,volume=6dB", "-ac", "2", "-ar", "44100",
             "-c:a", "aac", "-b:a", "192k", str(source)],
            check=True,
        )
        video = tmp_path / "video.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=black:s=160x284:r=30:d=2", "-i", str(source),
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-shortest", str(video)],
            check=True,
        )

        before = measure_loudness(source)["true_peak_dbtp"]
        after = measure_loudness(video)["true_peak_dbtp"]

        assert abs(after - before) <= 0.05, (
            f"copying changed the true peak: {before:.2f} -> {after:.2f} dBTP")
