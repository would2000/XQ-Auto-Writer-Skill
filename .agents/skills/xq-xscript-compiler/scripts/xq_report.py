#!/usr/bin/env python3
"""Capture one visible XQ backtest report into a private structured export."""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

import xq_backtest


REPORT_SCHEMA_VERSION = 1
EXIT_CODES = {
    "success": 0,
    "no_report": 2,
    "confirmation_required": 3,
    "environment_interruption": 3,
    "automation_error": 3,
}


class NativeExportError(RuntimeError):
    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def windows_desktop_directory() -> Path:
    if sys.platform != "win32":
        raise RuntimeError("XQ native export requires Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer)
    if result != 0 or not buffer.value:
        raise RuntimeError(f"Windows desktop folder lookup failed with HRESULT {result}")
    return Path(buffer.value).resolve()


def native_export_spec(action: str) -> tuple[str, str, bytes | None]:
    specifications = {
        "save": ("BTReport", "*.BTReport", b"SQLite format 3\x00"),
        "complete": ("xlsx", "*.xlsx", b"PK"),
        "trades": ("csv", "*.csv", None),
    }
    try:
        return specifications[action]
    except KeyError as exc:
        raise ValueError(f"Unsupported native action: {action}") from exc


def unique_native_output_path(directory: Path, action: str, report_handle: int) -> Path:
    extension, _, _ = native_export_spec(action)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = directory / f"XQ-backtest-{action}-{timestamp}-{report_handle}.{extension}"
    if candidate.exists():
        raise FileExistsError(f"Refusing to overwrite existing native export: {candidate}")
    return candidate.resolve()


def select_report(windows: list[Any], requested_handle: int | None) -> Any:
    if requested_handle is not None:
        matches = [window for window in windows if int(window.handle) == requested_handle]
        if len(matches) != 1:
            raise LookupError(f"Visible report handle {requested_handle} was not found")
        return matches[0]
    if len(windows) != 1:
        raise LookupError(f"Expected exactly one visible report, found {len(windows)}")
    return windows[0]


def capture_report(window: Any, include_failure_details: bool) -> dict[str, Any]:
    elements = xq_backtest.report_elements(window)
    if elements is None:
        raise RuntimeError("The selected window is not an accessible XQ backtest report")
    summary = xq_backtest.report_summary(elements)
    if summary is None:
        raise RuntimeError("The selected report does not contain a conclusive product summary")

    failure_details: list[dict[str, Any]] = []
    failure_detail_capture_error = None
    if include_failure_details and summary.failure_count > 0:
        try:
            failure_details = [
                asdict(detail)
                for detail in xq_backtest.extract_failure_details(window, summary.failure_count)
            ]
        except Exception as exc:
            failure_detail_capture_error = f"{type(exc).__name__}: {exc}"

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "captured_at": utc_timestamp(),
        "source": "xq_visible_backtest_report",
        "report_window_handle": int(window.handle),
        "classification": xq_backtest.classify_report(summary),
        "summary": asdict(summary),
        "failure_details_requested": include_failure_details,
        "failure_details": failure_details,
        "failure_detail_capture_error": failure_detail_capture_error,
        "report_checkpoint_association_proven": False,
        "contains_user_report_data": True,
        "excluded_sensitive_fields": [
            "window_title",
            "script_name",
            "script_source",
            "script_parameters",
            "account",
            "raw_dom",
            "raw_accessibility_tree",
        ],
    }


def csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def serialize_report(record: dict[str, Any], export_format: str) -> bytes:
    if export_format == "json":
        return (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if export_format != "csv":
        raise ValueError(f"Unsupported export format: {export_format}")

    fields = [
        "schema_version",
        "captured_at",
        "report_window_handle",
        "classification",
        "success_count",
        "failure_count",
        "total_trades",
        "detail_product",
        "detail_state",
        "detail_error_code",
        "detail_description",
        "failure_detail_capture_error",
    ]
    details = record["failure_details"] or [None]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for detail in details:
        row = {
            "schema_version": record["schema_version"],
            "captured_at": record["captured_at"],
            "report_window_handle": record["report_window_handle"],
            "classification": record["classification"],
            "success_count": record["summary"]["success_count"],
            "failure_count": record["summary"]["failure_count"],
            "total_trades": record["summary"]["total_trades"],
            "detail_product": detail["product"] if detail else None,
            "detail_state": detail["state"] if detail else None,
            "detail_error_code": detail["error_code"] if detail else None,
            "detail_description": detail["description"] if detail else None,
            "failure_detail_capture_error": record["failure_detail_capture_error"],
        }
        writer.writerow({key: csv_safe(value) for key, value in row.items()})
    return output.getvalue().encode("utf-8")


def default_output_path(config_path: Path, record: dict[str, Any], export_format: str) -> Path:
    timestamp = datetime.fromisoformat(record["captured_at"]).strftime("%Y%m%dT%H%M%S%fZ")
    directory = config_path.resolve().parent / "reports"
    return directory / f"backtest-report-{timestamp}-{record['report_window_handle']}.{export_format}"


def private_report_directory(config_path: Path) -> Path:
    return config_path.resolve().parent / "reports"


def validate_output_path(path: Path, export_format: str, allowed_directory: Path | None = None) -> Path:
    resolved = path.resolve()
    if resolved.suffix.lower() != f".{export_format}":
        raise ValueError(f"Output extension must be .{export_format}")
    if allowed_directory is not None and not resolved.is_relative_to(allowed_directory.resolve()):
        raise ValueError("Report exports must stay inside the private XQ reports directory")
    if resolved.exists():
        raise FileExistsError(f"Refusing to overwrite existing report export: {resolved}")
    return resolved


def write_new_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def visible_save_dialog(process_id: int) -> Any | None:
    from pywinauto import Desktop

    matches = []
    for window in Desktop(backend="uia").windows():
        try:
            if (
                window.is_visible()
                and window.process_id() == process_id
                and any(item.element_info.automation_id == "FileNameControlHost" for item in window.descendants())
            ):
                matches.append(window)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def wait_for_save_dialog(process_id: int, timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        dialog = visible_save_dialog(process_id)
        if dialog is not None:
            return dialog
        time.sleep(0.1)
    raise TimeoutError("Timed out waiting for the XQ native save dialog")


def invoke_native_entry(report: Any, action: str) -> None:
    if action == "save":
        controls = [
            item
            for item in report.descendants()
            if str(item.element_info.control_type or "") == "Button"
            and str(item.element_info.name or "").strip().endswith("儲存")
            and item.is_visible()
            and item.is_enabled()
        ]
    else:
        dropdowns = [
            item
            for item in report.descendants()
            if item.element_info.automation_id == "appDropdownButton"
            and item.is_visible()
            and item.is_enabled()
        ]
        if len(dropdowns) != 1:
            raise LookupError(f"Expected one XQ export dropdown, found {len(dropdowns)}")
        dropdowns[0].iface_invoke.Invoke()
        time.sleep(0.2)
        label = "完整匯出" if action == "complete" else "僅匯出交易紀錄"
        controls = [
            item
            for item in report.descendants()
            if str(item.element_info.control_type or "") == "MenuItem"
            and str(item.element_info.name or "") == label
            and item.is_visible()
            and item.is_enabled()
        ]
    if len(controls) != 1:
        raise LookupError(f"Expected one XQ native {action} control, found {len(controls)}")
    controls[0].iface_invoke.Invoke()


def save_dialog_controls(dialog: Any) -> tuple[Any, Any, str]:
    filename_edits = [
        item
        for item in dialog.descendants(control_type="Edit")
        if item.element_info.automation_id == "1001"
    ]
    save_buttons = [
        item
        for item in dialog.descendants(control_type="Button")
        if item.element_info.automation_id == "1" and item.is_visible() and item.is_enabled()
    ]
    file_types = [
        item
        for item in dialog.descendants(control_type="ComboBox")
        if item.element_info.automation_id == "FileTypeControlHost"
    ]
    if len(filename_edits) != 1 or len(save_buttons) != 1 or len(file_types) != 1:
        raise LookupError("XQ native save-dialog controls are not unique")
    return filename_edits[0], save_buttons[0], str(file_types[0].selected_text())


def recover_save_dialog(dialog: Any) -> None:
    try:
        confirmations = [
            item
            for item in dialog.descendants(control_type="Button")
            if str(item.element_info.name or "") == "確定" and item.is_visible() and item.is_enabled()
        ]
        if len(confirmations) == 1:
            confirmations[0].click_input()
            time.sleep(0.2)
        cancellations = [
            item
            for item in dialog.descendants(control_type="Button")
            if item.element_info.automation_id == "2" and item.is_visible() and item.is_enabled()
        ]
        if len(cancellations) == 1:
            cancellations[0].click_input()
    except Exception:
        pass


def wait_for_native_file(path: Path, timeout: float = 20.0) -> bytes:
    deadline = time.monotonic() + timeout
    previous_size = None
    stable_checks = 0
    while time.monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == previous_size:
                stable_checks += 1
                if stable_checks >= 2:
                    return path.read_bytes()
            else:
                stable_checks = 0
            previous_size = size
        time.sleep(0.2)
    raise TimeoutError("XQ did not create a stable native export before the timeout")


def validate_native_payload(action: str, payload: bytes) -> dict[str, Any]:
    extension, _, signature = native_export_spec(action)
    if signature is not None and not payload.startswith(signature):
        raise ValueError(f"Native {extension} export has an unexpected file signature")
    evidence: dict[str, Any] = {"native_format": extension}
    if action == "save":
        evidence["container"] = "sqlite"
    elif action == "complete":
        evidence["container"] = "zip_xlsx"
    else:
        decoded = None
        encoding = None
        for candidate in ("utf-8-sig", "cp950"):
            try:
                decoded = payload.decode(candidate)
                encoding = candidate
                break
            except UnicodeDecodeError:
                continue
        if decoded is None or encoding is None:
            raise ValueError("Native trade CSV is neither UTF-8 nor CP950")
        rows = list(csv.reader(io.StringIO(decoded)))
        if not rows:
            raise ValueError("Native trade CSV is empty")
        evidence.update(
            {
                "encoding": encoding,
                "row_count": len(rows),
                "column_count": len(rows[0]),
            }
        )
    return evidence


def validate_native_file(action: str, path: Path, payload: bytes) -> dict[str, Any]:
    evidence = validate_native_payload(action, payload)
    if action == "save":
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            quick_cursor = connection.execute("PRAGMA quick_check")
            table_cursor = connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
            try:
                quick_check = str(quick_cursor.fetchone()[0])
                table_count = int(table_cursor.fetchone()[0])
            finally:
                quick_cursor.close()
                table_cursor.close()
        if quick_check.lower() != "ok" or table_count <= 0:
            raise ValueError("Native BTReport failed SQLite integrity validation")
        evidence.update({"sqlite_quick_check": quick_check, "sqlite_table_count": table_count})
    elif action == "complete":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            bad_member = archive.testzip()
            names = archive.namelist()
        worksheet_count = sum(
            1
            for name in names
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if bad_member is not None or "xl/workbook.xml" not in names or worksheet_count <= 0:
            raise ValueError("Native XLSX failed ZIP/workbook integrity validation")
        evidence.update({"xlsx_zip_test": "ok", "xlsx_worksheet_count": worksheet_count})
    return evidence


def close_native_completion(report: Any, timeout: float = 10.0) -> tuple[bool, bool]:
    deadline = time.monotonic() + timeout
    completion_seen = False
    while time.monotonic() < deadline:
        blank_documents = [
            item
            for item in report.descendants()
            if str(item.element_info.control_type or "") == "Document"
            and not str(item.element_info.name or "")
        ]
        close_buttons = []
        for document in blank_documents:
            close_buttons.extend(
                item
                for item in document.descendants()
                if str(item.element_info.control_type or "") == "Button"
                and str(item.element_info.name or "") == "關閉"
                and item.is_visible()
                and item.is_enabled()
            )
        if len(close_buttons) == 1:
            completion_seen = True
            close_buttons[0].iface_invoke.Invoke()
            time.sleep(0.2)
        restored = any(
            item.element_info.automation_id == "appDropdownButton"
            and item.is_visible()
            and item.is_enabled()
            for item in report.descendants()
        )
        if completion_seen and restored:
            return True, True
        time.sleep(0.1)
    return completion_seen, False


def native_export(report: Any, action: str, output_directory: Path) -> dict[str, Any]:
    if not output_directory.exists() or not output_directory.is_dir():
        raise NotADirectoryError(f"Confirmed native export directory does not exist: {output_directory}")
    output_path = unique_native_output_path(output_directory, action, int(report.handle))
    extension, expected_filter, _ = native_export_spec(action)
    invoke_native_entry(report, action)
    dialog = wait_for_save_dialog(report.process_id())
    try:
        filename_edit, save_button, selected_file_type = save_dialog_controls(dialog)
        if expected_filter.lower() not in selected_file_type.lower():
            raise RuntimeError(
                f"XQ selected unexpected native file type {selected_file_type!r}; expected {expected_filter}"
            )
        if output_path.exists():
            raise FileExistsError(f"Refusing to overwrite existing native export: {output_path}")
        filename_edit.set_edit_text(str(output_path))
        if filename_edit.get_value() != str(output_path):
            raise RuntimeError("XQ native filename read-back did not match the confirmed path")
        save_button.click_input()
        payload = wait_for_native_file(output_path)
    except Exception:
        recover_save_dialog(dialog)
        raise
    completion_seen, report_restored = close_native_completion(report)
    base_evidence = {
        "native_action": action,
        "output_directory": str(output_directory),
        "output_path": str(output_path),
        "selected_file_type": selected_file_type,
        "byte_count": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "completion_dialog_seen": completion_seen,
        "report_restored": report_restored,
        "ui_recovery_complete": completion_seen and report_restored,
        "file_created": True,
        "existing_file_overwritten": False,
    }
    try:
        format_evidence = validate_native_file(action, output_path, payload)
    except Exception as exc:
        raise NativeExportError(
            f"Native file was created but failed validation: {type(exc).__name__}: {exc}",
            {**base_evidence, "native_validation_error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    evidence = {**base_evidence, **format_evidence}
    if not completion_seen or not report_restored:
        raise NativeExportError(
            "Native file was created, but the XQ completion dialog did not recover to the report",
            evidence,
        )
    return evidence


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list-reports", action="store_true")
    mode.add_argument("--export-format", choices=("json", "csv"))
    mode.add_argument("--native-action", choices=("save", "complete", "trades"))
    parser.add_argument("--report-handle", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--confirm-output-directory", action="store_true")
    parser.add_argument("--include-failure-details", action="store_true")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.report_handle is not None and args.report_handle <= 0:
        raise ValueError("--report-handle must be a positive integer")
    if args.list_reports and (
        args.report_handle is not None
        or args.output is not None
        or args.output_directory is not None
        or args.confirm_output_directory
        or args.include_failure_details
    ):
        raise ValueError("--list-reports cannot select a report, write output, or open failure details")
    if args.native_action is not None:
        if args.output is not None or args.include_failure_details:
            raise ValueError("Native export cannot use structured --output or --include-failure-details")
    elif args.output_directory is not None or args.confirm_output_directory:
        raise ValueError("--output-directory and --confirm-output-directory require --native-action")


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        validate_args(args)
        native_output_directory = None
        if args.native_action is not None:
            native_output_directory = (
                args.output_directory.resolve()
                if args.output_directory is not None
                else windows_desktop_directory()
            )
            if not args.confirm_output_directory:
                return emit(
                    "confirmation_required",
                    "Confirm the native XQ export directory before XQ is changed or a file is created",
                    mode="native_export",
                    native_action=args.native_action,
                    proposed_output_directory=str(native_output_directory),
                    default_is_windows_desktop=args.output_directory is None,
                    xq_touched=False,
                    file_created=False,
                    existing_file_overwritten=False,
                )
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")

        snapshot = xq_backtest.capture_runtime_snapshot(config)
        failure_kind = xq_backtest.classify_runtime_interruption(snapshot)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ runtime is not ready for report capture",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(snapshot),
            )

        windows = xq_backtest.visible_report_windows()
        if args.list_reports:
            reports = xq_backtest.visible_report_evidence()
            status = "success" if reports else "no_report"
            return emit(
                status,
                "Visible XQ backtest reports listed" if reports else "No visible XQ backtest report was found",
                mode="list_reports",
                read_only=True,
                report_count=len(reports),
                reports=reports,
            )
        if not windows:
            mode = "native_export" if args.native_action is not None else "export_report"
            return emit("no_report", "No visible XQ backtest report was found", mode=mode)

        report = select_report(windows, args.report_handle)
        if args.native_action is not None:
            if native_output_directory is None:
                raise RuntimeError("Native output directory was not confirmed")
            evidence = native_export(report, args.native_action, native_output_directory)
            return emit(
                "success",
                "XQ native backtest report export completed",
                mode="native_export",
                report_window_handle=int(report.handle),
                output_directory_confirmed=True,
                **evidence,
            )
        record = capture_report(report, args.include_failure_details)
        output_path = args.output or default_output_path(args.config, record, args.export_format)
        output_path = validate_output_path(
            output_path,
            args.export_format,
            allowed_directory=private_report_directory(args.config),
        )
        payload = serialize_report(record, args.export_format)
        write_new_atomic(output_path, payload)
        return emit(
            "success",
            "XQ backtest report captured to a new structured export",
            mode="export_report",
            export_format=args.export_format,
            output_path=str(output_path),
            byte_count=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            report_window_handle=record["report_window_handle"],
            classification=record["classification"],
            failure_details_requested=record["failure_details_requested"],
            failure_detail_count=len(record["failure_details"]),
            failure_detail_capture_error=record["failure_detail_capture_error"],
            report_checkpoint_association_proven=False,
            existing_file_overwritten=False,
        )
    except NativeExportError as exc:
        return emit("automation_error", str(exc), **exc.evidence)
    except Exception as exc:
        return emit("automation_error", f"XQ report capture failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
