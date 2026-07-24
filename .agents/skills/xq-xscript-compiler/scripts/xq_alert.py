#!/usr/bin/env python3
"""Run an isolated XQ Strategy Radar trigger/non-trigger alert probe."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any


EXIT_CODES = {"success": 0, "mismatch": 2, "automation_error": 3}
NEW_COMMAND = 17551
DELETE_COMMAND = 17553
COPY_COMMAND = 17627
START_COMMAND = 17554
STOP_COMMAND = 17555
RADAR_TITLE = "策略雷達 - XQ全球贏家(個人版)"
RUN_LABEL = re.compile(r"^(\d{2}:\d{2}:\d{2})\((\d+)\)$")
SEARCH_SENTINEL = "__Codex_Alert_No_Match_7B2E__"


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def command_index(toolbar: Any, command_id: int) -> int:
    for index in range(toolbar.button_count()):
        if toolbar.button(index).info.idCommand == command_id:
            return index
    raise RuntimeError(f"Strategy Radar toolbar command {command_id} was not found")


def command_enabled(toolbar: Any, command_id: int) -> bool:
    # TBSTATE_ENABLED is bit 2 (value 4).
    return bool(toolbar.button(command_index(toolbar, command_id)).info.fsState & 4)


def press_command(toolbar: Any, command_id: int) -> None:
    toolbar.button(command_index(toolbar, command_id)).click()


def parse_run_label(value: str) -> dict[str, Any] | None:
    match = RUN_LABEL.fullmatch(value.strip())
    if not match:
        return None
    return {"time": match.group(1), "trigger_count": int(match.group(2)), "label": value.strip()}


def latest_run(labels: list[str]) -> dict[str, Any] | None:
    runs = [parsed for value in labels if (parsed := parse_run_label(value)) is not None]
    return runs[-1] if runs else None


def evaluate_pair(true_count: int, false_count: int, false_completed: bool) -> dict[str, Any]:
    passed = true_count > 0 and false_count == 0 and false_completed
    return {
        "passed": passed,
        "true_trigger_count": true_count,
        "false_trigger_count": false_count,
        "false_execution_completed": false_completed,
    }


def replace_search_text(edit: Any, value: str) -> None:
    edit.set_edit_text(value)
    edit.set_focus()
    edit.type_keys("{END}{SPACE}{BACKSPACE}", set_foreground=False)


def visible_no_result(window: Any) -> bool:
    return any(
        item.control_id() == 33041
        and item.is_visible()
        and item.window_text() == "沒有搜尋出符合的策略雷達"
        for item in window.descendants(class_name="Static")
    )


def wait_no_result(window: Any, expected: bool, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if visible_no_result(window) == expected:
            return True
        time.sleep(0.1)
    return False


def search_exact(window: Any, value: str) -> bool:
    edit = window.child_window(control_id=33005, class_name="Edit")
    replace_search_text(edit, SEARCH_SENTINEL)
    if not wait_no_result(window, True):
        raise RuntimeError("Strategy Radar search did not accept the no-match sentinel")
    replace_search_text(edit, value)
    return wait_no_result(window, False)


def visible_dialogs(desktop: Any, excluded_handle: int) -> list[Any]:
    result = []
    for wrapper in desktop.windows():
        try:
            if wrapper.handle != excluded_handle and wrapper.is_visible() and wrapper.class_name() == "#32770":
                result.append(desktop.window(handle=wrapper.handle))
        except Exception:
            continue
    return result


def click_first_dialog_button(desktop: Any, radar_handle: int, control_id: int = 1) -> dict[str, Any]:
    dialogs = visible_dialogs(desktop, radar_handle)
    if len(dialogs) != 1:
        raise RuntimeError(f"Expected one Strategy Radar dialog, found {len(dialogs)}")
    dialog = dialogs[0]
    texts = [item.window_text() for item in dialog.descendants() if item.window_text()]
    title = dialog.window_text()
    dialog.child_window(control_id=control_id, class_name="Button").click_input()
    return {"title": title, "texts": texts}


def open_radar() -> tuple[Any, bool]:
    from pywinauto import Desktop
    import win32con
    import win32gui

    desktop32 = Desktop(backend="win32")
    existing = desktop32.window(title=RADAR_TITLE)
    if existing.exists(timeout=0.5):
        wrapper = existing.wrapper_object()
        opened = not wrapper.is_visible()
        if opened:
            win32gui.ShowWindow(wrapper.handle, win32con.SW_SHOW)
        existing.wait("visible enabled", timeout=10)
        return existing, opened

    desktop = Desktop(backend="uia")
    main = desktop.window(class_name="DAQXQLITEMainWnd")
    strategy = [
        item for item in main.descendants(control_type="MenuItem")
        if item.window_text() == "策略(D)" and item.is_visible()
    ]
    if not strategy:
        raise RuntimeError("XQ Strategy menu was not found")
    strategy[0].click_input()
    time.sleep(0.3)
    radar_items = [
        item for item in main.descendants(control_type="MenuItem")
        if item.window_text() == "策略雷達(L)..." and item.is_visible()
    ]
    if not radar_items:
        raise RuntimeError("XQ Strategy Radar menu item was not found")
    radar_items[0].click_input()
    window = desktop32.window(title=RADAR_TITLE)
    window.wait("visible enabled", timeout=10)
    return window, True


def select_tab(radar_handle: int, title: str) -> Any:
    from pywinauto import Desktop

    root = Desktop(backend="uia").window(handle=radar_handle)
    tab = root.child_window(title=title, control_type="TabItem")
    tab.select()
    time.sleep(0.3)
    return root


def select_script(dialog: Any, script_name: str) -> None:
    from pywinauto import Desktop

    dialog.child_window(control_id=17203, class_name="Button").click_input()
    chooser = Desktop(backend="win32").window(title="選擇使用腳本")
    chooser.wait("visible", timeout=10)
    chooser_uia = Desktop(backend="uia").window(handle=chooser.handle)
    custom = [
        item for item in chooser_uia.descendants(control_type="TreeItem")
        if item.window_text().startswith("自訂")
    ]
    if len(custom) != 1:
        raise RuntimeError("XQ custom-script root was not found uniquely")
    custom[0].expand()
    time.sleep(0.2)
    matches = [
        item for item in chooser_uia.descendants(control_type="TreeItem")
        if item.window_text() == script_name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one alert script named {script_name!r}, found {len(matches)}")
    matches[0].click_input()
    chooser.child_window(control_id=1, class_name="Button").click_input()


def select_product(dialog: Any, code: str, expected_readback: str) -> None:
    from pywinauto import Desktop

    dialog.child_window(control_id=17610, class_name="Button").click_input()
    chooser = Desktop(backend="win32").window(title="選擇商品")
    chooser.wait("visible", timeout=10)
    query = chooser.child_window(control_id=741, class_name="Edit")
    query.set_edit_text(code)
    query.type_keys("{END}{SPACE}{BACKSPACE}")
    chooser.child_window(control_id=802, class_name="Button").click_input()
    time.sleep(0.4)
    chooser_uia = Desktop(backend="uia").window(handle=chooser.handle)
    matches = [
        item for item in chooser_uia.descendants(control_type="ListItem")
        if item.window_text() == code
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one exact product code {code!r}, found {len(matches)}")
    matches[0].click_input()
    chooser.child_window(control_id=803, class_name="Button").click_input()
    chooser.child_window(control_id=1, class_name="Button").click_input()
    time.sleep(0.3)
    actual = dialog.child_window(control_id=17107, class_name="Static").window_text()
    if actual != expected_readback:
        raise RuntimeError(f"Product readback mismatch: expected {expected_readback!r}, got {actual!r}")


def create_true_strategy(
    radar: Any,
    toolbar: Any,
    strategy_name: str,
    script_name: str,
    product_code: str,
    product_readback: str,
    check_existing: bool = True,
) -> dict[str, Any]:
    from pywinauto import Desktop

    if check_existing and search_exact(radar, strategy_name):
        raise FileExistsError(f"Strategy {strategy_name!r} already exists; refusing to overwrite")
    press_command(toolbar, NEW_COMMAND)
    dialog = Desktop(backend="win32").window(title="新增策略雷達")
    dialog.wait("visible", timeout=10)
    dialog.child_window(control_id=17500, class_name="Edit").set_edit_text(strategy_name)
    select_script(dialog, script_name)
    select_product(dialog, product_code, product_readback)
    dialog.child_window(control_id=17035, class_name="ComboBox").select("單次洗價模式")
    readback = {
        "name": dialog.child_window(control_id=17500, class_name="Edit").window_text(),
        "script": dialog.child_window(control_id=17202, class_name="Edit").window_text(),
        "product": dialog.child_window(control_id=17107, class_name="Static").window_text(),
        "trigger_mode": dialog.child_window(control_id=17035, class_name="ComboBox").window_text(),
    }
    if readback != {
        "name": strategy_name,
        "script": script_name,
        "product": product_readback,
        "trigger_mode": "單次洗價模式",
    }:
        raise RuntimeError(f"New alert strategy readback mismatch: {readback}")
    dialog.child_window(control_id=1, class_name="Button").click_input()
    notice = click_first_dialog_button(Desktop(backend="win32"), radar.handle)
    return {"readback": readback, "notice": notice}


def wait_single_wash_complete(toolbar: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if command_enabled(toolbar, START_COMMAND) and not command_enabled(toolbar, STOP_COMMAND):
            return True
        time.sleep(0.2)
    return False


def trigger_run(radar_handle: int) -> dict[str, Any] | None:
    root = select_tab(radar_handle, "觸發商品")
    labels = [
        item.window_text() for item in root.descendants(control_type="TreeItem")
        if item.is_visible() and item.window_text()
    ]
    return latest_run(labels)


def copy_as_false(radar: Any, toolbar: Any, false_name: str, parameter_label: str) -> dict[str, Any]:
    from pywinauto import Desktop

    copy_stage = "select_content"
    try:
        # trigger_run leaves Strategy Radar on the trigger-results tab. Copying is
        # only deterministic from the strategy content tab in the current XQ UI.
        select_tab(radar.handle, "內容")
        copy_stage = "open_copy_dialog"
        press_command(toolbar, COPY_COMMAND)
        copy_dialog = Desktop(backend="win32").window(title="複製策略雷達")
        copy_dialog.wait("visible", timeout=10)
        copy_stage = "confirm_copy_dialog"
        copy_dialog.child_window(control_id=16100, class_name="Edit").set_edit_text(false_name)
        copy_dialog.child_window(control_id=1, class_name="Button").click_input()
        time.sleep(0.5)
        copy_stage = "select_copied_strategy"
        if not search_exact(radar, false_name):
            raise RuntimeError("Copied false strategy could not be selected")
        copy_stage = "locate_parameter"
        root = select_tab(radar.handle, "內容")
        rows = [
            item for item in root.descendants(control_type="ListItem")
            if item.window_text() == parameter_label and item.is_visible()
        ]
        if len(rows) != 1:
            raise RuntimeError(f"Expected one parameter row {parameter_label!r}, found {len(rows)}")
        copy_stage = "edit_parameter"
        parameter_list = radar.child_window(control_id=45243, class_name="SysListView32")
        rect = parameter_list.rectangle()
        parameter_list.double_click_input(coords=(max(1, rect.width() - 135), 33))
        time.sleep(0.2)
        editor = radar.child_window(control_id=45041, class_name="Edit")
        before = editor.window_text()
        editor.set_edit_text("0")
        editor.type_keys("{ENTER}")
        time.sleep(0.2)
        texts = [child.window_text() for child in rows[0].descendants(control_type="Text")]
        if not texts or texts[-1] != "0":
            raise RuntimeError(f"False parameter readback mismatch: {texts}")
        copy_stage = "start_false_strategy"
        press_command(toolbar, START_COMMAND)
        prompt = click_first_dialog_button(Desktop(backend="win32"), radar.handle)
        return {"parameter_before": before, "parameter_after": texts[-1], "save_prompt": prompt}
    except Exception as exc:
        if isinstance(exc, RuntimeError) and str(exc).startswith("False-copy stage"):
            raise
        raise RuntimeError(
            f"False-copy stage failed at {copy_stage}: {type(exc).__name__}: {exc}"
        ) from exc


def delete_exact(radar: Any, toolbar: Any, name: str, script_name: str, product_readback: str) -> bool:
    from pywinauto import Desktop

    if not search_exact(radar, name):
        return False
    select_tab(radar.handle, "內容")
    script = radar.child_window(control_id=17202, class_name="Edit").window_text()
    product = radar.child_window(control_id=17107, class_name="Static").window_text()
    if script != script_name or product != product_readback:
        raise RuntimeError(f"Refusing to delete {name!r}: readback was {script!r}, {product!r}")
    if command_enabled(toolbar, STOP_COMMAND):
        press_command(toolbar, STOP_COMMAND)
        click_first_dialog_button(Desktop(backend="win32"), radar.handle)
        time.sleep(0.3)
    press_command(toolbar, DELETE_COMMAND)
    click_first_dialog_button(Desktop(backend="win32"), radar.handle)
    time.sleep(0.3)
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--product-code", default="2330")
    parser.add_argument("--product-readback", default="台積電(2330)")
    parser.add_argument("--parameter-label", default="1觸發，0不觸發")
    parser.add_argument("--strategy-prefix", default="CodexAlertProbe")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--keep-strategies", action="store_true")
    values = parser.parse_args(argv)
    if values.timeout <= 0:
        parser.error("--timeout must be positive")
    return values


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stamp = time.strftime("%H%M%S")
    true_name = f"{args.strategy_prefix}T{stamp}"[:40]
    false_name = f"{args.strategy_prefix}F{stamp}"[:40]
    created: list[str] = []
    radar = None
    opened = False
    current_stage = "open_radar"
    details: dict[str, Any] = {"true_strategy": true_name, "false_strategy": false_name}
    try:
        radar, opened = open_radar()
        toolbar = radar.child_window(
            control_id=59392, class_name="ToolbarWindow32"
        ).wrapper_object()
        if search_exact(radar, true_name):
            raise FileExistsError(f"Strategy {true_name!r} already exists; refusing to overwrite")
        created.append(true_name)
        current_stage = "create_true_strategy"
        details["true_setup"] = create_true_strategy(
            radar,
            toolbar,
            true_name,
            args.script_name,
            args.product_code,
            args.product_readback,
            check_existing=False,
        )
        current_stage = "wait_true_wash"
        true_completed = wait_single_wash_complete(toolbar, args.timeout)
        if not true_completed:
            raise TimeoutError("True-case single wash did not complete")
        current_stage = "capture_true_run"
        true_run = trigger_run(radar.handle)
        true_count = true_run["trigger_count"] if true_run else 0
        details["true_run"] = true_run

        if search_exact(radar, false_name):
            raise FileExistsError(f"Strategy {false_name!r} already exists; refusing to overwrite")
        if not search_exact(radar, true_name):
            raise RuntimeError("True strategy could not be reselected before copying")
        created.append(false_name)
        current_stage = "copy_false_strategy"
        details["false_setup"] = copy_as_false(radar, toolbar, false_name, args.parameter_label)
        current_stage = "wait_false_wash"
        false_completed = wait_single_wash_complete(toolbar, args.timeout)
        if not false_completed:
            raise TimeoutError("False-case single wash did not complete")
        current_stage = "capture_false_run"
        false_run = trigger_run(radar.handle)
        false_count = false_run["trigger_count"] if false_run else 0
        details["false_run"] = false_run
        verdict = evaluate_pair(true_count, false_count, false_completed)
        details["verdict"] = verdict
        status = "success" if verdict["passed"] else "mismatch"
        message = (
            "XQ alert trigger/non-trigger probe passed"
            if verdict["passed"]
            else "XQ alert trigger/non-trigger result did not match expectations"
        )
    except (FileExistsError, TimeoutError, RuntimeError, LookupError) as exc:
        status = "automation_error"
        message = (
            f"XQ alert automation failed at {current_stage}: "
            f"{type(exc).__name__}: {exc}"
        )
    except Exception as exc:
        status = "automation_error"
        message = (
            f"XQ alert automation failed at {current_stage}: "
            f"{type(exc).__name__}: {exc}"
        )
    finally:
        cleanup: dict[str, Any] = {"requested": not args.keep_strategies, "deleted": [], "errors": []}
        if radar is not None and not args.keep_strategies:
            try:
                toolbar = radar.child_window(
                    control_id=59392, class_name="ToolbarWindow32"
                ).wrapper_object()
                for name in reversed(created):
                    try:
                        if delete_exact(radar, toolbar, name, args.script_name, args.product_readback):
                            cleanup["deleted"].append(name)
                    except Exception as exc:
                        cleanup["errors"].append(f"{name}: {type(exc).__name__}: {exc}")
            except Exception as exc:
                cleanup["errors"].append(f"cleanup: {type(exc).__name__}: {exc}")
        if radar is not None and opened:
            try:
                radar.close()
            except Exception:
                pass
        details["cleanup"] = cleanup
        if cleanup["errors"] and status == "success":
            status = "automation_error"
            message = "Alert results matched, but isolated Strategy Radar cleanup failed"
    return emit(status, message, **details)


if __name__ == "__main__":
    sys.exit(main())
