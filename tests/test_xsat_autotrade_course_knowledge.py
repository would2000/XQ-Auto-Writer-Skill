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
    / "xsat-autotrade-course.md"
)
SKILL = GUIDE.parents[1] / "SKILL.md"
OFFICIAL = GUIDE.with_name("official-knowledge.md")
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"


class XsatAutotradeCourseKnowledgeTests(unittest.TestCase):
    def test_guide_has_all_17_sidebar_pages_and_rights_boundary(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        rows = re.findall(
            r"^\| (\d{1,2}) \| 20\d{2}-\d{2}-\d{2} \| \[[^]]+\]\(https://www\.xq\.com\.tw/lesson/xsat/[^)]+\) \|$",
            text,
            flags=re.MULTILINE,
        )
        self.assertEqual(rows, [str(index) for index in range(1, 18)])
        self.assertIn("body_text_stored` | `false", text)
        self.assertIn("不保存正文、HTML、完整官方範例", text)
        self.assertIn("2026-07-21", text)

    def test_guide_preserves_core_runtime_and_backtest_contracts(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "Position <> Filled",
            "TradeMode",
            "策略部位計算區間",
            "不送券商委託",
            "FilledAvgPrice",
            "CancelAllOrders",
            "取消流程是非同步狀態機",
            "AT_EnableTrade",
            "AT_BID",
            "AT_AccType",
            "AT_AID",
            "部分成交且仍有未完成數量",
            "最大投入報酬率",
            "日、月、季、年週期分析",
            "觸發立即判斷成交",
            "手機只顯示已啟用交易帳號的策略",
            "電腦與 XQ 必須維持運作",
        ):
            self.assertIn(required, text)

    def test_autotrade_workflow_routes_to_course(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        official = OFFICIAL.read_text(encoding="utf-8")
        changelog = CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("references/xsat-autotrade-course.md", skill)
        self.assertIn("xsat-autotrade-course.md", official)
        self.assertIn("XS 自動交易」17 頁", changelog)


if __name__ == "__main__":
    unittest.main()
