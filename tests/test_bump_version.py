from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.bump_version import bump_semver, update_version_text


SAMPLE_VERSION = '''VERSION = "1.2.3"

HISTORY = [
    ("1.2.3", "2026-06-20", "Previous change"),
]

def get_version():
    return VERSION
'''


class BumpVersionTests(unittest.TestCase):
    def test_bump_semver(self) -> None:
        self.assertEqual(bump_semver("1.2.3", "patch"), "1.2.4")
        self.assertEqual(bump_semver("1.2.3", "minor"), "1.3.0")
        self.assertEqual(bump_semver("1.2.3", "major"), "2.0.0")

    def test_update_version_text_prepends_history_entry(self) -> None:
        updated, old_version, new_version = update_version_text(
            SAMPLE_VERSION,
            level="patch",
            change="Add release helper",
            entry_date="2026-06-21",
        )

        self.assertEqual(old_version, "1.2.3")
        self.assertEqual(new_version, "1.2.4")
        self.assertIn('VERSION = "1.2.4"', updated)
        self.assertIn('    ("1.2.4", "2026-06-21", "Add release helper"),', updated)
        self.assertLess(updated.index('"1.2.4"'), updated.index('"1.2.3"'))

    def test_cli_updates_version_file(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            version_file = Path(tempdir) / "version.py"
            version_file.write_text(SAMPLE_VERSION, encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "scripts/bump_version.py",
                    "minor",
                    "Add release helper",
                    "--date",
                    "2026-06-21",
                    "--version-file",
                    str(version_file),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Bumped version: 1.2.3 -> 1.3.0", result.stdout)
            updated = version_file.read_text(encoding="utf-8")
            self.assertIn('VERSION = "1.3.0"', updated)
            self.assertIn('("1.3.0", "2026-06-21", "Add release helper")', updated)


if __name__ == "__main__":
    unittest.main()
