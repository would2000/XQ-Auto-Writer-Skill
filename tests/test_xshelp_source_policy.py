from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"


class XSHelpSourcePolicyTests(unittest.TestCase):
    def test_repository_policy_allows_controlled_distillation(self) -> None:
        policy = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("專用知識維護任務", policy)
        self.assertIn("受控、分批、可恢復", policy)
        self.assertIn("不受三頁限制", policy)
        self.assertIn("checkpoint", policy)
        self.assertIn("原子寫入", policy)
        self.assertNotIn("XSHelp 每次最多即時讀取三頁", policy)

    def test_distillation_preserves_metadata_only_index_boundary(self) -> None:
        policy = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        official = (SKILL_ROOT / "references" / "official-knowledge.md").read_text(
            encoding="utf-8"
        )
        index = json.loads(
            (PROJECT_ROOT / "third_party" / "xshelp" / "index.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertFalse(index["body_text_stored"])
        for text in (policy, official):
            self.assertIn("body_text_stored", text)
            self.assertIn("完整官方範例", text)
            self.assertIn("原始", text)
            self.assertIn("文件蒸餾", text)
            self.assertIn("編譯器驗證", text)

    def test_skill_and_human_docs_explain_both_read_modes(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        official = (SKILL_ROOT / "references" / "official-knowledge.md").read_text(
            encoding="utf-8"
        )
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("ordinary script writing", skill)
        self.assertIn("knowledge-maintenance task", skill)
        self.assertIn("一般腳本撰寫", official)
        self.assertIn("專用知識維護", official)
        self.assertIn("專用知識維護", readme)

    def test_changelog_records_policy_change(self) -> None:
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## [0.2.0]", maxsplit=1)[0]

        self.assertIn("調整 XSHelp 來源政策", unreleased)
        self.assertIn("body_text_stored: false", unreleased)


if __name__ == "__main__":
    unittest.main()
