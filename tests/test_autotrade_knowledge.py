from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
REFERENCE_ROOT = SKILL_ROOT / "references"
GUIDE_PATH = REFERENCE_ROOT / "autotrade-official-guide.md"


class AutotradeKnowledgeTests(unittest.TestCase):
    def test_autotrade_workflow_routes_to_distilled_guide(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        types = (REFERENCE_ROOT / "xscript-types.md").read_text(encoding="utf-8")
        official = (REFERENCE_ROOT / "official-knowledge.md").read_text(encoding="utf-8")

        self.assertIn("references/autotrade-official-guide.md", skill)
        self.assertIn("autotrade-official-guide.md", types)
        self.assertIn("autotrade-official-guide.md", official)

    def test_guide_records_source_rights_and_no_body_storage(self) -> None:
        guide = GUIDE_PATH.read_text(encoding="utf-8")

        self.assertIn("2021-03-17", guide)
        self.assertIn("2026-07-20", guide)
        self.assertIn("body_text_stored", guide)
        self.assertIn("`false`", guide)
        self.assertIn("不建立爬蟲", guide)
        self.assertIn("未經授權不得翻載", guide)
        self.assertIn("https://www.xq.com.tw/xstrader/", guide)
        self.assertIn("https://xshelp.xq.com.tw/XSHelp/?HelpName=SetPosition", guide)

    def test_guide_contains_current_state_and_execution_contracts(self) -> None:
        guide = GUIDE_PATH.read_text(encoding="utf-8")

        for term in (
            "`Position`",
            "`Filled`",
            "`FilledAvgPrice`",
            "`FilledRecordCount`",
            "SetPosition(目標部位, 委託價格)",
            "只採用第一個交易指令",
            "先進先出",
            "未驗證",
        ):
            with self.subTest(term=term):
                self.assertIn(term, guide)

        self.assertNotIn("setposition(q_BestAsk1,v1)", guide)

    def test_changelog_records_user_visible_knowledge_addition(self) -> None:
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## [0.2.0]", maxsplit=1)[0]
        self.assertIn("XQ 官方交易語法專章", unreleased)


if __name__ == "__main__":
    unittest.main()
