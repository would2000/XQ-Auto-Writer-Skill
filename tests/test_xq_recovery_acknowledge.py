from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIRECTORY = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

import xq_backtest
import xq_recovery_acknowledge as acknowledgement


class RecoveryAcknowledgementTests(unittest.TestCase):
    def checkpoint(self) -> xq_backtest.RecoveryCheckpoint:
        return xq_backtest.RecoveryCheckpoint(
            schema_version=2,
            run_id="00000000-0000-0000-0000-000000000001",
            stage="running",
            started_at="2026-07-31T07:39:14+00:00",
            updated_at="2026-07-31T07:39:16+00:00",
            xq_process_id=100,
            xq_window_handle=10,
            xscript_window_handle=11,
            progress_window_handle=None,
            baseline_report_handles=(),
            backtest_started=True,
            cancellation_confirmed=False,
        )

    def recovery(self, checkpoint: xq_backtest.RecoveryCheckpoint, **overrides: object) -> dict[str, object]:
        result: dict[str, object] = {
            "decision": "manual_review_required",
            "reason_codes": ["checkpoint_present"],
            "checkpoint_present": True,
            "checkpoint_valid": True,
            "visible_progress": False,
            "inspection_errors": [],
            "saved_process_running": True,
            "report_checkpoint_association_proven": False,
            "runtime": {
                "xq_process_exists": True,
                "xq_window_exists": True,
                "xq_window_visible": True,
                "xq_window_enabled": True,
                "xq_window_hung": False,
                "xscript_window_exists": True,
                "xscript_window_visible": True,
                "xscript_window_enabled": True,
                "xscript_window_hung": False,
            },
        }
        result.update(overrides)
        return result

    def prepared_config(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, xq_backtest.RecoveryCheckpoint]:
        directory = tempfile.TemporaryDirectory()
        config_path = Path(directory.name) / "xq-ui.json"
        config_path.write_text('{"calibrated": true}', encoding="utf-8")
        checkpoint_path = xq_backtest.recovery_path(config_path)
        checkpoint = self.checkpoint()
        xq_backtest.write_checkpoint(checkpoint_path, checkpoint)
        return directory, config_path, checkpoint_path, checkpoint

    def test_archives_and_clears_only_exact_manually_acknowledged_checkpoint(self) -> None:
        directory, config_path, checkpoint_path, checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)

        evidence = acknowledgement.acknowledge_manual_recovery(
            config_path,
            {"calibrated": True},
            checkpoint.run_id,
            inspect=lambda _path, _config: self.recovery(checkpoint),
            now=lambda: "2026-07-31T08:00:00+00:00",
        )

        self.assertTrue(evidence["checkpoint_cleared"])
        self.assertFalse(checkpoint_path.exists())
        archive = Path(str(evidence["archive_path"]))
        payload = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(payload["event"], "manual_recovery_acknowledged")
        self.assertEqual(payload["acknowledged_run_id"], checkpoint.run_id)
        self.assertFalse(payload["report_checkpoint_association_proven"])
        self.assertEqual(set(payload["previous_checkpoint"]), set(checkpoint.__dict__))
        self.assertNotIn("products", payload)
        self.assertNotIn("script_name", payload)

    def test_safe_to_clear_accepts_restarted_xq_with_xscript_closed(self) -> None:
        directory, config_path, checkpoint_path, checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)
        restarted_runtime = {
            "xq_process_id": 200,
            "xq_process_exists": False,
            "xq_window_exists": True,
            "xq_window_visible": True,
            "xq_window_enabled": True,
            "xq_window_hung": False,
            "xscript_window_exists": False,
            "xscript_window_visible": False,
            "xscript_window_enabled": False,
            "xscript_window_hung": None,
        }

        evidence = acknowledgement.acknowledge_manual_recovery(
            config_path,
            {"calibrated": True},
            checkpoint.run_id,
            inspect=lambda _path, _config: self.recovery(
                checkpoint,
                decision="safe_to_clear_checkpoint",
                reason_codes=[
                    "checkpoint_present",
                    "xq_process_exited",
                    "saved_process_not_running",
                ],
                saved_process_running=False,
                runtime=restarted_runtime,
            ),
            now=lambda: "2026-07-31T08:30:00+00:00",
        )

        self.assertTrue(evidence["checkpoint_cleared"])
        self.assertFalse(checkpoint_path.exists())

    def test_safe_to_clear_rejects_unproven_replacement_process(self) -> None:
        directory, config_path, checkpoint_path, checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)
        original = checkpoint_path.read_bytes()
        runtime = dict(self.recovery(checkpoint)["runtime"])
        runtime.update(
            {"xq_process_id": checkpoint.xq_process_id, "xq_process_exists": False}
        )

        with self.assertRaisesRegex(RuntimeError, "health is insufficient"):
            acknowledgement.acknowledge_manual_recovery(
                config_path,
                {"calibrated": True},
                checkpoint.run_id,
                inspect=lambda _path, _config: self.recovery(
                    checkpoint,
                    decision="safe_to_clear_checkpoint",
                    reason_codes=[
                        "checkpoint_present",
                        "xq_process_exited",
                        "saved_process_not_running",
                    ],
                    saved_process_running=False,
                    runtime=runtime,
                ),
            )
        self.assertEqual(checkpoint_path.read_bytes(), original)

    def test_rejects_wrong_run_id_or_visible_progress_without_mutation(self) -> None:
        directory, config_path, checkpoint_path, checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)
        original = checkpoint_path.read_bytes()
        with self.assertRaises(ValueError):
            acknowledgement.acknowledge_manual_recovery(
                config_path,
                {"calibrated": True},
                "00000000-0000-0000-0000-000000000002",
                inspect=lambda _path, _config: self.recovery(checkpoint),
            )
        with self.assertRaises(RuntimeError):
            acknowledgement.acknowledge_manual_recovery(
                config_path,
                {"calibrated": True},
                checkpoint.run_id,
                inspect=lambda _path, _config: self.recovery(checkpoint, visible_progress=True),
            )
        self.assertEqual(checkpoint_path.read_bytes(), original)
        self.assertFalse(acknowledgement.archive_directory(config_path).exists())

    def test_checkpoint_change_after_archive_is_not_cleared(self) -> None:
        directory, config_path, checkpoint_path, checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)
        original_write = acknowledgement.write_new_archive

        def write_then_change(path: Path, payload: dict[str, object]) -> None:
            original_write(path, payload)
            changed = xq_backtest.update_checkpoint(checkpoint, stage="interrupted")
            xq_backtest.write_checkpoint(checkpoint_path, changed)

        with (
            patch.object(acknowledgement, "write_new_archive", side_effect=write_then_change),
            self.assertRaisesRegex(RuntimeError, "changed after archive"),
        ):
            acknowledgement.acknowledge_manual_recovery(
                config_path,
                {"calibrated": True},
                checkpoint.run_id,
                inspect=lambda _path, _config: self.recovery(checkpoint),
                now=lambda: "2026-07-31T08:00:00+00:00",
            )
        self.assertTrue(checkpoint_path.exists())
        self.assertEqual(xq_backtest.load_checkpoint(checkpoint_path).stage, "interrupted")
        self.assertEqual(len(list(acknowledgement.archive_directory(config_path).glob("*.json"))), 1)

    def test_cli_requires_explicit_confirmation_before_reading_configuration(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = acknowledgement.main(
                [
                    "--config",
                    "missing.json",
                    "--run-id",
                    "00000000-0000-0000-0000-000000000001",
                ]
            )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertIn("requires --confirm-manual-recovery", payload["message"])

    def test_legacy_backtest_flag_never_clears_a_checkpoint(self) -> None:
        directory, config_path, checkpoint_path, _checkpoint = self.prepared_config()
        self.addCleanup(directory.cleanup)
        output = io.StringIO()
        with (
            patch.object(xq_backtest, "configure_ui_pacing"),
            patch.object(xq_backtest, "visible_progress_window", return_value=None),
            patch.object(xq_backtest, "process_is_running", return_value=True),
            contextlib.redirect_stdout(output),
        ):
            code = xq_backtest.main(
                [
                    "--config",
                    str(config_path),
                    "--product",
                    "2330",
                    "--frequency",
                    "day",
                    "--start-date",
                    "2026-06-01",
                    "--end-date",
                    "2026-06-30",
                    "--acknowledge-stale-checkpoint",
                ]
            )

        self.assertEqual(code, 3)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "automation_error")
        self.assertTrue(payload["recovery_checkpoint_retained"])
        self.assertTrue(checkpoint_path.exists())
        self.assertIn("xq_recovery_acknowledge.py", payload["message"])


if __name__ == "__main__":
    unittest.main()
