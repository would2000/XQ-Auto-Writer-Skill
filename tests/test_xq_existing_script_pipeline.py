import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_existing_script_pipeline as pipeline  # noqa: E402


class ExistingScriptPipelineTests(unittest.TestCase):
    def test_child_python_is_forced_to_utf8_json_output(self):
        completed = type("Completed", (), {"stdout": '{"status":"success"}\n', "stderr": "", "returncode": 0})()
        with patch.object(pipeline.subprocess, "run", return_value=completed) as mocked:
            code, payload = pipeline.run_json_tool("child.py", [], 1)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(mocked.call_args.kwargs["env"]["PYTHONUTF8"], "1")

    def make_source(self, directory: Path, name: str, header: str) -> Path:
        path = directory / name
        path.write_text(f"{header}\nvalue = 1;\n", encoding="utf-8")
        return path

    def base_args(self, directory: Path, *extra: str):
        source = self.make_source(directory, "main.xs", "{@type:indicator}")
        return pipeline.parse_args([
            "--config", str(directory / "xq-ui.json"),
            "--source", str(source),
            "--script-type", "indicator",
            "--script-name", "CodexIndicator",
            *extra,
        ])

    @staticmethod
    def successful_runner(calls):
        def run(script, arguments, timeout):
            calls.append((script, list(arguments), timeout))
            return 0, {
                "status": "success",
                "script": script,
                "input_sent": False if "--dry-run" in arguments else True,
            }
        return run

    def test_dry_run_stops_after_read_only_open_plan(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            calls = []
            result = pipeline.execute(
                self.base_args(directory, "--dry-run"),
                runner=self.successful_runner(calls),
            )
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["input_sent"])
        self.assertEqual([call[0] for call in calls], ["xq_open_existing_script.py"])
        self.assertIn("--dry-run", calls[0][1])

    def test_compile_only_opens_exact_codex_document_before_compiling(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            calls = []
            result = pipeline.execute(
                self.base_args(directory), runner=self.successful_runner(calls)
            )
        self.assertEqual(
            [call[0] for call in calls],
            ["xq_open_existing_script.py", "xq_compile.py"],
        )
        compile_args = calls[1][1]
        self.assertEqual(
            compile_args[compile_args.index("--script-name") + 1],
            "CodexIndicator",
        )
        self.assertTrue(result["current_task_compiler_success"])
        self.assertFalse(result["runtime_executed"])

    def test_function_and_caller_compile_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            function_source = self.make_source(
                directory, "function.xs", "{@type:function}"
            )
            caller_source = self.make_source(
                directory, "caller.xs", "{@type:filter}"
            )
            args = pipeline.parse_args([
                "--config", str(directory / "xq-ui.json"),
                "--source", str(function_source),
                "--script-type", "function",
                "--script-name", "CodexFunction",
                "--function-return-type", "number",
                "--caller-source", str(caller_source),
                "--caller-type", "screener",
                "--caller-name", "CodexCaller",
            ])
            calls = []
            result = pipeline.execute(args, runner=self.successful_runner(calls))
        self.assertEqual(
            [call[0] for call in calls],
            [
                "xq_open_existing_script.py",
                "xq_compile.py",
                "xq_open_existing_script.py",
                "xq_compile.py",
            ],
        )
        self.assertEqual(result["validated"]["caller"]["script_name"], "CodexCaller")

    def test_compile_failure_stops_before_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            args = self.base_args(
                directory,
                "--runtime-tool", "indicator",
                "--", "--plot-label", "Value",
            )
            calls = []

            def runner(script, arguments, timeout):
                calls.append(script)
                if script == "xq_compile.py":
                    return 2, {"status": "compile_error", "compiler_output": "actual"}
                return 0, {"status": "success"}

            with self.assertRaises(pipeline.PipelineError) as caught:
                pipeline.execute(args, runner=runner)
        self.assertEqual(caught.exception.stage, "compile_main")
        self.assertEqual(calls, ["xq_open_existing_script.py", "xq_compile.py"])

    def test_runtime_reopens_main_and_injects_owned_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            args = self.base_args(
                directory,
                "--runtime-tool", "indicator",
                "--", "--plot-label", "Value", "--restore-bookmark", "Public",
            )
            calls = []
            result = pipeline.execute(args, runner=self.successful_runner(calls))
        self.assertEqual(
            [call[0] for call in calls],
            [
                "xq_open_existing_script.py",
                "xq_compile.py",
                "xq_open_existing_script.py",
                "xq_indicator.py",
            ],
        )
        runtime_args = calls[-1][1]
        self.assertEqual(
            runtime_args[runtime_args.index("--script-name") + 1],
            "CodexIndicator",
        )
        self.assertTrue(result["runtime_executed"])

    def test_runtime_mismatch_or_owned_option_is_rejected_before_input(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            mismatch = self.base_args(directory, "--runtime-tool", "alert")
            with self.assertRaisesRegex(pipeline.PipelineError, "must match"):
                pipeline.validate_request(mismatch)

            owned = self.base_args(
                directory,
                "--runtime-tool", "indicator",
                "--", "--script-name", "Another",
            )
            with self.assertRaisesRegex(pipeline.PipelineError, "owned by the pipeline"):
                pipeline.validate_request(owned)

    def test_partial_caller_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            function_source = self.make_source(
                directory, "function.xs", "{@type:function}"
            )
            args = pipeline.parse_args([
                "--config", str(directory / "xq-ui.json"),
                "--source", str(function_source),
                "--script-type", "function",
                "--script-name", "CodexFunction",
                "--function-return-type", "number",
                "--caller-name", "MissingParts",
            ])
            with self.assertRaisesRegex(pipeline.PipelineError, "provided together"):
                pipeline.validate_request(args)


if __name__ == "__main__":
    unittest.main()
