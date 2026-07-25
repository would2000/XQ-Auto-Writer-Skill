from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
GUIDE = SKILL_ROOT / "references" / "advanced-learning-guide.md"
SKILL = SKILL_ROOT / "SKILL.md"
OFFICIAL = SKILL_ROOT / "references" / "official-knowledge.md"
SCREENER_GUIDE = SKILL_ROOT / "references" / "screener-learning-guide.md"
INDICATOR_GUIDE = SKILL_ROOT / "references" / "indicator-window-guide.md"
AUTOTRADE_GUIDE = SKILL_ROOT / "references" / "autotrade-window-guide.md"


class AdvancedLearningKnowledgeTests(unittest.TestCase):
    def test_all_seventeen_sidebar_pages_and_dates_are_recorded(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        rows = re.findall(
            r"^\| (advanced-\d{2}) \| (\d{4}-\d{2}-\d{2}) \|",
            text,
            flags=re.MULTILINE,
        )
        self.assertEqual(
            rows,
            [
                ("advanced-01", "2026-05-04"),
                ("advanced-02", "2025-08-18"),
                ("advanced-03", "2025-10-20"),
                ("advanced-04", "2025-08-18"),
                ("advanced-05", "2025-08-18"),
                ("advanced-06", "2025-08-18"),
                ("advanced-07", "2025-08-18"),
                ("advanced-08", "2025-08-18"),
                ("advanced-09", "2025-08-18"),
                ("advanced-10", "2025-08-18"),
                ("advanced-11", "2025-08-18"),
                ("advanced-12", "2025-08-18"),
                ("advanced-13", "2025-08-18"),
                ("advanced-14", "2025-08-18"),
                ("advanced-15", "2025-08-18"),
                ("advanced-16", "2025-08-18"),
                ("advanced-17", "2025-08-18"),
            ],
        )
        self.assertIn("經濟指標行事曆功能說明", text)
        self.assertIn("技術分析的分點指標介紹", text)
        self.assertIn("2026-07-24（Asia/Taipei）", text)
        self.assertIn("分類首頁只用來確認側欄範圍，不算第 18 篇內容頁", text)

    def test_storage_rights_and_external_link_boundaries_are_explicit(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        self.assertIn("`body_text_stored` | `false`", text)
        self.assertIn(
            "不保存官方正文、HTML、圖片、完整表格或逐步畫面重製",
            text,
        )
        self.assertIn("不建立全文爬蟲", text)
        self.assertIn("七個短網址系列", text)
        self.assertIn("沒有開啟、追蹤或蒸餾", text)
        for forbidden_source_fragment in (
            "<html",
            "<table",
            "完整官方範例：",
            "逐字稿",
        ):
            with self.subTest(fragment=forbidden_source_fragment):
                self.assertNotIn(forbidden_source_fragment, text.lower())

    def test_feature_models_and_version_limits_are_distilled(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "預計日期、實際公告日期、XQ 欄位資料日期、時區與最後更新時間",
            "欄框、同步與保存",
            "一般貼上、選擇性貼上的「加入」與「覆蓋」",
            "盤前 04:00–09:30",
            "正常盤 09:30–16:00",
            "盤後 16:00–20:00",
            "XQ 7.17.01／3.17.01",
            "未成交委託、成交與 MIT 標記",
            "市場籌碼與券商分析",
            "系統券商群組的成員與分類規則可能隨版本或月份變動",
            "股權分散表",
            "籌碼選股",
            "賣方家數－買方家數",
            "族群透視",
            "分點進出",
            "分點買賣力",
            "分點成交力",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_private_data_and_trading_actions_remain_forbidden(self) -> None:
        text = GUIDE.read_text(encoding="utf-8")
        for required in (
            "自設頁面、我的最愛、自選商品、自選券商、追蹤券商",
            "Codex 不得登入／登出 XQ 或券商帳號",
            "送單、刪單、全刪委託",
            "不是自動化授權",
            "全面禁止",
            "不能拿畫面標記代替 XQ 報告",
            "只能處理本次 manifest 項目",
            "禁止固定、相對或推算座標",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_skill_and_project_docs_route_to_advanced_guide(self) -> None:
        routed_files = (
            SKILL,
            OFFICIAL,
            SCREENER_GUIDE,
            INDICATOR_GUIDE,
            AUTOTRADE_GUIDE,
            PROJECT_ROOT / "AGENTS.md",
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "CHANGELOG.md",
        )
        for path in routed_files:
            with self.subTest(path=path):
                self.assertIn(
                    "advanced-learning-guide.md",
                    path.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
