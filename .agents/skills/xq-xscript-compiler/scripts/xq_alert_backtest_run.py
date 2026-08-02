#!/usr/bin/env python3
"""Run one explicitly confirmed XQ alert backtest and clean its new report."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

import xq_alert_backtest
import xq_backtest
import xq_backtest_monitor
from xq_backtest_scope import validate_explicit_products


EXIT_CODES = {
    "success": 0,
    "failure": 2,
    "partial_failure": 2,
    "indeterminate_timeout": 3,
    "environment_interruption": 3,
    "automation_error": 3,
}
PRICE_BASIS_IDS = {"original": (2069, 2070), "adjusted": (2070, 2069)}
DIRECTION_IDS = {"long": (2061, 2062), "short": (2062, 2061)}
PRICE_IDS = {"next_open": (2063, 2064), "current_close": (2064, 2063)}
EXIT_PRICE_IDS = {"next_open": (2065, 2066), "current_close": (2066, 2065)}
UNIT_LABELS = {"percent": "％", "points": "點"}
PROGRESS_ERROR_CODE_RE = re.compile(r"(?:異常|錯誤)\((\d+)\)")
ALERT_MONITOR_POLL_SECONDS = 0.25
ALERT_LATE_REPORT_MIN_GRACE_SECONDS = 30.0
ALERT_LATE_REPORT_MAX_GRACE_SECONDS = 120.0
BM_CLICK = 0x00F5


@dataclass(frozen=True)
class AlertBacktestSettings:
    products: tuple[str, ...]
    product_kind: str
    direction: str
    frequency: str
    start_date: date
    end_date: date
    price_basis: str
    entry_price: str
    exit_price: str
    simulate_entry_ticks: bool
    simulate_exit_ticks: bool
    max_concurrent_entries: int
    take_profit: str
    take_profit_unit: str
    stop_loss: str
    stop_loss_unit: str
    max_holding_periods: int
    stock_fee_percent: str | None
    futures_fee: str | None
    futures_margin_percent: str | None
    print_enabled: bool


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--product", action="append", required=True)
    parser.add_argument("--product-kind", choices=("stock", "futures"), required=True)
    parser.add_argument("--direction", choices=tuple(DIRECTION_IDS), required=True)
    parser.add_argument("--frequency", choices=xq_backtest.FREQUENCIES, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--price-basis", choices=tuple(PRICE_BASIS_IDS), required=True)
    parser.add_argument("--entry-price", choices=tuple(PRICE_IDS), required=True)
    parser.add_argument("--exit-price", choices=tuple(EXIT_PRICE_IDS), required=True)
    parser.add_argument(
        "--simulate-entry-ticks",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument(
        "--simulate-exit-ticks",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--max-concurrent-entries", type=int, required=True)
    parser.add_argument("--take-profit", required=True)
    parser.add_argument("--take-profit-unit", choices=tuple(UNIT_LABELS), required=True)
    parser.add_argument("--stop-loss", required=True)
    parser.add_argument("--stop-loss-unit", choices=tuple(UNIT_LABELS), required=True)
    parser.add_argument("--max-holding-periods", type=int, required=True)
    parser.add_argument("--stock-fee-percent")
    parser.add_argument("--futures-fee")
    parser.add_argument("--futures-margin-percent")
    parser.add_argument(
        "--print-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> AlertBacktestSettings:
    if not args.dry_run and not args.confirm_historical_backtest:
        raise ValueError("Starting an alert backtest requires --confirm-historical-backtest")
    for label, value in (
        ("--simulate-entry-ticks/--no-simulate-entry-ticks", args.simulate_entry_ticks),
        ("--simulate-exit-ticks/--no-simulate-exit-ticks", args.simulate_exit_ticks),
        ("--print-enabled/--no-print-enabled", args.print_enabled),
    ):
        if value is None:
            raise ValueError(f"An explicit boolean choice is required: {label}")
    products = validate_explicit_products(args.product)
    start_date = xq_backtest.parse_iso_date(args.start_date)
    end_date = xq_backtest.parse_iso_date(args.end_date)
    if start_date > end_date:
        raise ValueError("--start-date must not be later than --end-date")
    if args.max_concurrent_entries <= 0 or args.max_holding_periods <= 0:
        raise ValueError("Entry and holding limits must be positive")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    take_profit = xq_backtest.decimal_text(args.take_profit, "--take-profit")
    stop_loss = xq_backtest.decimal_text(args.stop_loss, "--stop-loss")
    if float(take_profit) <= 0 or float(stop_loss) <= 0:
        raise ValueError("Take-profit and stop-loss values must be positive")
    stock_fee = (
        xq_backtest.decimal_text(args.stock_fee_percent, "--stock-fee-percent")
        if args.stock_fee_percent is not None
        else None
    )
    futures_fee = (
        xq_backtest.decimal_text(args.futures_fee, "--futures-fee")
        if args.futures_fee is not None
        else None
    )
    futures_margin = (
        xq_backtest.decimal_text(
            args.futures_margin_percent,
            "--futures-margin-percent",
        )
        if args.futures_margin_percent is not None
        else None
    )
    if args.product_kind == "stock" and stock_fee is None:
        raise ValueError("--stock-fee-percent is required for stock products")
    if args.product_kind == "futures" and (
        futures_fee is None or futures_margin is None
    ):
        raise ValueError(
            "--futures-fee and --futures-margin-percent are required for futures products"
        )
    return AlertBacktestSettings(
        products=products,
        product_kind=args.product_kind,
        direction=args.direction,
        frequency=args.frequency,
        start_date=start_date,
        end_date=end_date,
        price_basis=args.price_basis,
        entry_price=args.entry_price,
        exit_price=args.exit_price,
        simulate_entry_ticks=bool(args.simulate_entry_ticks),
        simulate_exit_ticks=bool(args.simulate_exit_ticks),
        max_concurrent_entries=args.max_concurrent_entries,
        take_profit=take_profit,
        take_profit_unit=args.take_profit_unit,
        stop_loss=stop_loss,
        stop_loss_unit=args.stop_loss_unit,
        max_holding_periods=args.max_holding_periods,
        stock_fee_percent=stock_fee,
        futures_fee=futures_fee,
        futures_margin_percent=futures_margin,
        print_enabled=bool(args.print_enabled),
    )


def frequency_label(value: str) -> str:
    return "日" if value == "day" else f"{value}分鐘"


def _check_state(window: Any, control_id: int) -> bool:
    return bool(xq_backtest.control_by_id(window, control_id).get_check_state())


def _edit_text(window: Any, control_id: int) -> str:
    return xq_backtest.normalized(
        xq_backtest.control_by_id(window, control_id).window_text()
    )


def _unit_key(window: Any, control_id: int) -> str:
    actual = xq_backtest.normalized(
        xq_backtest.control_by_id(window, control_id).window_text()
    )
    for key, label in UNIT_LABELS.items():
        if actual == xq_backtest.normalized(label):
            return key
    raise RuntimeError(f"Unsupported unit read back from control {control_id}: {actual}")


def _ownerdraw_fill(control: Any) -> dict[str, Any]:
    if int(control.style()) & 0xF != 0xB:
        raise RuntimeError(f"Control {control.control_id()} is not an owner-draw button")
    image = control.capture_as_image().convert("RGB")
    left = max(1, image.width // 6)
    top = max(1, image.height // 6)
    right = max(left + 1, image.width - left)
    bottom = max(top + 1, image.height - top)
    raw = image.crop((left, top, right, bottom)).tobytes()
    rgb = tuple(
        int(statistics.median(raw[offset::3]))
        for offset in range(3)
    )
    return {
        "rgb": list(rgb),
        "chroma": max(rgb) - min(rgb),
        "size": [image.width, image.height],
        "style_kind": "BS_OWNERDRAW",
    }


def set_alert_direction(
    window: Any,
    direction: str,
    guards: list[dict[str, Any]],
) -> dict[str, Any]:
    target_id, other_id = DIRECTION_IDS[direction]
    target = xq_backtest.control_by_id(window, target_id)
    other = xq_backtest.control_by_id(window, other_id)
    before = {
        "target": _ownerdraw_fill(target),
        "other": _ownerdraw_fill(other),
    }
    if (
        before["target"]["chroma"] < 40
        or before["target"]["chroma"] < before["other"]["chroma"] + 30
    ):
        guards.append(xq_backtest.guarded_paced_click(window, target))
    after = {
        "target": _ownerdraw_fill(target),
        "other": _ownerdraw_fill(other),
    }
    if (
        after["target"]["chroma"] < 40
        or after["target"]["chroma"] < after["other"]["chroma"] + 30
    ):
        raise RuntimeError(
            f"XQ did not visually retain owner-draw direction {direction}"
        )
    return {
        "direction": direction,
        "target_control_id": target_id,
        "other_control_id": other_id,
        "readback_method": "owner_draw_control_local_visual_fill",
        "before": before,
        "after": after,
    }


def apply_alert_settings(
    window: Any,
    settings: AlertBacktestSettings,
    timeout: float,
) -> dict[str, Any]:
    guards: list[dict[str, Any]] = []
    scope_selection = xq_backtest.choose_products(window, settings.products, timeout)
    direction_evidence = set_alert_direction(window, settings.direction, guards)
    xq_backtest.set_combo(
        window,
        2091,
        frequency_label(settings.frequency),
        foreground_records=guards,
    )
    xq_backtest.set_radio(
        window,
        *PRICE_BASIS_IDS[settings.price_basis],
        foreground_records=guards,
    )
    xq_backtest.set_date(
        window,
        2200,
        settings.start_date,
        foreground_records=guards,
    )
    xq_backtest.set_date(
        window,
        2201,
        settings.end_date,
        foreground_records=guards,
    )

    xq_backtest.set_checked(
        window,
        2121,
        settings.simulate_entry_ticks,
        foreground_records=guards,
    )
    xq_backtest.set_checked(window, 2125, True, foreground_records=guards)
    xq_backtest.set_edit(
        window,
        2006,
        settings.max_concurrent_entries,
        foreground_records=guards,
    )
    xq_backtest.set_radio(
        window,
        *PRICE_IDS[settings.entry_price],
        foreground_records=guards,
    )

    xq_backtest.set_checked(window, 2129, False, foreground_records=guards)
    xq_backtest.set_checked(window, 2127, False, foreground_records=guards)
    xq_backtest.set_checked(
        window,
        2128,
        settings.simulate_exit_ticks,
        foreground_records=guards,
    )
    xq_backtest.set_checked(window, 2122, True, foreground_records=guards)
    xq_backtest.set_checked(window, 2123, True, foreground_records=guards)
    xq_backtest.set_checked(window, 2124, True, foreground_records=guards)
    xq_backtest.set_edit(
        window,
        2005,
        settings.max_holding_periods,
        foreground_records=guards,
    )
    xq_backtest.set_radio(
        window,
        *EXIT_PRICE_IDS[settings.exit_price],
        foreground_records=guards,
    )

    if settings.product_kind == "stock":
        xq_backtest.set_edit(
            window,
            2003,
            settings.take_profit,
            foreground_records=guards,
        )
        xq_backtest.set_combo(
            window,
            2093,
            UNIT_LABELS[settings.take_profit_unit],
            foreground_records=guards,
        )
        xq_backtest.set_edit(
            window,
            2004,
            settings.stop_loss,
            foreground_records=guards,
        )
        xq_backtest.set_combo(
            window,
            2095,
            UNIT_LABELS[settings.stop_loss_unit],
            foreground_records=guards,
        )
        xq_backtest.set_edit(
            window,
            2014,
            settings.stock_fee_percent or "",
            foreground_records=guards,
        )
    else:
        xq_backtest.set_edit(
            window,
            2010,
            settings.take_profit,
            foreground_records=guards,
        )
        xq_backtest.set_combo(
            window,
            2094,
            UNIT_LABELS[settings.take_profit_unit],
            foreground_records=guards,
        )
        xq_backtest.set_edit(
            window,
            2011,
            settings.stop_loss,
            foreground_records=guards,
        )
        xq_backtest.set_combo(
            window,
            2096,
            UNIT_LABELS[settings.stop_loss_unit],
            foreground_records=guards,
        )
        xq_backtest.set_edit(
            window,
            2015,
            settings.futures_fee or "",
            foreground_records=guards,
        )
        xq_backtest.set_edit(
            window,
            2013,
            settings.futures_margin_percent or "",
            foreground_records=guards,
        )
    xq_backtest.set_checked(
        window,
        2131,
        settings.print_enabled,
        foreground_records=guards,
    )

    start = xq_backtest.control_by_id(window, 2200).get_time()
    end = xq_backtest.control_by_id(window, 2201).get_time()
    entry_preload = xq_backtest.control_by_id(window, 2007)
    take_profit_edit = 2003 if settings.product_kind == "stock" else 2010
    take_profit_unit = 2093 if settings.product_kind == "stock" else 2094
    stop_loss_edit = 2004 if settings.product_kind == "stock" else 2011
    stop_loss_unit = 2095 if settings.product_kind == "stock" else 2096
    evidence = {
        "scope_selection": scope_selection,
        "direction": settings.direction,
        "direction_readback": direction_evidence,
        "frequency": settings.frequency,
        "start_date": f"{start.wYear:04d}-{start.wMonth:02d}-{start.wDay:02d}",
        "end_date": f"{end.wYear:04d}-{end.wMonth:02d}-{end.wDay:02d}",
        "price_basis": settings.price_basis,
        "entry_price": settings.entry_price,
        "exit_price": settings.exit_price,
        "simulate_entry_ticks": _check_state(window, 2121),
        "simulate_exit_ticks": _check_state(window, 2128),
        "max_concurrent_entries_enabled": _check_state(window, 2125),
        "max_concurrent_entries": int(_edit_text(window, 2006)),
        "take_profit_enabled": _check_state(window, 2122),
        "take_profit": _edit_text(window, take_profit_edit),
        "take_profit_unit": _unit_key(window, take_profit_unit),
        "stop_loss_enabled": _check_state(window, 2123),
        "stop_loss": _edit_text(window, stop_loss_edit),
        "stop_loss_unit": _unit_key(window, stop_loss_unit),
        "max_holding_enabled": _check_state(window, 2124),
        "max_holding_periods": int(_edit_text(window, 2005)),
        "stock_fee_percent": (
            _edit_text(window, 2014) if settings.product_kind == "stock" else None
        ),
        "futures_fee": (
            _edit_text(window, 2015) if settings.product_kind == "futures" else None
        ),
        "futures_margin_percent": (
            _edit_text(window, 2013) if settings.product_kind == "futures" else None
        ),
        "print_enabled": _check_state(window, 2131),
        "entry_preload_control_enabled": bool(entry_preload.is_enabled()),
        "entry_preload_value_applied": False,
        "exit_script_enabled": _check_state(window, 2129),
        "foreground_guard": xq_backtest.summarize_foreground_guards(guards),
    }
    return evidence


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def capture_timeout_progress_evidence(
    config_path: Path,
    checkpoint: xq_backtest.RecoveryCheckpoint | None,
    *,
    stamp: datetime | None = None,
    window_factory: Any | None = None,
    file_prefix: str = "alert-backtest",
) -> dict[str, Any]:
    """Capture only the exact visible progress window saved in checkpoint."""
    if checkpoint is None or checkpoint.progress_window_handle is None:
        return {
            "status": "not_available",
            "reason": "checkpoint_has_no_progress_window_handle",
        }
    handle = int(checkpoint.progress_window_handle)
    if handle <= 0:
        return {
            "status": "not_available",
            "reason": "checkpoint_progress_window_handle_invalid",
            "window_handle": handle,
        }
    if window_factory is None:
        from pywinauto import Desktop

        window_factory = lambda target: Desktop(backend="win32").window(
            handle=target
        )
    window = window_factory(handle)
    exists = bool(window.exists(timeout=0.2))
    visible = bool(window.is_visible()) if exists else False
    enabled = bool(window.is_enabled()) if exists else False
    hung = xq_backtest.window_is_hung(handle) if exists else None
    health = {
        "exists": exists,
        "visible": visible,
        "enabled": enabled,
        "hung": hung,
    }
    if not exists or not visible or not enabled or hung is not False:
        return {
            "status": "not_captured",
            "reason": "progress_window_not_visible_enabled_responsive",
            "window_handle": handle,
            "window_health": health,
        }

    states: list[str] = []
    status_read_error = None
    try:
        details = xq_backtest.control_by_id(window, 3002)
        if details.is_visible():
            states = [
                xq_backtest.normalized(details.get_item(row, 1).text())
                for row in range(details.item_count())
            ]
    except Exception as exc:
        status_read_error = f"{type(exc).__name__}: {exc}"
    progress_error_codes = sorted(
        {
            int(match.group(1))
            for state in states
            for match in PROGRESS_ERROR_CODE_RE.finditer(state)
        }
    )

    captured_at = stamp or datetime.now(timezone.utc)
    directory = config_path.resolve().parent / "incidents"
    directory.mkdir(parents=True, exist_ok=True)
    if re.fullmatch(r"[a-z0-9-]+", file_prefix) is None:
        raise ValueError("Incident file prefix is invalid")
    path = directory / (
        f"{file_prefix}-{captured_at.strftime('%Y%m%dT%H%M%S_%fZ')}"
        f"-progress-{handle}.png"
    )
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite progress screenshot: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        image = window.capture_as_image()
        image.save(temporary, format="PNG")
        payload = temporary.read_bytes()
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Captured progress image is not a PNG")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "captured",
        "captured_at_utc": captured_at.isoformat(),
        "window_handle": handle,
        "window_health": health,
        "visible_execution_states": states,
        "actual_progress_error_codes": progress_error_codes,
        "actual_report_error_code": None,
        "status_read_error": status_read_error,
        "screenshot_path": str(path),
        "screenshot_bytes": len(payload),
        "screenshot_sha256": hashlib.sha256(payload).hexdigest(),
    }


def save_wait_incident(
    config_path: Path,
    config: dict[str, Any],
    phase: str,
    exc: BaseException,
    checkpoint: xq_backtest.RecoveryCheckpoint | None,
    *,
    task: str = "alert_backtest_smoke",
    file_prefix: str = "alert-backtest",
) -> Path:
    stamp = datetime.now(timezone.utc)
    directory = config_path.resolve().parent / "incidents"
    if re.fullmatch(r"[a-z0-9-]+", file_prefix) is None:
        raise ValueError("Incident file prefix is invalid")
    path = directory / f"{file_prefix}-{stamp.strftime('%Y%m%dT%H%M%S_%fZ')}.json"
    try:
        progress_capture = capture_timeout_progress_evidence(
            config_path,
            checkpoint,
            stamp=stamp,
            file_prefix=file_prefix,
        )
    except Exception as capture_exc:
        progress_capture = {
            "status": "capture_error",
            "error": f"{type(capture_exc).__name__}: {capture_exc}",
        }
    try:
        runtime = xq_backtest.capture_runtime_snapshot(config)
        runtime_evidence = xq_backtest.runtime_evidence(runtime)
    except Exception as runtime_exc:
        runtime_evidence = {"capture_error": f"{type(runtime_exc).__name__}: {runtime_exc}"}
    try:
        recovery = xq_backtest.inspect_recovery_status(config_path, config)
    except Exception as recovery_exc:
        recovery = {"inspection_error": f"{type(recovery_exc).__name__}: {recovery_exc}"}
    _atomic_private_json(
        path,
        {
            "recorded_at_utc": stamp.isoformat(),
            "task": task,
            "phase": phase,
            "exception_type": type(exc).__name__,
            "exception": str(exc),
            "runtime": runtime_evidence,
            "checkpoint": asdict(checkpoint) if checkpoint is not None else None,
            "progress_capture": progress_capture,
            "recovery_status": recovery,
        },
    )
    return path


def close_new_report(handle: int) -> dict[str, Any]:
    from xq_function_boundary_runner import close_manifest_reports

    results = close_manifest_reports([handle])
    if len(results) != 1:
        raise RuntimeError("Report cleanup did not return one exact result")
    result = results[0]
    if result.get("closed") is not True:
        raise RuntimeError(f"The new report could not be safely closed: {result}")
    return result


def validate_compiled_alert_title(title: str, expected_name: str) -> str:
    normalized = " ".join(title.split())
    expected = f"{expected_name}(警示)"
    if expected not in normalized:
        raise RuntimeError(
            f"The active XScript title does not match the alert: {normalized}"
        )
    if "未編譯" in normalized:
        raise RuntimeError(
            "The active alert is uncompiled; obtain a current real XQ compiler "
            "success before opening the backtest environment"
        )
    return normalized


def verify_active_alert_script(expected_name: str) -> dict[str, Any]:
    from pywinauto import Desktop
    from xq_function_boundary_runner import (
        _read_active_document,
        _verify_formula_property_readback,
    )

    native_xscript = Desktop(backend="win32").window(
        title_re="^XScript.*"
    ).wrapper_object()
    active_title = validate_compiled_alert_title(
        native_xscript.window_text(), expected_name
    )
    xscript = native_xscript
    name, script_type = _read_active_document(xscript, expected_name, "alert")
    if not _verify_formula_property_readback(
        int(xscript.handle), expected_name, "alert"
    ):
        raise RuntimeError(
            "The active alert script name, type, or 自訂/CODEX/ location did not match"
        )
    return {
        "script_name": name,
        "script_type": script_type,
        "location": "自訂/CODEX/",
        "active_title": active_title,
        "uncompiled_marker_present": False,
        "read_only": True,
    }


def post_alert_start_once(settings_window: Any) -> dict[str, Any]:
    """Post one semantic Start command without waiting on XQ's GUI thread."""
    guard = xq_backtest.ensure_window_foreground(settings_window)
    start = xq_backtest.control_by_id(settings_window, 2033)
    if not start.is_visible() or not start.is_enabled():
        raise RuntimeError("The alert backtest Start control is not usable")
    xq_backtest.ui_action_pause()
    if sys.platform != "win32":
        raise RuntimeError("The alert backtest Start command requires Windows")
    accepted = bool(ctypes.windll.user32.PostMessageW(int(start.handle), BM_CLICK, 0, 0))
    if not accepted:
        raise RuntimeError("Windows did not accept the alert backtest Start command")
    return {
        "command": "BM_CLICK_PostMessageW",
        "control_id": 2033,
        "control_handle": int(start.handle),
        "posted_once": True,
        "foreground_guard": guard,
    }


def alert_settings_window_visible(settings_window: Any) -> bool:
    handle = int(settings_window.handle)
    if sys.platform == "win32":
        return bool(
            ctypes.windll.user32.IsWindow(handle)
            and ctypes.windll.user32.IsWindowVisible(handle)
        )
    return bool(settings_window.is_visible())


def new_alert_report_candidates(
    baseline_handles: set[int],
    expected_script_name: str,
) -> list[dict[str, Any]]:
    expected_marker = xq_backtest.normalized(expected_script_name).casefold()
    candidates: list[dict[str, Any]] = []
    for window, elements in xq_backtest.visible_report_records(baseline_handles):
        try:
            title = xq_backtest.normalized(window.window_text())
            summary = xq_backtest.report_summary(elements)
            candidates.append(
                {
                    "window": window,
                    "window_handle": int(window.handle),
                    "window_title": title,
                    "marker_expected": expected_script_name,
                    "marker_matched": expected_marker in title.casefold(),
                    "summary": summary,
                }
            )
        except Exception:
            continue
    return candidates


def run_alert_and_monitor(
    settings_window: Any,
    timeout: float,
    expected_script_name: str,
    *,
    runtime_probe: Callable[[], xq_backtest.RuntimeSnapshot] | None = None,
    checkpoint_callback: Callable[[str, int | None, bool], None] | None = None,
    baseline_report_handles: set[int] | None = None,
    baseline_progress_handles: set[int] | None = None,
    late_report_grace_seconds: float | None = None,
    start_action: Callable[[Any], dict[str, Any]] = post_alert_start_once,
    progress_probe: Callable[[], list[Any]] | None = None,
    report_probe: Callable[[set[int], str], list[dict[str, Any]]] = (
        new_alert_report_candidates
    ),
    settings_visible_probe: Callable[[Any], bool] = alert_settings_window_visible,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    poll_seconds: float = ALERT_MONITOR_POLL_SECONDS,
) -> tuple[str, dict[str, Any]]:
    """Start once, then use read-only evidence to classify an alert backtest."""
    baseline = set(baseline_report_handles or ())
    progress_baseline = set(baseline_progress_handles or ())
    grace = late_report_grace_seconds
    if grace is None:
        grace = max(
            ALERT_LATE_REPORT_MIN_GRACE_SECONDS,
            min(ALERT_LATE_REPORT_MAX_GRACE_SECONDS, timeout),
        )
    if grace < 0 or poll_seconds <= 0:
        raise ValueError("Alert monitoring intervals must be positive")
    progress_probe = progress_probe or (
        lambda: xq_backtest.progress_windows(include_hidden=True)
    )

    state = "starting"
    transitions: list[dict[str, Any]] = [
        {"stage": state, "observed_at_seconds": 0.0}
    ]
    progress_handle: int | None = None
    progress_seen = False
    hidden_progress_seen = False
    settings_poll_count = 0
    settings_ever_closed = False
    report_decision = "not_seen"
    started_at = monotonic()
    regular_deadline = started_at + timeout
    hard_deadline = regular_deadline + grace
    next_runtime_heartbeat = started_at

    def transition(next_stage: str) -> None:
        nonlocal state
        if state == next_stage:
            return
        state = next_stage
        transitions.append(
            {
                "stage": next_stage,
                "observed_at_seconds": round(monotonic() - started_at, 3),
            }
        )
        if checkpoint_callback is not None:
            checkpoint_callback(next_stage, progress_handle, False)

    start_evidence = start_action(settings_window)
    while monotonic() < hard_deadline:
        now = monotonic()
        if runtime_probe is not None and now >= next_runtime_heartbeat:
            snapshot = runtime_probe()
            failure_kind = xq_backtest.classify_runtime_interruption(snapshot)
            if failure_kind is not None:
                transition("interrupted")
                return "environment_interruption", {
                    "failure_kind": failure_kind,
                    "last_safe_stage": transitions[-2]["stage"],
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "progress_seen": progress_seen,
                    "recovery_checkpoint_retained": True,
                    "runtime": xq_backtest.runtime_evidence(snapshot),
                }
            next_runtime_heartbeat = now + xq_backtest.RUNTIME_HEARTBEAT_SECONDS

        settings_poll_count += 1
        settings_visible = settings_visible_probe(settings_window)
        if not settings_visible:
            settings_ever_closed = True

        progress_matches = []
        for progress in progress_probe():
            handle = int(progress.handle)
            try:
                visible = bool(progress.is_visible())
            except Exception:
                visible = True
            if handle not in progress_baseline or visible:
                progress_matches.append(progress)
        if len(progress_matches) > 1:
            return "indeterminate_timeout", {
                "start_input": start_evidence,
                "state_transitions": transitions,
                "progress_seen": progress_seen,
                "report_decision": "progress_not_unique",
                "progress_candidate_count": len(progress_matches),
                "manual_review_required": True,
            }
        if len(progress_matches) == 1:
            progress = progress_matches[0]
            progress_seen = True
            progress_handle = int(progress.handle)
            try:
                hidden_progress_seen = hidden_progress_seen or not bool(
                    progress.is_visible()
                )
            except Exception:
                hidden_progress_seen = True
            transition("running")
        elif not settings_visible and state == "starting":
            transition("running")

        candidates = report_probe(baseline, expected_script_name)
        if len(candidates) > 1:
            return "indeterminate_timeout", {
                "start_input": start_evidence,
                "state_transitions": transitions,
                "progress_seen": progress_seen,
                "hidden_progress_seen": hidden_progress_seen,
                "report_decision": "report_not_unique",
                "new_report_count": len(candidates),
                "new_report_handles": sorted(
                    int(candidate["window_handle"]) for candidate in candidates
                ),
                "manual_review_required": True,
            }
        if len(candidates) == 1:
            candidate = candidates[0]
            if candidate.get("marker_matched") is not True:
                return "indeterminate_timeout", {
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "progress_seen": progress_seen,
                    "report_decision": "marker_mismatch",
                    "new_report_count": 1,
                    "report_window_handle": int(candidate["window_handle"]),
                    "marker_expected": expected_script_name,
                    "marker_actual": candidate.get("window_title"),
                    "manual_review_required": True,
                }
            summary = candidate.get("summary")
            if summary is not None:
                if state == "starting":
                    transition("running")
                transition("late_report")
                transition("completed")
                report_decision = "unique_new_report_and_marker_matched"
                status = xq_backtest.classify_report(summary)
                evidence: dict[str, Any] = {
                    "report_window_handle": int(candidate["window_handle"]),
                    "report_window_title": candidate.get("window_title"),
                    "success_count": summary.success_count,
                    "failure_count": summary.failure_count,
                    "total_trades": summary.total_trades,
                    "progress_seen": progress_seen,
                    "hidden_progress_seen": hidden_progress_seen,
                    "progress_window_handle": progress_handle,
                    "settings_window_delayed_close": settings_poll_count > 1,
                    "settings_window_closed": settings_ever_closed,
                    "start_input": start_evidence,
                    "state_transitions": transitions,
                    "report_decision": report_decision,
                    "new_report_count": 1,
                    "marker_expected": expected_script_name,
                    "marker_actual": candidate.get("window_title"),
                    "marker_matched": True,
                }
                if summary.failure_count > 0:
                    try:
                        details = xq_backtest.extract_failure_details(
                            candidate["window"], summary.failure_count
                        )
                        evidence["failure_details"] = [
                            asdict(item) for item in details
                        ]
                    except Exception as exc:
                        evidence["failure_details"] = []
                        evidence["failure_detail_capture_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                return status, evidence
            report_decision = "summary_not_yet_conclusive"

        if now >= regular_deadline and state != "late_report":
            if state == "starting":
                transition("running")
            transition("late_report")
        elif state == "running" and progress_seen and not progress_matches:
            transition("late_report")
        sleeper(poll_seconds)

    if state == "starting":
        transition("running")
    transition("late_report")
    return "indeterminate_timeout", {
        "start_input": start_evidence,
        "state_transitions": transitions,
        "progress_seen": progress_seen,
        "hidden_progress_seen": hidden_progress_seen,
        "progress_window_handle": progress_handle,
        "settings_window_delayed_close": settings_poll_count > 1,
        "settings_window_closed": settings_ever_closed,
        "settings_window_visible_at_timeout": not settings_ever_closed,
        "report_decision": report_decision,
        "new_report_count": 0,
        "manual_review_required": True,
        "timeout_seconds": timeout,
        "late_report_grace_seconds": grace,
    }


# Keep the alert runner's established import surface while routing production
# and tests through the shared monitor used by every backtest type.
post_alert_start_once = xq_backtest_monitor.post_start_once
alert_settings_window_visible = xq_backtest_monitor.settings_window_visible
new_alert_report_candidates = xq_backtest_monitor.new_report_candidates
run_alert_and_monitor = xq_backtest_monitor.run_report_monitor


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    config: dict[str, Any] | None = None
    args: argparse.Namespace | None = None
    settings: AlertBacktestSettings | None = None
    checkpoint = None
    checkpoint_file = None
    tracked_xq_process_id = None
    phase = "argument_validation"
    input_stop_required = False
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
                "A current XQ recovery state blocks this alert backtest",
                recovery=recovery,
            )
        xq_backtest.configure_ui_pacing(config)
        checkpoint_file = xq_backtest.recovery_path(args.config)
        phase = "runtime_preflight"
        snapshot = xq_backtest.capture_runtime_snapshot(config)
        tracked_xq_process_id = snapshot.expected_xq_process_id
        failure_kind = xq_backtest.classify_runtime_interruption(snapshot)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ is not healthy enough to start an alert backtest",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(snapshot),
            )

        phase = "active_script_readback"
        active_script = verify_active_alert_script(args.script_name)
        phase = "settings_open"
        open_guards: list[dict[str, Any]] = []
        settings_window = xq_alert_backtest.open_alert_backtest_settings(
            config,
            foreground_records=open_guards,
        )
        phase = "settings_apply"
        settings_evidence = apply_alert_settings(
            settings_window,
            settings,
            float(config.get("connect_timeout_seconds", 15)),
        )
        settings_evidence["open_foreground_guard"] = (
            xq_backtest.summarize_foreground_guards(open_guards)
        )
        settings_evidence["active_script"] = active_script
        if args.dry_run:
            phase = "settings_cancel"
            xq_backtest.guarded_paced_click(
                settings_window,
                xq_backtest.control_by_id(settings_window, 2034),
            )
            settings_window = None
            return emit(
                "success",
                "XQ alert backtest settings were verified and cancelled",
                dry_run=True,
                settings_evidence=settings_evidence,
            )

        phase = "pre_start_evidence"
        progress_before_start = xq_backtest.progress_windows(include_hidden=True)
        if any(progress.is_visible() for progress in progress_before_start):
            raise RuntimeError("An XQ backtest job already exists")
        baseline_progress_handles = {
            int(progress.handle) for progress in progress_before_start
        }
        start_snapshot = xq_backtest.capture_runtime_snapshot(
            config,
            tracked_xq_process_id,
        )
        start_failure = xq_backtest.classify_runtime_interruption(start_snapshot)
        if start_failure is not None:
            raise RuntimeError(f"XQ changed state before Start: {start_failure}")
        baseline_report_handles = xq_backtest.visible_report_handles()
        checkpoint = xq_backtest.create_checkpoint(
            start_snapshot,
            baseline_report_handles,
        )
        xq_backtest.write_checkpoint(checkpoint_file, checkpoint)

        def checkpoint_callback(
            stage: str,
            progress_handle: int | None,
            cancellation_confirmed: bool,
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
        status, evidence = run_alert_and_monitor(
            active_settings,
            args.timeout_seconds,
            args.script_name,
            runtime_probe=lambda: xq_backtest.capture_runtime_snapshot(
                config,
                tracked_xq_process_id,
            ),
            checkpoint_callback=checkpoint_callback,
            baseline_report_handles=baseline_report_handles,
            baseline_progress_handles=baseline_progress_handles,
        )
        evidence["settings_evidence"] = settings_evidence
        if status in {"success", "failure", "partial_failure"}:
            xq_backtest.remove_checkpoint(checkpoint_file)
            checkpoint = None
            evidence["recovery_checkpoint_retained"] = False
            phase = "report_cleanup"
            report_handle = evidence.get("report_window_handle")
            if not isinstance(report_handle, int) or report_handle <= 0:
                raise RuntimeError("Completed backtest evidence has no exact report handle")
            evidence["report_cleanup"] = close_new_report(report_handle)
            evidence["report_cleanup_complete"] = True
        else:
            evidence["recovery_checkpoint_retained"] = True
            evidence["recovery_run_id"] = checkpoint.run_id
            if status in {"indeterminate_timeout", "environment_interruption"}:
                evidence["incident_path"] = str(
                    save_wait_incident(
                        args.config,
                        config,
                        "backtest_timeout"
                        if status == "indeterminate_timeout"
                        else "backtest_environment_interruption",
                        TimeoutError(
                            "Alert backtest monitoring stopped without conclusive evidence"
                        ),
                        checkpoint,
                    )
                )
        messages = {
            "success": "XQ alert backtest report contains successful products only",
            "failure": "XQ alert backtest report contains failed products only",
            "partial_failure": "XQ alert backtest report contains successful and failed products",
            "indeterminate_timeout": "Alert backtest did not produce conclusive evidence before timeout",
            "environment_interruption": "XQ changed state while the alert backtest was running",
        }
        return emit(status, messages[status], **evidence)
    except Exception as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        if settings_window is not None and not input_stop_required:
            try:
                xq_backtest.guarded_paced_click(
                    settings_window,
                    xq_backtest.control_by_id(settings_window, 2034),
                )
                settings_window = None
            except Exception:
                pass
        if checkpoint is not None and checkpoint_file is not None:
            try:
                checkpoint = xq_backtest.update_checkpoint(
                    checkpoint,
                    stage="interrupted",
                )
                xq_backtest.write_checkpoint(checkpoint_file, checkpoint)
            except Exception:
                pass
        incident_path = None
        if input_stop_required and args is not None and config is not None:
            try:
                incident_path = str(
                    save_wait_incident(
                        args.config,
                        config,
                        phase,
                        exc,
                        checkpoint,
                    )
                )
            except Exception:
                incident_path = None
        return emit(
            "automation_error",
            f"XQ alert backtest automation failed: {type(exc).__name__}: {exc}",
            phase=phase,
            input_stopped=input_stop_required,
            incident_path=incident_path,
            recovery_checkpoint_retained=checkpoint is not None,
            recovery_run_id=checkpoint.run_id if checkpoint is not None else None,
        )


if __name__ == "__main__":
    sys.exit(main())
