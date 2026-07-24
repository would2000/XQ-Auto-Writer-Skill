from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCES = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references"
)
GUIDE = REFERENCES / "autotrade-window-guide.md"
SKILL = REFERENCES.parent / "SKILL.md"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"


class AutotradeWindowKnowledgeTests(unittest.TestCase):
    def test_verified_entry_selectors_are_coordinate_free(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            '"auto_id": "59419"',
            '"auto_id": "1604158800"',
            "^\\s*加入自動交易\\s*$",
            "^\\s*自動交易中心\\s*$",
            "NewStrategyButton",
            "ScriptEditorButton",
            "ExecutionButton",
            "CloseButton",
        ):
            self.assertIn(required, text)
        self.assertIn("不得保存或依賴本次量測到的矩形座標", text)
        self.assertNotIn("(L604,", text)
        self.assertNotIn("(L852,", text)

    def test_add_strategy_flow_records_safe_cancel_boundary(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "策略名稱、選擇腳本、執行商品、帳號設定、交易安控、進出場",
            "主視窗暫時為 disabled",
            "按下「取消」後",
            "不等於授權按「確認」",
            "未建立策略、未綁定帳號、未啟動策略、未送單",
        ):
            self.assertIn(required, text)

    def test_skill_routes_ui_work_to_verified_guide(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        changelog = CHANGELOG.read_text(encoding="utf-8")
        self.assertIn("references/autotrade-window-guide.md", skill)
        self.assertIn("XQ 3.19.03", changelog)

    def test_backtest_fields_and_cancel_boundary_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "^執行回測\\\\[策略\\\\]：.*",
            "ComboBox `2091`",
            "RadioButton `2069`／`2070`",
            "CheckBox `2121`",
            "CheckBox `2122`",
            "DateTimePicker `2200`",
            "DateTimePicker `2201`",
            "Edit `2007`",
            "ComboBox `2092`",
            "ListView `45243`",
            "`2124` | `2004`",
            "`2125` | `2005`",
            "`2126` | `2006`",
            "ComboBox `2093`",
            "ComboBox `2094`",
            "Edit `2016`",
            "CheckBox `2123`",
            "Edit `2014`",
            "Edit `2015`",
            "CheckBox `2131`",
            "CheckBox `2127`",
            "CheckBox `2128`",
            "開始回測`（control ID `2033`）",
            "取消`（control ID `2034`）",
        ):
            self.assertIn(required, text)
        self.assertIn("沒有回測執行狀態或回測報告視窗", text)
        self.assertIn("回測執行狀態", text)
        self.assertNotIn("台指網格回測實盤版", text)
        self.assertNotIn("FITXN", text)

    def test_backtest_progress_report_and_error_boundaries_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "SysListView32`，control ID `3002`",
            "AfxWnd140`，control ID `3001`",
            "msctls_progress32",
            "報告視窗出現本身不是成功證據",
            "Chrome_RenderWidgetHostHWND",
            "完整匯出",
            "僅匯出交易紀錄",
            "重新回測",
            "每日報表",
            "商品統計表",
            "商品分析",
            "交易分析",
            "腳本資料",
            "週期分析",
            "從檔案匯入",
            "文字檔案 (*.txt, *.csv)",
            "腳本執行期錯誤代碼",
            "工具主動中止、未勾選時無部分報告",
        ):
            self.assertIn(required, text)
        self.assertIn("本批已驗證純成功與純失敗兩種摘要", text)
        self.assertIn("不證明策略獲利、實盤安全", text)
        self.assertNotIn("台指網格回測實盤版", text)
        self.assertNotIn("FITXN", text)

    def test_backtest_autofill_contract_is_verified_and_recoverable(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "寫入 → 讀回 → 還原",
            "DateTimePicker `2200`、`2201`",
            "選擇「市價」後兩個檔數欄會變成 invisible",
            "查詢 Edit `741`",
            "結果 ListView `782`",
            "組合 ListBox `783`",
            "分類 TreeView `19902`",
            "交易帳號設定 Button `1010`",
            "標題 `從檔案匯入`",
            "ListView `45243`",
            "Edit `45041`",
            "column_widths()",
            "不能保存固定螢幕座標",
            "沒有 `回測執行狀態` 或新回測報告",
        ):
            self.assertIn(required, text)
        self.assertIn("沒有讀取或選擇使用者組合", text)
        self.assertIn("不得讀取、輸出或自行選擇帳號", text)
        self.assertIn("目前只驗證數值輸入", text)

    def test_backtest_start_classifier_has_non_boolean_terminal_states(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "自動啟動與終態判定",
            "摘要進度條可能持續顯示 0",
            "control ID 從 `5001` 變成 `5002`",
            "ListView `3002` 由 hidden 變為 visible",
            "`success`",
            "`failure`",
            "`partial_failure`",
            "`indeterminate_timeout`",
            "`cancelled`",
            "`Chrome_RenderWidgetHostHWND`",
            "`0(成功)1(失敗)`",
            "總交易次數為 21",
            "RaiseRunTimeError",
            "CheckBox `3003`",
            "hidden 容器不能判定回測仍在執行",
            "`partial_results_requested: false`",
            "`recovery_complete: true`",
            "`--cancel-after-seconds`",
            "`--cancel-after-completed-products`",
            "`partial_results_request_succeeded`",
            "`cancel_reason: timeout`",
            "監控期限只決定何時停止等待終態",
            "環境復原第一、二階段",
            "`recovery-state.json`",
            "`stale_checkpoint_cleared: true`",
        ):
            self.assertIn(required, text)
        self.assertIn("不能把時間超過門檻或 0% 當失敗", text)
        self.assertIn("「新報告可見」不足以代表成功", text)
        self.assertIn("`failure_details`", text)
        self.assertIn("`failure_detail_capture_error`", text)
        self.assertIn("`商品名稱`、`狀態`、`說明`", text)
        self.assertIn("部分報告摘要的同次穩定擷取仍待更多案例驗證", text)

    def test_success_report_does_not_prove_any_bar_executed(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "日頻 10,000 根歷史",
            "無條件 `RaiseRunTimeError` 哨兵未執行",
            "日頻 100 根",
            "不證明正式區間至少執行過一根",
            "不得宣稱函數回傳值、`Default` 行為或原生錯誤代碼",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
