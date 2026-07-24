from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from argparse import Namespace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "xq_function_integration.py"
)
SPEC = importlib.util.spec_from_file_location("xq_function_integration", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_function_integration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_function_integration
SPEC.loader.exec_module(xq_function_integration)


class XQFunctionIntegrationTests(unittest.TestCase):
    def test_confirmation_guard_stops_before_reading_sources_or_touching_xq(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config", "missing.json",
                "--function-source", "missing-function.xs",
                "--function-return-type", "number",
                "--function-name", "CodexFnGuard",
                "--red-source", "missing-red.xs",
                "--red-name", "CodexRedGuard",
                "--green-source", "missing-green.xs",
                "--green-name", "CodexGreenGuard",
                "--expected-red-marker", "CODEX_FN_RED_GUARD",
                "--product", "2330",
                "--frequency", "1",
                "--start-date", "2026-06-01",
                "--end-date", "2026-06-02",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(payload["status"], "automation_error")
        self.assertFalse(payload["xq_touched"])
        self.assertFalse(payload["backtest_started"])

    def test_red_control_requires_exact_1301_marker_and_cleared_checkpoint(self) -> None:
        payload = {
            "status": "failure",
            "success_count": 0,
            "failure_count": 1,
            "total_trades": 0,
            "failure_details": [
                {
                    "error_code": "1301",
                    "description": "RaiseRunTimeError:CODEX_FN_RED_EXPECTED",
                }
            ],
            "recovery_checkpoint_retained": False,
        }
        result = xq_function_integration.evaluate_red_result(
            payload, "CODEX_FN_RED_EXPECTED"
        )
        self.assertTrue(result["passed"])
        payload["failure_details"][0]["error_code"] = "1303"
        self.assertFalse(
            xq_function_integration.evaluate_red_result(
                payload, "CODEX_FN_RED_EXPECTED"
            )["passed"]
        )

    def test_green_control_requires_pure_success_and_cleared_checkpoint(self) -> None:
        payload = {
            "status": "success",
            "success_count": 1,
            "failure_count": 0,
            "total_trades": 2,
            "recovery_checkpoint_retained": False,
        }
        self.assertTrue(xq_function_integration.evaluate_green_result(payload)["passed"])
        payload["failure_count"] = 1
        self.assertFalse(xq_function_integration.evaluate_green_result(payload)["passed"])

    def test_argument_contract_rejects_unsafe_names_markers_and_warmup(self) -> None:
        valid = Namespace(
            function_name="CodexFnV1",
            red_name="CodexRedV1",
            green_name="CodexGreenV1",
            expected_red_marker="CODEX_FN_RED_EXPECTED",
            preload_records=5,
            timeout_seconds=60,
        )
        xq_function_integration.validate_args(valid)
        for field, value in (
            ("function_name", "中文函數"),
            ("red_name", "CodexFnV1"),
            ("expected_red_marker", "too-short"),
            ("preload_records", 0),
        ):
            case = Namespace(**vars(valid))
            setattr(case, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                xq_function_integration.validate_args(case)

    def test_backtest_command_pins_safe_historical_assumptions(self) -> None:
        args = Namespace(
            config=Path("config.json"),
            product="2330",
            frequency="1",
            start_date="2026-06-01",
            end_date="2026-06-02",
            preload_records=5,
            initial_capital_wan="100",
            timeout_seconds=60,
        )
        command = xq_function_integration.backtest_arguments(args)
        for required in (
            "--max-position",
            "--max-entries-per-day",
            "--max-trades-per-minute",
            "--simulate-ticks",
            "--no-daily-position-reset",
            "--fill-on-trigger",
            "--no-enable-print",
            "--no-direct-order",
        ):
            self.assertIn(required, command)

    def test_skill_documents_red_green_evidence_boundary(self) -> None:
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
        compiler_lessons = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "compiler-lessons.md"
        ).read_text(encoding="utf-8")
        self.assertIn("xq_function_integration.py", skill)
        for required in (
            "紅燈",
            "綠燈",
            "1301",
            "參數順序",
            "NumericSimple",
            "NumericSeries",
            "TrueFalseSimple",
            "TrueFalseSeries",
            "1、10、100",
            "呼叫端布林參數的歷史可回看性",
            "StringSimple",
            "數值、邏輯值與字串三種最小整合切片",
            "NumericRef",
            "NumericArrayRef",
            "Array_GetMaxIndex",
            "2×3",
            "Array_SetMaxIndex",
            "32 位元有號整數範圍",
            "1303",
            "不合法的陣列索引值",
            "函數呼叫函數",
            "CODEX_NESTED_INNER_GUARD",
            "內層錯誤傳播",
            "直接展開兩層公式",
            "SetBarMode(2)",
            "可能交點",
            "函數內部 series",
            "呼叫端接收變數",
            "CODEX_CONDITIONAL_STATE_RED_EXPECTED",
            "121",
            "114",
            "GetFieldDate",
            "前一根 1 分鐘 bar",
            "CODEX_XF_DAILY_RED_EXPECTED",
            "XfCurrentValue",
        ):
            self.assertIn(required, guide)
        for required in (
            '"Daily" 不允許當成變數開頭',
            "DailyCurrent",
            "XfCurrentValue",
        ):
            self.assertIn(required, compiler_lessons)


if __name__ == "__main__":
    unittest.main()
