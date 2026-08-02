from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import xq_runtime_evidence_suite as suite  # noqa: E402


CASE_FILE = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references"
    / "runtime-evidence-cases-v1.json"
)


class RuntimeEvidenceSuiteTests(unittest.TestCase):
    def test_child_python_is_forced_to_utf8_json_output(self) -> None:
        completed = type("Completed", (), {"stdout": '{"status":"success"}\n', "stderr": "", "returncode": 0})()
        with patch.object(suite.subprocess, "run", return_value=completed) as mocked:
            code, payload = suite.run_json_tool("child.py", [], 1)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(mocked.call_args.kwargs["env"]["PYTHONUTF8"], "1")

    def test_tracked_case_file_covers_four_callers_and_public_settings(self) -> None:
        raw, cases, digest = suite.load_cases(CASE_FILE)
        self.assertEqual(raw["schema_version"], 1)
        self.assertEqual({case.caller_type for case in cases}, suite.CALLER_TYPES)
        self.assertEqual(len(digest), 64)
        combined = " ".join(token for case in cases for token in case.runtime_args)
        self.assertIn("2330", combined)
        self.assertNotIn("--dry-run", combined)

    def test_dry_run_validates_without_xq_or_files(self) -> None:
        args = argparse.Namespace(
            config=Path("missing.json"), cases=CASE_FILE, output_directory=None,
            resume_manifest=None, only_case=[], confirm_historical_backtest=False,
            retry_failed=False, dry_run=True,
        )
        result = suite.run_suite(args, runner=lambda *_: self.fail("runner called"))
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["xq_touched"])
        self.assertEqual(len(result["cases"]), 4)

    def test_confirmation_is_required_before_xq_input(self) -> None:
        args = argparse.Namespace(
            config=Path("missing.json"), cases=CASE_FILE, output_directory=None,
            resume_manifest=None, only_case=[], confirm_historical_backtest=False,
            retry_failed=False, dry_run=False,
        )
        with self.assertRaisesRegex(suite.SuiteError, "confirm-historical-backtest"):
            suite.run_suite(args, runner=lambda *_: self.fail("runner called"))

    def test_execute_case_orders_recovery_compile_open_runtime_recovery(self) -> None:
        _raw, cases, _digest = suite.load_cases(CASE_FILE)
        case = next(item for item in cases if item.caller_type == "alert")
        calls = []

        def runner(script, arguments, timeout):
            calls.append((script, list(arguments)))
            if script == "xq_backtest.py" and "--recovery-status" in arguments:
                return 0, {"status": "success", "decision": "safe_to_start"}
            if script == "xq_existing_script_pipeline.py":
                return 0, {
                    "status": "success",
                    "validated": {
                        "main": {"source_sha256": "a" * 64},
                        "caller": {"source_sha256": "b" * 64},
                    },
                    "stages": {
                        "compile_main": {"status": "success"},
                        "compile_caller": {"status": "success"},
                    },
                }
            if script == "xq_alert_backtest_run.py":
                return 0, {
                    "status": "success", "success_count": 1, "failure_count": 0,
                    "total_trades": 1, "report_cleanup_complete": True,
                    "recovery_checkpoint_retained": False,
                }
            return 0, {"status": "success"}

        result = suite.execute_case(Path("config.json"), case, runner)
        self.assertEqual([item[0] for item in calls], [
            "xq_backtest.py", "xq_existing_script_pipeline.py",
            "xq_open_existing_script.py", "xq_alert_backtest_run.py", "xq_backtest.py",
        ])
        runtime_args = calls[3][1]
        self.assertIn("--confirm-historical-backtest", runtime_args)
        self.assertEqual(result["normalized"]["caller_compile_status"], "success")

    def test_compile_failure_stops_before_open_and_runtime(self) -> None:
        _raw, cases, _digest = suite.load_cases(CASE_FILE)
        calls = []

        def runner(script, arguments, timeout):
            calls.append(script)
            if script == "xq_backtest.py":
                return 0, {"status": "success", "decision": "safe_to_start"}
            return 2, {"status": "compile_error", "compiler_output": "actual"}

        with self.assertRaises(suite.SuiteError) as caught:
            suite.execute_case(Path("config.json"), cases[0], runner)
        self.assertEqual(caught.exception.stage, "compile_pair")
        self.assertEqual(calls, ["xq_backtest.py", "xq_existing_script_pipeline.py"])

    def test_non_safe_recovery_stops_before_compilation(self) -> None:
        _raw, cases, _digest = suite.load_cases(CASE_FILE)
        with self.assertRaisesRegex(suite.SuiteError, "manual_review_required"):
            suite.execute_case(
                Path("config.json"), cases[0],
                lambda *_: (0, {"status": "success", "decision": "manual_review_required"}),
            )

    def test_resume_skips_completed_case_and_rejects_failed_without_confirmation(self) -> None:
        _raw, cases, digest = suite.load_cases(CASE_FILE)
        with tempfile.TemporaryDirectory() as raw_directory:
            private_root = Path(raw_directory).resolve()
            output = private_root / "run"
            output.mkdir()
            with patch.object(suite, "PRIVATE_ROOT", private_root):
                manifest = suite._new_manifest(output, digest, cases)
                manifest["cases"][cases[0].case_id]["status"] = "completed"
                manifest["cases"][cases[1].case_id]["status"] = "failed"
                suite._atomic_json(output / "manifest.json", manifest)
                args = argparse.Namespace(
                    config=Path("config.json"), cases=CASE_FILE, output_directory=None,
                    resume_manifest=output / "manifest.json", only_case=[cases[0].case_id],
                    confirm_historical_backtest=True, retry_failed=False, dry_run=False,
                )
                result = suite.run_suite(args, runner=lambda *_: self.fail("completed case reran"))
                self.assertIn(cases[0].case_id, result["completed_case_ids"])

                args.only_case = [cases[1].case_id]
                with self.assertRaisesRegex(suite.SuiteError, "retry-failed"):
                    suite.run_suite(args, runner=lambda *_: self.fail("failed case reran"))

    def test_summaries_are_json_junit_and_markdown(self) -> None:
        _raw, cases, digest = suite.load_cases(CASE_FILE)
        with tempfile.TemporaryDirectory() as raw_directory:
            private_root = Path(raw_directory).resolve()
            output = private_root / "run"
            output.mkdir()
            with patch.object(suite, "PRIVATE_ROOT", private_root):
                manifest = suite._new_manifest(output, digest, cases)
                for case in cases:
                    manifest["cases"][case.case_id] = {
                        "status": "completed",
                        "caller_type": case.caller_type,
                        "result": {"normalized": {"runtime_status": "success"}},
                    }
                suite._write_summaries(output, manifest, cases)
                summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(summary["completed"], 4)
                self.assertIn("testsuite", (output / "junit.xml").read_text(encoding="utf-8"))
                self.assertIn("| Case | Caller |", (output / "summary.md").read_text(encoding="utf-8"))

    def test_unexpected_exception_is_persisted_and_active_case_is_cleared(self) -> None:
        _raw, cases, _digest = suite.load_cases(CASE_FILE)
        with tempfile.TemporaryDirectory() as raw_directory:
            private_root = Path(raw_directory).resolve()
            output = private_root / "run"
            args = argparse.Namespace(
                config=Path("config.json"), cases=CASE_FILE, output_directory=output,
                resume_manifest=None, only_case=[cases[0].case_id],
                confirm_historical_backtest=True, retry_failed=False, dry_run=False,
            )

            def exploding_runner(*_args):
                raise RuntimeError("simulated child crash")

            with patch.object(suite, "PRIVATE_ROOT", private_root):
                with self.assertRaises(suite.SuiteError) as raised:
                    suite.run_suite(args, runner=exploding_runner)

            self.assertEqual(raised.exception.stage, "unexpected_exception")
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertIsNone(manifest["active_case"])
            state = manifest["cases"][cases[0].case_id]
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["stage"], "unexpected_exception")
            self.assertIn("RuntimeError: simulated child crash", state["error"])

    def test_retry_archives_previous_failure_without_stale_current_error(self) -> None:
        state = {
            "status": "completed", "started_at": "2026-08-02T00:00:00Z",
            "stage": "runtime", "error": "old failure", "child": {"status": "automation_error"},
        }
        suite._archive_stale_failure(state)
        self.assertNotIn("error", state)
        self.assertNotIn("child", state)
        self.assertEqual(state["attempts"][0]["error"], "old failure")


if __name__ == "__main__":
    unittest.main()
