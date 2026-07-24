import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / ".agents/skills/xq-xscript-compiler/references/indicator-window-guide.md"
SKILL = ROOT / ".agents/skills/xq-xscript-compiler/SKILL.md"
README = ROOT / "README.md"


class IndicatorWindowKnowledgeTests(unittest.TestCase):
    def test_guide_records_capture_comparison_and_recovery_contract(self):
        text = GUIDE.read_text(encoding="utf-8")
        for marker in (
            "複製成新頁面",
            "新增副圖指標設定",
            "XS指標 > 自訂",
            "輸出到Excel",
            "Running Object Table",
            "mismatch",
            "179 列",
            "書籤復原",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_skill_routes_indicator_runtime_proof_through_new_tool(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("references/indicator-window-guide.md", text)
        self.assertIn("scripts/xq_indicator.py", text)
        self.assertIn("--restore-bookmark", text)
        self.assertIn("numeric export alone", text)

    def test_readme_documents_user_facing_command_and_limits(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("xq_indicator.py", text)
        self.assertIn("--expected-column", text)
        self.assertIn("指標實際繪圖結果擷取指南", text)


if __name__ == "__main__":
    unittest.main()
