from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "autotrade-error-codes.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
LEARNING = SKILL_ROOT / "references" / "autotrade-learning-guide.md"


class AutotradeErrorCodeKnowledgeTests(unittest.TestCase):
    def test_source_and_storage_boundary_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        self.assertIn("文章 ID／日期 | 14111／2024-12-10", text)
        self.assertIn("2026-07-20（Asia/Taipei）", text)
        self.assertIn("`body_text_stored` | `false`", text)
        self.assertIn("回測流程的 `1301` 已在目前 XQ 3.19.03 觸發驗證", text)
        self.assertIn("`商品名稱`、`狀態`、`說明`", text)
        self.assertIn("`[(1301)RaiseRunTimeError:<自訂訊息>]`", text)

    def test_all_documented_codes_and_context_differences_exist(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for code in (
            "1000", "1001", "1002", "1003", "1004",
            "1100", "1101", "1102",
            "1200", "1201", "1202", "1203", "1204",
            "1300", "1301", "1302", "1303", "1304", "1305", "1306", "1307",
            "1400", "1401", "1402", "1403", "1404", "1405",
            "1500", "1501",
        ):
            self.assertIn(f"| {code} |", text)
        self.assertIn("| 1 | 回測發生未細分的異常", text)
        self.assertIn("不能直接解讀成策略執行表", text)
        self.assertIn("官方回測表未列此碼", text)

    def test_diagnostic_and_reporting_contracts_are_safe(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "strategy_runtime",
            "backtest",
            "系統或自動化錯誤不得用改交易邏輯掩蓋",
            "最小重現",
            "XQservice@XQ.com.tw",
            "C:\\SysJust\\XQLite\\LOG",
            "包含所依賴的選股策略及引用函數",
            "不得輸出帳號或憑證",
            "寄送前必須取得使用者明確授權",
        ):
            self.assertIn(required, text)

    def test_skill_and_guides_route_error_diagnosis(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        official = OFFICIAL.read_text(encoding="utf-8")
        learning = LEARNING.read_text(encoding="utf-8")
        for text in (skill, official, learning):
            self.assertIn("autotrade-error-codes.md", text)
        self.assertIn("strategy runtime or backtest", skill)
        self.assertIn("`1300`", learning)
        self.assertIn("`1307`", learning)


if __name__ == "__main__":
    unittest.main()
