from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import xq_category_observer as observer  # noqa: E402


class XQCategoryObserverTests(unittest.TestCase):
    def test_observed_formula_pane_ids_are_complete_and_unique(self) -> None:
        self.assertEqual(observer.FORMULA_PANE_IDS, {1, 2, 3, 4, 7})
        self.assertEqual(
            observer.EXPECTED_MANUAL_ORDER,
            ["indicator", "screener", "alert", "autotrade", "function"],
        )

    def test_scope_patterns_reject_prefix_collisions(self) -> None:
        self.assertIsNotNone(observer.CUSTOM_PATTERN.fullmatch("自訂 (106)"))
        self.assertIsNotNone(observer.CODEX_PATTERN.fullmatch("CODEX (0)"))
        self.assertIsNone(observer.CUSTOM_PATTERN.fullmatch("私人自訂 (106)"))
        self.assertIsNone(observer.CODEX_PATTERN.fullmatch("CODEX測試 (0)"))

    def test_observer_source_contains_no_ui_input_or_coordinates(self) -> None:
        source = (SCRIPTS / "xq_category_observer.py").read_text(encoding="utf-8")
        for forbidden in (
            "click_input",
            "type_keys",
            "send_keys",
            "mouse.",
            "SetForegroundWindow",
            "SetCursorPos",
        ):
            self.assertNotIn(forbidden, source)

    def test_observer_records_no_unrestricted_tree_text(self) -> None:
        source = (SCRIPTS / "xq_category_observer.py").read_text(encoding="utf-8")
        self.assertIn("private_text_storage", source)
        self.assertIn("CUSTOM_PATTERN.fullmatch", source)
        self.assertIn("CODEX_PATTERN.fullmatch", source)
        self.assertNotIn("root.text()", source)


if __name__ == "__main__":
    unittest.main()
