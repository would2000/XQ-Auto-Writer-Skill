from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
BACKTEST_PATH = SCRIPTS_DIR / "xq_backtest.py"
REPORT_PATH = SCRIPTS_DIR / "xq_report.py"
SKILL_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "SKILL.md"
GUIDE_PATH = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references" / "autotrade-window-guide.md"
README_PATH = PROJECT_ROOT / "README.md"

if "xq_backtest" not in sys.modules:
    backtest_spec = importlib.util.spec_from_file_location("xq_backtest", BACKTEST_PATH)
    assert backtest_spec is not None and backtest_spec.loader is not None
    xq_backtest = importlib.util.module_from_spec(backtest_spec)
    sys.modules[backtest_spec.name] = xq_backtest
    backtest_spec.loader.exec_module(xq_backtest)
else:
    xq_backtest = sys.modules["xq_backtest"]

sys.path.insert(0, str(SCRIPTS_DIR))
try:
    report_spec = importlib.util.spec_from_file_location("xq_report", REPORT_PATH)
    assert report_spec is not None and report_spec.loader is not None
    xq_report = importlib.util.module_from_spec(report_spec)
    sys.modules[report_spec.name] = xq_report
    report_spec.loader.exec_module(xq_report)
finally:
    sys.path.remove(str(SCRIPTS_DIR))


class FakeWindow:
    def __init__(self, handle: int) -> None:
        self.handle = handle


def minimal_xlsx_payload() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook />")
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet />")
    return output.getvalue()


class XQReportTests(unittest.TestCase):
    def test_report_cli_and_privacy_contract_are_documented(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SKILL_PATH, GUIDE_PATH, README_PATH)
        )
        for required in (
            "scripts/xq_report.py",
            "--list-reports",
            "--export-format json",
            "--export-format csv",
            "--include-failure-details",
            ".xq-auto-writer/reports/",
            "SHA-256",
            "不會覆寫",
            "report_checkpoint_association_proven",
            "--native-action",
            "--confirm-output-directory",
            "confirmation_required",
            "proposed_output_directory",
            "BTReport",
            "CP950",
            "completion_dialog_seen",
            "每次實際匯出都必須重新確認目的地",
        ):
            self.assertIn(required, combined)

    def test_capture_uses_whitelisted_schema_and_optional_failure_details(self) -> None:
        summary = xq_backtest.ReportSummary(success_count=1, failure_count=1, total_trades=4)
        detail = xq_backtest.FailureDetail(
            product="=PUBLIC",
            state="失敗",
            error_code="1301",
            description="RaiseRunTimeError",
        )
        with (
            patch.object(xq_report.xq_backtest, "report_elements", return_value=[("DataItem", "report")]),
            patch.object(xq_report.xq_backtest, "report_summary", return_value=summary),
            patch.object(xq_report.xq_backtest, "classify_report", return_value="partial_failure"),
            patch.object(xq_report.xq_backtest, "extract_failure_details", return_value=[detail]),
        ):
            record = xq_report.capture_report(FakeWindow(42), include_failure_details=True)

        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["classification"], "partial_failure")
        self.assertEqual(record["failure_details"][0]["error_code"], "1301")
        self.assertFalse(record["report_checkpoint_association_proven"])
        for forbidden in (
            "window_title", "script_name", "script_source", "script_parameters",
            "account", "raw_dom", "raw_accessibility_tree",
        ):
            self.assertNotIn(forbidden, record)
            self.assertIn(forbidden, record["excluded_sensitive_fields"])

    def test_json_and_csv_exports_are_deterministic_and_csv_safe(self) -> None:
        record = {
            "schema_version": 1,
            "captured_at": "2026-07-21T00:00:00+00:00",
            "source": "xq_visible_backtest_report",
            "report_window_handle": 42,
            "classification": "failure",
            "summary": {"success_count": 0, "failure_count": 1, "total_trades": 0},
            "failure_details_requested": True,
            "failure_details": [{
                "product": "=1+1",
                "state": "失敗",
                "error_code": "1301",
                "description": "+formula",
            }],
            "failure_detail_capture_error": None,
            "report_checkpoint_association_proven": False,
            "contains_user_report_data": True,
            "excluded_sensitive_fields": [],
        }
        json_payload = xq_report.serialize_report(record, "json")
        self.assertEqual(json.loads(json_payload)["classification"], "failure")
        self.assertEqual(json_payload, xq_report.serialize_report(record, "json"))
        self.assertEqual(len(hashlib.sha256(json_payload).hexdigest()), 64)

        csv_payload = xq_report.serialize_report(record, "csv").decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(csv_payload)))
        self.assertEqual(rows[0]["detail_product"], "'=1+1")
        self.assertEqual(rows[0]["detail_description"], "'+formula")

    def test_atomic_export_never_overwrites_and_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            output = directory / "report.json"
            xq_report.write_new_atomic(output, b"first")
            self.assertEqual(output.read_bytes(), b"first")
            with self.assertRaises(FileExistsError):
                xq_report.validate_output_path(output, "json")
            with self.assertRaises(FileExistsError):
                xq_report.write_new_atomic(output, b"second")
            self.assertEqual(output.read_bytes(), b"first")
            self.assertEqual(list(directory.glob("*.tmp")), [])

    def test_export_path_is_restricted_to_private_report_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            private = root / ".xq-auto-writer" / "reports"
            allowed = xq_report.validate_output_path(private / "report.json", "json", private)
            self.assertEqual(allowed, (private / "report.json").resolve())
            with self.assertRaises(ValueError):
                xq_report.validate_output_path(root / "tracked-report.json", "json", private)

    def test_native_formats_and_payload_validation_match_xq_files(self) -> None:
        saved = xq_report.validate_native_payload("save", b"SQLite format 3\x00payload")
        complete = xq_report.validate_native_payload("complete", minimal_xlsx_payload())
        trades = xq_report.validate_native_payload("trades", "欄一,欄二\r\n1,2\r\n".encode("cp950"))
        self.assertEqual(saved["native_format"], "BTReport")
        self.assertEqual(saved["container"], "sqlite")
        self.assertEqual(complete["container"], "zip_xlsx")
        self.assertEqual(trades["encoding"], "cp950")
        self.assertEqual(trades["row_count"], 2)
        self.assertEqual(trades["column_count"], 2)
        with self.assertRaises(ValueError):
            xq_report.validate_native_payload("save", b"not sqlite")
        with self.assertRaises(ValueError):
            xq_report.validate_native_payload("complete", b"not xlsx")

        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "report.BTReport"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE report_data(value INTEGER)")
                connection.commit()
            finally:
                connection.close()
            database_payload = database.read_bytes()
            sqlite_evidence = xq_report.validate_native_file("save", database, database_payload)
            xlsx = Path(temporary_directory) / "report.xlsx"
            xlsx.write_bytes(minimal_xlsx_payload())
            xlsx_evidence = xq_report.validate_native_file("complete", xlsx, xlsx.read_bytes())
        self.assertEqual(sqlite_evidence["sqlite_quick_check"], "ok")
        self.assertEqual(sqlite_evidence["sqlite_table_count"], 1)
        self.assertEqual(xlsx_evidence["xlsx_zip_test"], "ok")
        self.assertEqual(xlsx_evidence["xlsx_worksheet_count"], 1)

    def test_native_export_requires_explicit_directory_confirmation_before_config_or_xq(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_config = Path(temporary_directory) / "missing.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPORT_PATH),
                    "--config",
                    str(missing_config),
                    "--native-action",
                    "complete",
                    "--output-directory",
                    temporary_directory,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(payload["status"], "confirmation_required")
        self.assertFalse(payload["xq_touched"])
        self.assertFalse(payload["file_created"])
        self.assertEqual(Path(payload["proposed_output_directory"]), Path(temporary_directory).resolve())

    def test_native_export_orchestration_verifies_filter_file_and_ui_recovery(self) -> None:
        report = MagicMock()
        report.handle = 42
        report.process_id.return_value = 100
        dialog = MagicMock()
        filename_edit = MagicMock()
        save_button = MagicMock()
        filename_edit.get_value.side_effect = lambda: filename_edit.set_edit_text.call_args.args[0]
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)

            def create_payload(path: Path) -> bytes:
                payload = minimal_xlsx_payload()
                path.write_bytes(payload)
                return payload

            with (
                patch.object(xq_report, "invoke_native_entry") as invoke,
                patch.object(xq_report, "wait_for_save_dialog", return_value=dialog),
                patch.object(
                    xq_report,
                    "save_dialog_controls",
                    return_value=(filename_edit, save_button, "Excel 活頁簿(*.xlsx)"),
                ),
                patch.object(xq_report, "wait_for_native_file", side_effect=create_payload),
                patch.object(xq_report, "close_native_completion", return_value=(True, True)),
            ):
                evidence = xq_report.native_export(report, "complete", directory)

        invoke.assert_called_once_with(report, "complete")
        save_button.click_input.assert_called_once_with()
        self.assertEqual(evidence["native_format"], "xlsx")
        self.assertTrue(evidence["completion_dialog_seen"])
        self.assertTrue(evidence["report_restored"])
        self.assertTrue(evidence["ui_recovery_complete"])
        self.assertTrue(evidence["file_created"])
        self.assertFalse(evidence["existing_file_overwritten"])

    def test_native_export_reports_created_file_when_ui_recovery_is_incomplete(self) -> None:
        report = MagicMock()
        report.handle = 42
        report.process_id.return_value = 100
        filename_edit = MagicMock()
        filename_edit.get_value.side_effect = lambda: filename_edit.set_edit_text.call_args.args[0]
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)

            def create_payload(path: Path) -> bytes:
                payload = minimal_xlsx_payload()
                path.write_bytes(payload)
                return payload

            with (
                patch.object(xq_report, "invoke_native_entry"),
                patch.object(xq_report, "wait_for_save_dialog", return_value=MagicMock()),
                patch.object(
                    xq_report,
                    "save_dialog_controls",
                    return_value=(filename_edit, MagicMock(), "Excel 活頁簿(*.xlsx)"),
                ),
                patch.object(xq_report, "wait_for_native_file", side_effect=create_payload),
                patch.object(xq_report, "close_native_completion", return_value=(True, False)),
                self.assertRaises(xq_report.NativeExportError) as raised,
            ):
                xq_report.native_export(report, "complete", directory)

        self.assertTrue(raised.exception.evidence["file_created"])
        self.assertFalse(raised.exception.evidence["ui_recovery_complete"])
        self.assertIn("output_path", raised.exception.evidence)

    def test_default_output_stays_below_private_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / ".xq-auto-writer" / "xq-ui.json"
            record = {
                "captured_at": "2026-07-21T00:00:00+00:00",
                "report_window_handle": 42,
            }
            output = xq_report.default_output_path(config, record, "json")
        self.assertEqual(output.parent.name, "reports")
        self.assertEqual(output.parent.parent.name, ".xq-auto-writer")
        self.assertEqual(output.suffix, ".json")

    def test_cli_emits_one_json_object_without_touching_xq_when_uncalibrated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / "xq-ui.json"
            config.write_text('{"calibrated": false}', encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPORT_PATH),
                    "--config",
                    str(config),
                    "--list-reports",
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        self.assertEqual(json.loads(completed.stdout)["status"], "automation_error")


if __name__ == "__main__":
    unittest.main()
