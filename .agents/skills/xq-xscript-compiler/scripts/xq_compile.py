#!/usr/bin/env python3
"""Drive a calibrated XQ XScript compiler and emit one machine-readable result."""

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
    return {"success": 0, "compile_error": 2, "automation_error": 3}[status]


def selector_kwargs(selector: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "title_re", "auto_id", "control_type", "class_name", "found_index"}
    result = {key: value for key, value in selector.items() if key in allowed and value not in (None, "")}
    if not result:
        raise ValueError("A UI selector is empty")
    return result


def wrapper_matches(wrapper: Any, selector: dict[str, Any]) -> bool:
    info = wrapper.element_info
    checks = {
        "title": " ".join(str(info.name or "").split()),
        "auto_id": str(info.automation_id or ""),
        "control_type": str(info.control_type or ""),
        "class_name": str(info.class_name or ""),
    }
    for key, actual in checks.items():
        expected = selector.get(key)
        normalized_expected = " ".join(str(expected).split()) if key == "title" else str(expected)
        if expected not in (None, "") and actual != normalized_expected:
            return False
    title_re = selector.get("title_re")
    if title_re and not re.search(str(title_re), checks["title"]):
        return False
    return True


def find_descendant(root: Any, selector: dict[str, Any]) -> Any:
    candidates = [item for item in root.descendants() if wrapper_matches(item, selector)]
    index = int(selector.get("found_index", 0))
    if index < 0 or index >= len(candidates):
        raise LookupError(f"UI control not found for selector: {selector}")
    return candidates[index]


def find(root: Any, selector: dict[str, Any]) -> Any:
    current = root.wrapper_object() if hasattr(root, "wrapper_object") else root
    for step in selector.get("path", [selector]):
        selector_kwargs(step)
        current = find_descendant(current, step)
    return current


def find_editor(root: Any, selector: dict[str, Any]) -> Any:
    if not selector.get("active_mdi"):
        return find(root, selector)
    root_wrapper = root.wrapper_object() if hasattr(root, "wrapper_object") else root
    root_title = root_wrapper.window_text()
    mdi_candidates = [
        item
        for item in root_wrapper.descendants()
        if wrapper_matches(item, selector["mdi_selector"])
        and item.window_text()
        and f"[{item.window_text()}]" in root_title
    ]
    if len(mdi_candidates) != 1:
        raise LookupError(
            f"Expected one active XScript MDI document, found {len(mdi_candidates)} for title: {root_title}"
        )
    return find_descendant(mdi_candidates[0], selector["content_selector"])


def find_win32_control(window_selector: dict[str, Any], selector: dict[str, Any], visible_only: bool = False) -> Any:
    from pywinauto import Desktop

    win32_window_args = {
        key: value
        for key, value in window_selector.items()
        if key in {"title", "title_re", "class_name", "class_name_re", "found_index"} and value not in (None, "")
    }
    win32_root = Desktop(backend="win32").window(**win32_window_args).wrapper_object()
    candidates = []
    for item in win32_root.descendants():
        if visible_only and not item.is_visible():
            continue
        if selector.get("control_id") not in (None, "") and item.control_id() != int(selector["control_id"]):
            continue
        if selector.get("class_name") and item.class_name() != str(selector["class_name"]):
            continue
        if selector.get("title") and " ".join(item.window_text().split()) != " ".join(str(selector["title"]).split()):
            continue
        if selector.get("title_re") and not re.search(str(selector["title_re"]), " ".join(item.window_text().split())):
            continue
        candidates.append(item)
    index = int(selector.get("found_index", 0))
    if index < 0 or index >= len(candidates):
        raise LookupError(f"Win32 result control not found for selector: {selector}")
    return candidates[index]


def find_result(root: Any, selector: dict[str, Any], window_selector: dict[str, Any]) -> Any:
    if selector.get("backend") != "win32":
        return find(root, selector)
    return find_win32_control(window_selector, selector)


def copy_error_details(window_selector: dict[str, Any], selector: dict[str, Any]) -> str:
    import win32clipboard
    from pywinauto import Desktop

    deadline = time.monotonic() + 5
    report = None
    while time.monotonic() < deadline:
        try:
            report = find_win32_control(window_selector, selector, visible_only=True)
            break
        except LookupError:
            time.sleep(0.2)
    if report is None:
        raise LookupError("Visible XQ error report was not found")

    report.set_focus()
    report.right_click_input(coords=(min(300, max(20, report.rectangle().width() // 3)), 30))
    time.sleep(0.2)
    menu = Desktop(backend="uia").window(control_type="Menu")
    menu.child_window(title=selector.get("select_all_title", "全部選取"), control_type="MenuItem").click_input()
    time.sleep(0.2)
    report.right_click_input(coords=(min(300, max(20, report.rectangle().width() // 3)), 30))
    time.sleep(0.2)
    menu = Desktop(backend="uia").window(control_type="Menu")
    menu.child_window(title=selector.get("copy_title", "複製"), control_type="MenuItem").click_input()
    time.sleep(0.3)

    win32clipboard.OpenClipboard()
    try:
        details = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return str(details).replace("\r\n", "\n").strip()


def run_actions(root: Any, actions: list[dict[str, Any]], keyboard: Any) -> None:
    for item in actions:
        action = item.get("action")
        if action == "click":
            find(root, item["selector"]).click_input()
        elif action == "select":
            find(root, item["selector"]).select(item["value"])
        elif action == "keys":
            keyboard.send_keys(item["keys"], pause=0.05, with_spaces=True)
        elif action == "wait":
            time.sleep(float(item.get("seconds", 1)))
        else:
            raise ValueError(f"Unsupported action: {action!r}")


def replace_editor_text(editor: Any, source: str, keyboard: Any) -> None:
    if str(getattr(editor.element_info, "class_name", "") or "") == "Scintilla":
        from ctypes import create_string_buffer

        import win32gui
        from pywinauto.remote_memory_block import RemoteMemoryBlock

        def set_scintilla_text(value: str) -> None:
            raw = value.encode("cp950") + b"\0"
            buffer = create_string_buffer(raw)
            remote = RemoteMemoryBlock(editor, size=len(raw))
            try:
                remote.Write(buffer, size=len(raw))
                win32gui.SendMessage(editor.handle, 2181, 0, remote.Address())  # SCI_SETTEXT
            finally:
                remote.CleanUp()

        set_scintilla_text(source + "\n ")
        set_scintilla_text(source)
        written = result_text(editor).replace("\r\n", "\n").strip()
        expected = source.replace("\r\n", "\n").strip()
        if written != expected:
            raise RuntimeError("Scintilla source verification failed after SCI_SETTEXT")
        return

    try:
        editor.set_edit_text(source)
    except Exception:
        editor.click_input()
        keyboard.send_keys("^a{BACKSPACE}")
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(source, win32clipboard.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
            keyboard.send_keys("^v")
        except Exception as exc:
            raise RuntimeError(f"Unable to put source in the editor: {exc}") from exc


def result_text(control: Any) -> str:
    class_name = str(getattr(control.element_info, "class_name", "") or "")
    if class_name == "Scintilla":
        from ctypes import create_string_buffer

        import win32gui
        from pywinauto.remote_memory_block import RemoteMemoryBlock

        sci_get_text = 2182
        sci_get_text_length = 2183
        length = int(win32gui.SendMessage(control.handle, sci_get_text_length, 0, 0))
        if length <= 0:
            return ""
        remote = RemoteMemoryBlock(control, size=length + 1)
        try:
            win32gui.SendMessage(control.handle, sci_get_text, length + 1, remote.Address())
            buffer = create_string_buffer(length + 1)
            remote.Read(buffer, size=length + 1)
            raw = buffer.raw[:length]
        finally:
            remote.CleanUp()
        for encoding in ("utf-8", "cp950", "big5", "mbcs"):
            try:
                return raw.decode(encoding).replace("\r\r\n", "\n").replace("\r\n", "\n").strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("cp950", errors="replace").strip()

    texts = [text.strip() for text in control.texts() if text and text.strip()]
    return "\n".join(dict.fromkeys(texts)).strip()


def compiler_signals(
    current: str, before: str, success_regex: str, error_regex: str
) -> tuple[bool, bool]:
    candidate = current
    if before and current.startswith(before):
        candidate = current[len(before) :].lstrip()
    conclusive_lines = [line for line in candidate.splitlines() if "編譯開始" not in line]
    conclusive_text = "\n".join(conclusive_lines)
    success = re.search(success_regex, conclusive_text, re.I | re.M) is not None
    failure = re.search(error_regex, conclusive_text, re.I | re.M) is not None
    return success, failure


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    parser.add_argument("--function-return-type", choices=sorted(FUNCTION_RETURN_TYPES))
    parser.add_argument("--calibration-mode", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        source = args.source.read_text(encoding="utf-8")
    except Exception as exc:
        return emit("automation_error", f"Unable to read input: {exc}")

    if not config.get("calibrated"):
        return emit("automation_error", "XQ UI configuration is not calibrated")
    if args.script_type == "function" and not args.function_return_type:
        return emit("automation_error", "--function-return-type is required for function scripts")
    if args.script_type != "function" and args.function_return_type:
        return emit("automation_error", "--function-return-type is only valid for function scripts")
    verified_types = set(config.get("verified_preopened_types", []))
    if (
        config.get("requires_preopened_script")
        and args.script_type not in verified_types
        and not args.calibration_mode
    ):
        return emit("automation_error", f"Preopened XScript type is not calibrated: {args.script_type}")
    if (
        args.script_type == "function"
        and args.function_return_type not in set(config.get("verified_function_return_types", []))
        and not args.calibration_mode
    ):
        return emit(
            "automation_error",
            f"Function return type is not calibrated: {args.function_return_type}",
        )
    if not source.strip():
        return emit("automation_error", "Source file is empty")

    try:
        from pywinauto import Application, Desktop, keyboard

        executable = config.get("executable")
        if executable:
            app = Application(backend="uia").connect(path=executable, timeout=float(config.get("connect_timeout_seconds", 15)))
            root = app.window(**selector_kwargs(config["window"]))
        else:
            root = Desktop(backend="uia").window(**selector_kwargs(config["window"]))
        root.wait("visible enabled ready", timeout=float(config.get("connect_timeout_seconds", 15)))
        root.set_focus()

        open_keys = config.get("open_compiler_keys")
        if open_keys:
            keyboard.send_keys(open_keys, pause=0.05)
            time.sleep(float(config.get("open_wait_seconds", 1)))

        run_actions(root, config.get("actions_by_type", {}).get(args.script_type, []), keyboard)
        expected_type = config.get("active_type_title_regex", {}).get(args.script_type)
        active_title = root.wrapper_object().window_text()
        if expected_type and not re.search(expected_type, active_title):
            return emit(
                "automation_error",
                f"Active XScript type does not match {args.script_type}: {active_title}",
            )
        if args.script_type == "function":
            return_label = config.get("function_return_type_labels", {}).get(args.function_return_type)
            if not return_label:
                return emit(
                    "automation_error",
                    f"No XQ property label configured for function return type: {args.function_return_type}",
                )
            root_wrapper = root.wrapper_object()
            label_matches = [
                item
                for item in root_wrapper.descendants()
                if wrapper_matches(item, {"title": return_label, "control_type": "Text"})
            ]
            if not label_matches:
                return emit(
                    "automation_error",
                    f"Active XQ function return type does not match {args.function_return_type}: expected {return_label}",
                )
        editor = find_editor(root, config["editor"])
        replace_editor_text(editor, source, keyboard)

        result = find_result(root, config["result"], config["window"])
        before = result_text(result)
        find(root, config["compile_button"]).click_input()

        deadline = time.monotonic() + float(config.get("compile_timeout_seconds", 30))
        latest = ""
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            result = find_result(root, config["result"], config["window"])
            current = result_text(result)
            if current != latest:
                latest = current
                stable_since = time.monotonic()
            success, failure = compiler_signals(
                current, before, config["success_regex"], config["error_regex"]
            )
            conclusive = current and current != before
            if conclusive and (success or failure) and time.monotonic() - stable_since >= 0.5:
                if success:
                    return emit("success", current, compiler_output=current)
                details = ""
                detail_error = ""
                if config.get("error_report"):
                    try:
                        details = copy_error_details(config["window"], config["error_report"])
                    except Exception as exc:
                        detail_error = f"{type(exc).__name__}: {exc}"
                compiler_output = current + (f"\n{details}" if details else "")
                extra = {"compiler_output": compiler_output}
                if detail_error:
                    extra["error_detail_capture_error"] = detail_error
                return emit("compile_error", compiler_output, **extra)
            time.sleep(0.25)

        return emit("automation_error", "Timed out without a conclusive compiler result", compiler_output=latest)
    except Exception as exc:
        return emit("automation_error", f"XQ UI automation failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
