"""A forced re-render must reproduce the same video (T41 prerequisite).

This exists because it did not. `--force` deleted the whole studio tree, including the recorded
dialogue, so every render re-synthesised speech through Edge-TTS. That service does not return the
same bytes for the same line twice, the visemes are derived from the audio envelope, and so the
mouths - and therefore the video - changed slightly on every render. Two consequences:

* a before/after comparison could not be trusted, which is how a delta of about 48 dB PSNR stayed
  unexplained across two milestones;
* an episode became impossible to re-render while the TTS service was unreachable, even though its
  audio was already on disk.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.media.hindi_renderer import _purge_render_outputs


def _make_tree(root: Path) -> None:
    (root / "intermediate" / "ep").mkdir(parents=True)
    (root / "episodes").mkdir(parents=True)
    audio = root / "intermediate"
    (audio / "ep_s1_narrator.mp3").write_bytes(b"voice-one")
    (audio / "ep_s1_narrator.boundaries.json").write_text("[]", encoding="utf-8")
    (audio / "scene_001_mixed.wav").write_bytes(b"mix")
    (root / "intermediate" / "ep" / "scene_001.mp4").write_bytes(b"video")
    (root / "intermediate" / "ep" / "project.json").write_text("{}", encoding="utf-8")
    (root / "episodes" / "ep_final.mp4").write_bytes(b"final")


class PurgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="purge-test-"))
        self.root = self.tmp / "studio"
        _make_tree(self.root)

    def tearDown(self):
        for path in sorted(self.tmp.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        self.tmp.rmdir()

    def test_a_forced_render_keeps_the_recorded_dialogue(self):
        _purge_render_outputs(self.root, keep_audio=True)
        self.assertTrue((self.root / "intermediate" / "ep_s1_narrator.mp3").is_file())
        self.assertTrue((self.root / "intermediate" / "ep_s1_narrator.boundaries.json").is_file())

    def test_a_forced_render_discards_derived_artifacts(self):
        _purge_render_outputs(self.root, keep_audio=True)
        self.assertFalse((self.root / "intermediate" / "scene_001_mixed.wav").exists())
        # The scene checkpoint has to go with the scenes, or a resume would skip them.
        self.assertFalse((self.root / "intermediate" / "ep" / "project.json").exists())
        self.assertFalse((self.root / "episodes" / "ep_final.mp4").exists())

    def test_the_kept_dialogue_is_byte_identical(self):
        _purge_render_outputs(self.root, keep_audio=True)
        self.assertEqual((self.root / "intermediate" / "ep_s1_narrator.mp3").read_bytes(),
                         b"voice-one")

    def test_asking_for_fresh_audio_removes_it(self):
        _purge_render_outputs(self.root, keep_audio=False)
        self.assertFalse((self.root / "intermediate" / "ep_s1_narrator.mp3").exists())

    def test_nothing_is_left_behind_beside_the_studio_tree(self):
        _purge_render_outputs(self.root, keep_audio=True)
        leftovers = [path.name for path in self.tmp.iterdir() if path.name != "studio"]
        self.assertEqual(leftovers, [], "the audio stash must not survive the purge")

    def test_the_renderer_asks_for_fresh_audio_only_when_told_to(self):
        source = (Path(__file__).resolve().parents[2]
                  / "factory" / "media" / "hindi_renderer.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("FACTORY_FRESH_AUDIO") == "1"', source)
        self.assertIn("_purge_render_outputs(studio_out, keep_audio=not purge_audio)", source)


if __name__ == "__main__":
    unittest.main()
