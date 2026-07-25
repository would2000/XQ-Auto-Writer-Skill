import sys
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_category_selector as selector  # noqa: E402


class XQCategorySelectorTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "formula_category_switch": {
                "method": "manual_only",
                "automatic_switch_available": False,
                "pane_control_ids": {
                    "indicator": 1,
                    "screener": 4,
                    "alert": 2,
                    "autotrade": 7,
                    "function": 3,
                },
            }
        }

    def evidence(self, pane_id: int, codex_count: int = 1) -> dict:
        return {
            "visible_formula_pane_count": 1,
            "formula_pane_control_id": pane_id,
            "visible_tree_count": 1,
            "custom_root_count": 1,
            "codex_direct_child_count": codex_count,
        }

    def test_contract_allows_only_manual_fail_closed_method(self) -> None:
        contract = selector.load_contract(self.config())
        self.assertFalse(contract["automatic_switch_available"])
        bad = self.config()
        bad["formula_category_switch"]["method"] = "wm_command"
        with self.assertRaisesRegex(
            selector.CategorySelectorError,
            "manual_only",
        ):
            selector.load_contract(bad)

    def test_requested_active_category_and_codex_scope_succeed(self) -> None:
        result = selector.evaluate_category_request(
            self.evidence(7),
            "autotrade",
            selector.load_contract(self.config())["pane_control_ids"],
        )
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["codex_scope_verified"])
        self.assertFalse(result["input_sent"])

    def test_inactive_category_requires_manual_switch_without_input(self) -> None:
        result = selector.evaluate_category_request(
            self.evidence(7),
            "function",
            selector.load_contract(self.config())["pane_control_ids"],
        )
        self.assertEqual(result["status"], "automation_error")
        self.assertEqual(result["reason_code"], "manual_switch_required")
        self.assertTrue(result["manual_switch_required"])
        self.assertFalse(result["input_sent"])

    def test_active_category_with_ambiguous_codex_scope_is_refused(self) -> None:
        result = selector.evaluate_category_request(
            self.evidence(3, codex_count=2),
            "function",
            selector.load_contract(self.config())["pane_control_ids"],
        )
        self.assertEqual(result["status"], "automation_error")
        self.assertEqual(result["reason_code"], "codex_scope_readback_not_unique")

    def test_selector_source_contains_no_ui_input_or_coordinates(self) -> None:
        source = (
            SCRIPTS / "xq_category_selector.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in (
            "click_input(",
            ".click(",
            "send_keys(",
            "type_keys(",
            "setcursorpos",
            "wm_command",
            "coords=",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
