from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "sensor-learning-guide.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
ALERT_WINDOW = SKILL_ROOT / "references" / "alert-window-guide.md"


class SensorLearningKnowledgeTests(unittest.TestCase):
    def test_exact_sidebar_range_and_storage_boundary_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        source_ids = re.findall(
            r"^\| (sensor-\d{2}) \| \d{4}-\d{2}-\d{2} \|",
            text,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            source_ids,
            [f"sensor-{index:02d}" for index in range(1, 16)],
        )
        self.assertIn("策略雷達基本操作", text)
        self.assertIn("策略雷達與雷達回測的錯誤代碼說明", text)
        self.assertIn("2026-07-24（Asia/Taipei）", text)
        self.assertIn("`body_text_stored` | `false`", text)
        self.assertIn(
            "不保存文章正文、HTML、圖片、完整官方範例",
            text,
        )
        self.assertNotIn("](https://xstrader", text)

    def test_operational_and_backtest_contracts_are_distilled(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "連續觸發",
            "K 棒內單次觸發",
            "啟動後只觸發一次",
            "單次洗價模式",
            '`GetInfo("IsTimerMode")`',
            "`q_MarketState`",
            "基準商品參照",
            "`GetSymbolField`",
            "最大同時進場次數",
            "模擬逐筆洗價",
            "啟動腳本內 `Print`",
            "時間加權",
            "成功／失敗商品數",
            "手機圖示或「傳送中」只證明設定狀態",
            "不得登入、登出、串接或選取實際證券帳號",
            "沒有代碼就保持 `null`",
        ):
            self.assertIn(required, text)

    def test_error_code_namespaces_are_complete_and_separate(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        live_section, backtest_section = text.split(
            "### 雷達回測", maxsplit=1
        )
        live_codes = {
            int(code)
            for code in re.findall(r"^\| (\d+) \|", live_section, re.MULTILINE)
        }
        backtest_codes = {
            int(code)
            for code in re.findall(
                r"^\| (\d+) \|", backtest_section, re.MULTILINE
            )
        }
        self.assertEqual(
            live_codes,
            {5023, 5024, 5025, 5026, 5027, 5029, 5030, 5031, 5032},
        )
        self.assertEqual(
            backtest_codes,
            set(range(1, 35))
            | set(range(101, 110))
            | set(range(1001, 1014)),
        )
        self.assertIn(
            "Windows timeout、網路猜測、進度窗消失或本地例外都不得轉換",
            text,
        )

    def test_skill_and_project_docs_route_to_sensor_guide(self) -> None:
        routed_files = (
            SKILL,
            OFFICIAL,
            ALERT_WINDOW,
            PROJECT_ROOT / "AGENTS.md",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "CHANGELOG.md",
        )
        for path in routed_files:
            with self.subTest(path=path):
                self.assertIn(
                    "sensor-learning-guide.md",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
