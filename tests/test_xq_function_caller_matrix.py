from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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
    / "xq_function_caller_matrix.py"
)
SPEC = importlib.util.spec_from_file_location("xq_function_caller_matrix", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_function_caller_matrix = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_function_caller_matrix
SPEC.loader.exec_module(xq_function_caller_matrix)


class XQFunctionCallerMatrixTests(unittest.TestCase):
    def matrix_args(self, root: Path) -> Namespace:
        paths = {}
        for label in ("function", "indicator", "screener", "alert"):
            path = root / f"{label}.xs"
            path.write_text("test", encoding="utf-8")
            paths[label] = path
        return Namespace(
            config=Path("config.json"),
            function_source=paths["function"],
            function_return_type="number",
            function_name="CodexFnMatrix",
            indicator_source=paths["indicator"],
            indicator_name="CodexIndicatorMatrix",
            screener_source=paths["screener"],
            screener_name="CodexScreenerMatrix",
            alert_source=paths["alert"],
            alert_name="CodexAlertMatrix",
        )

    def test_validation_requires_unique_ascii_names_and_existing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = self.matrix_args(Path(temp_dir))
            xq_function_caller_matrix.validate_args(args)

            args.alert_name = args.function_name
            with self.assertRaises(ValueError):
                xq_function_caller_matrix.validate_args(args)

            args.alert_name = "中文警示"
            with self.assertRaises(ValueError):
                xq_function_caller_matrix.validate_args(args)

    def test_missing_source_stops_before_xq_tools(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--config", "missing.json",
                "--function-source", "missing-function.xs",
                "--function-return-type", "number",
                "--function-name", "CodexFnMatrix",
                "--indicator-source", "missing-indicator.xs",
                "--indicator-name", "CodexIndicatorMatrix",
                "--screener-source", "missing-screener.xs",
                "--screener-name", "CodexScreenerMatrix",
                "--alert-source", "missing-alert.xs",
                "--alert-name", "CodexAlertMatrix",
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
        self.assertIn("does not exist", payload["message"])

    def test_matrix_contract_is_compile_only_for_three_caller_types(self) -> None:
        self.assertEqual(
            xq_function_caller_matrix.CALLER_TYPES,
            ("indicator", "screener", "alert"),
        )
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn('proof_scope="compile_only"', source)
        self.assertIn("runtime_result_proven=False", source)

    def test_skill_and_guide_route_cross_caller_matrix(self) -> None:
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
        self.assertIn("xq_function_caller_matrix.py", skill)
        for required in (
            "跨腳本呼叫矩陣",
            "跨腳本執行結果矩陣",
            "proof_scope: compile_only",
            "runtime_result_proven: false",
            "mismatch_count = 0",
            "error_count = 0",
            "TrueFalseSimple",
            "StringSimple",
            "指標",
            "選股",
            "警示",
        ):
            self.assertIn(required, guide)


if __name__ == "__main__":
    unittest.main()
