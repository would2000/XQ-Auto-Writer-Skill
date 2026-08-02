#!/usr/bin/env python3
"""Safely verify transient product scope in an XQ alert backtest window.

This first alert adapter is deliberately dry-run only.  It proves the same
product-replacement contract as autotrade, then cancels the settings window;
it neither starts a Strategy Radar job nor enables any account/order feature.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import xq_backtest
from xq_backtest_scope import BacktestScopeError, validate_explicit_products


EXIT_CODES = {"success": 0, "automation_error": 3, "environment_interruption": 3}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def open_alert_backtest_settings(
    config: dict[str, Any],
    *,
    foreground_records: list[dict[str, Any]] | None = None,
) -> Any:
    from pywinauto import Desktop

    timeout = float(config.get("connect_timeout_seconds", 15))
    native_xscript = Desktop(backend="win32").window(title_re="^XScript.*")
    native_xscript.wait("visible enabled ready", timeout=timeout)
    root = native_xscript.wrapper_object()
    expected = config.get("active_type_title_regex", {}).get("alert")
    if not isinstance(expected, str) or not expected:
        raise RuntimeError("The XQ configuration has no active-title rule for alert")
    if re.search(expected, root.window_text()) is None:
        raise RuntimeError("The active XScript document is not an alert script")

    # Enumerating the complete XScript UIA tree can take minutes even though the
    # local window is healthy.  The backtest command lives on the one native
    # XTP toolbar named "工具列", so scope UIA to that small subtree only.
    toolbars = [
        item
        for item in root.descendants()
        if item.class_name() == "XTPToolBar"
        and xq_backtest.normalized(item.window_text()) == "工具列"
        and item.is_visible()
    ]
    if len(toolbars) != 1:
        raise LookupError(
            f"Expected one visible XScript tool bar, found {len(toolbars)}"
        )
    toolbar = Desktop(backend="uia").window(
        handle=int(toolbars[0].handle)
    ).wrapper_object()
    buttons = [
        item
        for item in toolbar.descendants(control_type="Button")
        if item.element_info.control_type == "Button"
        and xq_backtest.normalized(item.element_info.name) == "回測"
    ]
    if len(buttons) != 1:
        raise LookupError(f"Expected one XScript alert backtest button, found {len(buttons)}")
    guard = xq_backtest.guarded_paced_click(root, buttons[0])
    if foreground_records is not None:
        foreground_records.append(guard)
    return xq_backtest.visible_dialog_with_control(2033, timeout)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--product", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    input_stop_required = False
    foreground_records: list[dict[str, Any]] = []
    try:
        args = parse_args(argv)
        if not args.dry_run:
            raise ValueError("Alert backtest scope verification currently requires --dry-run")
        products = validate_explicit_products(args.product)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        recovery = xq_backtest.inspect_recovery_status(args.config, config)
        if recovery["decision"] != "safe_to_start":
            return emit(
                "environment_interruption",
                "A current XQ backtest recovery state blocks alert scope verification",
                recovery=recovery,
            )
        xq_backtest.configure_ui_pacing(config)
        runtime = xq_backtest.capture_runtime_snapshot(config)
        failure_kind = xq_backtest.classify_runtime_interruption(runtime)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ is not in a safe state for alert scope verification",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(runtime),
            )
        settings_window = open_alert_backtest_settings(
            config,
            foreground_records=foreground_records,
        )
        evidence = xq_backtest.choose_products(
            settings_window,
            products,
            float(config.get("connect_timeout_seconds", 15)),
        )
        foreground_records.append(
            xq_backtest.guarded_paced_click(
                settings_window,
                xq_backtest.control_by_id(settings_window, 2034),
            )
        )
        settings_window = None
        return emit(
            "success",
            "XQ alert backtest product scope verified and cancelled",
            dry_run=True,
            settings_evidence={
                "scope_selection": evidence,
                "foreground_guard": xq_backtest.summarize_foreground_guards(
                    foreground_records
                ),
            },
        )
    except (BacktestScopeError, ValueError, OSError, json.JSONDecodeError) as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        return emit("automation_error", f"Alert backtest scope validation failed: {exc}")
    except Exception as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        return emit(
            "automation_error",
            f"XQ alert backtest scope automation failed: {type(exc).__name__}: {exc}",
        )
    finally:
        if settings_window is not None and not input_stop_required:
            try:
                xq_backtest.guarded_paced_click(
                    settings_window,
                    xq_backtest.control_by_id(settings_window, 2034),
                )
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
