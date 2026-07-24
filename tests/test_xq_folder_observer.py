from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import xq_folder_observer as observer  # noqa: E402


class XQFolderObserverTests(unittest.TestCase):
    def test_exact_codex_tree_label_rejects_prefix_collisions(self) -> None:
        self.assertTrue(observer.is_exact_codex_tree_label("CODEX"))
        self.assertTrue(observer.is_exact_codex_tree_label("CODEX (0)"))
        self.assertTrue(observer.is_exact_codex_tree_label(" CODEX   (12) "))
        self.assertFalse(observer.is_exact_codex_tree_label("CODEX專屬資料夾 (0)"))
        self.assertFalse(observer.is_exact_codex_tree_label("CodexScript"))

    def test_public_text_whitelist_does_not_store_private_names(self) -> None:
        self.assertEqual(observer.public_text("新增資料夾"), "新增資料夾")
        self.assertEqual(observer.public_text("取消"), "取消")
        self.assertEqual(observer.public_text("CODEX"), "CODEX")
        self.assertEqual(observer.public_text("私人策略名稱"), "")
        self.assertEqual(observer.public_text("CodexPrivateScript"), "")

    def test_observer_source_contains_no_ui_input_or_coordinates(self) -> None:
        source = (SCRIPTS / "xq_folder_observer.py").read_text(encoding="utf-8")
        for forbidden in (
            "click_input",
            "type_keys",
            "send_keys",
            "mouse.",
            "coords",
            "SetForegroundWindow",
        ):
            self.assertNotIn(forbidden, source)

    def test_skill_and_calibration_guide_preserve_evidence_boundary(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        guide = (SKILL_ROOT / "references" / "windows-calibration.md").read_text(
            encoding="utf-8",
        )
        for required in (
            "xq_folder_observer.py",
            "`#32768`",
            "control ID `45242`",
            "建立對話框",
            "不得推測",
            "五種腳本類型",
        ):
            self.assertIn(required, skill + guide)


if __name__ == "__main__":
    unittest.main()
