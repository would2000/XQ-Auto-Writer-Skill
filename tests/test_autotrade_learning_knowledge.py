from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUIDE = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "references"
    / "autotrade-learning-guide.md"
)
SKILL = GUIDE.parents[1] / "SKILL.md"
OFFICIAL = GUIDE.with_name("official-knowledge.md")
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"


class AutotradeLearningKnowledgeTests(unittest.TestCase):
    def test_guide_has_exact_official_article_set_and_rights_boundary(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        source_ids = re.findall(r"^\| (\d{5}) \| 2024-12-", text, flags=re.MULTILINE)
        self.assertEqual(
            set(source_ids),
            {
                "13001", "13643", "13712", "13754", "13793", "13841", "13910",
                "13943", "13997", "14111", "14117", "12626", "14759",
            },
        )
        self.assertEqual(len(source_ids), 13)
        self.assertIn("body_text_stored` | `false", text)
        self.assertIn("不保存文章正文、HTML、完整官方範例", text)
        self.assertIn("2026-07-20", text)

    def test_guide_distinguishes_code_backtest_and_ui_contracts(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "交易腳本",
            "回測系統",
            "自動交易中心",
            "觸發即判斷成交",
            "不設定",
            "延續前次執行",
            "與庫存同步",
            "由腳本計算",
            "Position <> Filled",
            "AT_EnableTrade",
            "AT_BID",
            "AT_AccType",
            "AT_AID",
            "IsFirstCall",
            "Print",
            "停止全部策略是高影響操作",
        ):
            self.assertIn(required, text)

    def test_autotrade_workflow_routes_to_learning_guide(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        official = OFFICIAL.read_text(encoding="utf-8")
        changelog = CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("references/autotrade-learning-guide.md", skill)
        self.assertIn("autotrade-learning-guide.md", official)
        self.assertIn("13 篇自動交易教學", changelog)


if __name__ == "__main__":
    unittest.main()
