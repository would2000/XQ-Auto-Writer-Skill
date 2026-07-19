from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


class CIWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_read_only_permissions_and_pinned_actions(self) -> None:
        self.assertIn("permissions:\n  contents: read\n", self.workflow)
        self.assertNotIn("pull_request_target", self.workflow)
        self.assertNotIn("${{ secrets.", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("timeout-minutes: 10", self.workflow)

        action_references = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", self.workflow)
        self.assertGreater(len(action_references), 0)
        for reference in action_references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"^[^@]+@[0-9a-f]{40}$")

    def test_required_events_and_validation_commands(self) -> None:
        for event in ("pull_request:", "push:", "workflow_dispatch:"):
            with self.subTest(event=event):
                self.assertIn(event, self.workflow)
        for command in (
            "python scripts/check_release_metadata.py",
            "python scripts/check_repository_hygiene.py",
            "python -W error::ResourceWarning -m unittest discover -s tests -v",
            "python -m py_compile",
            "git submodule status --recursive",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.workflow)
        self.assertIn("Unable to Test（未驗證）", self.workflow)


if __name__ == "__main__":
    unittest.main()
