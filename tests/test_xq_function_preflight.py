from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "xq_function_preflight.py"
)
SPEC = importlib.util.spec_from_file_location("xq_function_preflight", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_function_preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_function_preflight
SPEC.loader.exec_module(xq_function_preflight)


class XQFunctionPreflightTests(unittest.TestCase):
    def test_skill_routes_function_work_to_guide_and_preflight(self) -> None:
        skill = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        guide = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "function-guide.md"
        ).read_text(encoding="utf-8")
        self.assertIn("references/function-guide.md", skill)
        self.assertIn("xq_function_preflight.py", skill)
        for required in (
            "{@type:function}",
            "{@type:function_bool}",
            "{@type:function_string}",
            "retval",
            "最小呼叫端",
            "0項錯誤，0項警告",
        ):
            self.assertIn(required, guide)

    def test_data_shortage_requires_execution_evidence(self) -> None:
        guide = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "function-guide.md"
        ).read_text(encoding="utf-8")
        skill = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        for required in (
            "SetTotalBar",
            "SetBarBack",
            "GetFieldStartOffset",
            "無正式執行證據",
            "CODEX_SUFFICIENT_DAILY_PATH_EXECUTED",
            "不得查表補成 `1401`",
        ):
            self.assertIn(required, guide)
        self.assertIn("execution-path sentinel", skill)
        self.assertIn("Record a native error code only", skill)

    def test_accepts_all_three_canonical_return_types(self) -> None:
        cases = {
            "number": "{@type:function}\nretval = close;",
            "boolean": "{@type:function_bool}\nretval = close > open;",
            "string": '{@type:function_string}\nretval = "OK";',
        }
        for return_type, source in cases.items():
            with self.subTest(return_type=return_type):
                result = xq_function_preflight.inspect_function(source, return_type)
                self.assertTrue(result["valid"], result["errors"])

    def test_rejects_header_that_does_not_match_requested_type(self) -> None:
        result = xq_function_preflight.inspect_function(
            "{@type:function}\nretval = true;", "boolean"
        )
        self.assertFalse(result["valid"])
        self.assertIn("does not match", " ".join(result["errors"]))

    def test_requires_retval_not_ret(self) -> None:
        result = xq_function_preflight.inspect_function(
            "{@type:function_bool}\nret = close > open;", "boolean"
        )
        self.assertFalse(result["valid"])
        self.assertIn("must use retval", " ".join(result["errors"]))

    def test_comments_and_strings_do_not_trigger_forbidden_constructs(self) -> None:
        source = """{@type:function_string}
// SetPosition(1); Plot1(close);
{ OutputField(1, close); }
retval = "CancelAllOrders";
"""
        result = xq_function_preflight.inspect_function(source, "string")
        self.assertTrue(result["valid"], result["errors"])

    def test_rejects_chart_report_and_order_side_effects(self) -> None:
        for statement in (
            "SetPosition(1);",
            "CancelAllOrders;",
            "Plot1(close);",
            "OutputField(1, close);",
        ):
            with self.subTest(statement=statement):
                result = xq_function_preflight.inspect_function(
                    "{@type:function}\nretval = close;\n" + statement, "number"
                )
                self.assertFalse(result["valid"])
                self.assertTrue(result["forbidden_constructs"])

    def test_header_or_assignment_in_comments_does_not_satisfy_contract(self) -> None:
        result = xq_function_preflight.inspect_function(
            "// {@type:function}\n{ retval = close; }", "number"
        )
        self.assertFalse(result["valid"])
        self.assertFalse(result["retval_assignment_found"])

    def test_header_text_inside_string_is_not_a_type_declaration(self) -> None:
        result = xq_function_preflight.inspect_function(
            'retval = "{@type:function_string}";', "string"
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["observed_headers"], [])


if __name__ == "__main__":
    unittest.main()
