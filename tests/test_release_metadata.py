from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_release_metadata.py"
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_release_metadata import (  # noqa: E402
    ReleaseMetadataError,
    load_release_metadata,
)


def changelog(*releases: tuple[str, str]) -> str:
    entries = "\n".join(
        f"## [{version}] - {release_date}\n\n### 新增\n\n- 測試版本 {version}\n"
        for version, release_date in releases
    )
    return f"# 更新紀錄\n\n## [Unreleased]\n\n### 新增\n\n{entries}"


class ReleaseMetadataTests(unittest.TestCase):
    def write_metadata(self, root: Path, version: str, change_text: str) -> None:
        (root / "VERSION").write_text(version, encoding="utf-8")
        (root / "CHANGELOG.md").write_text(change_text, encoding="utf-8")

    def assert_invalid(
        self, version: str | None, change_text: str | None, message: str
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            if version is not None:
                (root / "VERSION").write_text(version, encoding="utf-8")
            if change_text is not None:
                (root / "CHANGELOG.md").write_text(change_text, encoding="utf-8")
            with self.assertRaisesRegex(ReleaseMetadataError, message):
                load_release_metadata(root)

    def test_create_write_read_update_save_reload_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_metadata(root, "0.1.0\n", changelog(("0.1.0", "2026-07-18")))

            created = load_release_metadata(root)
            self.assertEqual(created.version, "0.1.0")
            self.assertIsInstance(created.version, str)
            self.assertEqual(created.release_count, 1)
            self.assertIsInstance(created.release_count, int)
            self.assertEqual(created.latest_release_date, "2026-07-18")
            self.assertEqual(created.changelog_versions, ["0.1.0"])

            self.write_metadata(
                root,
                "0.2.0\n",
                changelog(("0.2.0", "2026-07-19"), ("0.1.0", "2026-07-18")),
            )
            reloaded = load_release_metadata(root)
            self.assertEqual(reloaded.version, "0.2.0")
            self.assertEqual(reloaded.release_count, 2)
            self.assertEqual(reloaded.latest_release_date, "2026-07-19")
            self.assertEqual(reloaded.changelog_versions, ["0.2.0", "0.1.0"])
            self.assertEqual((root / "VERSION").read_text(encoding="utf-8"), "0.2.0\n")

            cleanup_target = root
        self.assertFalse(cleanup_target.exists())

    def test_invalid_and_boundary_metadata(self) -> None:
        valid = changelog(("0.1.0", "2026-07-19"))
        cases = [
            (None, valid, "Missing required file: VERSION"),
            ("0.1.0\n", None, "Missing required file: CHANGELOG.md"),
            ("", valid, "exactly one non-empty line"),
            ("0.1.0\n0.1.1\n", valid, "exactly one non-empty line"),
            ("v0.1.0\n", valid, "must not include the tag prefix"),
            ("01.0.0\n", valid, "not valid Semantic Versioning"),
            ("1." + "0" * 130, valid, "128-character safety limit"),
            (
                "0.1.0\n",
                valid.replace("## [Unreleased]", "## [Unreleased]\n\n## [Unreleased]"),
                "exactly one '## \\[Unreleased\\]' heading",
            ),
            (
                "0.1.0\n",
                valid + "\n## [0.1.0] - 2026-07-18\n",
                "duplicate release version",
            ),
            ("0.2.0\n", valid, "VERSION must match"),
            (
                "0.1.0\n",
                changelog(("0.1.0", "2026-02-30")),
                "invalid release date",
            ),
            (
                "0.1.0\n",
                "# 更新紀錄\n\n## 說明\n\n## [Unreleased]\n\n"
                "## [0.1.0] - 2026-07-19\n",
                "must be the first level-two heading",
            ),
            (
                "0.1.0\n",
                changelog(("0.1.0", "2026-07-18"), ("0.0.9", "2026-07-19")),
                "release dates must be in descending order",
            ),
            (
                "0.1.0\n",
                valid + "\n## Notes\n",
                "Invalid CHANGELOG.md release heading",
            ),
        ]
        for version, change_text, message in cases:
            with self.subTest(message=message):
                self.assert_invalid(version, change_text, message)

    def test_cli_exit_codes_and_single_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.write_metadata(root, "1.2.3\n", changelog(("1.2.3", "2026-07-19")))
            success = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(success.stderr, "")
            success_lines = success.stdout.splitlines()
            self.assertEqual(len(success_lines), 1)
            self.assertEqual(json.loads(success_lines[0])["status"], "success")

            (root / "VERSION").write_text("not-a-version\n", encoding="utf-8")
            failure = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(failure.returncode, 3, failure.stderr)
            self.assertEqual(failure.stderr, "")
            failure_lines = failure.stdout.splitlines()
            self.assertEqual(len(failure_lines), 1)
            failure_payload = json.loads(failure_lines[0])
            self.assertEqual(failure_payload["status"], "automation_error")
            self.assertIn("not valid Semantic Versioning", failure_payload["message"])

    def test_invalid_utf8_and_filesystem_read_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "VERSION").write_bytes(b"\xff\xfe\x00")
            (root / "CHANGELOG.md").write_text(
                changelog(("0.1.0", "2026-07-19")), encoding="utf-8"
            )
            with self.assertRaisesRegex(ReleaseMetadataError, "Cannot read VERSION as UTF-8"):
                load_release_metadata(root)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "VERSION").mkdir()
            (root / "CHANGELOG.md").write_text(
                changelog(("0.1.0", "2026-07-19")), encoding="utf-8"
            )
            with self.assertRaisesRegex(ReleaseMetadataError, "Cannot read VERSION"):
                load_release_metadata(root)


if __name__ == "__main__":
    unittest.main()
