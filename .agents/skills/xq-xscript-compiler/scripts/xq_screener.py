#!/usr/bin/env python3
"""Create or run one XQ screener strategy and capture its native CSV result."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


EXIT_CODES = {
    "success": 0,
    "failure": 2,
    "partial_failure": 2,
    "cancelled": 2,
    "automation_error": 3,
}
START_COMMAND = 17554
STOP_COMMAND = 17555
EXPORT_COMMAND = 20616
NEW_STRATEGY_COMMAND = 17551
TAIWAN_SYSTEM_UNIVERSES = (
    "普通股全部(系統)",
    "普通股與ETF(系統)",
    "上市普通股全部(系統)",
    "上櫃普通股全部(系統)",
    "可以放空的個股(系統)",
    "平盤下可空個股(系統)",
    "股期標的(系統)",
    "台灣五十成分股(系統)",
    "權值股前100檔(系統)",
    "中型100(系統)",
)
DIRECTIONS = {"unspecified": "不指定", "long": "多", "short": "空"}
INVALID_XQ_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
SEARCH_SENTINEL = "__Codex_No_Match_9F4A__"


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def decode_xq_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError("XQ CSV is neither UTF-8 nor CP950/Big5")


def parse_xq_screener_csv(path: Path) -> dict[str, Any]:
    lines = decode_xq_csv(path.read_bytes()).splitlines()
    if len(lines) < 4:
        raise ValueError("XQ screener CSV does not contain the expected metadata and header")

    result_kind = lines[0].strip()
    date_match = re.search(r"資料日期[：:]\s*(.+)", lines[1])
    strategy_match = re.search(r"策略\s*[,\t]+\s*(.+)", lines[2])
    if not date_match or not strategy_match:
        raise ValueError("XQ screener CSV metadata is incomplete")

    reader = csv.reader(lines[3:])
    records = list(reader)
    if not records:
        raise ValueError("XQ screener CSV header is missing")
    columns = [value.strip() for value in records[0]]
    rows: list[dict[str, str]] = []
    for raw_line in lines[4:]:
        if raw_line.strip().startswith(("無任何", "沒有任何")) or raw_line.strip() == "所有商品都已正常執行!!":
            continue
        # XQ 3.19.03 writes the first separator as TAB+comma while the rest are CSV.
        fixed_line = re.sub(r"^(\s*\d+)\t,", r"\1,", raw_line)
        values = next(csv.reader([fixed_line]))
        if not any(value.strip() for value in values):
            continue
        if len(values) != len(columns):
            raise ValueError(
                f"XQ screener CSV row has {len(values)} values but header has {len(columns)}"
            )
        rows.append(dict(zip(columns, values)))

    return {
        "result_kind": result_kind,
        "data_date": date_match.group(1).strip(),
        "strategy_name": strategy_match.group(1).strip(),
        "columns": columns,
        "rows": rows,
    }


def command_index(toolbar: Any, command_id: int) -> int:
    for index in range(toolbar.button_count()):
        if toolbar.get_button(index).idCommand == command_id:
            return index
    raise RuntimeError(f"Toolbar command {command_id} was not found")


def top_and_result_toolbars(window: Any) -> tuple[Any, Any]:
    toolbars = window.descendants(class_name="ToolbarWindow32")
    candidates = [toolbar for toolbar in toolbars if toolbar.button_count() >= 10]
    if len(candidates) < 2:
        raise RuntimeError("Selection Center toolbars were not found")
    candidates.sort(key=lambda toolbar: toolbar.rectangle().top)
    return candidates[0], candidates[-1]


def open_selection_center() -> bool:
    from pywinauto import Desktop

    desktop = Desktop(backend="uia")
    if desktop.window(title_re=r"^選股中心.*").exists(timeout=0.5):
        return False
    main = desktop.window(class_name="DAQXQLITEMainWnd")
    if not main.exists(timeout=2):
        raise RuntimeError("XQ main window was not found")
    strategy_menu = [
        control
        for control in main.descendants()
        if control.window_text() == "策略(D)" and control.is_visible()
    ]
    if not strategy_menu:
        raise RuntimeError("XQ Strategy menu was not found")
    strategy_menu[0].click_input()
    time.sleep(0.4)
    items = [
        control
        for control in main.descendants()
        if control.window_text() == "選股中心(S)..." and control.is_visible()
    ]
    if not items:
        raise RuntimeError("Selection Center menu item was not found")
    items[0].click_input()
    desktop.window(title_re=r"^選股中心.*").wait("visible", timeout=10)
    return True


def validate_xq_name(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    if INVALID_XQ_NAME.search(normalized):
        raise ValueError(f"{label} contains a character XQ cannot safely use")
    return normalized


def has_visible_no_result(window: Any) -> bool:
    visible_no_result = [
        control
        for control in window.descendants(class_name="Static")
        if control.control_id() == 20502 and control.is_visible()
    ]
    return bool(visible_no_result)


def replace_search_text(edit: Any, value: str) -> None:
    edit.set_edit_text(value)
    edit.set_focus()
    # WM_SETTEXT alone does not consistently trigger XQ's filter. Preserve the value while
    # generating real edit notifications through one inserted and removed trailing space.
    edit.type_keys("{END}{SPACE}{BACKSPACE}", set_foreground=False)


def wait_for_no_result(window: Any, expected: bool, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if has_visible_no_result(window) == expected:
            return True
        time.sleep(0.1)
    return False


def search_has_result(window: Any, query: str, search_control_id: int) -> bool:
    edit = window.child_window(control_id=search_control_id, class_name="Edit")
    sentinel_ready = False
    for _ in range(2):
        replace_search_text(edit, "")
        time.sleep(0.2)
        replace_search_text(edit, SEARCH_SENTINEL)
        if wait_for_no_result(window, True):
            sentinel_ready = True
            break
    if not sentinel_ready:
        raise RuntimeError(
            f"XQ search control {search_control_id} did not clear for the no-match sentinel"
        )
    replace_search_text(edit, query)
    if wait_for_no_result(window, False):
        return True
    return False


def cancel_new_strategy_dialog(dialog: Any) -> bool:
    if not dialog.exists() or not dialog.is_visible():
        return True
    cancel = dialog.child_window(control_id=2, class_name="Button")
    if cancel.exists() and cancel.is_visible():
        cancel.click_input()
        time.sleep(0.3)
    return not dialog.exists()


def visible_condition_script_names(dialog: Any) -> list[str]:
    return [
        control.window_text().strip()
        for control in dialog.descendants(class_name="Static")
        if control.control_id() == 18710 and control.is_visible() and control.window_text().strip()
    ]


def create_strategy(
    window: Any,
    strategy_name: str,
    script_name: str,
    universe: str,
    direction: str,
) -> dict[str, Any]:
    from pywinauto import Desktop

    if search_has_result(window, strategy_name, 17786):
        raise FileExistsError(
            f"A screener strategy already matches {strategy_name!r}; refusing to overwrite"
        )
    top, _ = top_and_result_toolbars(window)
    top.press_button(command_index(top, NEW_STRATEGY_COMMAND))
    dialog = Desktop(backend="win32").window(title="新增選股策略")
    dialog.wait("visible", timeout=10)
    completed = False
    try:
        market = dialog.child_window(control_id=20853, class_name="ComboBox")
        if "台股" not in market.item_texts():
            raise RuntimeError("Taiwan market was not available in the new strategy dialog")
        market.select("台股")
        dialog.child_window(control_id=20067, class_name="Edit").set_edit_text(strategy_name)
        dialog.child_window(control_id=20011, class_name="ComboBox").select(
            DIRECTIONS[direction]
        )
        universe_control = dialog.child_window(control_id=20069, class_name="ComboBox")
        if universe not in universe_control.item_texts():
            raise RuntimeError(f"XQ does not currently offer universe {universe!r}")
        universe_control.select(universe)

        dialog.child_window(control_id=20014, class_name="Button").click_input()
        time.sleep(0.8)
        if not search_has_result(dialog, script_name, 17053):
            raise LookupError(f"No compiled screener script matched {script_name!r}")
        script_grid = dialog.child_window(control_id=20000, class_name="MFCGridCtrl")
        if not script_grid.exists() or not script_grid.is_visible():
            raise RuntimeError("Compiled screener script grid was not available")
        # The exact unique search leaves one row; click its add glyph relative to the grid.
        script_grid.click_input(coords=(15, 16))
        time.sleep(0.4)
        selected_scripts = visible_condition_script_names(dialog)
        if selected_scripts != [script_name]:
            raise RuntimeError(
                "Added screener script did not match the requested script exactly: "
                f"{selected_scripts!r}"
            )
        finish = dialog.child_window(control_id=1, class_name="Button")
        if not finish.is_enabled():
            raise RuntimeError("XQ did not enable Finish after adding the screener script")
        finish.click_input()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and dialog.exists():
            time.sleep(0.2)
        if dialog.exists():
            raise RuntimeError("New strategy dialog did not close after Finish")
        completed = True
        return {
            "strategy_created": True,
            "script_name": script_name,
            "market": "台股",
            "direction": DIRECTIONS[direction],
            "universe": universe,
        }
    finally:
        if not completed and not cancel_new_strategy_dialog(dialog):
            raise RuntimeError("New strategy dialog could not be cancelled after failure")


def select_strategy(window: Any, strategy_name: str) -> None:
    if not search_has_result(window, strategy_name, 17786):
        raise LookupError(f"No screener strategy matched {strategy_name!r}")
    grid = window.child_window(control_id=20200, class_name="MFCGridCtrl")
    if not grid.exists() or not grid.is_visible():
        raise RuntimeError("Screener strategy grid was not available")
    # The exact-name search isolates one row. Click its body relative to the verified grid.
    grid.click_input(coords=(250, 40))
    time.sleep(0.8)


def visible_execution_time(window: Any) -> str | None:
    for control in window.descendants(class_name="Static"):
        if control.is_visible() and control.window_text().startswith("執行時間："):
            return control.window_text().removeprefix("執行時間：").strip()
    return None


def toolbar_button_enabled(toolbar: Any, index: int) -> bool:
    return bool(toolbar.get_button(index).fsState & 4)


def run_strategy(
    window: Any, timeout_seconds: float, stop_recovery_seconds: float = 10.0
) -> dict[str, Any]:
    top, _ = top_and_result_toolbars(window)
    start_index = command_index(top, START_COMMAND)
    stop_index = command_index(top, STOP_COMMAND)
    top.press_button(start_index)

    deadline = time.monotonic() + timeout_seconds
    start_enabled = toolbar_button_enabled(top, start_index)
    stop_enabled = toolbar_button_enabled(top, stop_index)
    observed_running = stop_enabled or not start_enabled
    while time.monotonic() < deadline:
        time.sleep(0.1)
        start_enabled = toolbar_button_enabled(top, start_index)
        stop_enabled = toolbar_button_enabled(top, stop_index)
        observed_running = observed_running or stop_enabled or not start_enabled
        if observed_running and start_enabled and not stop_enabled:
            time.sleep(0.3)
            return {
                "outcome": "completed",
                "timed_out": False,
                "cancelled": False,
                "observed_running": True,
                "stop_requested": False,
                "recovery_complete": True,
                "start_enabled": True,
                "stop_enabled": False,
                "executed_at": visible_execution_time(window),
            }

    start_enabled = toolbar_button_enabled(top, start_index)
    stop_enabled = toolbar_button_enabled(top, stop_index)
    if start_enabled and not stop_enabled:
        # Very small universes can finish before the first state poll.
        time.sleep(0.3)
        return {
            "outcome": "completed",
            "timed_out": False,
            "cancelled": False,
            "observed_running": observed_running,
            "stop_requested": False,
            "recovery_complete": True,
            "start_enabled": True,
            "stop_enabled": False,
            "executed_at": visible_execution_time(window),
        }

    stop_requested = False
    if stop_enabled:
        top.press_button(stop_index)
        stop_requested = True
    recovery_deadline = time.monotonic() + stop_recovery_seconds
    while time.monotonic() < recovery_deadline:
        time.sleep(0.1)
        start_enabled = toolbar_button_enabled(top, start_index)
        stop_enabled = toolbar_button_enabled(top, stop_index)
        if start_enabled and not stop_enabled:
            return {
                "outcome": "cancelled",
                "timed_out": True,
                "cancelled": True,
                "observed_running": observed_running,
                "stop_requested": stop_requested,
                "recovery_complete": True,
                "start_enabled": True,
                "stop_enabled": False,
                "executed_at": None,
            }
    return {
        "outcome": "recovery_failed",
        "timed_out": True,
        "cancelled": stop_requested,
        "observed_running": observed_running,
        "stop_requested": stop_requested,
        "recovery_complete": False,
        "start_enabled": toolbar_button_enabled(top, start_index),
        "stop_enabled": toolbar_button_enabled(top, stop_index),
        "executed_at": None,
    }


def select_result_kind(window: Any, index: int) -> dict[str, Any]:
    combo = window.child_window(control_id=20665, class_name="ComboBox")
    items = combo.item_texts()
    if index < 0 or index >= len(items):
        raise RuntimeError(f"XQ result kind index {index} is unavailable")
    combo.select(index)
    time.sleep(0.4)
    if combo.selected_index() != index:
        raise RuntimeError(f"XQ result kind did not switch to index {index}")
    return {"index": index, "label": items[index]}


def normalize_error_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        message = row.get("錯誤訊息", "").strip()
        code_match = re.search(r"\((\d{3,5})\)", message)
        normalized.append(
            {
                "sequence": row.get("序號", "").strip(),
                "symbol": row.get("代碼", "").strip(),
                "product": row.get("商品", "").strip(),
                "error_code": code_match.group(1) if code_match else None,
                "message": message,
            }
        )
    return normalized


def classify_screener_result(matched_count: int, error_count: int) -> tuple[str, str]:
    if error_count and matched_count:
        return "partial_failure", "XQ screener returned matched products and execution errors"
    if error_count:
        return "failure", "XQ screener returned execution errors"
    return "success", "XQ screener execution result captured"


def export_native_csv(window: Any, destination: Path) -> None:
    from pywinauto import Desktop

    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing export: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _, result_toolbar = top_and_result_toolbars(window)
    result_toolbar.press_button(command_index(result_toolbar, EXPORT_COMMAND))

    dialog = Desktop(backend="win32").window(title="匯出選股結果")
    dialog.wait("visible", timeout=10)
    saved = False
    try:
        dialog.child_window(control_id=1001, class_name="Edit").set_edit_text(str(destination))
        save_buttons = [
            button
            for button in dialog.descendants(class_name="Button")
            if button.control_id() == 1 and button.is_visible()
        ]
        if not save_buttons:
            raise RuntimeError("Save button was not found in the screener export dialog")
        save_buttons[-1].click_input()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not destination.exists():
            time.sleep(0.2)
        if not destination.exists():
            raise RuntimeError("XQ did not create the screener CSV export")
        saved = True
    finally:
        if not saved and dialog.exists() and dialog.is_visible():
            cancel = dialog.child_window(control_id=2, class_name="Button")
            if cancel.exists() and cancel.is_visible():
                cancel.click_input()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or run an XQ screener strategy and return its rows as JSON"
    )
    parser.add_argument("--config", required=True, help="Calibrated xq-ui.json")
    parser.add_argument("--strategy-name", required=True)
    parser.add_argument(
        "--create-strategy",
        action="store_true",
        help="Create a new Taiwan screener strategy before running it; never overwrites",
    )
    parser.add_argument("--script-name", help="Compiled XQ screener script for --create-strategy")
    parser.add_argument(
        "--universe",
        choices=TAIWAN_SYSTEM_UNIVERSES,
        default="台灣五十成分股(系統)",
        help="Public XQ system universe used only when creating a strategy",
    )
    parser.add_argument(
        "--direction", choices=tuple(DIRECTIONS), default="unspecified"
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--stop-recovery-seconds",
        type=float,
        default=10.0,
        help="Seconds to verify Start/Stop recovery after a timeout-triggered stop",
    )
    parser.add_argument(
        "--native-export",
        type=Path,
        help="Optional path for retaining XQ's native CSV; existing files are never overwritten",
    )
    parser.add_argument(
        "--native-error-export",
        type=Path,
        help="Optional new path for retaining XQ's execution-error CSV",
    )
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--max-error-rows", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        args.timeout_seconds <= 0
        or args.stop_recovery_seconds <= 0
        or args.max_rows < 0
        or args.max_error_rows < 0
    ):
        return emit(
            "automation_error",
            "timeouts must be positive and row limits must be non-negative",
        )
    if args.create_strategy != bool(args.script_name):
        return emit(
            "automation_error",
            "--create-strategy and --script-name must be provided together",
            strategy_name=args.strategy_name,
        )
    config_path = Path(args.config)
    opened_by_tool = False
    window: Any | None = None
    safe_to_close = True
    creation: dict[str, Any] = {"strategy_created": False}
    try:
        args.strategy_name = validate_xq_name(args.strategy_name, "strategy-name", 40)
        if args.script_name:
            args.script_name = validate_xq_name(args.script_name, "script-name", 80)
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            raise RuntimeError("XQ UI configuration is not calibrated")
        opened_by_tool = open_selection_center()

        from pywinauto import Desktop

        window = Desktop(backend="win32").window(title_re=r"^選股中心.*")
        window.set_focus()
        if args.create_strategy:
            creation = create_strategy(
                window,
                args.strategy_name,
                args.script_name,
                args.universe,
                args.direction,
            )
        select_strategy(window, args.strategy_name)
        execution = run_strategy(
            window, args.timeout_seconds, args.stop_recovery_seconds
        )
        if not execution["recovery_complete"]:
            safe_to_close = False
            return emit(
                "automation_error",
                "Screener timeout stop did not restore the Start/Stop controls",
                strategy_name=args.strategy_name,
                execution=execution,
                result_capture_skipped=True,
                **creation,
            )
        if execution["cancelled"]:
            return emit(
                "cancelled",
                "Screener exceeded the timeout, was stopped, and the UI recovered",
                strategy_name=args.strategy_name,
                execution=execution,
                result_capture_skipped=True,
                **creation,
            )

        temp_dir = Path(tempfile.mkdtemp(prefix="xq-screener-"))
        export_path = (
            args.native_export.resolve()
            if args.native_export is not None
            else temp_dir / f"{args.strategy_name}-matches.csv"
        )
        error_export_path = (
            args.native_error_export.resolve()
            if args.native_error_export is not None
            else temp_dir / f"{args.strategy_name}-errors.csv"
        )
        result_kind = window.child_window(control_id=20665, class_name="ComboBox")
        original_result_index = result_kind.selected_index()
        try:
            matched_kind = select_result_kind(window, 0)
            export_native_csv(window, export_path)
            matched_result = parse_xq_screener_csv(export_path)
            error_kind = select_result_kind(window, 3)
            export_native_csv(window, error_export_path)
            error_result = parse_xq_screener_csv(error_export_path)
        finally:
            try:
                select_result_kind(window, original_result_index)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        if matched_result["strategy_name"] != args.strategy_name:
            raise RuntimeError(
                "Exported strategy does not match the requested strategy: "
                f"{matched_result['strategy_name']!r}"
            )
        if error_result["strategy_name"] != args.strategy_name:
            raise RuntimeError(
                "Exported error strategy does not match the requested strategy: "
                f"{error_result['strategy_name']!r}"
            )
        if matched_result["result_kind"] != matched_kind["label"]:
            raise RuntimeError("XQ matched-result export kind did not match the selected kind")
        if error_result["result_kind"] != error_kind["label"]:
            raise RuntimeError("XQ error-result export kind did not match the selected kind")

        all_rows = matched_result.pop("rows")
        returned_rows = all_rows[: args.max_rows]
        all_errors = normalize_error_rows(error_result.pop("rows"))
        returned_errors = all_errors[: args.max_error_rows]
        status, message = classify_screener_result(len(all_rows), len(all_errors))
        return emit(
            status,
            message,
            executed_at=execution["executed_at"],
            execution=execution,
            matched_count=len(all_rows),
            returned_count=len(returned_rows),
            truncated=len(returned_rows) < len(all_rows),
            error_count=len(all_errors),
            returned_error_count=len(returned_errors),
            errors_truncated=len(returned_errors) < len(all_errors),
            native_export_path=str(export_path) if args.native_export is not None else None,
            native_error_export_path=(
                str(error_export_path) if args.native_error_export is not None else None
            ),
            rows=returned_rows,
            error_details=returned_errors,
            error_result_kind=error_result["result_kind"],
            error_columns=error_result["columns"],
            **creation,
            **matched_result,
        )
    except (LookupError, FileExistsError) as exc:
        return emit(
            "failure",
            str(exc),
            strategy_name=args.strategy_name,
            **creation,
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"XQ screener automation failed: {type(exc).__name__}: {exc}",
            strategy_name=args.strategy_name,
            **creation,
        )
    finally:
        if safe_to_close and opened_by_tool and window is not None and window.exists():
            try:
                window.close()
                time.sleep(0.3)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
