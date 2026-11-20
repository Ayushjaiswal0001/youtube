"""Every story pose is pinned by a golden frame (T30b).

The older golden set covered four poses per character. A change to limb state resetting
(T33) altered ``boast_proud`` and ``skeptical_eyebrow`` without any test noticing, which is
exactly the failure mode a golden set exists to prevent.
"""

from __future__ import annotations

import json
import unittest

from tools.capture_goldens import GOLDENS, POSES, build


class PoseGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = GOLDENS / "poses.json"
        if not path.is_file():
            raise unittest.SkipTest("pose goldens not captured (run tools.capture_goldens)")
        cls.recorded = json.loads(path.read_text(encoding="utf-8"))

    def test_every_pose_is_covered(self) -> None:
        for character, poses in POSES.items():
            for pose in poses:
                keys = [k for k in self.recorded if k.startswith(f"{character}__{pose}__")]
                self.assertTrue(keys, f"{character}/{pose} has no golden frame")

    def test_rendering_matches_the_recorded_frames(self) -> None:
        current = build()
        for key, digest in self.recorded.items():
            self.assertEqual(current.get(key), digest, f"{key} changed")

    def test_manifest_has_no_orphans(self) -> None:
        current = build()
        self.assertEqual(sorted(current), sorted(self.recorded))


if __name__ == "__main__":
    unittest.main()
