import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / ".agents/skills/xq-xscript-compiler/references/alert-window-guide.md"


class AlertWindowKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = GUIDE.read_text(encoding="utf-8")

    def test_guide_records_red_green_runtime_contract(self):
        for value in ("單次洗價模式", "HH:MM:SS(N)", "觸發日期樹", "執行紀錄"):
            self.assertIn(value, self.text)

    def test_guide_records_safety_and_cleanup(self):
        for value in ("不覆寫使用者策略", "讀回腳本與商品", "cleanup.errors", "不會送出委託"):
            self.assertIn(value, self.text)

    def test_guide_documents_cli_and_exit_contract(self):
        self.assertIn("scripts/xq_alert.py", self.text)
        self.assertIn("`mismatch`／`2`", self.text)
        self.assertIn("`automation_error`／`3`", self.text)


if __name__ == "__main__":
    unittest.main()
