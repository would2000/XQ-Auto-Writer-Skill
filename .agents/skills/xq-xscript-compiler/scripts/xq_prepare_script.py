#!/usr/bin/env python3
"""Open XScript from XQ and create a new script document of the requested type."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import xq_codex_scope
import xq_ui_pacing


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


def open_xscript(config: dict[str, Any], force_menu: bool, pacing: xq_ui_pacing.UiPacing) -> Any:
    from pywinauto import Desktop, keyboard

    timeout = float(config.get("connect_timeout_seconds", 15))
    xscript_selector = selector_kwargs(config["window"])

    # The XScript top-level window is a native Win32 window.  Looking it up
    # through a full UIA tree can block for minutes even though the visible
    # editor is responsive, so use the narrow native lookup first.
    native_desktop = Desktop(backend="win32")
    existing = native_desktop.window(**xscript_selector)
    if existing.exists(timeout=0.2) and not force_menu:
        existing.wait("visible enabled ready", timeout=timeout)
        return existing.wrapper_object()

    desktop = Desktop(backend="uia")
    launcher = config["launcher"]
    xq = desktop.window(**selector_kwargs(launcher["xq_window"]))
    xq.wait("visible enabled ready", timeout=timeout)
    xq.set_focus()
    menu = xq.child_window(**selector_kwargs(launcher["strategy_menu"]))
    menu.click_input()
    time.sleep(pacing.scale(float(launcher.get("menu_wait_seconds", 0.3)), floor_seconds=0.25))
    keyboard.send_keys(
        launcher.get("open_xscript_keys", "{END}{ENTER}"),
        pause=pacing.keyboard_pause(0.05),
    )

    xscript = desktop.window(**xscript_selector)
    xscript.wait("visible enabled ready", timeout=timeout)
    return xscript


def open_new_script_dialog(
    config: dict[str, Any],
    xscript: Any,
    pacing: xq_ui_pacing.UiPacing,
    action_settle_seconds: float,
) -> Any:
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
    time.sleep(action_settle_seconds)
    keyboard.send_keys(
        dialog_config.get("open_file_menu_keys", "%f"), pause=pacing.keyboard_pause(0.15),
    )
    time.sleep(max(action_settle_seconds, pacing.scale(
        float(dialog_config.get("menu_wait_seconds", 0.3)), floor_seconds=0.25,
    )))
    keyboard.send_keys(
        dialog_config.get("new_script_keys", "{HOME}{ENTER}"), pause=pacing.keyboard_pause(0.15),
    )
    return wait_for_win32_window(
        str(dialog_config["class_name"]), str(dialog_config["title"]), timeout
    )


def choose_checked(
    dialog: Any,
    control_id: int,
    label: str,
    action_settle_seconds: float,
) -> None:
    control = control_by_id(dialog, control_id)
    # XQ 3.19.03 exposes the type choices as native Button controls.  The
    # function choice did not update through a UIA-style click(), while a
    # physical native click_input() did and can be verified by check state.
    control.click_input()
    time.sleep(action_settle_seconds)
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
    parser.add_argument("--folder", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-open-via-xq-menu", action="store_true")
    return parser.parse_args()


def record_wait_incident(
    config_path: Path,
    *,
    script_type: str,
    name: str,
    stage_error: Exception,
) -> Path:
    recovery: dict[str, Any]
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("xq_backtest.py")),
                "--config",
                str(config_path),
                "--recovery-status",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        recovery = json.loads(completed.stdout) if completed.stdout.strip() else {
            "status": "unavailable",
            "error_type": "empty_recovery_output",
        }
    except Exception as exc:
        recovery = {
            "status": "unavailable",
            "error_type": type(exc).__name__,
        }

    occurred_at = datetime.now(timezone.utc)
    runtime = recovery.get("runtime") if isinstance(recovery.get("runtime"), dict) else {}
    incident = {
        "schema_version": 1,
        "occurred_at_utc": occurred_at.isoformat(),
        "case": "xq_prepare_script",
        "document": name,
        "script_type": script_type,
        "stage": "new_script_storage_scope",
        "incident_type": "dialog_timeout",
        "input_stopped_immediately": True,
        "error_type": type(stage_error).__name__,
        "xq_process_id": runtime.get("xq_process_id"),
        "window_health": runtime,
        "checkpoint": recovery.get("checkpoint"),
        "visible_reports": recovery.get("visible_reports", []),
        "recovery_status": recovery,
    }
    output_dir = config_path.resolve().parent / "windows_wait_incidents"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (
        occurred_at.strftime("%Y%m%dT%H%M%SZ")
        + "-prepare-script-storage-timeout.json"
    )
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(incident, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def main() -> int:
    args = parse_args()
    dialog = None
    storage_contract = None
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
        try:
            storage_contract = xq_codex_scope.load_new_script_storage_contract(
                config, args.folder,
            )
        except (xq_codex_scope.CodexScopeError, xq_ui_pacing.UiPacingError) as exc:
            return emit(
                "automation_error",
                str(exc),
                xq_touched=False,
                codex_scope_verified=False,
            )

        xscript = open_xscript(config, args.force_open_via_xq_menu, storage_contract.ui_pacing)
        dialog = open_new_script_dialog(
            config, xscript, storage_contract.ui_pacing, storage_contract.action_settle_seconds,
        )
        dialog_config = config["new_script_dialog"]
        type_id = int(dialog_config["type_control_ids"][args.script_type])
        choose_checked(
            dialog,
            type_id,
            args.script_type,
            storage_contract.action_settle_seconds,
        )

        if args.script_type == "function":
            return_id = int(dialog_config["function_return_type_control_ids"][args.function_return_type])
            choose_checked(
                dialog,
                return_id,
                args.function_return_type,
                storage_contract.action_settle_seconds,
            )

        scope_evidence = xq_codex_scope.ensure_new_script_codex_storage(
            dialog,
            storage_contract,
            create_missing=not args.dry_run,
        )

        if args.dry_run:
            control_by_id(dialog, int(dialog_config["cancel_control_id"])).click()
            time.sleep(storage_contract.action_settle_seconds)
            dialog = None
            if scope_evidence["would_create_folder"]:
                return emit(
                    "success",
                    "CODEX folder is missing; dry run cancelled without creating it",
                    script_type=args.script_type,
                    function_return_type=args.function_return_type,
                    name=name,
                    codex_scope=scope_evidence,
                    dry_run=True,
                )
            return emit(
                "success",
                "XQ new-script selection verified and cancelled",
                script_type=args.script_type,
                function_return_type=args.function_return_type,
                name=name,
                codex_scope=scope_evidence,
                dry_run=True,
            )

        name_control = control_by_id(dialog, int(dialog_config["name_control_id"]))
        name_control.set_edit_text(name)
        time.sleep(storage_contract.action_settle_seconds)
        if " ".join(name_control.window_text().split()) != name:
            raise RuntimeError("XQ script name verification failed")

        control_by_id(dialog, int(dialog_config["confirm_control_id"])).click()
        time.sleep(storage_contract.action_settle_seconds)
        dialog = None
        title = verify_created_document(config, args.script_type, args.function_return_type, name)
        return emit(
            "success",
            "XQ script document created",
            script_type=args.script_type,
            function_return_type=args.function_return_type,
            name=name,
            active_title=title,
            codex_scope=scope_evidence,
        )
    except xq_codex_scope.CodexScopeWaitError as exc:
        incident_path = record_wait_incident(
            args.config,
            script_type=args.script_type,
            name=" ".join(args.name.split()).strip(),
            stage_error=exc,
        )
        return emit(
            "automation_error",
            f"XQ script preparation stopped after a dialog timeout: {exc}",
            input_stopped=True,
            windows_wait_incident=str(incident_path),
        )
    except Exception as exc:
        if dialog is not None:
            try:
                if storage_contract is not None:
                    xq_codex_scope.cancel_new_script_storage_dialogs(
                        dialog,
                        storage_contract,
                    )
                dialog_config = config.get("new_script_dialog", {})
                control_by_id(dialog, int(dialog_config.get("cancel_control_id", 30002))).click()
            except Exception:
                pass
        return emit("automation_error", f"XQ script preparation failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
