"""Every third-party import must be declared in requirements.txt.

CI installs only what requirements.txt lists, so an undeclared import (soundfile was
the first one) fails on the runner even though a developer machine has it installed.
This test turns that into a local failure instead of a red CI run.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("factory", "studio", "uploader")
REQUIREMENTS = REPO_ROOT / "requirements.txt"
# Distribution name -> import name(s), when they differ or are not the only export.
DISTRIBUTION_ALIASES = {
    "pillow": {"PIL"},
    "edge-tts": {"edge_tts"},
    "gtts": {"gtts"},
    "pycairo": {"cairo"},
    "soundfile": {"soundfile"},
    "numpy": {"numpy"},
}
# Import names provided by the repository itself.
LOCAL_MODULES = set(PACKAGES) | {"tests"}


def _declared_imports() -> set[str]:
    names: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        distribution = re.split(r"[=<>!\[]", line)[0].strip().lower()
        names.add(distribution)
        names.update(DISTRIBUTION_ALIASES.get(distribution, set()))
    return names


def _imported_modules() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for package in PACKAGES:
        for path in (REPO_ROOT / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        found.setdefault(alias.name.split(".")[0], path)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import inside the package
                        continue
                    if node.module:
                        found.setdefault(node.module.split(".")[0], path)
    return found


class DeclaredDependencyTests(unittest.TestCase):
    def test_no_undeclared_third_party_imports(self) -> None:
        declared = _declared_imports()
        stdlib = set(sys.stdlib_module_names)
        undeclared = {
            name: path
            for name, path in _imported_modules().items()
            if name not in declared and name not in stdlib and name not in LOCAL_MODULES
        }
        self.assertEqual(
            undeclared,
            {},
            "imports missing from requirements.txt: "
            + ", ".join(f"{name} ({path.relative_to(REPO_ROOT)})" for name, path in sorted(undeclared.items())),
        )

    def test_requirements_file_is_pinned(self) -> None:
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            self.assertRegex(entry, r"^[A-Za-z0-9_.\-]+(==[0-9][^\s]*)?$", f"unpinned requirement: {entry}")


if __name__ == "__main__":
    unittest.main()
