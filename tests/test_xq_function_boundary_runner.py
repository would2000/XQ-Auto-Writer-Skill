from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
    / "xq_function_boundary_runner.py"
)
SPEC = importlib.util.spec_from_file_location("xq_function_boundary_runner", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def checkpoint(*baseline: int):
    return runner.xq_backtest.RecoveryCheckpoint(
        schema_version=2,
        run_id="00000000-0000-0000-0000-000000000001",
        stage="running",
        started_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:01+00:00",
        xq_process_id=100,
        xq_window_handle=10,
        xscript_window_handle=11,
        progress_window_handle=12,
        baseline_report_handles=baseline,
        backtest_started=True,
        cancellation_confirmed=False,
    )


def report(handle: int, marker: str) -> dict:
    return {
        "window_handle": handle,
        "status": "failure",
        "success_count": 0,
        "failure_count": 1,
        "total_trades": 0,
        "failure_details": [{
            "error_code": "1301",
            "description": f"RaiseRunTimeError:{marker}",
        }],
    }


class XQFunctionBoundaryRunnerTests(unittest.TestCase):
    def sample_case(self, **changes):
        case = runner.BoundaryCase(
            case_id="daily-control",
            pair_id="daily",
            role="control",
            product="7818",
            start_date="2026-07-20",
            end_date="2026-07-21",
            caller_frequency="day",
            source_frequency="D",
            index=44,
            caller_index=0,
            default_value=None,
            set_total_bar=None,
            set_bar_back_count=46,
            set_bar_back_frequency="D",
            preload_records=5,
            expected_sentinel="CODEX_B4_D44_CONTROL_PATH",
            expected_result="sentinel_failure",
            expected_preload_state="enabled",
            expect_default_value=True,
            access_mode="dynamic",
        )
        return runner.replace(case, **changes)

    def test_case_file_automatically_pairs_shorter_control(self) -> None:
        case_path = PROJECT_ROOT / "generated" / "function-data-boundary-cases-v4.json"
        _suite, cases = runner.load_case_file(case_path)
        self.assertEqual([item.role for item in cases], ["control", "shortage"])
        self.assertLess(cases[0].index, cases[1].index)
        self.assertEqual(cases[0].pair_id, cases[1].pair_id)
        self.assertNotEqual(cases[0].expected_sentinel, cases[1].expected_sentinel)

    def test_v5_matrix_covers_frequency_access_default_and_preload_dimensions(self) -> None:
        case_path = PROJECT_ROOT / "generated" / "function-data-boundary-cases-v5.json"
        _suite, cases = runner.load_case_file(case_path)
        self.assertEqual(len(cases), 8)
        self.assertEqual({item.caller_frequency for item in cases}, {"1", "day"})
        self.assertEqual({item.source_frequency for item in cases}, {"D", "W", "M"})
        self.assertEqual({item.access_mode for item in cases}, {"dynamic", "fixed"})
        self.assertEqual({item.expected_preload_state for item in cases}, {"enabled", "disabled"})
        self.assertTrue(any(item.default_value is None for item in cases))
        self.assertTrue(any(item.default_value is not None for item in cases))
        self.assertTrue(any(item.set_total_bar is not None for item in cases))
        self.assertTrue(any(item.set_bar_back_count is not None for item in cases))
        self.assertTrue(any(item.caller_index > 0 for item in cases))
        for control, shortage in zip(cases[::2], cases[1::2]):
            self.assertLessEqual(control.index, shortage.index)
            self.assertLessEqual(control.caller_index, shortage.caller_index)
            self.assertTrue(
                control.index < shortage.index
                or control.caller_index < shortage.caller_index
            )

    def test_v6_smoke_uses_two_public_products_dates_and_marker_cases(self) -> None:
        case_path = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "function-regression"
            / "cases-v6.json"
        )
        _suite, cases = runner.load_case_file(case_path)
        self.assertEqual({case.product for case in cases}, {"7818", "2330"})
        self.assertEqual(
            {(case.start_date, case.end_date) for case in cases},
            {("2026-07-20", "2026-07-21"), ("2026-06-01", "2026-06-02")},
        )
        self.assertTrue(all(case.expected_result == "sentinel_failure" for case in cases))

    def test_normal_completion_preserves_actual_runtime_evidence(self) -> None:
        case = self.sample_case()
        payload = {
            **report(50, case.expected_sentinel),
            "settings_evidence": {
                "preload_control_enabled": True,
                "preload_records_requested": 5,
                "preload_records_applied": True,
            },
            "report_window_handle": 50,
        }
        result = runner.evaluate_case_result(case, payload)
        self.assertTrue(result["passed"])
        self.assertEqual(result["actual_error_code"], "1301")
        self.assertEqual(result["actual_marker"], case.expected_sentinel)
        self.assertTrue(result["execution_evidence"]["formal_execution_proven"])

        no_execution = runner.evaluate_case_result(
            self.sample_case(
                role="shortage",
                expected_result="no_execution_evidence",
                expected_sentinel="CODEX_B4_D45_SHORTAGE_PATH",
                index=45,
            ),
            {
                "status": "success", "success_count": 1, "failure_count": 0,
                "total_trades": 0, "failure_details": [],
                "settings_evidence": {
                    "preload_control_enabled": True,
                    "preload_records_requested": 5,
                    "preload_records_applied": True,
                },
            },
        )
        self.assertTrue(no_execution["passed"])
        self.assertIsNone(no_execution["actual_error_code"])
        self.assertTrue(no_execution["execution_evidence"]["no_execution_evidence"])

    def test_late_report_requires_unique_new_handle_and_marker(self) -> None:
        assessment = runner.evaluate_late_report_recovery(
            checkpoint(20),
            [report(20, "CODEX_OLD_REPORT"), report(21, "CODEX_EXPECTED_LATE")],
            "CODEX_EXPECTED_LATE",
        )
        self.assertEqual(assessment["decision"], "recovered")
        self.assertTrue(assessment["checkpoint_may_be_cleared"])
        self.assertEqual(assessment["report_window_handle"], 21)

    def test_late_report_merges_only_actual_backtest_settings_and_handle(self) -> None:
        late = report(21, "CODEX_EXPECTED_LATE")
        merged = runner.merge_late_report_evidence(
            late,
            {
                "settings_evidence": {
                    "preload_control_enabled": True,
                    "preload_records_requested": 5,
                    "preload_records_applied": True,
                },
                "untrusted_other_field": "must-not-be-copied",
            },
        )
        self.assertEqual(merged["report_window_handle"], 21)
        self.assertTrue(merged["settings_evidence"]["preload_control_enabled"])
        self.assertNotIn("untrusted_other_field", merged)

    def test_nonunique_late_reports_remain_manual_review(self) -> None:
        assessment = runner.evaluate_late_report_recovery(
            checkpoint(20),
            [report(21, "CODEX_EXPECTED_LATE"), report(22, "CODEX_EXPECTED_LATE")],
            "CODEX_EXPECTED_LATE",
        )
        self.assertEqual(assessment["decision"], "manual_review_required")
        self.assertEqual(assessment["reason"], "new_report_not_unique")
        self.assertFalse(assessment["checkpoint_may_be_cleared"])

    def test_marker_mismatch_remains_manual_review_without_inferred_code(self) -> None:
        candidate = report(21, "CODEX_DIFFERENT_MARKER")
        candidate["failure_details"][0]["error_code"] = None
        assessment = runner.evaluate_late_report_recovery(
            checkpoint(20), [candidate], "CODEX_EXPECTED_LATE",
        )
        self.assertEqual(assessment["decision"], "manual_review_required")
        self.assertEqual(assessment["reason"], "marker_mismatch")
        self.assertIsNone(assessment["actual_error_code"])
        self.assertFalse(assessment["checkpoint_may_be_cleared"])

    def test_cleanup_refuses_name_type_or_manifest_mismatch(self) -> None:
        record = {
            "name": "CodexB4Doc",
            "script_type": "function",
            "type_readback": "function",
            "storage_location": "自訂/CODEX/",
            "created": True,
        }
        self.assertTrue(runner.authorize_document_cleanup(record, "CodexB4Doc", "function"))
        self.assertFalse(
            runner.authorize_document_cleanup(
                record, "CodexB4Doc", "function", "自訂/",
            )
        )
        for name, script_type, created in (
            ("OtherDoc", "function", True),
            ("CodexB4Doc", "autotrade", True),
            ("CodexB4Doc", "function", False),
        ):
            changed = dict(record, created=created)
            self.assertFalse(runner.authorize_document_cleanup(changed, name, script_type))

    def test_cleanup_treats_uncreated_manifest_record_as_noop(self) -> None:
        outcome = runner.delete_manifest_document(
            {},
            {
                "name": "CodexB5NeverCreated",
                "script_type": "autotrade",
                "created": False,
                "deleted": False,
                "creation_disproven": True,
            },
        )
        self.assertTrue(outcome["deleted"])
        self.assertTrue(outcome["not_created"])
        self.assertFalse(outcome["xq_delete_attempted"])

        uncertain = runner.delete_manifest_document(
            {},
            {
                "name": "CodexB5MaybeCreated",
                "script_type": "function",
                "created": False,
                "deleted": False,
            },
        )
        self.assertFalse(uncertain["deleted"])
        self.assertEqual(uncertain["reason"], "manifest_creation_state_unconfirmed")

    def test_settotalbar_disabled_preload_is_reported_not_assumed(self) -> None:
        case = self.sample_case(set_total_bar=21, expected_preload_state="disabled")
        payload = {
            **report(51, case.expected_sentinel),
            "settings_evidence": {
                "preload_control_enabled": False,
                "preload_records_requested": 5,
                "preload_records_applied": False,
            },
        }
        result = runner.evaluate_case_result(case, payload)
        self.assertTrue(result["passed"])
        self.assertFalse(result["settings_applied"]["preload_control_enabled"])
        self.assertFalse(result["settings_applied"]["preload_records_applied"])
        function_source, caller_source = runner.render_sources(case, "CodexB4Fn")
        self.assertIn("SetTotalBar(21);", caller_source)
        self.assertNotIn("SetTotalBar", function_source)

    def test_started_automation_error_with_checkpoint_requires_reconciliation(self) -> None:
        self.assertTrue(runner.backtest_requires_reconciliation({
            "status": "automation_error",
            "recovery_checkpoint_retained": True,
        }))
        self.assertTrue(runner.backtest_requires_reconciliation({
            "status": "indeterminate_timeout",
            "recovery_checkpoint_retained": True,
        }))
        self.assertFalse(runner.backtest_requires_reconciliation({
            "status": "automation_error",
            "recovery_checkpoint_retained": False,
        }))

    def test_render_sources_supports_fixed_default_and_caller_series_index(self) -> None:
        case = self.sample_case(
            role="shortage",
            access_mode="fixed",
            default_value=-999,
            caller_index=2,
            expected_sentinel="CODEX_B5_FIXED_DEFAULT_PATH",
        )
        function_source, caller_source = runner.render_sources(case, "CodexB5Fn")
        self.assertIn('GetField("Close", "D", Default := -999)[44]', function_source)
        self.assertIn("BoundaryObserved = BoundaryValue[2];", caller_source)
        self.assertIn("if BoundaryObserved = -999 then", caller_source)

        nondefault_case = self.sample_case(
            role="shortage",
            access_mode="fixed",
            default_value=-999,
            expect_default_value=False,
            expected_sentinel="CODEX_B5_FIXED_NONDEFAULT_PATH",
        )
        _, nondefault_source = runner.render_sources(nondefault_case, "CodexB5Fn")
        self.assertIn(
            'else\n    RaiseRunTimeError("CODEX_B5_FIXED_NONDEFAULT_PATH");',
            nondefault_source,
        )

    def test_completed_cases_are_not_selected_for_resume(self) -> None:
        cases = [self.sample_case(), self.sample_case(case_id="daily-shortage", role="shortage")]
        manifest = {"case_states": runner.initialize_case_states(cases)}
        manifest["case_states"]["daily-control"]["status"] = "completed"
        self.assertEqual(
            [item.case_id for item in runner.pending_cases(cases, manifest)],
            ["daily-shortage"],
        )

    def test_only_pair_selection_keeps_control_and_shortage_together(self) -> None:
        cases = [
            self.sample_case(case_id="pair-a-control", pair_id="pair-a", role="control"),
            self.sample_case(case_id="pair-a-shortage", pair_id="pair-a", role="shortage"),
            self.sample_case(case_id="pair-b-control", pair_id="pair-b", role="control"),
            self.sample_case(case_id="pair-b-shortage", pair_id="pair-b", role="shortage"),
        ]
        selected, pair_ids = runner.select_case_pairs(cases, ["pair-b"])
        self.assertEqual(pair_ids, ["pair-b"])
        self.assertEqual(
            [case.case_id for case in selected],
            ["pair-b-control", "pair-b-shortage"],
        )
        with self.assertRaisesRegex(ValueError, "Unknown boundary pair"):
            runner.select_case_pairs(cases, ["missing-pair"])

    def test_progress_outputs_are_machine_readable_json_and_junit(self) -> None:
        case = self.sample_case()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "suite_id": "function-data-boundary-v5",
                "run_id": "00000000-0000-0000-0000-000000000002",
                "case_digest": "a" * 64,
                "runner_contract_version": runner.RUNNER_CONTRACT_VERSION,
                "selected_pair_ids": [case.pair_id],
                "active_case_id": None,
                "cleanup_states": {},
                "active_cleanup_document_id": None,
                "case_states": runner.initialize_case_states([case]),
                "output_json": str(root / "summary.json"),
                "output_junit": str(root / "summary.xml"),
            }
            runner.write_progress_outputs(manifest)
            payload = json.loads((root / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["counts"], {
                "total": 1, "completed": 0, "failed": 0, "pending": 1,
            })
            xml_root = ElementTree.fromstring((root / "summary.xml").read_text(encoding="utf-8"))
            self.assertEqual(xml_root.attrib["tests"], "1")
            self.assertEqual(xml_root.attrib["skipped"], "1")

    def test_resume_reconciles_unique_marker_without_rerunning_completed_case(self) -> None:
        case = self.sample_case(expected_sentinel="CODEX_B5_RESUME_MARKER")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "xq-ui.json"
            config_path.write_text("{}", encoding="utf-8")
            manifest_path = root / "manifest.json"
            manifest = {
                "suite_id": "function-data-boundary-v5",
                "run_id": "00000000-0000-0000-0000-000000000003",
                "case_digest": "b" * 64,
                "runner_contract_version": runner.RUNNER_CONTRACT_VERSION,
                "selected_pair_ids": [case.pair_id],
                "documents": [],
                "report_handles": [],
                "temp_paths": [],
                "completed_case_ids": [],
                "case_states": runner.initialize_case_states([case]),
                "active_case_id": case.case_id,
                "output_json": str(root / "summary.json"),
                "output_junit": str(root / "summary.xml"),
            }
            state = manifest["case_states"][case.case_id]
            state.update({
                "status": "running",
                "stage": "backtest_started",
                "attempts": 1,
                "baseline_report_handles": [20],
                "backtest_evidence": {
                    "settings_evidence": {
                        "preload_control_enabled": True,
                        "preload_records_requested": 5,
                        "preload_records_applied": True,
                    },
                },
                "compile": {"function": {"compiler_message": "ok"}, "caller": {"compiler_message": "ok"}},
            })
            runner.atomic_write_json(manifest_path, manifest)
            late = report(21, case.expected_sentinel)
            with mock.patch.object(
                runner, "capture_visible_reports_with_details", return_value=[late],
            ):
                result = runner.reconcile_active_case_on_resume(
                    config_path, {}, manifest, manifest_path, [case], 0,
                )
            self.assertTrue(result["resumed_without_rerun"])
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["attempts"], 1)
            self.assertEqual(runner.pending_cases([case], manifest), [])

    def test_resume_manifest_requires_same_digest_and_case_contracts(self) -> None:
        suite_path = PROJECT_ROOT / "generated" / "function-data-boundary-cases-v5.json"
        suite, cases = runner.load_case_file(suite_path)
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory)
            base = private_root / "function-boundary-runs"
            run_root = base / "run"
            run_root.mkdir(parents=True)
            manifest_path = run_root / "manifest.json"
            manifest = {
                "schema_version": runner.MANIFEST_SCHEMA_VERSION,
                "run_id": "00000000-0000-0000-0000-000000000004",
                "suite_id": suite["suite_id"],
                "case_file": str(suite_path),
                "case_digest": runner.case_file_digest(suite),
                "runner_contract_version": runner.RUNNER_CONTRACT_VERSION,
                "selected_pair_ids": list(dict.fromkeys(case.pair_id for case in cases)),
                "documents": [],
                "report_handles": [],
                "temp_paths": [],
                "completed_case_ids": [],
                "case_states": runner.initialize_case_states(cases),
                "active_case_id": None,
                "cleanup_states": {},
                "active_cleanup_document_id": None,
                "output_json": str(private_root / "results" / "summary.json"),
                "output_junit": str(private_root / "results" / "summary.xml"),
                "late_recovery_probe": {
                    "case_id": cases[0].case_id,
                    "required": True,
                    "observed": False,
                },
                "pacing": runner.asdict(runner.UiWaitPolicy()),
                "windows_wait_incidents": [{
                    "error": "Timed out waiting for XScript open dialog",
                }],
            }
            runner.atomic_write_json(manifest_path, manifest)
            loaded = runner.validate_resume_manifest(manifest_path, base, suite, cases)
            self.assertEqual(loaded["run_id"], manifest["run_id"])
            manifest["case_digest"] = "0" * 64
            runner.atomic_write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "does not match"):
                runner.validate_resume_manifest(manifest_path, base, suite, cases)

    def test_adaptive_wait_reports_ready_late_and_timeout(self) -> None:
        policy = runner.UiWaitPolicy(
            action_settle_seconds=0.1,
            poll_initial_seconds=0.1,
            poll_max_seconds=0.2,
            poll_backoff=2,
            dialog_late_after_seconds=0.15,
            dialog_timeout_seconds=1,
            state_timeout_seconds=1,
            inter_case_seconds=1,
        )
        now = [0.0]
        attempts = [0]

        def clock():
            return now[0]

        def sleep(seconds):
            now[0] += seconds

        def late_probe():
            attempts[0] += 1
            return "dialog" if attempts[0] == 3 else None

        late = runner.adaptive_wait_for(
            late_probe,
            timeout_seconds=1,
            late_after_seconds=0.15,
            policy=policy,
            clock=clock,
            sleeper=sleep,
        )
        self.assertEqual(late["status"], "late")
        self.assertEqual(late["value"], "dialog")
        self.assertEqual(late["attempts"], 3)

        now[0] = 0
        timeout = runner.adaptive_wait_for(
            lambda: None,
            timeout_seconds=0.25,
            policy=policy,
            clock=clock,
            sleeper=sleep,
        )
        self.assertEqual(timeout["status"], "timeout")

    def test_ctrl_o_late_dialog_stops_without_fallback_input(self) -> None:
        xscript = mock.Mock(handle=11)
        xscript.window_text.return_value = "XScript"
        dialog = mock.Mock(handle=12)
        with (
            mock.patch.object(
                runner, "desktop_windows", side_effect=[[xscript], []],
            ),
            mock.patch.object(runner, "wait_for_window_enabled"),
            mock.patch.object(runner, "ui_action_pause"),
            mock.patch.object(
                runner,
                "adaptive_wait_for",
                return_value={
                    "status": "late", "value": dialog,
                    "elapsed_seconds": 5, "attempts": 4,
                },
            ),
            mock.patch("pywinauto.keyboard.send_keys") as send_keys,
            mock.patch("ctypes.windll.user32.ShowWindow"),
        ):
            with self.assertRaisesRegex(runner.UiWaitIncident, "ctrl_o_dialog_late"):
                runner._open_xscript_open_dialog({})
        send_keys.assert_called_once_with("^o")

    def test_temporarily_disabled_window_waits_without_input(self) -> None:
        window = mock.Mock(handle=11)
        with mock.patch.object(
            runner,
            "adaptive_wait_for",
            return_value={
                "status": "ready", "value": window,
                "elapsed_seconds": 1, "attempts": 3,
            },
        ) as wait:
            result = runner.wait_for_window_enabled(window, "temporary_disabled")
        self.assertEqual(result["attempts"], 3)
        wait.assert_called_once()

    def test_cleanup_state_machine_skips_repeated_verified_document(self) -> None:
        record = {
            "case_id": "daily-control",
            "name": "CodexB7Doc",
            "script_type": "function",
            "created": True,
            "deleted": False,
            "type_readback": "function",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            manifest = {
                "documents": [record],
                "cleanup_states": runner.initialize_cleanup_states([record]),
                "active_cleanup_document_id": None,
            }

            def delete(_config, _record, *, on_stage):
                on_stage("open_requested", {})
                on_stage("identity_readback_verified", {})
                on_stage("delete_confirmation_verified", {})
                on_stage("absence_verified", {"already_absent": True})
                return {"deleted": True, "already_absent": True}

            with mock.patch.object(
                runner, "delete_manifest_document", side_effect=delete,
            ) as delete_mock:
                first = runner.cleanup_one_manifest_document({}, manifest, path, record)
                second = runner.cleanup_one_manifest_document({}, manifest, path, record)
            self.assertTrue(first["absence_verified"])
            self.assertTrue(second["cleanup_state_skipped"])
            self.assertEqual(delete_mock.call_count, 1)
            state = next(iter(manifest["cleanup_states"].values()))
            self.assertEqual(state["stage"], "completed")
            self.assertEqual(state["attempts"], 1)

    def test_incident_resume_continues_cleanup_without_rerunning_completed_case(self) -> None:
        case = self.sample_case()
        record = {
            "case_id": case.case_id,
            "name": "CodexB7Resume",
            "script_type": "autotrade",
            "created": True,
            "deleted": False,
            "type_readback": "autotrade",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            states = runner.initialize_case_states([case])
            states[case.case_id]["status"] = "completed"
            cleanup_states = runner.initialize_cleanup_states([record])
            cleanup_state = next(iter(cleanup_states.values()))
            cleanup_state.update({
                "status": "in_progress",
                "stage": "identity_readback_verified",
                "attempts": 1,
            })
            manifest = {
                "documents": [record],
                "cleanup_states": cleanup_states,
                "active_cleanup_document_id": cleanup_state["document_id"],
                "case_states": states,
            }

            def resumed_delete(_config, _record, *, on_stage):
                on_stage("open_requested", {"resume": True})
                on_stage("absence_verified", {"already_absent": True})
                return {"deleted": True, "already_absent": True}

            with mock.patch.object(
                runner, "delete_manifest_document", side_effect=resumed_delete,
            ):
                outcome = runner.cleanup_one_manifest_document({}, manifest, path, record)
            self.assertTrue(outcome["deleted"])
            self.assertEqual(runner.pending_cases([case], manifest), [])
            self.assertEqual(cleanup_state["stage"], "completed")

    def test_temp_cleanup_refuses_paths_outside_manifest_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            root.mkdir()
            inside = root / "inside.tmp"
            outside = Path(directory) / "outside.tmp"
            inside.write_text("x", encoding="utf-8")
            outside.write_text("y", encoding="utf-8")
            results = runner.cleanup_temp_paths(root, [str(inside), str(outside)])
            self.assertTrue(results[0]["removed"])
            self.assertFalse(results[1]["removed"])
            self.assertTrue(outside.exists())

    def test_inter_case_pacing_has_safe_default_and_accepts_slower_value(self) -> None:
        required = [
            "--config", "xq-ui.json",
            "--cases", "cases.json",
            "--confirm-historical-backtest",
        ]
        defaults = runner.parse_args(required)
        self.assertEqual(defaults.inter_case_seconds, runner.DEFAULT_INTER_CASE_SECONDS)
        slower = runner.parse_args([*required, "--inter-case-seconds", "12"])
        self.assertEqual(slower.inter_case_seconds, 12)

    def test_resume_wait_policy_never_becomes_faster(self) -> None:
        recorded = runner.UiWaitPolicy(
            action_settle_seconds=4,
            poll_initial_seconds=0.5,
            poll_max_seconds=2,
            poll_backoff=2,
            dialog_late_after_seconds=8,
            dialog_timeout_seconds=30,
            state_timeout_seconds=30,
            inter_case_seconds=10,
        )
        effective = runner.slower_resume_policy(
            recorded, runner.UiWaitPolicy(),
        )
        self.assertEqual(effective, recorded)

    def test_windows_wait_incident_records_runtime_and_active_case(self) -> None:
        case = self.sample_case()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest = {
                "active_case_id": case.case_id,
                "case_states": runner.initialize_case_states([case]),
                "windows_wait_incidents": [],
            }
            manifest["case_states"][case.case_id]["stage"] = "caller_compiled"
            recovery = {
                "status": "success",
                "decision": "manual_review_required",
                "reason_codes": ["environment_unknown"],
                "runtime": {"xscript_window_hung": True, "xq_process_id": 100},
                "checkpoint_present": False,
                "visible_reports": [],
            }
            with mock.patch.object(
                runner,
                "run_json_tool",
                return_value={"payload": recovery, "returncode": 0},
            ):
                incident = runner.record_windows_wait_incident(
                    root / "xq-ui.json",
                    manifest,
                    manifest_path,
                    RuntimeError("Window (hwnd=11) is not responding!"),
                )
            self.assertIsNotNone(incident)
            self.assertEqual(incident["active_case_id"], case.case_id)
            self.assertEqual(incident["active_case_stage"], "caller_compiled")
            self.assertTrue(
                incident["recovery_status"]["runtime"]["xscript_window_hung"]
            )
            stored = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(stored["windows_wait_incidents"]), 1)

    def test_non_wait_error_does_not_create_windows_wait_incident(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = {"active_case_id": None, "case_states": {}}
            incident = runner.record_windows_wait_incident(
                Path(directory) / "xq-ui.json",
                manifest,
                Path(directory) / "manifest.json",
                ValueError("bad case schema"),
            )
            self.assertIsNone(incident)
            self.assertNotIn("windows_wait_incidents", manifest)


if __name__ == "__main__":
    unittest.main()
