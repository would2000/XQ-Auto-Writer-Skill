from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "xspractice-learning-guide.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
FUNCTION_GUIDE = SKILL_ROOT / "references" / "function-guide.md"
RUNTIME_GUIDE = SKILL_ROOT / "references" / "runtime-data-alert-debugging.md"
SCREENER_GUIDE = SKILL_ROOT / "references" / "screener-learning-guide.md"


class XsPracticeLearningKnowledgeTests(unittest.TestCase):
    def test_exact_sidebar_range_and_source_dates_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        rows = re.findall(
            r"^\| (xspractice-\d{2}) \| (\d{4}-\d{2}-\d{2}) \|",
            text,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            rows,
            [
                ("xspractice-01", "2025-12-30"),
                ("xspractice-02", "2016-03-09"),
                ("xspractice-03", "2021-08-19"),
                ("xspractice-04", "2016-03-09"),
                ("xspractice-05", "2016-03-17"),
                ("xspractice-06", "2016-03-17"),
                ("xspractice-07", "2016-03-10"),
            ],
        )
        self.assertIn(
            "XQ 18.01 版本 XS 重點功能：美股盤前盤後、函數彈性與編輯器優化",
            text,
        )
        self.assertIn("計算區間漲跌幅的自訂函數", text)
        self.assertIn("2026-07-24（Asia/Taipei）", text)

    def test_storage_and_copyright_boundaries_are_explicit(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        self.assertIn("`body_text_stored` | `false`", text)
        self.assertIn(
            "不保存官方正文、HTML、圖片或完整官方範例",
            text,
        )
        self.assertIn("不建立全文爬蟲", text)
        for forbidden_source_fragment in (
            "setposition(1,market)",
            "rangechange=value3*100;",
            "Value1 = Close - Close[1];",
            "<html",
        ):
            with self.subTest(fragment=forbidden_source_fragment):
                self.assertNotIn(forbidden_source_fragment, text)

    def test_version_data_series_debug_and_function_contracts_are_distilled(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "盤前 04:00–09:30",
            "`GetSymbolField`",
            "`GetSymbolGroup`",
            "`0 項錯誤` 不等於 `0 項警告`",
            "回測／介面的預載值",
            "`SetTotalBar`",
            "`SetBarBack`",
            "序列 `[n]`",
            "較短足量控制組及唯一 marker",
            "變數也是序列",
            "`Print` 的安全除錯契約",
            "`C:\\Print\\`",
            "`OutputField` 與 `GetFieldDate`",
            "不等於程式執行日、資料下載時間或公告時間",
            "回傳型別為數值",
            "起點價格為 0",
            "日期轉 offset",
            "`ret`、`OutputField`、`Plot` 或交易指令留在呼叫端",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_documentation_and_current_xq_evidence_are_separated(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        self.assertIn("`文件蒸餾`", text)
        self.assertIn("目前 XQ 3.19.03 的專案證據", text)
        self.assertIn("不應外推", text)
        self.assertIn(
            "不得推測原生錯誤碼或 `Default` 分支",
            text,
        )
        self.assertIn(
            "本專案以目前 XSHelp 與既有 XQ 驗證採用的 `SetBarBack` 為 canonical 名稱",
            text,
        )

    def test_skill_and_project_docs_route_to_xspractice_guide(self) -> None:
        routed_files = (
            SKILL,
            OFFICIAL,
            FUNCTION_GUIDE,
            RUNTIME_GUIDE,
            SCREENER_GUIDE,
            PROJECT_ROOT / "AGENTS.md",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "CHANGELOG.md",
        )
        for path in routed_files:
            with self.subTest(path=path):
                self.assertIn(
                    "xspractice-learning-guide.md",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
