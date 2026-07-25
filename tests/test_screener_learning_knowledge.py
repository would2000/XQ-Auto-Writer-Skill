from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "screener-learning-guide.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
SCREENER_WINDOW = SKILL_ROOT / "references" / "screener-window-guide.md"


class ScreenerLearningKnowledgeTests(unittest.TestCase):
    def test_exact_sidebar_range_and_storage_boundary_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        source_ids = re.findall(
            r"^\| (screener-\d{2}) \| \d{4}-\d{2}-\d{2} \|",
            text,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            source_ids,
            [f"screener-{index:02d}" for index in range(1, 14)],
        )
        self.assertIn("選股因子分析：用數據說話，打造高勝率選股策略", text)
        self.assertIn("用XS寫籌碼集中度的選股策略", text)
        self.assertIn("2026-07-24（Asia/Taipei）", text)
        self.assertIn("`body_text_stored` | `false`", text)
        self.assertIn(
            "不保存文章正文、HTML、圖片、完整官方範例",
            text,
        )
        self.assertIn("文章股票名單", text)

    def test_design_factor_and_backtest_contracts_are_distilled(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "`{@type:filter}`",
            "`ret`",
            "`OutputField`",
            "`order := 1`",
            "`order := -1`",
            "每日自動執行",
            "自訂排行",
            "因子分析",
            "ZScore",
            "`Q1 - 1.5 × IQR`",
            "存活者偏誤",
            "回溯是在指定過去日期重新檢視選股結果",
            "唯一新增報告 handle 與指定 marker",
            "成功／失敗商品數",
            "股權分散",
            "除息事件",
            "籌碼集中度",
            "沒有代碼時保持 `null`",
        ):
            self.assertIn(required, text)

    def test_official_error_code_set_is_complete(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        code_section = text.split("## 選股中心錯誤碼", maxsplit=1)[1]
        code_section = code_section.split("## 13 頁來源清單", maxsplit=1)[0]
        actual = {
            int(code)
            for code in re.findall(r"^\| (\d+) \|", code_section, re.MULTILINE)
        }
        expected = {
            50000,
            50001,
            50101,
            50102,
            50103,
            50104,
            50022,
            50023,
            50024,
            50025,
            50027,
            50031,
            50032,
            50033,
            50034,
            50201,
            50202,
            50301,
            50302,
            50303,
            50304,
            50305,
            50306,
            50307,
            50308,
            50003,
            50008,
            50009,
            50010,
            50011,
            50012,
            50013,
            50014,
            50021,
            50030,
            50035,
            50037,
            50401,
            50402,
            50004,
            50015,
            50016,
            50017,
            50019,
            50020,
            50501,
            50502,
            50503,
            50504,
            50505,
            50506,
            50507,
            50508,
            50509,
            50601,
            50602,
            50603,
            50036,
            59901,
            59902,
            59903,
            59904,
        }
        self.assertEqual(actual, expected)
        self.assertIn(
            "Windows timeout、應用程式無回應、網路推測、本地例外或空結果都不得轉換",
            text,
        )

    def test_skill_and_project_docs_route_to_screener_guide(self) -> None:
        routed_files = (
            SKILL,
            OFFICIAL,
            SCREENER_WINDOW,
            PROJECT_ROOT / "AGENTS.md",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "CHANGELOG.md",
        )
        for path in routed_files:
            with self.subTest(path=path):
                self.assertIn(
                    "screener-learning-guide.md",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
