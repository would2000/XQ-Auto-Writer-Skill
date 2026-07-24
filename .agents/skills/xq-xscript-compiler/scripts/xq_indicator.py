#!/usr/bin/env python3
"""Capture an XQ indicator's native chart export and compare plotted values."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable


EXIT_CODES = {"success": 0, "mismatch": 2, "automation_error": 3}
ADD_INDICATOR_DIALOG = "新增副圖指標設定"
COPY_PAGE_PREFIX = "複製成新頁面"
ADD_PANE_PREFIX = "增加副圖"
EXPORT_EXCEL_PREFIX = "輸出到Excel"


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return str(value)


def table_from_excel_values(values: Any) -> dict[str, Any]:
    if not isinstance(values, tuple) or len(values) < 2:
        raise ValueError("XQ Excel export has no data rows")
    header_row = values[0] if isinstance(values[0], tuple) else (values[0],)
    raw_columns = [str(value).strip() if value is not None else "" for value in header_row]
    if not all(raw_columns):
        raise ValueError("XQ Excel export contains an empty column name")
    duplicate_columns = sorted(
        {name for name in raw_columns if raw_columns.count(name) > 1}
    )
    occurrences: dict[str, int] = {}
    columns: list[str] = []
    for name in raw_columns:
        occurrences[name] = occurrences.get(name, 0) + 1
        columns.append(
            name if occurrences[name] == 1 else f"{name} [{occurrences[name]}]"
        )

    rows: list[dict[str, Any]] = []
    for raw in values[1:]:
        cells = raw if isinstance(raw, tuple) else (raw,)
        if len(cells) != len(columns):
            raise ValueError("XQ Excel export row width does not match its header")
        if not any(value is not None and str(value).strip() for value in cells):
            continue
        rows.append(dict(zip(columns, (json_value(value) for value in cells))))
    if not rows:
        raise ValueError("XQ Excel export has no non-empty data rows")
    return {
        "columns": columns,
        "duplicate_source_columns": duplicate_columns,
        "rows": rows,
    }


def numeric(value: Any, column: str, row_number: int) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Row {row_number} column {column!r} is not numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Row {row_number} column {column!r} is not numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"Row {row_number} column {column!r} is not finite")
    return result


def compare_affine_column(
    table: dict[str, Any],
    plot_label: str,
    expected_column: str,
    multiplier: float,
    offset: float,
    tolerance: float,
) -> dict[str, Any]:
    columns = table["columns"]
    for required in (plot_label, expected_column):
        if required not in columns:
            raise ValueError(f"Required export column was not found: {required}")
        if required in table.get("duplicate_source_columns", []):
            raise ValueError(f"Required export column is ambiguous: {required}")
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("Absolute tolerance must be a finite non-negative number")
    if not math.isfinite(multiplier) or not math.isfinite(offset):
        raise ValueError("Expected multiplier and offset must be finite")

    mismatches: list[dict[str, Any]] = []
    max_abs_delta = 0.0
    for index, row in enumerate(table["rows"], start=2):
        source = numeric(row[expected_column], expected_column, index)
        actual = numeric(row[plot_label], plot_label, index)
        expected = source * multiplier + offset
        delta = actual - expected
        max_abs_delta = max(max_abs_delta, abs(delta))
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            if len(mismatches) < 10:
                mismatches.append(
                    {
                        "row_number": index,
                        "time": row.get("時間"),
                        "source": source,
                        "actual": actual,
                        "expected": expected,
                        "delta": delta,
                    }
                )
    mismatch_count = sum(
        1
        for index, row in enumerate(table["rows"], start=2)
        if not math.isclose(
            numeric(row[plot_label], plot_label, index),
            numeric(row[expected_column], expected_column, index) * multiplier + offset,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    )
    return {
        "expected_column": expected_column,
        "multiplier": multiplier,
        "offset": offset,
        "absolute_tolerance": tolerance,
        "row_count": len(table["rows"]),
        "matched_count": len(table["rows"]) - mismatch_count,
        "mismatch_count": mismatch_count,
        "max_absolute_delta": max_abs_delta,
        "mismatch_examples": mismatches,
    }


def visible_exact(root: Any, control_type: str, text: str) -> list[Any]:
    return [
        item
        for item in root.descendants(control_type=control_type)
        if item.window_text() == text and item.is_visible() and item.is_enabled()
    ]


def visible_prefix(root: Any, control_type: str, prefix: str) -> list[Any]:
    return [
        item
        for item in root.descendants(control_type=control_type)
        if item.window_text().startswith(prefix) and item.is_visible() and item.is_enabled()
    ]


def unique(items: Iterable[Any], label: str) -> Any:
    values = list(items)
    if len(values) != 1:
        raise LookupError(f"Expected one visible {label}, found {len(values)}")
    return values[0]


def active_chart_page(main_win32: Any) -> tuple[Any, Any]:
    pages = []
    for child in main_win32.children():
        try:
            rect = child.rectangle()
            if (
                child.is_visible()
                and child.window_text()
                and child.class_name().startswith("Afx:")
                and rect.width() > 500
                and rect.height() > 400
            ):
                pages.append(child)
        except Exception:
            continue
    page = max(pages, key=lambda item: item.rectangle().width() * item.rectangle().height())
    charts = [
        item
        for item in page.descendants()
        if item.control_id() == 101 and item.is_visible() and item.is_enabled()
    ]
    if not charts:
        raise LookupError("No visible technical-analysis chart control was found")
    # A page may contain a small linked chart beside the primary technical chart. The
    # largest verified chart surface is the one whose context menu owns indicator export.
    chart = max(
        charts,
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )
    return page, chart


def chart_menu_item(main_uia: Any, chart: Any, prefix: str) -> Any:
    width = chart.rectangle().width()
    height = chart.rectangle().height()
    chart.right_click_input(coords=(max(10, width // 2), max(10, height // 2)))
    time.sleep(0.4)
    return unique(visible_prefix(main_uia, "MenuItem", prefix), f"chart menu item {prefix!r}")


def prevalidate_restore_bookmark(main_uia: Any, name: str) -> Any:
    return unique(visible_exact(main_uia, "Button", name), f"bookmark button {name!r}")


def copy_active_page(main_uia: Any) -> None:
    menu = unique(visible_exact(main_uia, "MenuItem", "自訂頁面(U)"), "custom-page menu")
    menu.click_input()
    time.sleep(0.3)
    unique(
        visible_prefix(main_uia, "MenuItem", COPY_PAGE_PREFIX),
        "copy-to-new-page menu item",
    ).click_input()
    time.sleep(0.8)


def add_indicator(main_uia: Any, main_win32: Any, script_name: str) -> str:
    from pywinauto import Desktop

    page, chart = active_chart_page(main_win32)
    chart_menu_item(main_uia, chart, ADD_PANE_PREFIX).click_input()
    dialog = Desktop(backend="win32").window(title=ADD_INDICATOR_DIALOG)
    dialog.wait("visible enabled", timeout=10)
    completed = False
    try:
        midpoint = dialog.rectangle().left + dialog.rectangle().width() // 2
        search_edits = [
            item
            for item in dialog.descendants()
            if item.control_id() == 1122
            and item.class_name() == "Edit"
            and item.is_visible()
            and item.is_enabled()
            and item.rectangle().left < midpoint
        ]
        search = unique(search_edits, "indicator search box")
        search.set_edit_text(script_name)
        search.set_focus()
        search.type_keys("{END}{SPACE}{BACKSPACE}", set_foreground=False)
        time.sleep(0.7)

        trees = [
            item
            for item in dialog.descendants(class_name="SysTreeView32")
            if item.is_visible() and item.is_enabled()
        ]
        tree = unique(trees, "indicator tree")
        roots = [root for root in tree.roots() if root.text() == "XS指標"]
        xs_root = unique(roots, "XS indicator root")
        custom = unique(
            [item for item in xs_root.children() if item.text() == "自訂"],
            "custom-indicator node",
        )
        custom.expand()
        matches = [item for item in custom.children() if item.text() == script_name]
        unique(matches, f"compiled indicator {script_name!r}").click_input()
        time.sleep(0.3)
        dialog.child_window(control_id=1, class_name="Button").click_input()
        completed = True
        time.sleep(1.0)
        return page.window_text()
    finally:
        if not completed and dialog.exists() and dialog.is_visible():
            cancel = dialog.child_window(control_id=2, class_name="Button")
            if cancel.exists() and cancel.is_visible():
                cancel.click_input()


def excel_apps() -> dict[int, Any]:
    """Return every ROT-registered Excel instance, not only GetActiveObject's instance."""
    import pythoncom
    import win32com.client

    context = pythoncom.CreateBindCtx(0)
    table = pythoncom.GetRunningObjectTable()
    monikers = table.EnumRunning()
    apps: dict[int, Any] = {}
    while True:
        values = monikers.Next(1)
        if not values:
            break
        try:
            unknown = table.GetObject(values[0])
            dispatch = unknown.QueryInterface(pythoncom.IID_IDispatch)
            obj = win32com.client.Dispatch(dispatch)
            app = getattr(obj, "Application", None)
            if app is not None:
                apps[int(app.Hwnd)] = app
        except Exception:
            continue
    return apps


def excel_snapshot() -> tuple[set[int], set[tuple[int, str, str]]]:
    apps = excel_apps()
    keys = {
        (handle, str(workbook.Name), str(workbook.FullName))
        for handle, app in apps.items()
        for workbook in app.Workbooks
    }
    return set(apps), keys


def wait_for_new_workbook(
    original_app_handles: set[int],
    original_keys: set[tuple[int, str, str]],
    timeout: float,
) -> tuple[Any, Any, bool]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for handle, app in excel_apps().items():
            for workbook in app.Workbooks:
                key = (handle, str(workbook.Name), str(workbook.FullName))
                if key not in original_keys:
                    return app, workbook, handle not in original_app_handles
        time.sleep(0.2)
    raise TimeoutError("XQ did not create a new Excel workbook")


def close_export_workbook(app: Any, workbook: Any, quit_when_empty: bool) -> None:
    try:
        workbook.Close(SaveChanges=False)
    finally:
        if quit_when_empty and app.Workbooks.Count == 0:
            app.Quit()


def wait_for_workbook_values(workbook: Any, timeout: float) -> Any:
    """Wait for XQ to finish populating the workbook created before its data is ready."""
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        try:
            last_value = workbook.Worksheets.Item(1).UsedRange.Value
            if isinstance(last_value, tuple) and len(last_value) >= 2:
                return last_value
        except Exception:
            pass
        time.sleep(0.2)
    if last_value is None:
        raise TimeoutError("XQ created an Excel workbook but did not populate it")
    raise TimeoutError("XQ Excel workbook did not receive any data rows")


def close_excel_notice() -> None:
    from pywinauto import Desktop

    for window in Desktop(backend="win32").windows():
        if (
            window.is_visible()
            and window.class_name() == "NUIDialog"
            and window.window_text() == "取得正版 Office"
        ):
            window.close()


def export_chart_table(main_uia: Any, main_win32: Any, timeout: float) -> dict[str, Any]:
    original_app_handles, original_keys = excel_snapshot()
    _, chart = active_chart_page(main_win32)
    chart_menu_item(main_uia, chart, EXPORT_EXCEL_PREFIX).click_input()
    app = workbook = None
    started_excel = False
    try:
        app, workbook, started_excel = wait_for_new_workbook(
            original_app_handles, original_keys, timeout
        )
        worksheet = workbook.Worksheets.Item(1)
        table = table_from_excel_values(wait_for_workbook_values(workbook, timeout))
        table["workbook_name"] = str(workbook.Name)
        table["worksheet_name"] = str(worksheet.Name)
        return table
    finally:
        if app is not None and workbook is not None:
            close_export_workbook(app, workbook, started_excel)
            if started_excel:
                time.sleep(0.4)
                close_excel_notice()


def restore_bookmark(main_uia: Any, main_win32: Any, name: str) -> bool:
    button = prevalidate_restore_bookmark(main_uia, name)
    button.click_input()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            page, _ = active_chart_page(main_win32)
            if page.window_text().rstrip("*") == name:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def run_live(args: argparse.Namespace) -> dict[str, Any]:
    from pywinauto import Desktop

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if config.get("calibrated") is not True:
        raise RuntimeError("XQ UI config is not calibrated")
    desktop_uia = Desktop(backend="uia")
    desktop_win32 = Desktop(backend="win32")
    main_uia = desktop_uia.window(class_name="DAQXQLITEMainWnd")
    main_win32 = desktop_win32.window(class_name="DAQXQLITEMainWnd")
    main_uia.wait("visible enabled ready", timeout=10)
    main_uia.set_focus()

    prevalidate_restore_bookmark(main_uia, args.restore_bookmark)
    original_page, original_chart = active_chart_page(main_win32)
    original_page_title = original_page.window_text()
    original_chart_handle = original_chart.handle
    restored = False
    result: dict[str, Any] | None = None
    try:
        copy_active_page(main_uia)
        page_title = add_indicator(main_uia, main_win32, args.script_name)
        table = export_chart_table(main_uia, main_win32, args.excel_timeout_seconds)
        if args.plot_label not in table["columns"]:
            raise ValueError(f"Plotted export column was not found: {args.plot_label}")
        comparison = None
        status = "success"
        if args.expected_column:
            comparison = compare_affine_column(
                table,
                args.plot_label,
                args.expected_column,
                args.expected_multiplier,
                args.expected_offset,
                args.absolute_tolerance,
            )
            if comparison["mismatch_count"]:
                status = "mismatch"
        rows = table["rows"][: args.max_rows] if args.max_rows else table["rows"]
        result = {
            "status": status,
            "message": (
                "XQ indicator export matched the expected values"
                if status == "success" and comparison
                else "XQ indicator export captured"
                if status == "success"
                else "XQ indicator export did not match the expected values"
            ),
            "script_name": args.script_name,
            "plot_label": args.plot_label,
            "temporary_page_title": page_title,
            "workbook_name": table["workbook_name"],
            "worksheet_name": table["worksheet_name"],
            "columns": table["columns"],
            "row_count": len(table["rows"]),
            "rows_returned": len(rows),
            "rows": rows,
            "comparison": comparison,
            "original_page_title": original_page_title,
            "original_chart_handle": original_chart_handle,
        }
    finally:
        restored = restore_bookmark(main_uia, main_win32, args.restore_bookmark)
        if not restored:
            raise RuntimeError(f"XQ page recovery failed for bookmark {args.restore_bookmark!r}")
    if result is None:
        raise RuntimeError("XQ indicator capture ended without a result")
    result["recovery"] = {
        "complete": restored,
        "restored_bookmark": args.restore_bookmark,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture and compare one compiled XQ indicator on the active chart"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--plot-label", required=True)
    parser.add_argument("--restore-bookmark", required=True)
    parser.add_argument("--expected-column")
    parser.add_argument("--expected-multiplier", type=float, default=1.0)
    parser.add_argument("--expected-offset", type=float, default=0.0)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-9)
    parser.add_argument("--excel-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-rows", type=int, default=100)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_rows < 0:
        return emit("automation_error", "--max-rows must not be negative")
    if args.excel_timeout_seconds <= 0:
        return emit("automation_error", "--excel-timeout-seconds must be positive")
    try:
        result = run_live(args)
        status = result.pop("status")
        message = result.pop("message")
        return emit(status, message, **result)
    except Exception as exc:
        return emit("automation_error", str(exc))


if __name__ == "__main__":
    sys.exit(main())
