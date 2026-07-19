from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASING_PATH = PROJECT_ROOT / "docs" / "RELEASING.md"
AGENTS_PATH = PROJECT_ROOT / "AGENTS.md"
TEMPLATE_PATH = PROJECT_ROOT / "docs" / "release-notes-template.md"


class ReleaseWorkflowDocumentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.releasing = RELEASING_PATH.read_text(encoding="utf-8")
        self.agents = AGENTS_PATH.read_text(encoding="utf-8")
        self.template = TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_release_is_created_as_draft_before_publication(self) -> None:
        create_block = re.search(
            r'gh release create "v\$version"(?P<body>.*?)```',
            self.releasing,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(create_block)
        assert create_block is not None
        self.assertIn("--verify-tag", create_block.group("body"))
        self.assertIn("--draft", create_block.group("body"))

        publish_block = re.search(
            r'gh release edit "v\$version".*?--draft=false.*?--latest',
            self.releasing,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(publish_block)
        self.assertIn("不得直接建立正式 Release", self.agents)

    def test_published_release_requires_immutable_attestation(self) -> None:
        self.assertIn('gh release verify "v$version"', self.releasing)
        self.assertIn("isImmutable: true", self.releasing)
        self.assertIn("Release Immutable", self.template)
        self.assertIn("Release attestation", self.template)
        self.assertIn("Release Assets", self.template)

    def test_recovery_uses_a_patch_instead_of_mutation(self) -> None:
        for text in (self.releasing, self.agents):
            with self.subTest(path="release policy"):
                self.assertIn("PATCH", text)
                self.assertIn("替換附件", text)


if __name__ == "__main__":
    unittest.main()
