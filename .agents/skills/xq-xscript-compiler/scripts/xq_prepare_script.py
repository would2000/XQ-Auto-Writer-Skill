#!/usr/bin/env python3
"""Open XScript from XQ and create a new script document of the requested type."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_TYPES = {"indicator", "screener", "alert", "function", "autotrade"}
FUNCTION_RETURN_TYPES = {"number", "boolean", "string"}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def selector_kwargs(selector: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "title_re", "auto_id", "control_type", "class_name", "found_index"}
    result = {key: value for key, value in selector.items() if key in allowed and value not in (None, "")}
    if not result:
        raise ValueError("A UI selector is empty")
    return result


def wait_for_win32_window(class_name: str, title: str, timeout: float) -> Any:
    from pywinauto import Desktop

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = [
            item
            for item in Desktop(backend="win32").windows()
            if item.is_visible()
            and item.class_name() == class_name
            and " ".join(item.window_text().split()) == " ".join(title.split())
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LookupError(f"Expected one {title!r} dialog, found {len(matches)}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for dialog: {title}")


def control_by_id(root: Any, control_id: int) -> Any:
    matches = [item for item in root.descendants() if item.control_id() == control_id]
    if len(matches) != 1:
        raise LookupError(f"Expected one control id {control_id}, found {len(matches)}")
    return matches[0]


def open_xscript(config: dict[str, Any], force_menu: bool) -> Any:
    from pywinauto import Desktop, keyboard

    desktop = Desktop(backend="uia")
    timeout = float(config.get("connect_timeout_seconds", 15))
    xscript_selector = selector_kwargs(config["window"])

    existing = desktop.window(**xscript_selector)
    if existing.exists(timeout=0.2) and not force_menu:
        existing.wait("visible enabled ready", timeout=timeout)
        return existing

    launcher = config["launcher"]
    xq = desktop.window(**selector_kwargs(launcher["xq_window"]))
    xq.wait("visible enabled ready", timeout=timeout)
    xq.set_focus()
    menu = xq.child_window(**selector_kwargs(launcher["strategy_menu"]))
    menu.click_input()
    time.sleep(float(launcher.get("menu_wait_seconds", 0.3)))
    keyboard.send_keys(launcher.get("open_xscript_keys", "{END}{ENTER}"), pause=0.05)

    xscript = desktop.window(**xscript_selector)
    xscript.wait("visible enabled ready", timeout=timeout)
    return xscript


def open_new_script_dialog(config: dict[str, Any], xscript: Any) -> Any:
    from pywinauto import keyboard

    dialog_config = config["new_script_dialog"]
    timeout = float(config.get("connect_timeout_seconds", 15))
    try:
        return wait_for_win32_window(
            str(dialog_config["class_name"]), str(dialog_config["title"]), 0.2
        )
    except TimeoutError:
        pass

    xscript.set_focus()
    time.sleep(0.2)
    keyboard.send_keys(dialog_config.get("open_file_menu_keys", "%f"), pause=0.05)
    time.sleep(float(dialog_config.get("menu_wait_seconds", 0.3)))
    keyboard.send_keys(dialog_config.get("new_script_keys", "{HOME}{ENTER}"), pause=0.05)
    return wait_for_win32_window(
        str(dialog_config["class_name"]), str(dialog_config["title"]), timeout
    )


def choose_checked(dialog: Any, control_id: int, label: str) -> None:
    control = control_by_id(dialog, control_id)
    control.click_input()
    time.sleep(0.15)
    if control.get_check_state() != 1:
        raise RuntimeError(f"XQ did not select {label}")


def verify_created_document(
    config: dict[str, Any], script_type: str, function_return_type: str | None, name: str
) -> str:
    from pywinauto import Desktop

    timeout = float(config.get("connect_timeout_seconds", 15))
    root = Desktop(backend="uia").window(**selector_kwargs(config["window"]))
    root.wait("visible enabled ready", timeout=timeout)
    title = root.wrapper_object().window_text()
    expected_type = config.get("active_type_title_regex", {}).get(script_type)
    if expected_type and not re.search(expected_type, title):
        raise RuntimeError(f"Created XScript type does not match {script_type}: {title}")
    if name not in title:
        raise RuntimeError(f"Created XScript name was not activated: expected {name!r}, got {title!r}")
    if script_type == "function":
        expected_label = config.get("function_return_type_labels", {}).get(function_return_type)
        labels = [
            item.window_text()
            for item in root.wrapper_object().descendants()
            if item.element_info.control_type == "Text"
        ]
        if expected_label not in labels:
            raise RuntimeError(f"Created function return type is not {expected_label}")
    return title


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    parser.add_argument("--function-return-type", choices=sorted(FUNCTION_RETURN_TYPES))
    parser.add_argument("--name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-open-via-xq-menu", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dialog = None
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        if args.script_type == "function" and not args.function_return_type:
            return emit("automation_error", "--function-return-type is required for function scripts")
        if args.script_type != "function" and args.function_return_type:
            return emit("automation_error", "--function-return-type is only valid for function scripts")
        name = " ".join(args.name.split()).strip()
        if not name:
            return emit("automation_error", "--name must not be empty")

        xscript = open_xscript(config, args.force_open_via_xq_menu)
        dialog = open_new_script_dialog(config, xscript)
        dialog_config = config["new_script_dialog"]
        type_id = int(dialog_config["type_control_ids"][args.script_type])
        choose_checked(dialog, type_id, args.script_type)

        if args.script_type == "function":
            return_id = int(dialog_config["function_return_type_control_ids"][args.function_return_type])
            choose_checked(dialog, return_id, args.function_return_type)

        name_control = control_by_id(dialog, int(dialog_config["name_control_id"]))
        name_control.set_edit_text(name)
        if " ".join(name_control.window_text().split()) != name:
            raise RuntimeError("XQ script name verification failed")

        if args.dry_run:
            control_by_id(dialog, int(dialog_config["cancel_control_id"])).click_input()
            dialog = None
            return emit(
                "success",
                "XQ new-script selection verified and cancelled",
                script_type=args.script_type,
                function_return_type=args.function_return_type,
                name=name,
                dry_run=True,
            )

        control_by_id(dialog, int(dialog_config["confirm_control_id"])).click_input()
        dialog = None
        title = verify_created_document(config, args.script_type, args.function_return_type, name)
        return emit(
            "success",
            "XQ script document created",
            script_type=args.script_type,
            function_return_type=args.function_return_type,
            name=name,
            active_title=title,
        )
    except Exception as exc:
        if dialog is not None:
            try:
                dialog_config = config.get("new_script_dialog", {})
                control_by_id(dialog, int(dialog_config.get("cancel_control_id", 30002))).click_input()
            except Exception:
                pass
        return emit("automation_error", f"XQ script preparation failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
