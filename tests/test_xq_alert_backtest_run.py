from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_alert_backtest_run


class AlertBacktestRunTests(unittest.TestCase):
    class FakeClock:
        def __init__(self) -> None:
            self.value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    def base_args(self) -> list[str]:
        return [
            "--config",
            "missing.json",
            "--script-name",
            "MyBullishSignalAlert",
            "--product",
            "2330",
            "--product-kind",
            "stock",
            "--direction",
            "long",
            "--frequency",
            "day",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-30",
            "--price-basis",
            "original",
            "--entry-price",
            "next_open",
            "--exit-price",
            "next_open",
            "--no-simulate-entry-ticks",
            "--no-simulate-exit-ticks",
            "--max-concurrent-entries",
            "1",
            "--take-profit",
            "8",
            "--take-profit-unit",
            "percent",
            "--stop-loss",
            "8",
            "--stop-loss-unit",
            "percent",
            "--max-holding-periods",
            "20",
            "--stock-fee-percent",
            "0.2",
            "--no-print-enabled",
        ]

    def calibrated_config(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "xq-ui.json"
        path.write_text(json.dumps({"calibrated": True}), encoding="utf-8")
        return path

    def test_ownerdraw_direction_uses_local_visual_readback(self) -> None:
        long_control = Mock()
        long_control.style.return_value = 0x5000000B
        long_control.control_id.return_value = 2061
        long_control.capture_as_image.return_value = Image.new(
            "RGB", (105, 57), (223, 57, 58)
        )
        short_control = Mock()
        short_control.style.return_value = 0x5000000B
        short_control.control_id.return_value = 2062
        short_control.capture_as_image.return_value = Image.new(
            "RGB", (105, 57), (219, 219, 219)
        )
        controls = {2061: long_control, 2062: short_control}

        with (
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "control_by_id",
                side_effect=lambda _window, control_id: controls[control_id],
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "guarded_paced_click",
            ) as click,
        ):
            evidence = xq_alert_backtest_run.set_alert_direction(
                Mock(), "long", []
            )

        self.assertEqual(
            evidence["readback_method"],
            "owner_draw_control_local_visual_fill",
        )
        self.assertGreater(evidence["after"]["target"]["chroma"], 40)
        click.assert_not_called()

    def test_start_requires_explicit_confirmation_before_reading_config(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = xq_alert_backtest_run.main(self.base_args())

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["phase"], "argument_validation")
        self.assertIn("--confirm-historical-backtest", payload["message"])

    def test_dry_run_allows_setting_verification_without_start_confirmation(self) -> None:
        args = xq_alert_backtest_run.parse_args([*self.base_args(), "--dry-run"])
        settings = xq_alert_backtest_run.settings_from_args(args)

        self.assertEqual(settings.products, ("2330",))
        self.assertFalse(settings.simulate_entry_ticks)
        self.assertFalse(settings.simulate_exit_ticks)
        self.assertFalse(settings.print_enabled)

    def test_uncompiled_alert_title_is_rejected_before_backtest(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "uncompiled"):
            xq_alert_backtest_run.validate_compiled_alert_title(
                "XScript 編輯器 - [MyBullishSignalAlert(警示)未編譯]",
                "MyBullishSignalAlert",
            )

        title = xq_alert_backtest_run.validate_compiled_alert_title(
            "XScript 編輯器 - [MyBullishSignalAlert(警示)]",
            "MyBullishSignalAlert",
        )
        self.assertNotIn("未編譯", title)

    def test_stock_requires_fee_and_all_explicit_boolean_choices(self) -> None:
        missing_fee = self.base_args()
        fee_index = missing_fee.index("--stock-fee-percent")
        del missing_fee[fee_index : fee_index + 2]
        with self.assertRaisesRegex(ValueError, "--stock-fee-percent"):
            xq_alert_backtest_run.settings_from_args(
                xq_alert_backtest_run.parse_args([*missing_fee, "--dry-run"])
            )

        missing_boolean = self.base_args()
        missing_boolean.remove("--no-simulate-exit-ticks")
        with self.assertRaisesRegex(ValueError, "simulate-exit-ticks"):
            xq_alert_backtest_run.settings_from_args(
                xq_alert_backtest_run.parse_args([*missing_boolean, "--dry-run"])
            )

    def test_completed_run_closes_only_the_exact_new_report_and_clears_checkpoint(self) -> None:
        config_path = self.calibrated_config()
        args = self.base_args()
        args[1] = str(config_path)
        args.append("--confirm-historical-backtest")
        settings_window = Mock()
        snapshot = Mock(expected_xq_process_id=100)
        checkpoint = Mock(run_id="run-1")
        output = io.StringIO()
        with (
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "inspect_recovery_status",
                return_value={"decision": "safe_to_start"},
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "configure_ui_pacing",
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "capture_runtime_snapshot",
                return_value=snapshot,
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "classify_runtime_interruption",
                return_value=None,
            ),
            patch.object(
                xq_alert_backtest_run.xq_alert_backtest,
                "open_alert_backtest_settings",
                return_value=settings_window,
            ),
            patch.object(
                xq_alert_backtest_run,
                "verify_active_alert_script",
                return_value={"script_name": "MyBullishSignalAlert"},
            ),
            patch.object(
                xq_alert_backtest_run,
                "apply_alert_settings",
                return_value={},
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "progress_windows",
                return_value=[],
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "visible_report_handles",
                return_value={10},
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "create_checkpoint",
                return_value=checkpoint,
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "write_checkpoint",
            ),
            patch.object(
                xq_alert_backtest_run,
                "run_alert_and_monitor",
                return_value=(
                    "success",
                    {
                        "report_window_handle": 20,
                        "success_count": 1,
                        "failure_count": 0,
                        "total_trades": 0,
                    },
                ),
            ) as run_monitor,
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "remove_checkpoint",
            ) as remove_checkpoint,
            patch.object(
                xq_alert_backtest_run,
                "close_new_report",
                return_value={"window_handle": 20, "closed": True},
            ) as close_report,
            contextlib.redirect_stdout(output),
        ):
            code = xq_alert_backtest_run.main(args)

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["success_count"], 1)
        self.assertEqual(payload["total_trades"], 0)
        self.assertTrue(payload["report_cleanup_complete"])
        run_monitor.assert_called_once()
        self.assertEqual(run_monitor.call_args.kwargs["baseline_report_handles"], {10})
        close_report.assert_called_once_with(20)
        remove_checkpoint.assert_called_once()

    def test_timeout_retains_checkpoint_and_never_closes_an_old_report(self) -> None:
        config_path = self.calibrated_config()
        args = self.base_args()
        args[1] = str(config_path)
        args.append("--confirm-historical-backtest")
        checkpoint = Mock(run_id="run-timeout")
        output = io.StringIO()
        with (
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "inspect_recovery_status",
                return_value={"decision": "safe_to_start"},
            ),
            patch.object(xq_alert_backtest_run.xq_backtest, "configure_ui_pacing"),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "capture_runtime_snapshot",
                return_value=Mock(expected_xq_process_id=100),
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "classify_runtime_interruption",
                return_value=None,
            ),
            patch.object(
                xq_alert_backtest_run.xq_alert_backtest,
                "open_alert_backtest_settings",
                return_value=Mock(),
            ),
            patch.object(
                xq_alert_backtest_run,
                "verify_active_alert_script",
                return_value={"script_name": "MyBullishSignalAlert"},
            ),
            patch.object(xq_alert_backtest_run, "apply_alert_settings", return_value={}),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "progress_windows",
                return_value=[],
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "visible_report_handles",
                return_value={10},
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "create_checkpoint",
                return_value=checkpoint,
            ),
            patch.object(xq_alert_backtest_run.xq_backtest, "write_checkpoint"),
            patch.object(
                xq_alert_backtest_run,
                "run_alert_and_monitor",
                return_value=("indeterminate_timeout", {"progress_seen": True}),
            ),
            patch.object(
                xq_alert_backtest_run,
                "close_new_report",
            ) as close_report,
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "remove_checkpoint",
            ) as remove_checkpoint,
            patch.object(
                xq_alert_backtest_run,
                "save_wait_incident",
                return_value=Path("incident.json"),
            ) as save_incident,
            contextlib.redirect_stdout(output),
        ):
            code = xq_alert_backtest_run.main(args)

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["recovery_checkpoint_retained"])
        self.assertEqual(payload["recovery_run_id"], "run-timeout")
        self.assertEqual(payload["incident_path"], "incident.json")
        save_incident.assert_called_once()
        close_report.assert_not_called()
        remove_checkpoint.assert_not_called()

    def test_monitor_posts_start_once_and_handles_delayed_settings_close(self) -> None:
        clock = self.FakeClock()
        start_action = Mock(return_value={"posted_once": True})
        progress = Mock(handle=301)
        progress.is_visible.return_value = False
        progress_calls = iter(([], [], [progress], []))
        report_calls = {"count": 0}

        def reports(_baseline: set[int], _name: str) -> list[dict[str, object]]:
            report_calls["count"] += 1
            if report_calls["count"] < 4:
                return []
            return [
                {
                    "window": Mock(),
                    "window_handle": 401,
                    "window_title": "回測報告：MyBullishSignalAlert",
                    "marker_matched": True,
                    "summary": xq_alert_backtest_run.xq_backtest.ReportSummary(
                        1, 0, 1
                    ),
                }
            ]

        visible_calls = {"count": 0}

        def settings_visible(_window: object) -> bool:
            visible_calls["count"] += 1
            return visible_calls["count"] <= 2

        stages: list[str] = []
        status, evidence = xq_alert_backtest_run.run_alert_and_monitor(
            Mock(),
            2.0,
            "MyBullishSignalAlert",
            late_report_grace_seconds=1.0,
            start_action=start_action,
            progress_probe=lambda: next(progress_calls, []),
            report_probe=reports,
            settings_visible_probe=settings_visible,
            checkpoint_callback=lambda stage, _handle, _cancelled: stages.append(
                stage
            ),
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            poll_seconds=0.1,
        )

        self.assertEqual(status, "success")
        start_action.assert_called_once()
        self.assertTrue(evidence["settings_window_delayed_close"])
        self.assertTrue(evidence["hidden_progress_seen"])
        self.assertEqual(
            [item["stage"] for item in evidence["state_transitions"]],
            ["starting", "running", "late_report", "completed"],
        )
        self.assertEqual(stages, ["running", "late_report", "completed"])

    def test_monitor_accepts_unique_report_during_late_report_grace(self) -> None:
        clock = self.FakeClock()

        def reports(_baseline: set[int], _name: str) -> list[dict[str, object]]:
            if clock.value < 1.2:
                return []
            return [
                {
                    "window": Mock(),
                    "window_handle": 501,
                    "window_title": "MyBullishSignalAlert 回測報告",
                    "marker_matched": True,
                    "summary": xq_alert_backtest_run.xq_backtest.ReportSummary(
                        1, 0, 3
                    ),
                }
            ]

        status, evidence = xq_alert_backtest_run.run_alert_and_monitor(
            Mock(),
            1.0,
            "MyBullishSignalAlert",
            late_report_grace_seconds=1.0,
            start_action=lambda _window: {"posted_once": True},
            progress_probe=lambda: [],
            report_probe=reports,
            settings_visible_probe=lambda _window: False,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            poll_seconds=0.1,
        )

        self.assertEqual(status, "success")
        self.assertEqual(evidence["total_trades"], 3)
        self.assertEqual(
            evidence["report_decision"],
            "unique_new_report_and_marker_matched",
        )
        self.assertGreaterEqual(clock.value, 1.2)

    def test_monitor_rejects_nonunique_new_reports(self) -> None:
        clock = self.FakeClock()
        candidate = {
            "window": Mock(),
            "window_title": "MyBullishSignalAlert 回測報告",
            "marker_matched": True,
            "summary": xq_alert_backtest_run.xq_backtest.ReportSummary(1, 0, 1),
        }
        status, evidence = xq_alert_backtest_run.run_alert_and_monitor(
            Mock(),
            1.0,
            "MyBullishSignalAlert",
            start_action=lambda _window: {"posted_once": True},
            progress_probe=lambda: [],
            report_probe=lambda _baseline, _name: [
                {**candidate, "window_handle": 601},
                {**candidate, "window_handle": 602},
            ],
            settings_visible_probe=lambda _window: False,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            poll_seconds=0.1,
        )

        self.assertEqual(status, "indeterminate_timeout")
        self.assertEqual(evidence["report_decision"], "report_not_unique")
        self.assertEqual(evidence["new_report_handles"], [601, 602])
        self.assertTrue(evidence["manual_review_required"])

    def test_monitor_rejects_unique_report_with_wrong_marker(self) -> None:
        clock = self.FakeClock()
        status, evidence = xq_alert_backtest_run.run_alert_and_monitor(
            Mock(),
            1.0,
            "MyBullishSignalAlert",
            start_action=lambda _window: {"posted_once": True},
            progress_probe=lambda: [],
            report_probe=lambda _baseline, _name: [
                {
                    "window": Mock(),
                    "window_handle": 701,
                    "window_title": "AnotherAlert 回測報告",
                    "marker_matched": False,
                    "summary": xq_alert_backtest_run.xq_backtest.ReportSummary(
                        1, 0, 1
                    ),
                }
            ],
            settings_visible_probe=lambda _window: False,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            poll_seconds=0.1,
        )

        self.assertEqual(status, "indeterminate_timeout")
        self.assertEqual(evidence["report_decision"], "marker_mismatch")
        self.assertTrue(evidence["manual_review_required"])

    def test_monitor_ignores_hidden_progress_present_before_start(self) -> None:
        clock = self.FakeClock()
        stale = Mock(handle=801)
        stale.is_visible.return_value = False
        candidate = {
            "window": Mock(),
            "window_handle": 802,
            "window_title": "MyBullishSignalAlert 回測報告",
            "marker_matched": True,
            "summary": xq_alert_backtest_run.xq_backtest.ReportSummary(1, 0, 1),
        }

        status, evidence = xq_alert_backtest_run.run_alert_and_monitor(
            Mock(),
            1.0,
            "MyBullishSignalAlert",
            baseline_progress_handles={801},
            start_action=lambda _window: {"posted_once": True},
            progress_probe=lambda: [stale],
            report_probe=lambda _baseline, _name: [candidate],
            settings_visible_probe=lambda _window: False,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            poll_seconds=0.1,
        )

        self.assertEqual(status, "success")
        self.assertFalse(evidence["progress_seen"])
        self.assertFalse(evidence["hidden_progress_seen"])

    def test_timeout_progress_capture_writes_exact_private_png_and_status(self) -> None:
        config_path = self.calibrated_config()
        checkpoint = xq_alert_backtest_run.xq_backtest.RecoveryCheckpoint(
            schema_version=2,
            run_id="run-capture",
            stage="running",
            started_at="2026-08-01T07:00:00+00:00",
            updated_at="2026-08-01T07:01:00+00:00",
            xq_process_id=100,
            xq_window_handle=200,
            xscript_window_handle=300,
            progress_window_handle=400,
            baseline_report_handles=(),
            backtest_started=True,
            cancellation_confirmed=False,
        )
        details = Mock()
        details.is_visible.return_value = True
        details.item_count.return_value = 1
        details.get_item.return_value.text.return_value = (
            "其他失敗 - 回測執行異常(1)"
        )
        window = Mock()
        window.exists.return_value = True
        window.is_visible.return_value = True
        window.is_enabled.return_value = True
        window.capture_as_image.return_value = Image.new("RGB", (64, 32), "white")
        stamp = datetime(2026, 8, 1, 7, 10, 5, tzinfo=timezone.utc)

        with (
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "window_is_hung",
                return_value=False,
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "control_by_id",
                return_value=details,
            ),
        ):
            evidence = xq_alert_backtest_run.capture_timeout_progress_evidence(
                config_path,
                checkpoint,
                stamp=stamp,
                window_factory=lambda handle: window,
            )

        screenshot = Path(evidence["screenshot_path"])
        self.assertEqual(evidence["status"], "captured")
        self.assertEqual(evidence["window_handle"], 400)
        self.assertEqual(
            evidence["visible_execution_states"],
            ["其他失敗 - 回測執行異常(1)"],
        )
        self.assertEqual(evidence["actual_progress_error_codes"], [1])
        self.assertIsNone(evidence["actual_report_error_code"])
        self.assertTrue(screenshot.is_file())
        self.assertEqual(screenshot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(len(evidence["screenshot_sha256"]), 64)

    def test_wait_incident_keeps_capture_error_without_losing_recovery(self) -> None:
        config_path = self.calibrated_config()
        checkpoint = xq_alert_backtest_run.xq_backtest.RecoveryCheckpoint(
            schema_version=2,
            run_id="run-incident",
            stage="running",
            started_at="2026-08-01T07:00:00+00:00",
            updated_at="2026-08-01T07:01:00+00:00",
            xq_process_id=100,
            xq_window_handle=200,
            xscript_window_handle=300,
            progress_window_handle=400,
            baseline_report_handles=(),
            backtest_started=True,
            cancellation_confirmed=False,
        )
        with (
            patch.object(
                xq_alert_backtest_run,
                "capture_timeout_progress_evidence",
                side_effect=RuntimeError("capture unavailable"),
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "capture_runtime_snapshot",
                side_effect=RuntimeError("runtime unavailable"),
            ),
            patch.object(
                xq_alert_backtest_run.xq_backtest,
                "inspect_recovery_status",
                return_value={"decision": "monitor_existing"},
            ),
        ):
            incident = xq_alert_backtest_run.save_wait_incident(
                config_path,
                {"calibrated": True},
                "backtest_timeout",
                TimeoutError("timed out"),
                checkpoint,
            )

        payload = json.loads(incident.read_text(encoding="utf-8"))
        self.assertEqual(payload["progress_capture"]["status"], "capture_error")
        self.assertIn("capture unavailable", payload["progress_capture"]["error"])
        self.assertEqual(
            payload["recovery_status"]["decision"], "monitor_existing"
        )

    def test_skill_and_guides_document_confirmation_and_report_baseline(self) -> None:
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
            / "alert-backtest-product-guide.md"
        ).read_text(encoding="utf-8")
        contract = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "xq-xscript-compiler"
            / "references"
            / "backtest-configuration-contract.md"
        ).read_text(encoding="utf-8")

        for document in (skill, guide, contract):
            self.assertIn("xq_alert_backtest_run.py", document)
            self.assertIn("checkpoint", document)
        self.assertIn("--confirm-historical-backtest", skill)
        self.assertIn("唯一新增報告", guide)
        self.assertIn("未編譯", skill)
        self.assertIn("未編譯", guide)


if __name__ == "__main__":
    unittest.main()
