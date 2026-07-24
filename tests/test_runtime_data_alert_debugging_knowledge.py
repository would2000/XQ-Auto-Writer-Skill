from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "runtime-data-alert-debugging.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
LEARNING = SKILL_ROOT / "references" / "autotrade-learning-guide.md"


class RuntimeDataAlertDebuggingKnowledgeTests(unittest.TestCase):
    def test_four_sources_and_storage_boundary_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "XQ 資料欄位：資料什麼時候更新？",
            "什麼是 XQ 警示中心？",
            "利用語法控管第一次洗價",
            "如何使用 Print 指令進行腳本除錯？",
            "2024-12-10",
            "2024-12-06",
            "2024-12-17／14759",
            "2024-12-11／14117",
            "2026-07-20（Asia/Taipei）",
            "`body_text_stored` | `false`",
        ):
            self.assertIn(required, text)

    def test_update_times_are_complete_and_not_promises(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for label, time in (
            ("上市櫃日線", "15:45"),
            ("期交所日線", "15:15"),
            ("上市櫃信用交易相關資料", "22:30"),
            ("三大法人", "19:30"),
            ("主力", "19:00"),
            ("上海證券交易所資料", "18:00"),
            ("深圳證券交易所資料", "17:40"),
            ("香港交易所資料", "20:30"),
        ):
            self.assertIn(f"| {label} | {time} |", text)
        self.assertIn("不得被解讀成準時完成保證", text)
        self.assertIn("資料可用性條件＋合理緩衝", text)

    def test_alert_center_state_model_is_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "`策略` → `警示中心`",
            "即時監控（警示紀錄）",
            "報價組合",
            "商品盤勢與技術分析",
            "`設定` → `警示設定`",
            "`設定` → `我的設定` → `警示提示`",
            "沒有彈窗不代表警示沒有執行",
            "條件成立",
            "警示被記錄",
        ):
            self.assertIn(required, text)

    def test_isfirstcall_semantics_and_traps_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for argument in ('`" "`', '`"Bar"`', '`"Date"`', '`"Realtime"`'):
            self.assertIn(argument, text)
        for required in (
            "不是程式碼第一次執行到該函數",
            "歷史區間第一根 Bar",
            "依商品交易日切換",
            "由歷史洗價區間進入即時區間",
            "股票約 09:00",
            "一般期貨約 08:45",
            "全日期貨約 15:00",
            "已初始化",
            "不保證委託只送一次",
        ):
            self.assertIn(required, text)

    def test_print_contract_and_skill_routes_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "指標、選股、警示與交易腳本",
            "C:\\SysJust\\XQ2005\\XS\\Print",
            "[Symbol]",
            "[ScriptName]",
            "[Freq]",
            "[Date]",
            "control ID `2131`",
            "選股中心的開關仍只有文件證據",
            "不得記錄券商帳號、Token、憑證",
            "不得把 Print 日誌提交到儲存庫",
        ):
            self.assertIn(required, text)
        for routed in (SKILL, OFFICIAL, LEARNING):
            self.assertIn(
                "runtime-data-alert-debugging.md",
                routed.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
