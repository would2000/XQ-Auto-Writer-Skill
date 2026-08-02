#!/usr/bin/env python3
"""Prepare, compile, create, run, and capture one XQ screener strategy."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
EXIT_CODES = {
    "success": 0,
    "compile_error": 2,
    "failure": 2,
    "partial_failure": 2,
    "cancelled": 2,
    "automation_error": 3,
}
SAFE_SCRIPT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")
INVALID_STRATEGY_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def run_json_tool(script_name: str, arguments: list[str], timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script_name), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{script_name} did not emit exactly one valid JSON object: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise RuntimeError(f"{script_name} returned an invalid result object")
    return {
        "script": script_name,
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": completed.stderr.strip(),
    }


class StageError(RuntimeError):
    def __init__(self, status: str, stage: str, result: dict[str, Any]):
        super().__init__(f"{stage} failed")
        self.status = status
        self.stage = stage
        self.result = result


def require_success(result: dict[str, Any], stage: str) -> dict[str, Any]:
    payload = result["payload"]
    if result["returncode"] == 0 and payload.get("status") == "success":
        return payload
    child_status = payload.get("status")
    if child_status == "compile_error":
        status = "compile_error"
    elif child_status in {"failure", "partial_failure", "cancelled"}:
        status = child_status
    else:
        status = "automation_error"
    raise StageError(status, stage, result)


def validate_inputs(args: argparse.Namespace) -> dict[str, Any]:
    if not args.config.is_file():
        raise ValueError(f"Configuration file does not exist: {args.config}")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read configuration: {exc}") from exc
    if not config.get("calibrated"):
        raise ValueError("XQ UI configuration is not calibrated")
    if not args.source.is_file():
        raise ValueError(f"Source file does not exist: {args.source}")
    if not args.source.read_text(encoding="utf-8").strip():
        raise ValueError("Source file is empty")
    if not SAFE_SCRIPT_NAME.fullmatch(args.script_name):
        raise ValueError(
            "script-name must be a 1-50 character ASCII XScript identifier"
        )
    args.strategy_name = args.strategy_name.strip()
    if not args.strategy_name or len(args.strategy_name) > 40:
        raise ValueError("strategy-name must contain 1-40 characters")
    if INVALID_STRATEGY_NAME.search(args.strategy_name):
        raise ValueError("strategy-name contains a character XQ cannot safely use")
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    if args.stop_recovery_seconds <= 0:
        raise ValueError("stop-recovery-seconds must be positive")
    if args.max_rows < 0 or args.max_error_rows < 0:
        raise ValueError("row limits must be non-negative")
    if args.native_export is not None and args.native_export.exists():
        raise ValueError(f"Refusing to overwrite existing export: {args.native_export}")
    if args.native_error_export is not None and args.native_error_export.exists():
        raise ValueError(
            f"Refusing to overwrite existing error export: {args.native_error_export}"
        )
    return config


def xscript_windows() -> list[dict[str, Any]]:
    from pywinauto import Desktop

    windows = []
    for window in Desktop(backend="win32").windows():
        title = " ".join(window.window_text().split())
        if window.is_visible() and title.startswith("XScript"):
            windows.append({"handle": int(window.handle), "title": title})
    return windows


def close_pipeline_editor(existing_handles: set[int], script_name: str) -> dict[str, Any]:
    from pywinauto import Desktop
    import win32gui

    matches = []
    for window in Desktop(backend="win32").windows():
        title = " ".join(window.window_text().split())
        if (
            window.is_visible()
            and int(window.handle) not in existing_handles
            and title.startswith("XScript")
            and re.search(rf"\[{re.escape(script_name)}(?:\]|\()", title) is not None
        ):
            matches.append(window)
    if len(matches) != 1:
        return {
            "attempted": False,
            "closed": False,
            "reason": "no_unique_new_matching_editor",
            "matching_count": len(matches),
        }
    window = matches[0]
    handle = int(window.handle)
    title = " ".join(window.window_text().split())
    window.close()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        still_exists = bool(win32gui.IsWindow(handle))
        still_visible = still_exists and bool(win32gui.IsWindowVisible(handle))
        if not still_visible:
            return {
                "attempted": True,
                "closed": True,
                "handle": handle,
                "title": title,
                "disposition": "destroyed" if not still_exists else "hidden",
            }
        time.sleep(0.1)
    return {
        "attempted": True,
        "closed": False,
        "handle": handle,
        "title": title,
        "reason": "editor_did_not_close",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the complete XQ screener source-to-results workflow"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--strategy-name", required=True)
    parser.add_argument(
        "--universe",
        default="台灣五十成分股(系統)",
        help="Public Taiwan system universe accepted by xq_screener.py",
    )
    parser.add_argument(
        "--direction", choices=("unspecified", "long", "short"), default="unspecified"
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--stop-recovery-seconds", type=float, default=10.0)
    parser.add_argument("--native-export", type=Path)
    parser.add_argument("--native-error-export", type=Path)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--max-error-rows", type=int, default=500)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    existing_handles: set[int] = set()
    compile_succeeded = False
    completed_stages: dict[str, Any] = {}
    current_stage = "validation"
    xq_touched = False
    cleanup: dict[str, Any] = {"attempted": False, "closed": False, "reason": "not_created"}
    final_status = "automation_error"
    final_message = "XQ screener pipeline did not start"
    final_extra: dict[str, Any] = {"failed_stage": "validation", "xq_touched": False}
    try:
        validate_inputs(args)
        current_stage = "capture_baseline"
        baseline = xscript_windows()
        existing_handles = {item["handle"] for item in baseline}

        current_stage = "prepare_script"
        xq_touched = True
        prepare_arguments = [
            "--config", str(args.config),
            "--script-type", "screener",
            "--name", args.script_name,
            "--folder", "CODEX",
        ]
        preflight_result = run_json_tool(
            "xq_prepare_script.py",
            [*prepare_arguments, "--dry-run"],
            45,
        )
        completed_stages["preflight"] = require_success(preflight_result, "preflight_script")
        prepare_result = run_json_tool("xq_prepare_script.py", prepare_arguments, 45)
        prepare = require_success(prepare_result, "prepare_script")
        completed_stages["prepare"] = prepare

        current_stage = "compile_script"
        compile_result = run_json_tool(
            "xq_compile.py",
            [
                "--config", str(args.config),
                "--source", str(args.source),
                "--script-type", "screener",
                "--script-name", args.script_name,
            ],
            60,
        )
        compiled = require_success(compile_result, "compile_script")
        compile_succeeded = True
        completed_stages["compile"] = compiled

        current_stage = "create_run_capture"
        screener_arguments = [
            "--config", str(args.config),
            "--strategy-name", args.strategy_name,
            "--create-strategy",
            "--script-name", args.script_name,
            "--universe", args.universe,
            "--direction", args.direction,
            "--timeout-seconds", str(args.timeout_seconds),
            "--stop-recovery-seconds", str(args.stop_recovery_seconds),
            "--max-rows", str(args.max_rows),
            "--max-error-rows", str(args.max_error_rows),
        ]
        if args.native_export is not None:
            screener_arguments.extend(["--native-export", str(args.native_export)])
        if args.native_error_export is not None:
            screener_arguments.extend(
                ["--native-error-export", str(args.native_error_export)]
            )
        screener_result = run_json_tool(
            "xq_screener.py", screener_arguments, args.timeout_seconds + 45
        )
        screener_attempts = 1
        first_screener_payload = screener_result["payload"]
        if (
            screener_result["returncode"] != 0
            and first_screener_payload.get("status") == "automation_error"
            and first_screener_payload.get("strategy_created") is False
            and "search control 17053 did not clear" in str(first_screener_payload.get("message"))
        ):
            screener_result = run_json_tool(
                "xq_screener.py", screener_arguments, args.timeout_seconds + 45
            )
            screener_attempts = 2
        captured = require_success(screener_result, "create_run_capture")

        final_status = "success"
        final_message = "XQ screener source-to-results pipeline completed"
        final_extra = {
            "completed_stage": "create_run_capture",
            "xq_touched": True,
            "script_name": args.script_name,
            "strategy_name": args.strategy_name,
            "prepare": prepare,
            "compile": compiled,
            "screener": captured,
            "screener_attempts": screener_attempts,
            "matched_count": captured.get("matched_count"),
            "returned_count": captured.get("returned_count"),
            "rows": captured.get("rows", []),
        }
    except StageError as exc:
        final_status = exc.status
        final_message = f"XQ screener pipeline stage failed: {exc.stage}"
        final_extra = {
            "failed_stage": exc.stage,
            "xq_touched": True,
            "script_name": args.script_name,
            "strategy_name": args.strategy_name,
            "stage_result": exc.result["payload"],
            "completed_stages": completed_stages,
            "child_returncode": exc.result["returncode"],
            "child_stderr": exc.result["stderr"],
        }
    except Exception as exc:
        final_status = "automation_error"
        final_message = f"XQ screener pipeline failed: {type(exc).__name__}: {exc}"
        final_extra = {
            "failed_stage": current_stage,
            "xq_touched": xq_touched,
            "script_name": args.script_name,
            "strategy_name": args.strategy_name,
            "completed_stages": completed_stages,
        }
    finally:
        if compile_succeeded:
            try:
                cleanup = close_pipeline_editor(existing_handles, args.script_name)
            except Exception as exc:
                cleanup = {
                    "attempted": True,
                    "closed": False,
                    "reason": f"cleanup_failed: {type(exc).__name__}: {exc}",
                }
        final_extra["editor_cleanup"] = cleanup
    return emit(final_status, final_message, **final_extra)


if __name__ == "__main__":
    sys.exit(main())
