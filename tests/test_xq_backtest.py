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
    def test_explicit_script_name_must_match_active_codex_document(self):
        args = xq_backtest.parse_args(
            ["--config", "config.json", "--script-name", "CodexExpected"]
        )
        self.assertEqual(args.script_name, "CodexExpected")
        xq_backtest.require_expected_script_name(
            {"script_name": "CodexExpected"}, args.script_name
        )
        with self.assertRaisesRegex(RuntimeError, "explicitly requested"):
            xq_backtest.require_expected_script_name(
                {"script_name": "AnotherScript"}, args.script_name
            )

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

        set_edit.assert_called_once_with(
            ANY,
            2007,
            5,
            foreground_records=None,
        )
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

    def test_set_combo_invokes_the_native_selection_once(self) -> None:
        control = Mock()
        control.item_texts.return_value = ["day"]
        control.window_text.return_value = "day"
        owner = object()
        guard = {"foreground_verified": True}
        records = []
        with (
            patch.object(xq_backtest, "control_by_id", return_value=control),
            patch.object(
                xq_backtest,
                "guarded_paced_select",
                return_value=guard,
            ) as guarded_select,
        ):
            xq_backtest.set_combo(
                owner,
                2091,
                "day",
                foreground_records=records,
            )

        guarded_select.assert_called_once_with(owner, control, "day")
        self.assertEqual(records, [guard])

    def test_foreground_guard_accepts_an_already_foreground_window(self) -> None:
        window = Mock(handle=10)
        window.is_visible.return_value = True
        window.is_enabled.return_value = True
        set_foreground = Mock(return_value=True)
        show_window = Mock(return_value=True)
        sleeper = Mock()

        evidence = xq_backtest.ensure_window_foreground(
            window,
            get_foreground_handle=lambda: 10,
            set_foreground=set_foreground,
            show_window=show_window,
            is_window=lambda _handle: True,
            is_hung=lambda _handle: False,
            sleeper=sleeper,
        )

        self.assertTrue(evidence["foreground_verified"])
        self.assertFalse(evidence["foreground_request_sent"])
        set_foreground.assert_not_called()
        show_window.assert_not_called()
        sleeper.assert_not_called()

    def test_foreground_guard_switches_and_verifies_the_exact_handle(self) -> None:
        window = Mock(handle=10)
        window.is_visible.return_value = True
        window.is_enabled.return_value = True
        foreground = iter((99, 10))
        set_foreground = Mock(return_value=True)
        show_window = Mock(return_value=True)
        sleeper = Mock()

        evidence = xq_backtest.ensure_window_foreground(
            window,
            get_foreground_handle=lambda: next(foreground),
            set_foreground=set_foreground,
            show_window=show_window,
            is_window=lambda _handle: True,
            is_hung=lambda _handle: False,
            sleeper=sleeper,
        )

        self.assertTrue(evidence["foreground_verified"])
        self.assertTrue(evidence["foreground_request_sent"])
        self.assertTrue(evidence["foreground_request_accepted"])
        show_window.assert_called_once_with(10)
        set_foreground.assert_called_once_with(10)
        sleeper.assert_called_once()

    def test_foreground_guard_refuses_a_covered_or_disabled_target(self) -> None:
        visible = Mock(handle=10)
        visible.is_visible.return_value = True
        visible.is_enabled.return_value = True
        foreground = iter((99, 99))
        with self.assertRaises(xq_backtest.ForegroundGuardError):
            xq_backtest.ensure_window_foreground(
                visible,
                get_foreground_handle=lambda: next(foreground),
                set_foreground=lambda _handle: False,
                show_window=lambda _handle: True,
                is_window=lambda _handle: True,
                is_hung=lambda _handle: False,
                sleeper=lambda _seconds: None,
            )

        disabled = Mock(handle=10)
        disabled.is_visible.return_value = True
        disabled.is_enabled.return_value = False
        set_foreground = Mock(return_value=True)
        with self.assertRaises(xq_backtest.ForegroundGuardError):
            xq_backtest.ensure_window_foreground(
                disabled,
                get_foreground_handle=lambda: 99,
                set_foreground=set_foreground,
                show_window=lambda _handle: True,
                is_window=lambda _handle: True,
                is_hung=lambda _handle: False,
                sleeper=lambda _seconds: None,
            )
        set_foreground.assert_not_called()

    def test_guarded_click_never_clicks_after_foreground_rejection(self) -> None:
        control = Mock()
        with (
            patch.object(
                xq_backtest,
                "ensure_window_foreground",
                side_effect=xq_backtest.ForegroundGuardError("covered"),
            ),
            self.assertRaises(xq_backtest.ForegroundGuardError),
        ):
            xq_backtest.guarded_paced_click(Mock(), control)
        control.click_input.assert_not_called()

    def test_timeout_and_wait_incidents_forbid_followup_input(self) -> None:
        for exc in (
            TimeoutError("dialog"),
            xq_backtest.ForegroundGuardError("covered"),
            RuntimeError("WaitGuiThreadIdle"),
            RuntimeError("dialog_late"),
            RuntimeError("window_disabled"),
        ):
            with self.subTest(exc=exc):
                self.assertTrue(xq_backtest.input_must_stop(exc))
        self.assertFalse(xq_backtest.input_must_stop(ValueError("final set mismatch")))

    def test_selected_product_codes_reads_existing_product_group(self) -> None:
        selected_list = Mock()
        selected_list.item_texts.return_value = ["FITX*1.TF 台股指數近月(一般)", "2330.TW 台積電"]
        with patch.object(xq_backtest, "control_by_id", return_value=selected_list):
            self.assertEqual(
                xq_backtest.selected_product_codes(object()),
                ["FITX*1", "2330"],
            )

    def test_choose_products_replaces_only_transient_backtest_selection(self) -> None:
        source = Mock()
        source.window_text.return_value = "商品"
        results = Mock()
        results.item_count.return_value = 1
        results.get_item.return_value.text.return_value = "FITX*1"
        controls = {
            2092: source,
            2031: Mock(),
            741: Mock(),
            782: results,
            802: Mock(),
            803: Mock(),
            805: Mock(),
            806: Mock(),
            1: Mock(),
            2001: Mock(),
        }
        controls[2001].window_text.return_value = "FITX*1"
        settings_window = Mock()
        settings_window.handle = 123
        settings_window.is_enabled.return_value = True
        product_window = Mock()
        product_window.handle = 456

        def controls_by_id(_root: object, control_id: int) -> Mock:
            return controls[control_id]

        def foreground_evidence(window: object) -> dict[str, object]:
            return {
                "window_handle": int(window.handle),
                "foreground_request_sent": False,
                "foreground_verified": True,
            }

        with (
            patch.object(xq_backtest, "control_by_id", side_effect=controls_by_id),
            patch.object(
                xq_backtest,
                "visible_dialog_with_control",
                return_value=product_window,
            ),
            patch.object(
                xq_backtest,
                "ensure_window_foreground",
                side_effect=foreground_evidence,
            ),
            patch.object(
                xq_backtest,
                "selected_product_codes",
                side_effect=[["7818"], [], ["FITX*1"]],
            ),
        ):
            evidence = xq_backtest.choose_products(settings_window, ("FITX*1",), 1)

        controls[805].click_input.assert_called_once_with()
        controls[803].click_input.assert_called_once_with()
        self.assertEqual(
            evidence,
            {
                "selection_mode": "explicit_products",
                "source": "product",
                "requested_product_count": 1,
                "preexisting_selection_present": True,
                "cleared_selection_verified": True,
                "final_selection_verified": True,
                "private_source_touched": False,
                "foreground_guard": {
                    "required": True,
                    "all_verified": True,
                    "verification_count": 7,
                    "focus_request_count": 0,
                    "target_window_handles": [123, 456],
                },
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
        for stage in ("late_report", "completed"):
            stage_payload = dict(payload)
            stage_payload["stage"] = stage
            self.assertEqual(
                xq_backtest.validate_checkpoint_payload(stage_payload).stage,
                stage,
            )
        payload["product"] = "2330"
        with self.assertRaises(ValueError):
            xq_backtest.validate_checkpoint_payload(payload)

    def test_report_enumeration_targets_only_native_dialog_candidates(self) -> None:
        native = Mock(handle=20)
        report_window = Mock(handle=20)
        desktop = Mock()
        desktop.window.return_value.wrapper_object.return_value = report_window
        elements = [("Document", "XS回測報告")]

        with (
            patch.object(
                xq_backtest,
                "_native_dialog_windows",
                return_value=[native],
            ),
            patch("pywinauto.Desktop", return_value=desktop) as desktop_factory,
            patch.object(xq_backtest, "report_elements", return_value=elements),
        ):
            records = xq_backtest.visible_report_records({10})

        self.assertEqual(records, [(report_window, elements)])
        desktop_factory.assert_called_once_with(backend="uia")
        desktop.window.assert_called_once_with(handle=20)
        desktop.windows.assert_not_called()

    def test_normal_monitor_routes_through_shared_one_shot_core(self) -> None:
        with patch(
            "xq_backtest_monitor.run_report_monitor",
            return_value=("success", {"report_window_handle": 20}),
        ) as monitor:
            result = xq_backtest.run_and_monitor(
                Mock(),
                60,
                False,
                baseline_report_handles={10},
                baseline_progress_handles={11},
                expected_report_marker="CodexV1FlowAutotrade",
            )

        self.assertEqual(result[0], "success")
        monitor.assert_called_once()
        self.assertEqual(monitor.call_args.args[2], "CodexV1FlowAutotrade")
        self.assertEqual(
            monitor.call_args.kwargs["baseline_progress_handles"], {11}
        )

    def test_normal_monitor_requires_script_name_marker(self) -> None:
        with self.assertRaisesRegex(ValueError, "report marker"):
            xq_backtest.run_and_monitor(Mock(), 60, False)

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
