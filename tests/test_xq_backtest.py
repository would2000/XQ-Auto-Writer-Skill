from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import ANY, Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts" / "xq_backtest.py"
SKILL_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
GUIDE_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references" / "autotrade-window-guide.md"
SPEC = importlib.util.spec_from_file_location("xq_backtest", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
xq_backtest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = xq_backtest
SPEC.loader.exec_module(xq_backtest)


class XQBacktestTests(unittest.TestCase):
    def healthy_runtime(self) -> object:
        return xq_backtest.RuntimeSnapshot(
            captured_at="2026-07-21T00:00:00+00:00",
            expected_xq_process_id=100,
            xq_process_id=100,
            xq_process_exists=True,
            xq_window_handle=10,
            xq_window_exists=True,
            xq_window_visible=True,
            xq_window_enabled=True,
            xq_window_hung=False,
            xscript_window_handle=11,
            xscript_window_exists=True,
            xscript_window_visible=True,
            xscript_window_enabled=True,
            xscript_window_hung=False,
        )

    def test_apply_preload_records_writes_enabled_control(self) -> None:
        control = Mock()
        control.is_enabled.return_value = True
        with (
            patch.object(xq_backtest, "control_by_id", return_value=control),
            patch.object(xq_backtest, "set_edit") as set_edit,
        ):
            evidence = xq_backtest.apply_preload_records(object(), 5)

        set_edit.assert_called_once_with(ANY, 2007, 5)
        self.assertEqual(
            evidence,
            {
                "preload_control_enabled": True,
                "preload_records_requested": 5,
                "preload_records_applied": True,
            },
        )

    def test_apply_preload_records_skips_disabled_control(self) -> None:
        control = Mock()
        control.is_enabled.return_value = False
        with (
            patch.object(xq_backtest, "control_by_id", return_value=control),
            patch.object(xq_backtest, "set_edit") as set_edit,
        ):
            evidence = xq_backtest.apply_preload_records(object(), 5)

        set_edit.assert_not_called()
        self.assertEqual(
            evidence,
            {
                "preload_control_enabled": False,
                "preload_records_requested": 5,
                "preload_records_applied": False,
            },
        )

    def test_skill_and_guide_document_cli_and_safety_boundary(self) -> None:
        skill = SKILL_PATH.read_text(encoding="utf-8")
        guide = GUIDE_PATH.read_text(encoding="utf-8")
        for required in (
            "scripts/xq_backtest.py",
            "--dry-run",
            "--cancel-after-seconds",
            "--cancel-after-completed-products",
            "--show-partial-results-on-cancel",
            "--acknowledge-stale-checkpoint",
            "--recovery-status",
            "`safe_to_start`",
            "`monitor_existing`",
            "`manual_review_required`",
            "`environment_interruption`",
            "`partial_failure`",
            "`indeterminate_timeout`",
            "`recovery_complete: true`",
            "never selects an account",
        ):
            self.assertIn(required, skill)
        for required in (
            "可重用回測 CLI",
            "記錄所有可見頂層 handle",
            "代碼完全相符列",
            "`partial_results_requested`",
            "`recovery_complete`",
            "一至二十個明確公開代碼",
            "第三階段",
            "`cancel_reason: timeout`",
            "環境復原第一、二階段",
            "`xq_process_exited`",
            "`checkpoint_invalid`",
            "唯讀復原診斷與安全決策",
            "`report_checkpoint_association_proven: false`",
            "真實 XQ 當機、強制關閉及實際斷網不列入驗證範圍",
        ):
            self.assertIn(required, guide)

    def test_report_summary_and_five_state_classification(self) -> None:
        success = xq_backtest.report_summary(
            [("DataItem", "1(成功)"), ("DataItem", "總交易次數"), ("DataItem", "21")]
        )
        self.assertEqual(success, xq_backtest.ReportSummary(1, 0, 21))
        self.assertEqual(xq_backtest.classify_report(success), "success")

        failure = xq_backtest.report_summary(
            [("DataItem", "0(成功)1(失敗)"), ("DataItem", "總交易次數"), ("DataItem", "0")]
        )
        self.assertEqual(failure, xq_backtest.ReportSummary(0, 1, 0))
        self.assertEqual(xq_backtest.classify_report(failure), "failure")

        partial = xq_backtest.report_summary([("DataItem", "2(成功)3(失敗)")])
        self.assertEqual(xq_backtest.classify_report(partial), "partial_failure")
        self.assertIsNone(xq_backtest.report_summary([("DataItem", "0(成功)0(失敗)")]))
        self.assertIsNone(xq_backtest.report_summary([("Text", "沒有任何交易資料")]))

    def test_failure_detail_extracts_actual_code_without_inference(self) -> None:
        detail = xq_backtest.failure_detail(
            "2330.TW(台積電)",
            "錯誤",
            "執行時發生錯誤[(1301)RaiseRunTimeError:CodexBacktestIntentionalFailure]",
        )
        self.assertEqual(detail.error_code, "1301")
        self.assertEqual(detail.product, "2330.TW(台積電)")
        self.assertIn("RaiseRunTimeError", detail.description)

        unknown = xq_backtest.failure_detail("TEST", "錯誤", "未提供代碼")
        self.assertIsNone(unknown.error_code)

    def test_settings_validation_rejects_unsafe_boundaries(self) -> None:
        base = [
            "--config", "config.json", "--product", "2330", "--frequency", "day",
            "--start-date", "2026-06-01", "--end-date", "2026-06-30",
        ]
        settings = xq_backtest.settings_from_args(xq_backtest.parse_args(base))
        self.assertEqual(settings.products, ("2330",))
        self.assertEqual(settings.max_position, 1)
        self.assertFalse(settings.direct_order)

        invalid_cases = (
            base[:-1] + ["2026-05-31"],
            base + ["--max-position", "0"],
            base + ["--product", "23 30"],
            base + ["--timeout-seconds", "0"],
            base + ["--cancel-after-seconds", "60", "--timeout-seconds", "60"],
            base + ["--cancel-after-seconds", "1", "--cancel-on-timeout"],
            base + ["--cancel-after-seconds", "1", "--dry-run"],
            base + ["--show-partial-results-on-cancel"],
            base + ["--product", "2330"],
            base + ["--cancel-after-completed-products", "0"],
            base + ["--cancel-after-completed-products", "1", "--cancel-after-seconds", "1"],
        )
        for arguments in invalid_cases:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                xq_backtest.settings_from_args(xq_backtest.parse_args(arguments))

        multiple = xq_backtest.settings_from_args(
            xq_backtest.parse_args(base + ["--product", "2317"])
        )
        self.assertEqual(multiple.products, ("2330", "2317"))

    def test_cancellation_recovery_requires_requested_report_contract(self) -> None:
        base = dict(
            confirmation_seen=True,
            progress_closed=True,
            xscript_ready=True,
            partial_results_request_succeeded=True,
            partial_report_summary_available=False,
            partial_success_count=None,
            partial_failure_count=None,
            partial_total_trades=None,
        )
        no_partial = xq_backtest.CancellationEvidence(
            partial_results_requested=False,
            partial_report_seen=False,
            **base,
        )
        with_partial = xq_backtest.CancellationEvidence(
            partial_results_requested=True,
            partial_report_seen=True,
            **base,
        )
        missing_partial = xq_backtest.CancellationEvidence(
            partial_results_requested=True,
            partial_report_seen=False,
            **base,
        )
        self.assertTrue(xq_backtest.cancellation_recovery_complete(no_partial))
        self.assertTrue(xq_backtest.cancellation_recovery_complete(with_partial))
        self.assertFalse(xq_backtest.cancellation_recovery_complete(missing_partial))
        request_failed = xq_backtest.CancellationEvidence(
            partial_results_requested=False,
            partial_results_request_succeeded=False,
            partial_report_seen=False,
            **{key: value for key, value in base.items() if key != "partial_results_request_succeeded"},
        )
        self.assertFalse(xq_backtest.cancellation_recovery_complete(request_failed))

    def test_completed_product_count_uses_only_terminal_states(self) -> None:
        self.assertEqual(
            xq_backtest.completed_product_count(["完成", "成功", "執行中", "等待中", "錯誤"]),
            3,
        )
        self.assertEqual(xq_backtest.cancellation_recovery_timeout(False), 10.0)
        self.assertEqual(xq_backtest.cancellation_recovery_timeout(True), 30.0)

    def test_runtime_interruption_classification_uses_explicit_evidence(self) -> None:
        healthy = self.healthy_runtime()
        self.assertIsNone(xq_backtest.classify_runtime_interruption(healthy))
        self.assertEqual(
            xq_backtest.classify_runtime_interruption(replace(healthy, xq_process_exists=False)),
            "xq_process_exited",
        )
        self.assertEqual(
            xq_backtest.classify_runtime_interruption(replace(healthy, xq_window_hung=True)),
            "xq_unresponsive",
        )
        self.assertEqual(
            xq_backtest.classify_runtime_interruption(replace(healthy, xscript_window_exists=False)),
            "xscript_closed",
        )
        self.assertEqual(
            xq_backtest.classify_runtime_interruption(replace(healthy, xq_window_exists=False)),
            "xq_window_missing",
        )
        self.assertEqual(
            xq_backtest.classify_runtime_interruption(
                replace(healthy, expected_xq_process_id=None, xq_process_id=None)
            ),
            "environment_unknown",
        )

    def test_recovery_checkpoint_is_atomic_private_and_reconcilable(self) -> None:
        snapshot = self.healthy_runtime()
        checkpoint = xq_backtest.create_checkpoint(snapshot)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "recovery-state.json"
            xq_backtest.write_checkpoint(path, checkpoint)
            loaded = xq_backtest.load_checkpoint(path)
            self.assertEqual(loaded, checkpoint)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for forbidden in (
                "products", "product", "script_name", "script_source", "account",
                "parameters", "performance",
            ):
                self.assertNotIn(forbidden, payload)
            updated = xq_backtest.update_checkpoint(
                checkpoint,
                stage="running",
                progress_window_handle=12,
            )
            xq_backtest.write_checkpoint(path, updated)
            self.assertEqual(xq_backtest.load_checkpoint(path).progress_window_handle, 12)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            xq_backtest.remove_checkpoint(path)
            self.assertFalse(path.exists())

        self.assertEqual(xq_backtest.reconcile_stale_checkpoint(checkpoint, True, False), "block")
        self.assertEqual(xq_backtest.reconcile_stale_checkpoint(checkpoint, False, False), "clear")
        self.assertEqual(xq_backtest.reconcile_stale_checkpoint(checkpoint, False, True), "block")
        not_started = replace(checkpoint, backtest_started=False)
        self.assertEqual(xq_backtest.reconcile_stale_checkpoint(not_started, True, False), "clear")

    def test_checkpoint_schema_rejects_unknown_or_sensitive_fields(self) -> None:
        checkpoint = xq_backtest.RecoveryCheckpoint(
            schema_version=2,
            run_id="00000000-0000-0000-0000-000000000001",
            stage="running",
            started_at="2026-07-21T00:00:00+00:00",
            updated_at="2026-07-21T00:00:01+00:00",
            xq_process_id=100,
            xq_window_handle=10,
            xscript_window_handle=11,
            progress_window_handle=12,
            baseline_report_handles=(20, 21),
            backtest_started=True,
            cancellation_confirmed=False,
        )
        payload = checkpoint.__dict__.copy()
        payload["baseline_report_handles"] = list(payload["baseline_report_handles"])
        self.assertEqual(xq_backtest.validate_checkpoint_payload(payload), checkpoint)
        payload["product"] = "2330"
        with self.assertRaises(ValueError):
            xq_backtest.validate_checkpoint_payload(payload)

    def test_recovery_assessment_has_five_conservative_decisions(self) -> None:
        healthy = self.healthy_runtime()
        checkpoint = xq_backtest.create_checkpoint(healthy)
        self.assertEqual(
            xq_backtest.assess_recovery_state(None, None, healthy, False, None).decision,
            "safe_to_start",
        )
        self.assertEqual(
            xq_backtest.assess_recovery_state(checkpoint, None, healthy, True, True).decision,
            "monitor_existing",
        )
        self.assertEqual(
            xq_backtest.assess_recovery_state(checkpoint, None, healthy, False, False).decision,
            "safe_to_clear_checkpoint",
        )
        self.assertEqual(
            xq_backtest.assess_recovery_state(
                checkpoint,
                None,
                replace(healthy, xscript_window_exists=False),
                False,
                True,
            ).decision,
            "ui_recovery_required",
        )
        self.assertEqual(
            xq_backtest.assess_recovery_state(checkpoint, None, healthy, False, True).decision,
            "manual_review_required",
        )
        contradictory = xq_backtest.assess_recovery_state(
            checkpoint,
            None,
            replace(healthy, xq_process_exists=False),
            True,
            False,
        )
        self.assertEqual(contradictory.decision, "manual_review_required")
        self.assertIn("visible_progress", contradictory.reason_codes)

    def test_recovery_status_is_read_only_and_reports_unassociated_reports(self) -> None:
        checkpoint = xq_backtest.create_checkpoint(self.healthy_runtime())
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "xq-ui.json"
            config_path.write_text('{"calibrated": true}', encoding="utf-8")
            checkpoint_path = xq_backtest.recovery_path(config_path)
            xq_backtest.write_checkpoint(checkpoint_path, checkpoint)
            before = checkpoint_path.read_bytes()
            evidence = xq_backtest.inspect_recovery_status(
                config_path,
                {"calibrated": True},
                runtime_probe=lambda _config, _pid: self.healthy_runtime(),
                progress_probe=lambda: None,
                report_probe=lambda: [{
                    "window_handle": 20,
                    "summary_available": True,
                    "classification": "success",
                    "success_count": 1,
                    "failure_count": 0,
                    "total_trades": 4,
                }],
                process_probe=lambda _pid: True,
            )
            after = checkpoint_path.read_bytes()

        self.assertEqual(before, after)
        self.assertTrue(evidence["read_only"])
        self.assertEqual(evidence["decision"], "manual_review_required")
        self.assertEqual(evidence["visible_report_count"], 1)
        self.assertFalse(evidence["report_checkpoint_association_proven"])
        self.assertFalse(evidence["automatic_replay_allowed"])

    def test_recovery_status_argument_contract_requires_no_backtest_inputs(self) -> None:
        status_args = xq_backtest.parse_args(["--config", "config.json", "--recovery-status"])
        xq_backtest.validate_recovery_status_args(status_args)
        with self.assertRaises(ValueError):
            xq_backtest.validate_recovery_status_args(
                xq_backtest.parse_args(
                    ["--config", "config.json", "--recovery-status", "--product", "2330"]
                )
            )
        with self.assertRaises(ValueError):
            xq_backtest.settings_from_args(xq_backtest.parse_args(["--config", "config.json"]))

    def test_cli_emits_one_json_object_without_touching_xq_when_uncalibrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / "xq-ui.json"
            config.write_text('{"calibrated": false}', encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable, str(SCRIPT_PATH), "--config", str(config), "--product", "2330",
                    "--frequency", "day", "--start-date", "2026-06-01", "--end-date", "2026-06-30",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("not calibrated", payload["message"])


if __name__ == "__main__":
    unittest.main()
