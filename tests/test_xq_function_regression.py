from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
    / "xq_function_regression.py"
)
SPEC = importlib.util.spec_from_file_location("xq_function_regression", SCRIPT_PATH)
assert SPEC and SPEC.loader
regression = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(regression)


def completed_row(
    case_id: str = "pair-a-control",
    *,
    pair_id: str = "pair-a",
    role: str = "control",
    marker: str = "CODEX_REGRESSION_MARKER",
    state: str = "completed",
) -> dict:
    compiler = {
        "compiler_message": "編譯成功，0項錯誤，0項警告",
        "compiler_output": "編譯成功，0項錯誤，0項警告",
        "name": "PrivateDocumentName",
    }
    evaluated = {
        "classification": "failure",
        "success_count": 0,
        "failure_count": 1,
        "total_trades": 0,
        "actual_error_code": "1301",
        "actual_marker": marker,
        "marker_matches": True,
        "execution_evidence": {
            "formal_execution_proven": True,
            "path_sentinel_observed": True,
            "no_execution_evidence": False,
        },
        "settings_applied": {
            "preload_control_enabled": True,
            "expected_preload_state": "enabled",
            "preload_state_matches": True,
            "preload_records_requested": 5,
            "preload_records_applied": True,
        },
        "report_window_handle": 123456,
    }
    return {
        "case_id": case_id,
        "status": state,
        "case": {
            "case_id": case_id,
            "pair_id": pair_id,
            "role": role,
            "product": "2330",
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "caller_frequency": "1",
            "source_frequency": "D",
            "index": 5,
            "caller_index": 0,
            "default_value": None,
            "set_total_bar": None,
            "set_bar_back_count": 6,
            "set_bar_back_frequency": "D",
            "preload_records": 5,
            "expected_sentinel": marker,
            "expected_result": "sentinel_failure",
            "expected_preload_state": "enabled",
            "expect_default_value": True,
            "access_mode": "dynamic",
        },
        "compile": {"function": compiler, "caller": compiler},
        "result": {"result": evaluated} if state == "completed" else None,
    }


def summary(*rows: dict) -> dict:
    return {
        "schema_version": 1,
        "suite_id": "function-regression-smoke-v6",
        "run_id": "private-run-id",
        "cases": list(rows),
    }


class FunctionRegressionTests(unittest.TestCase):
    def normalize(self, payload: dict, *, xq_version: str = "3.19.03") -> dict:
        return regression.normalize_result(
            payload,
            xq_version=xq_version,
            case_schema_version=2,
            runner_contract_version="6",
        )

    def test_normalization_is_private_and_preserves_required_evidence(self) -> None:
        normalized = self.normalize(summary(completed_row()))
        encoded = json.dumps(normalized, ensure_ascii=False)
        self.assertNotIn("PrivateDocumentName", encoded)
        self.assertNotIn("private-run-id", encoded)
        self.assertNotIn("report_window_handle", encoded)
        self.assertNotIn('"product"', encoded)
        case = normalized["cases"]["pair-a-control"]
        self.assertEqual(case["compile"]["function"]["status"], "success")
        self.assertEqual(case["outcome"]["actual_error_code"], "1301")
        self.assertTrue(case["execution_evidence"]["path_sentinel_observed"])

    def test_unchanged_comparison_has_no_affected_pairs(self) -> None:
        current = self.normalize(summary(completed_row()))
        baseline = regression.baseline_from_current(current, 1)
        diff = regression.compare_normalized(current, baseline)
        self.assertEqual(diff["classification"], "unchanged")
        self.assertEqual(diff["affected_pair_ids"], [])
        self.assertEqual(diff["runner_only_pair_arguments"], [])
        self.assertEqual(diff["incremental_plan"]["mode"], "none")

    def test_changed_evidence_selects_the_whole_affected_pair(self) -> None:
        current = self.normalize(summary(completed_row()))
        baseline = regression.baseline_from_current(current, 1)
        baseline["cases"]["pair-a-control"]["outcome"]["total_trades"] = 2
        diff = regression.compare_normalized(current, baseline)
        self.assertEqual(diff["classification"], "regression")
        self.assertEqual(diff["affected_pair_ids"], ["pair-a"])
        self.assertEqual(diff["runner_only_pair_arguments"], ["--only-pair", "pair-a"])
        self.assertEqual(diff["incremental_plan"], {
            "mode": "only_pair",
            "safe_to_execute": True,
            "pair_ids": ["pair-a"],
            "runner_arguments": ["--only-pair", "pair-a"],
            "reason": "normalized_case_difference",
        })

    def test_xq_case_or_runner_version_mismatch_never_looks_unchanged(self) -> None:
        current = self.normalize(summary(completed_row()))
        for field, value in (
            ("xq_version", "3.20.00"),
            ("case_schema_version", 3),
            ("runner_contract_version", "7"),
        ):
            with self.subTest(field=field):
                baseline = regression.baseline_from_current(current, 1)
                baseline[field] = value
                diff = regression.compare_normalized(current, baseline)
                self.assertEqual(diff["classification"], "version_mismatch")
                self.assertEqual(
                    diff["incremental_plan"]["mode"], "full_matrix_required",
                )
                self.assertFalse(diff["incremental_plan"]["safe_to_execute"])
                self.assertEqual(diff["incremental_plan"]["runner_arguments"], [])
                self.assertEqual(diff["runner_only_pair_arguments"], [])

    def test_baseline_update_requires_confirmation_and_preserves_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "result.json"
            old_path = root / "baseline-v1.json"
            new_path = root / "baseline-v2.json"
            output = root / "reports"
            payload = summary(completed_row())
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            current = self.normalize(payload)
            old_path.write_text(
                json.dumps(regression.baseline_from_current(current, 1)),
                encoding="utf-8",
            )
            original = old_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                refused = regression.main([
                    "--result-json", str(result_path),
                    "--baseline", str(old_path),
                    "--xq-version", "3.19.03",
                    "--case-schema-version", "2",
                    "--output-directory", str(output),
                    "--write-baseline", str(new_path),
                    "--baseline-version", "2",
                ])
            self.assertEqual(refused, 3)
            self.assertFalse(new_path.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                written = regression.main([
                    "--result-json", str(result_path),
                    "--baseline", str(old_path),
                    "--xq-version", "3.19.03",
                    "--case-schema-version", "2",
                    "--output-directory", str(output),
                    "--write-baseline", str(new_path),
                    "--baseline-version", "2",
                    "--confirm-baseline-update",
                ])
            self.assertEqual(written, 0)
            self.assertTrue(new_path.exists())
            self.assertEqual(old_path.read_bytes(), original)

    def test_simulated_crash_state_is_evidence_insufficient_not_replayed(self) -> None:
        complete = self.normalize(summary(completed_row()))
        baseline = regression.baseline_from_current(complete, 1)
        interrupted = self.normalize(summary(completed_row(state="running")))
        diff = regression.compare_normalized(interrupted, baseline)
        self.assertEqual(diff["classification"], "evidence_insufficient")
        self.assertEqual(diff["affected_pair_ids"], ["pair-a"])

    def test_simulated_network_loss_without_xq_report_does_not_infer_code(self) -> None:
        complete = self.normalize(summary(completed_row()))
        baseline = regression.baseline_from_current(complete, 1)
        row = completed_row(state="running")
        row["network_observation"] = "injected_disconnect"
        current = self.normalize(summary(row))
        diff = regression.compare_normalized(current, baseline)
        self.assertEqual(diff["classification"], "evidence_insufficient")
        self.assertIsNone(current["cases"]["pair-a-control"]["outcome"]["actual_error_code"])

    def test_tracked_v1_baseline_is_private_and_version_locked(self) -> None:
        path = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "function-regression"
            / "baseline-v1.json"
        )
        baseline = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(baseline["baseline_version"], 1)
        self.assertEqual(baseline["xq_version"], "3.19.03")
        self.assertEqual(baseline["case_schema_version"], 2)
        self.assertEqual(baseline["runner_contract_version"], "6")
        self.assertEqual(len(baseline["cases"]), 4)
        serialized = json.dumps(baseline, ensure_ascii=False)
        for forbidden in (
            "6c85d6c1",
            "CodexB5",
            "7818",
            "2330",
            "2026-07",
            "2026-06",
            "window_handle",
            "report_handle",
            "run_id",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_reports_are_machine_readable_and_markdown_is_sanitized(self) -> None:
        current = self.normalize(summary(completed_row()))
        baseline = regression.baseline_from_current(current, 1)
        diff = regression.compare_normalized(current, baseline)
        with tempfile.TemporaryDirectory() as directory:
            paths = regression.write_reports(Path(directory), diff, current, 1)
            self.assertEqual(json.loads(Path(paths["json"]).read_text())["classification"], "unchanged")
            self.assertEqual(
                json.loads(Path(paths["plan"]).read_text())["mode"], "none",
            )
            xml = ElementTree.parse(paths["junit"]).getroot()
            self.assertEqual(xml.attrib["failures"], "0")
            markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
            self.assertNotIn("PrivateDocumentName", markdown)
            self.assertNotIn("2330", markdown)

if __name__ == "__main__":
    unittest.main()
