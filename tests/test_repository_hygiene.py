from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_repository_hygiene.py"
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.check_repository_hygiene import inspect_repository  # noqa: E402


VALID_SKILL = """---
name: test-skill
description: "A test skill used only inside an isolated repository."
---

# Test Skill
"""


class RepositoryHygieneTests(unittest.TestCase):
    def initialize_repository(self, root: Path) -> None:
        (root / "docs").mkdir()
        (root / ".agents" / "skills" / "test-skill").mkdir(parents=True)
        (root / "generated").mkdir()
        (root / "README.md").write_text(
            "# Test\n\nRead [the guide](docs/guide.md).\n", encoding="utf-8"
        )
        (root / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
        (root / ".agents" / "skills" / "test-skill" / "SKILL.md").write_text(
            VALID_SKILL, encoding="utf-8"
        )
        (root / "generated" / ".gitkeep").write_text("", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
        self.stage_all(root)

    def stage_all(self, root: Path) -> None:
        subprocess.run(["git", "add", "--", "."], cwd=root, check=True, capture_output=True)

    def test_create_write_read_update_save_reload_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_repository(root)

            created = inspect_repository(root)
            self.assertEqual(created.status, "success")
            self.assertEqual(created.finding_count, 0)
            self.assertEqual(created.skill_files, 1)
            self.assertIsInstance(created.tracked_files, int)

            (root / "README.md").write_text(
                "# Test\n\nRead [missing](docs/missing.md).\n", encoding="utf-8"
            )
            self.stage_all(root)
            updated = inspect_repository(root)
            self.assertEqual(updated.status, "automation_error")
            self.assertIn("markdown_link", {finding.category for finding in updated.findings})

            (root / "README.md").write_text(
                "# Test\n\nRead [the guide](docs/guide.md).\n", encoding="utf-8"
            )
            self.stage_all(root)
            reloaded = inspect_repository(root)
            self.assertEqual(reloaded.status, "success")
            cleanup_target = root
        self.assertFalse(cleanup_target.exists())

    def test_failure_and_boundary_findings(self) -> None:
        cases = {
            "secret": (
                "README.md",
                "ghp_" + "abcdefghijklmnopqrstuvwxyz123456\n",
            ),
            "local_path": ("README.md", "C:\\Users\\Example\\secret.txt\n"),
            "trailing_whitespace": ("README.md", "# Test \n"),
            "markdown_fence": ("README.md", "# Test\n\n```text\nopen\n"),
            "markdown_link": ("README.md", "[missing](not-there.md)\n"),
            "skill_frontmatter": (
                ".agents/skills/test-skill/SKILL.md",
                "# Missing frontmatter\n",
            ),
            "forbidden_path": ("generated/private-strategy.xs", "ret = 1;\n"),
        }
        for expected_category, (relative_path, content) in cases.items():
            with self.subTest(expected_category=expected_category):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    self.initialize_repository(root)
                    target = root / relative_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    self.stage_all(root)
                    report = inspect_repository(root)
                    categories = {finding.category for finding in report.findings}
                    self.assertEqual(report.status, "automation_error")
                    self.assertIn(expected_category, categories)

    def test_cli_exit_codes_and_single_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_repository(root)
            success = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(len(success.stdout.splitlines()), 1)
            self.assertEqual(json.loads(success.stdout)["status"], "success")

            (root / "README.md").write_text("D:\\Projects\\private\n", encoding="utf-8")
            self.stage_all(root)
            failure = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(failure.returncode, 3, failure.stderr)
            self.assertEqual(len(failure.stdout.splitlines()), 1)
            payload = json.loads(failure.stdout)
            self.assertEqual(payload["status"], "automation_error")
            self.assertGreater(payload["finding_count"], 0)

    def test_invalid_utf8_and_non_repository_cli_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self.initialize_repository(root)
            (root / "README.md").write_bytes(b"\xff\xfe\x00")
            self.stage_all(root)
            report = inspect_repository(root)
            self.assertEqual(report.status, "automation_error")
            self.assertIn("utf8", {finding.category for finding in report.findings})

        with tempfile.TemporaryDirectory() as temporary_directory:
            not_a_repository = Path(temporary_directory)
            failure = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--root", str(not_a_repository)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(failure.returncode, 3, failure.stderr)
            self.assertEqual(len(failure.stdout.splitlines()), 1)
            payload = json.loads(failure.stdout)
            self.assertEqual(payload["status"], "automation_error")
            self.assertIn("git ls-files failed", payload["message"])


if __name__ == "__main__":
    unittest.main()
