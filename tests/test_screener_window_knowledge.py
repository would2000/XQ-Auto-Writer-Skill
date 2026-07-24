import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / ".agents/skills/xq-xscript-compiler/references/screener-window-guide.md"
SKILL = ROOT / ".agents/skills/xq-xscript-compiler/SKILL.md"


class ScreenerWindowKnowledgeTests(unittest.TestCase):
    def test_guide_records_verified_execution_and_empty_result_contract(self):
        text = GUIDE.read_text(encoding="utf-8")
        for marker in (
            "17554",
            "20616",
            "CP950",
            "無任何符合選股條件的商品",
            "matched_count: 0",
            "OutputField",
            "--create-strategy",
            "哨兵",
            "公開的 XQ `(系統)` 範圍",
            "18710",
            "xq_screener_pipeline.py",
            "CodexScreenPipelineV2",
            "0 項錯誤與 0 項警告",
            "執行錯誤的商品",
            "error_code: null",
            "partial_failure",
            "CodexScreenTimeoutAllV1",
            "recovery_complete: true",
        ):
            self.assertIn(marker, text)

    def test_skill_routes_execution_capture_to_guide_and_cli(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("references/screener-window-guide.md", text)
        self.assertIn("scripts/xq_screener.py", text)
        self.assertIn("scripts/xq_screener_pipeline.py", text)


if __name__ == "__main__":
    unittest.main()
