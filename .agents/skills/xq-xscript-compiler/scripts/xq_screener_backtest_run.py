#!/usr/bin/env python3
"""Run one explicitly confirmed XQ screener backtest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import xq_alert_backtest_run
import xq_backtest
import xq_backtest_monitor
import xq_screener_backtest
from xq_backtest_scope import normalized


EXIT_CODES = {
    "success": 0,
    "failure": 2,
    "partial_failure": 2,
    "indeterminate_timeout": 3,
    "environment_interruption": 3,
    "automation_error": 3,
}
PRICE_IDS = {"next_open": (2063, 2064), "current_close": (2064, 2063)}
EXIT_PRICE_IDS = {"next_open": (2065, 2066), "current_close": (2066, 2065)}
UNIT_LABELS = {"percent": "％", "points": "點"}


@dataclass(frozen=True)
class ScreenerBacktestSettings:
    market: str
    system_default_scope: str
    direction: str
    frequency: str
    start_date: date
    end_date: date
    entry_price: str
    exit_price: str
    take_profit_enabled: bool
    take_profit: str | None
    take_profit_unit: str | None
    stop_loss_enabled: bool
    stop_loss: str | None
    stop_loss_unit: str | None
    max_holding_enabled: bool
    max_holding_periods: int | None
    stock_fee_percent: str
    print_enabled: bool


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--system-default-scope", required=True)
    parser.add_argument("--direction", choices=("long", "short"), required=True)
    parser.add_argument("--frequency", choices=("day",), required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--entry-price", choices=tuple(PRICE_IDS), required=True)
    parser.add_argument("--exit-price", choices=tuple(EXIT_PRICE_IDS), required=True)
    parser.add_argument(
        "--take-profit-enabled", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--take-profit")
    parser.add_argument("--take-profit-unit", choices=tuple(UNIT_LABELS))
    parser.add_argument(
        "--stop-loss-enabled", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--stop-loss")
    parser.add_argument("--stop-loss-unit", choices=tuple(UNIT_LABELS))
    parser.add_argument(
        "--max-holding-enabled", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--max-holding-periods", type=int)
    parser.add_argument("--stock-fee-percent", required=True)
    parser.add_argument(
        "--print-enabled", action=argparse.BooleanOptionalAction, default=None
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _optional_rule(
    enabled: bool | None,
    value: str | None,
    unit: str | None,
    label: str,
) -> tuple[bool, str | None, str | None]:
    if enabled is None:
        raise ValueError(f"An explicit boolean choice is required: --{label}-enabled")
    if enabled:
        if value is None or unit is None:
            raise ValueError(
                f"--{label} and --{label}-unit are required when enabled"
            )
        value = xq_backtest.decimal_text(value, f"--{label}")
        if float(value) <= 0:
            raise ValueError(f"--{label} must be positive when enabled")
    elif value is not None or unit is not None:
        raise ValueError(f"Disabled --{label} must not include a value or unit")
    return bool(enabled), value, unit


def settings_from_args(args: argparse.Namespace) -> ScreenerBacktestSettings:
    if not args.dry_run and not args.confirm_historical_backtest:
        raise ValueError("Starting a screener backtest requires --confirm-historical-backtest")
    if not args.system_default_scope.endswith("(系統)"):
        raise ValueError("--system-default-scope must name a public (系統) range")
    take_profit_enabled, take_profit, take_profit_unit = _optional_rule(
        args.take_profit_enabled, args.take_profit, args.take_profit_unit, "take-profit"
    )
    stop_loss_enabled, stop_loss, stop_loss_unit = _optional_rule(
        args.stop_loss_enabled, args.stop_loss, args.stop_loss_unit, "stop-loss"
    )
    if args.max_holding_enabled is None:
        raise ValueError("An explicit boolean choice is required: --max-holding-enabled")
    if args.max_holding_enabled:
        if args.max_holding_periods is None or args.max_holding_periods <= 0:
            raise ValueError("--max-holding-periods must be positive when enabled")
    elif args.max_holding_periods is not None:
        raise ValueError("Disabled max holding must not include a period")
    if args.print_enabled is None:
        raise ValueError("An explicit boolean choice is required: --print-enabled")
    start_date = xq_backtest.parse_iso_date(args.start_date)
    end_date = xq_backtest.parse_iso_date(args.end_date)
    if start_date > end_date:
        raise ValueError("--start-date must not be later than --end-date")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    return ScreenerBacktestSettings(
        market=normalized(args.market),
        system_default_scope=normalized(args.system_default_scope),
        direction=args.direction,
        frequency=args.frequency,
        start_date=start_date,
        end_date=end_date,
        entry_price=args.entry_price,
        exit_price=args.exit_price,
        take_profit_enabled=take_profit_enabled,
        take_profit=take_profit,
        take_profit_unit=take_profit_unit,
        stop_loss_enabled=stop_loss_enabled,
        stop_loss=stop_loss,
        stop_loss_unit=stop_loss_unit,
        max_holding_enabled=bool(args.max_holding_enabled),
        max_holding_periods=args.max_holding_periods,
        stock_fee_percent=xq_backtest.decimal_text(
            args.stock_fee_percent, "--stock-fee-percent"
        ),
        print_enabled=bool(args.print_enabled),
    )


def validate_compiled_screener_title(title: str, expected_name: str) -> str:
    title = normalized(title)
    if f"{expected_name}(選股)" not in title:
        raise RuntimeError(f"The active XScript title does not match: {title}")
    if "未編譯" in title:
        raise RuntimeError("The active screener script is uncompiled")
    return title


def verify_active_screener_script(expected_name: str) -> dict[str, Any]:
    from pywinauto import Desktop
    from xq_function_boundary_runner import (
        _read_active_document,
        _verify_formula_property_readback,
    )

    xscript = Desktop(backend="win32").window(
        title_re="^XScript.*"
    ).wrapper_object()
    title = validate_compiled_screener_title(
        xscript.window_text(), expected_name
    )
    name, script_type = _read_active_document(xscript, expected_name, "screener")
    if not _verify_formula_property_readback(
        int(xscript.handle), expected_name, "screener"
    ):
        raise RuntimeError(
            "The active screener name, type, or 自訂/CODEX/ location did not match"
        )
    return {
        "script_name": name,
        "script_type": script_type,
        "location": "自訂/CODEX/",
        "active_title": title,
        "uncompiled_marker_present": False,
        "read_only": True,
    }


def _read_date(window: Any, control_id: int) -> str:
    value = xq_backtest.control_by_id(window, control_id).get_time()
    return f"{value.wYear:04d}-{value.wMonth:02d}-{value.wDay:02d}"


def _read_unit(window: Any, control_id: int) -> str:
    actual = normalized(xq_backtest.control_by_id(window, control_id).window_text())
    for key, label in UNIT_LABELS.items():
        if actual == normalized(label):
            return key
    raise RuntimeError(f"Unsupported unit read back from control {control_id}: {actual}")


def apply_settings(
    window: Any,
    settings: ScreenerBacktestSettings,
) -> dict[str, Any]:
    guards: list[dict[str, Any]] = []
    scope = xq_screener_backtest.apply_system_scope(
        window,
        settings.market,
        settings.system_default_scope,
        foreground_records=guards,
    )
    direction = xq_alert_backtest_run.set_alert_direction(
        window, settings.direction, guards
    )
    xq_backtest.set_combo(window, 2091, "日", foreground_records=guards)
    xq_backtest.set_date(window, 2200, settings.start_date, foreground_records=guards)
    xq_backtest.set_date(window, 2201, settings.end_date, foreground_records=guards)
    xq_backtest.set_radio(window, *PRICE_IDS[settings.entry_price], foreground_records=guards)
    xq_backtest.set_radio(window, *EXIT_PRICE_IDS[settings.exit_price], foreground_records=guards)

    for enabled, checkbox, edit, unit_control, value, unit in (
        (
            settings.take_profit_enabled,
            2122,
            2003,
            2093,
            settings.take_profit,
            settings.take_profit_unit,
        ),
        (
            settings.stop_loss_enabled,
            2123,
            2004,
            2095,
            settings.stop_loss,
            settings.stop_loss_unit,
        ),
    ):
        xq_backtest.set_checked(window, checkbox, enabled, foreground_records=guards)
        if enabled:
            xq_backtest.set_edit(window, edit, value or "", foreground_records=guards)
            xq_backtest.set_combo(
                window, unit_control, UNIT_LABELS[unit or "percent"], foreground_records=guards
            )
    xq_backtest.set_checked(
        window, 2124, settings.max_holding_enabled, foreground_records=guards
    )
    if settings.max_holding_enabled:
        xq_backtest.set_edit(
            window, 2005, settings.max_holding_periods or 0, foreground_records=guards
        )
    xq_backtest.set_edit(
        window, 2014, settings.stock_fee_percent, foreground_records=guards
    )
    xq_backtest.set_checked(
        window, 2131, settings.print_enabled, foreground_records=guards
    )

    return {
        "scope_selection": scope,
        "direction": settings.direction,
        "direction_readback": direction,
        "frequency": "day",
        "start_date": _read_date(window, 2200),
        "end_date": _read_date(window, 2201),
        "entry_price": settings.entry_price,
        "exit_price": settings.exit_price,
        "take_profit_enabled": bool(xq_backtest.control_by_id(window, 2122).get_check_state()),
        "take_profit": normalized(xq_backtest.control_by_id(window, 2003).window_text()) if settings.take_profit_enabled else None,
        "take_profit_unit": _read_unit(window, 2093) if settings.take_profit_enabled else None,
        "stop_loss_enabled": bool(xq_backtest.control_by_id(window, 2123).get_check_state()),
        "stop_loss": normalized(xq_backtest.control_by_id(window, 2004).window_text()) if settings.stop_loss_enabled else None,
        "stop_loss_unit": _read_unit(window, 2095) if settings.stop_loss_enabled else None,
        "max_holding_enabled": bool(xq_backtest.control_by_id(window, 2124).get_check_state()),
        "max_holding_periods": int(normalized(xq_backtest.control_by_id(window, 2005).window_text())) if settings.max_holding_enabled else None,
        "stock_fee_percent": normalized(xq_backtest.control_by_id(window, 2014).window_text()),
        "print_enabled": bool(xq_backtest.control_by_id(window, 2131).get_check_state()),
        "foreground_guard": xq_backtest.summarize_foreground_guards(guards),
    }


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    checkpoint = None
    checkpoint_file = None
    config: dict[str, Any] | None = None
    args: argparse.Namespace | None = None
    input_stop_required = False
    phase = "argument_validation"
    try:
        args = parse_args(argv)
        settings = settings_from_args(args)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        recovery = xq_backtest.inspect_recovery_status(args.config, config)
        if recovery["decision"] != "safe_to_start":
            return emit(
                "environment_interruption",
                "A current XQ recovery state blocks this screener backtest",
                recovery=recovery,
            )
        xq_backtest.configure_ui_pacing(config)
        checkpoint_file = xq_backtest.recovery_path(args.config)
        snapshot = xq_backtest.capture_runtime_snapshot(config)
        tracked_pid = snapshot.expected_xq_process_id
        failure_kind = xq_backtest.classify_runtime_interruption(snapshot)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ is not healthy enough to start a screener backtest",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(snapshot),
            )
        active_script = verify_active_screener_script(args.script_name)
        phase = "settings_open"
        open_guards: list[dict[str, Any]] = []
        settings_window = xq_screener_backtest.open_screener_backtest_settings(
            config, foreground_records=open_guards
        )
        phase = "settings_apply"
        evidence_settings = apply_settings(settings_window, settings)
        evidence_settings["open_foreground_guard"] = (
            xq_backtest.summarize_foreground_guards(open_guards)
        )
        evidence_settings["active_script"] = active_script
        if args.dry_run:
            xq_backtest.guarded_paced_click(
                settings_window, xq_backtest.control_by_id(settings_window, 2034)
            )
            settings_window = None
            return emit(
                "success",
                "XQ screener settings were verified and cancelled",
                dry_run=True,
                settings_evidence=evidence_settings,
            )

        progress_before = xq_backtest.progress_windows(include_hidden=True)
        if any(progress.is_visible() for progress in progress_before):
            raise RuntimeError("A visible XQ backtest job already exists")
        baseline_progress = {int(progress.handle) for progress in progress_before}
        baseline_reports = xq_backtest.visible_report_handles()
        start_snapshot = xq_backtest.capture_runtime_snapshot(config, tracked_pid)
        start_failure = xq_backtest.classify_runtime_interruption(start_snapshot)
        if start_failure is not None:
            raise RuntimeError(f"XQ changed state before Start: {start_failure}")
        checkpoint = xq_backtest.create_checkpoint(start_snapshot, baseline_reports)
        xq_backtest.write_checkpoint(checkpoint_file, checkpoint)

        def checkpoint_callback(
            stage: str, progress_handle: int | None, cancellation_confirmed: bool
        ) -> None:
            nonlocal checkpoint
            if checkpoint is None or checkpoint_file is None:
                raise RuntimeError("Recovery checkpoint was not initialized")
            checkpoint = xq_backtest.update_checkpoint(
                checkpoint,
                stage=stage,
                progress_window_handle=progress_handle,
                cancellation_confirmed=cancellation_confirmed,
            )
            xq_backtest.write_checkpoint(checkpoint_file, checkpoint)

        phase = "backtest_running"
        active_settings = settings_window
        settings_window = None
        status, evidence = xq_backtest_monitor.run_report_monitor(
            active_settings,
            args.timeout_seconds,
            args.script_name,
            runtime_probe=lambda: xq_backtest.capture_runtime_snapshot(config, tracked_pid),
            checkpoint_callback=checkpoint_callback,
            baseline_report_handles=baseline_reports,
            baseline_progress_handles=baseline_progress,
        )
        evidence["settings_evidence"] = evidence_settings
        if status in {"success", "failure", "partial_failure"}:
            xq_backtest.remove_checkpoint(checkpoint_file)
            checkpoint = None
            evidence["recovery_checkpoint_retained"] = False
            report_handle = evidence.get("report_window_handle")
            if not isinstance(report_handle, int) or report_handle <= 0:
                raise RuntimeError("Completed result has no exact report handle")
            evidence["report_cleanup"] = xq_alert_backtest_run.close_new_report(
                report_handle
            )
            evidence["report_cleanup_complete"] = True
        else:
            evidence["recovery_checkpoint_retained"] = True
            evidence["recovery_run_id"] = checkpoint.run_id
            if status in {"indeterminate_timeout", "environment_interruption"}:
                try:
                    evidence["incident_path"] = str(
                        xq_alert_backtest_run.save_wait_incident(
                            args.config,
                            config,
                            "screener_backtest_timeout"
                            if status == "indeterminate_timeout"
                            else "screener_backtest_environment_interruption",
                            TimeoutError(
                                "Screener backtest monitoring stopped without conclusive evidence"
                            ),
                            checkpoint,
                            task="screener_backtest_smoke",
                            file_prefix="screener-backtest",
                        )
                    )
                except Exception as incident_exc:
                    evidence["incident_capture_error"] = (
                        f"{type(incident_exc).__name__}: {incident_exc}"
                    )
        messages = {
            "success": "XQ screener backtest report contains successful products only",
            "failure": "XQ screener backtest report contains failed products only",
            "partial_failure": "XQ screener backtest report contains successful and failed products",
            "indeterminate_timeout": "Screener backtest did not produce conclusive evidence before timeout",
            "environment_interruption": "XQ changed state while the screener backtest was running",
        }
        return emit(status, messages[status], **evidence)
    except Exception as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        if settings_window is not None and not input_stop_required:
            try:
                xq_backtest.guarded_paced_click(
                    settings_window, xq_backtest.control_by_id(settings_window, 2034)
                )
            except Exception:
                pass
        if checkpoint is not None and checkpoint_file is not None:
            try:
                checkpoint = xq_backtest.update_checkpoint(checkpoint, stage="interrupted")
                xq_backtest.write_checkpoint(checkpoint_file, checkpoint)
            except Exception:
                pass
        return emit(
            "automation_error",
            f"XQ screener backtest automation failed: {type(exc).__name__}: {exc}",
            phase=phase,
            input_stopped=input_stop_required,
            recovery_checkpoint_retained=checkpoint is not None,
            recovery_run_id=checkpoint.run_id if checkpoint is not None else None,
        )


if __name__ == "__main__":
    sys.exit(main())
