#!/usr/bin/env python3
"""Safely verify a pre-opened XQ screener backtest range.

The screener interface is not a product-list dialog.  Its range can be either
a public system default scope or a private watchlist group.  This dry-run
adapter may set/read only the former.  For the latter it preserves the user's
manual choice, records no group name, and cancels the dialog.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import xq_backtest
from xq_backtest_scope import (
    BacktestScopeError,
    apply_system_default_scope,
    manual_watchlist_group_evidence,
    normalized,
)


EXIT_CODES = {"success": 0, "automation_error": 3, "environment_interruption": 3}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def preopened_screener_settings() -> Any:
    from pywinauto import Desktop

    matches = []
    for window in Desktop(backend="win32").windows():
        try:
            if not window.is_visible() or not window.is_enabled() or window.class_name() != "#32770":
                continue
            control_ids = {item.control_id() for item in window.descendants()}
            if {2092, 2094, 2033, 2034}.issubset(control_ids):
                matches.append(window)
        except Exception:
            continue
    if len(matches) != 1:
        raise LookupError(
            f"Expected one enabled pre-opened screener backtest settings dialog, found {len(matches)}"
        )
    return matches[0]


def open_screener_backtest_settings(
    config: dict[str, Any],
    *,
    foreground_records: list[dict[str, Any]] | None = None,
) -> Any:
    from pywinauto import Desktop

    timeout = float(config.get("connect_timeout_seconds", 15))
    native_xscript = Desktop(backend="win32").window(title_re="^XScript.*")
    native_xscript.wait("visible enabled ready", timeout=timeout)
    root = native_xscript.wrapper_object()
    expected = config.get("active_type_title_regex", {}).get("screener")
    if not isinstance(expected, str) or not expected:
        raise RuntimeError("The XQ configuration has no active-title rule for screener")
    if re.search(expected, root.window_text()) is None:
        raise RuntimeError("The active XScript document is not a screener script")
    if "未編譯" in xq_backtest.normalized(root.window_text()):
        raise RuntimeError("The active screener script is uncompiled")

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
        raise LookupError(
            f"Expected one XScript screener backtest button, found {len(buttons)}"
        )
    guard = xq_backtest.guarded_paced_click(root, buttons[0])
    if foreground_records is not None:
        foreground_records.append(guard)
    return xq_backtest.visible_dialog_with_control(2033, timeout)


def apply_system_scope(
    window: Any,
    market: str,
    system_default_scope: str,
    *,
    foreground_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    market_control = xq_backtest.control_by_id(window, 2092)
    universe_control = xq_backtest.control_by_id(window, 2094)

    def guarded_set_combo(control_id: int, value: str) -> None:
        xq_backtest.set_combo(
            window,
            control_id,
            value,
            foreground_records=foreground_records,
        )

    return apply_system_default_scope(
        market,
        system_default_scope,
        available_markets=lambda: market_control.item_texts(),
        select_market=lambda value: guarded_set_combo(2092, value),
        read_market=lambda: market_control.window_text(),
        available_universes=lambda: universe_control.item_texts(),
        select_universe=lambda value: guarded_set_combo(2094, value),
        read_universe=lambda: universe_control.window_text(),
    )


def preserve_manual_watchlist_group(window: Any) -> dict[str, Any]:
    """Verify only that a non-system range was selected by the user."""

    scope_control = xq_backtest.control_by_id(window, 2094)
    return manual_watchlist_group_evidence(scope_control.window_text())


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--market")
    scope_mode = parser.add_mutually_exclusive_group(required=True)
    scope_mode.add_argument("--system-default-scope")
    scope_mode.add_argument("--manual-watchlist-group-selected", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    input_stop_required = False
    foreground_records: list[dict[str, Any]] = []
    try:
        args = parse_args(argv)
        if not args.dry_run:
            raise ValueError("Screener backtest scope verification currently requires --dry-run")
        if args.system_default_scope is not None and not args.market:
            raise ValueError("--market is required with --system-default-scope")
        if args.manual_watchlist_group_selected and args.market is not None:
            raise ValueError("--market must not be supplied for a manually selected watchlist group")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        recovery = xq_backtest.inspect_recovery_status(args.config, config)
        if recovery["decision"] != "safe_to_start":
            return emit(
                "environment_interruption",
                "A current XQ backtest recovery state blocks screener scope verification",
                recovery=recovery,
            )
        xq_backtest.configure_ui_pacing(config)
        runtime = xq_backtest.capture_runtime_snapshot(config)
        failure_kind = xq_backtest.classify_runtime_interruption(runtime)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ is not in a safe state for screener scope verification",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(runtime),
        )
        settings_window = open_screener_backtest_settings(
            config,
            foreground_records=foreground_records,
        )
        if args.system_default_scope is not None:
            evidence = apply_system_scope(
                settings_window,
                normalized(args.market),
                args.system_default_scope,
                foreground_records=foreground_records,
            )
        else:
            evidence = preserve_manual_watchlist_group(settings_window)
        foreground_records.append(
            xq_backtest.guarded_paced_click(
                settings_window,
                xq_backtest.control_by_id(settings_window, 2034),
            )
        )
        settings_window = None
        return emit(
            "success",
            "XQ screener backtest range verified and cancelled",
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
        return emit("automation_error", f"Screener backtest scope validation failed: {exc}")
    except Exception as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        return emit(
            "automation_error",
            f"XQ screener backtest scope automation failed: {type(exc).__name__}: {exc}",
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
