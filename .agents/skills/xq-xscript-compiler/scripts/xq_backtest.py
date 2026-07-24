#!/usr/bin/env python3
"""Fill and run one verified XQ autotrade backtest, then classify its report."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from uuid import UUID, uuid4


FREQUENCIES = tuple(str(value) for value in (1, 2, 3, 5, 10, 15, 20, 30, 45, 60)) + ("day",)
PRICE_BASES = {"original": "原始值", "adjusted": "還原值"}
PRICE_MODES = {"trigger": "觸發價", "market": "市價"}
CANCELLATION_RECOVERY_TIMEOUT_SECONDS = 10.0
PARTIAL_REPORT_RECOVERY_TIMEOUT_SECONDS = 30.0
RECOVERY_SCHEMA_VERSION = 2
RECOVERY_FILE_NAME = "recovery-state.json"
RUNTIME_HEARTBEAT_SECONDS = 0.5
EXIT_CODES = {
    "success": 0,
    "failure": 2,
    "partial_failure": 2,
    "indeterminate_timeout": 3,
    "cancelled": 3,
    "environment_interruption": 3,
    "automation_error": 3,
}


@dataclass(frozen=True)
class ReportSummary:
    success_count: int
    failure_count: int
    total_trades: int | None


@dataclass(frozen=True)
class FailureDetail:
    product: str
    state: str
    error_code: str | None
    description: str


@dataclass(frozen=True)
class CancellationEvidence:
    confirmation_seen: bool
    partial_results_requested: bool
    partial_results_request_succeeded: bool
    progress_closed: bool
    xscript_ready: bool
    partial_report_seen: bool
    partial_report_summary_available: bool
    partial_success_count: int | None
    partial_failure_count: int | None
    partial_total_trades: int | None


@dataclass(frozen=True)
class BacktestSettings:
    products: tuple[str, ...]
    frequency: str
    start_date: date
    end_date: date
    preload_records: int
    initial_capital_wan: str
    max_position: int
    max_entries_per_day: int
    max_trades_per_minute: int
    price_basis: str
    buy_price: str
    sell_price: str
    buy_offset: int
    sell_offset: int
    stock_fee_percent: str
    futures_fee: str
    simulate_ticks: bool
    daily_position_reset: bool
    fill_on_trigger: bool
    enable_print: bool
    us_all_sessions: bool
    direct_order: bool


@dataclass(frozen=True)
class RuntimeSnapshot:
    captured_at: str
    expected_xq_process_id: int | None
    xq_process_id: int | None
    xq_process_exists: bool
    xq_window_handle: int | None
    xq_window_exists: bool
    xq_window_visible: bool
    xq_window_enabled: bool
    xq_window_hung: bool | None
    xscript_window_handle: int | None
    xscript_window_exists: bool
    xscript_window_visible: bool
    xscript_window_enabled: bool
    xscript_window_hung: bool | None


@dataclass(frozen=True)
class RecoveryCheckpoint:
    schema_version: int
    run_id: str
    stage: str
    started_at: str
    updated_at: str
    xq_process_id: int | None
    xq_window_handle: int | None
    xscript_window_handle: int | None
    progress_window_handle: int | None
    baseline_report_handles: tuple[int, ...]
    backtest_started: bool
    cancellation_confirmed: bool


@dataclass(frozen=True)
class RecoveryAssessment:
    decision: str
    reason_codes: tuple[str, ...]
    recommended_action: str


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def normalized(value: Any) -> str:
    return " ".join(str(value or "").split())


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_is_running(process_id: int | None) -> bool:
    if process_id is None or process_id <= 0 or sys.platform != "win32":
        return False
    process_query_limited_information = 0x1000
    still_active = 259
    handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, process_id)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def window_is_hung(handle: int | None) -> bool | None:
    if handle is None or sys.platform != "win32":
        return None
    return bool(ctypes.windll.user32.IsHungAppWindow(handle))


def window_matches_selector(window: Any, selector: dict[str, Any]) -> bool:
    title = normalized(window.window_text())
    if selector.get("title") and title != normalized(selector["title"]):
        return False
    if selector.get("title_re") and re.search(str(selector["title_re"]), title) is None:
        return False
    if selector.get("class_name") and window.class_name() != selector["class_name"]:
        return False
    return True


def unique_window(windows: Sequence[Any], selector: dict[str, Any]) -> Any | None:
    matches = []
    for window in windows:
        try:
            if window_matches_selector(window, selector):
                matches.append(window)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def capture_runtime_snapshot(
    config: dict[str, Any],
    expected_xq_process_id: int | None = None,
    process_probe: Callable[[int | None], bool] = process_is_running,
) -> RuntimeSnapshot:
    from pywinauto import Desktop

    windows = Desktop(backend="win32").windows()
    xq_selector = dict(config.get("launcher", {}).get("xq_window", {}))
    xscript_selector = dict(config.get("window", {"title_re": "^XScript.*"}))
    xq_window = unique_window(windows, xq_selector) if xq_selector else None
    xscript_window = unique_window(windows, xscript_selector)
    xq_process_id = xq_window.process_id() if xq_window is not None else None
    tracked_process_id = expected_xq_process_id or xq_process_id
    tracked_process_exists = process_probe(tracked_process_id) or (
        tracked_process_id is not None
        and xq_process_id == tracked_process_id
        and xq_window is not None
    )

    def handle_of(window: Any | None) -> int | None:
        return int(window.handle) if window is not None else None

    def bool_property(window: Any | None, method: str) -> bool:
        if window is None:
            return False
        try:
            return bool(getattr(window, method)())
        except Exception:
            return False

    xq_handle = handle_of(xq_window)
    xscript_handle = handle_of(xscript_window)
    return RuntimeSnapshot(
        captured_at=utc_timestamp(),
        expected_xq_process_id=tracked_process_id,
        xq_process_id=xq_process_id,
        xq_process_exists=tracked_process_exists,
        xq_window_handle=xq_handle,
        xq_window_exists=xq_window is not None,
        xq_window_visible=bool_property(xq_window, "is_visible"),
        xq_window_enabled=bool_property(xq_window, "is_enabled"),
        xq_window_hung=window_is_hung(xq_handle),
        xscript_window_handle=xscript_handle,
        xscript_window_exists=xscript_window is not None,
        xscript_window_visible=bool_property(xscript_window, "is_visible"),
        xscript_window_enabled=bool_property(xscript_window, "is_enabled"),
        xscript_window_hung=window_is_hung(xscript_handle),
    )


def classify_runtime_interruption(snapshot: RuntimeSnapshot) -> str | None:
    if snapshot.expected_xq_process_id is None:
        return "environment_unknown"
    if snapshot.expected_xq_process_id is not None and not snapshot.xq_process_exists:
        return "xq_process_exited"
    if snapshot.xq_window_hung or snapshot.xscript_window_hung:
        return "xq_unresponsive"
    if not snapshot.xq_window_exists:
        return "xq_window_missing"
    if snapshot.xq_process_exists and not snapshot.xscript_window_exists:
        return "xscript_closed"
    return None


def runtime_evidence(snapshot: RuntimeSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def recovery_path(config_path: Path) -> Path:
    return config_path.resolve().parent / RECOVERY_FILE_NAME


def validate_checkpoint_payload(payload: Any) -> RecoveryCheckpoint:
    if not isinstance(payload, dict):
        raise ValueError("Recovery checkpoint must be a JSON object")
    expected_keys = {field.name for field in RecoveryCheckpoint.__dataclass_fields__.values()}
    if set(payload) != expected_keys:
        raise ValueError("Recovery checkpoint fields do not match the current schema")
    normalized_payload = dict(payload)
    baseline_handles = normalized_payload.get("baseline_report_handles")
    if not isinstance(baseline_handles, list):
        raise ValueError("Recovery checkpoint baseline report handles must be a JSON list")
    normalized_payload["baseline_report_handles"] = tuple(baseline_handles)
    checkpoint = RecoveryCheckpoint(**normalized_payload)
    if checkpoint.schema_version != RECOVERY_SCHEMA_VERSION:
        raise ValueError("Unsupported recovery checkpoint schema")
    UUID(checkpoint.run_id)
    if checkpoint.stage not in {"starting", "running", "cancelling", "interrupted"}:
        raise ValueError("Invalid recovery checkpoint stage")
    datetime.fromisoformat(checkpoint.started_at)
    datetime.fromisoformat(checkpoint.updated_at)
    for value in (
        checkpoint.xq_process_id,
        checkpoint.xq_window_handle,
        checkpoint.xscript_window_handle,
        checkpoint.progress_window_handle,
    ):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise ValueError("Recovery checkpoint identifiers must be positive integers")
    if len(set(checkpoint.baseline_report_handles)) != len(checkpoint.baseline_report_handles):
        raise ValueError("Recovery checkpoint baseline report handles must be unique")
    for value in checkpoint.baseline_report_handles:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Recovery checkpoint baseline report handles must be positive integers")
    if not isinstance(checkpoint.backtest_started, bool) or not isinstance(checkpoint.cancellation_confirmed, bool):
        raise ValueError("Recovery checkpoint state flags must be boolean")
    return checkpoint


def load_checkpoint(path: Path) -> RecoveryCheckpoint | None:
    if not path.exists():
        return None
    return validate_checkpoint_payload(json.loads(path.read_text(encoding="utf-8")))


def write_checkpoint(path: Path, checkpoint: RecoveryCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(asdict(checkpoint), ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def remove_checkpoint(path: Path) -> None:
    path.unlink(missing_ok=True)


def create_checkpoint(
    snapshot: RuntimeSnapshot,
    baseline_report_handles: Iterable[int] = (),
) -> RecoveryCheckpoint:
    now = utc_timestamp()
    return RecoveryCheckpoint(
        schema_version=RECOVERY_SCHEMA_VERSION,
        run_id=str(uuid4()),
        stage="starting",
        started_at=now,
        updated_at=now,
        xq_process_id=snapshot.expected_xq_process_id,
        xq_window_handle=snapshot.xq_window_handle,
        xscript_window_handle=snapshot.xscript_window_handle,
        progress_window_handle=None,
        baseline_report_handles=tuple(sorted(set(baseline_report_handles))),
        backtest_started=True,
        cancellation_confirmed=False,
    )


def update_checkpoint(checkpoint: RecoveryCheckpoint, **changes: Any) -> RecoveryCheckpoint:
    return replace(checkpoint, updated_at=utc_timestamp(), **changes)


def reconcile_stale_checkpoint(
    checkpoint: RecoveryCheckpoint,
    saved_process_running: bool,
    visible_progress: bool,
) -> str:
    if visible_progress:
        return "block"
    if not checkpoint.backtest_started:
        return "clear"
    if not saved_process_running:
        return "clear"
    return "block"


def assess_recovery_state(
    checkpoint: RecoveryCheckpoint | None,
    checkpoint_error: str | None,
    snapshot: RuntimeSnapshot,
    visible_progress: bool,
    saved_process_running: bool | None,
    inspection_errors: Sequence[str] = (),
) -> RecoveryAssessment:
    runtime_failure = classify_runtime_interruption(snapshot)
    reasons: list[str] = []
    if checkpoint_error is not None:
        reasons.append("checkpoint_invalid")
    if inspection_errors:
        reasons.append("inspection_incomplete")
    if visible_progress:
        reasons.append("visible_progress")
    if checkpoint is not None:
        reasons.append("checkpoint_present")
    if runtime_failure is not None:
        reasons.append(runtime_failure)

    if checkpoint_error is not None or inspection_errors:
        return RecoveryAssessment(
            decision="manual_review_required",
            reason_codes=tuple(reasons),
            recommended_action="Inspect the reported evidence; do not clear state or start another backtest.",
        )
    if visible_progress:
        if runtime_failure is None:
            return RecoveryAssessment(
                decision="monitor_existing",
                reason_codes=tuple(reasons),
                recommended_action="Monitor the existing backtest; do not start a duplicate run.",
            )
        return RecoveryAssessment(
            decision="manual_review_required",
            reason_codes=tuple(reasons),
            recommended_action="Visible progress conflicts with runtime evidence; inspect XQ without replaying the backtest.",
        )
    if checkpoint is not None and (not checkpoint.backtest_started or saved_process_running is False):
        if not checkpoint.backtest_started:
            reasons.append("backtest_not_started")
        if saved_process_running is False:
            reasons.append("saved_process_not_running")
        return RecoveryAssessment(
            decision="safe_to_clear_checkpoint",
            reason_codes=tuple(reasons),
            recommended_action="Explicitly acknowledge and clear the stale checkpoint before starting a new backtest.",
        )
    if runtime_failure in {"xscript_closed", "xq_window_missing"}:
        return RecoveryAssessment(
            decision="ui_recovery_required",
            reason_codes=tuple(reasons),
            recommended_action="Restore the XQ/XScript UI, then run recovery status again; do not replay automatically.",
        )
    if checkpoint is not None:
        return RecoveryAssessment(
            decision="manual_review_required",
            reason_codes=tuple(reasons),
            recommended_action="The saved XQ process may still own the run; inspect XQ and do not start a duplicate.",
        )
    if runtime_failure is None:
        return RecoveryAssessment(
            decision="safe_to_start",
            reason_codes=("runtime_healthy",),
            recommended_action="A new backtest may be started after its normal settings are confirmed.",
        )
    return RecoveryAssessment(
        decision="manual_review_required",
        reason_codes=tuple(reasons),
        recommended_action="Restore or inspect the XQ environment, then run recovery status again.",
    )


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO date: {value!r}") from exc


def decimal_text(value: str, label: str) -> str:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if number < 0:
        raise ValueError(f"{label} must not be negative")
    return str(value).strip()


def validate_product(value: str) -> str:
    product = value.strip()
    if not product or len(product) > 40 or any(ord(char) < 32 or char.isspace() for char in product):
        raise ValueError("--product must be one non-whitespace XQ product code of at most 40 characters")
    return product


def report_summary(elements: Sequence[tuple[str, str]]) -> ReportSummary | None:
    status_names = [name for control_type, name in elements if control_type == "DataItem" and ("成功" in name or "失敗" in name)]
    if not status_names:
        status_names = [name for control_type, name in elements if control_type == "Hyperlink" and ("成功" in name or "失敗" in name)]
    if not status_names:
        return None

    status_text = max(status_names, key=lambda item: (int("成功" in item) + int("失敗" in item), len(item)))
    success_match = re.search(r"(\d+)\s*\(成功\)", status_text)
    failure_match = re.search(r"(\d+)\s*\(失敗\)", status_text)
    if success_match is None and failure_match is None:
        return None
    success_count = int(success_match.group(1)) if success_match else 0
    failure_count = int(failure_match.group(1)) if failure_match else 0
    if success_count == 0 and failure_count == 0:
        return None

    total_trades = None
    for index, (control_type, name) in enumerate(elements):
        if control_type != "DataItem" or normalized(name) != "總交易次數":
            continue
        for next_type, next_name in elements[index + 1 : index + 5]:
            if next_type == "DataItem" and re.fullmatch(r"\d+", normalized(next_name)):
                total_trades = int(normalized(next_name))
                break
        break
    return ReportSummary(success_count, failure_count, total_trades)


def classify_report(summary: ReportSummary) -> str:
    if summary.success_count > 0 and summary.failure_count == 0:
        return "success"
    if summary.success_count == 0 and summary.failure_count > 0:
        return "failure"
    if summary.success_count > 0 and summary.failure_count > 0:
        return "partial_failure"
    raise ValueError("A report with no successful or failed products is not conclusive")


def failure_detail(product: str, state: str, description: str) -> FailureDetail:
    code_match = re.search(r"\[\s*\((\d+)\)", description)
    return FailureDetail(
        product=normalized(product),
        state=normalized(state),
        error_code=code_match.group(1) if code_match else None,
        description=normalized(description),
    )


def control_by_id(root: Any, control_id: int) -> Any:
    matches = [item for item in root.descendants() if item.control_id() == control_id]
    if len(matches) != 1:
        raise LookupError(f"Expected one control id {control_id}, found {len(matches)}")
    return matches[0]


def visible_dialog_with_control(control_id: int, timeout: float, exclude_handle: int | None = None) -> Any:
    from pywinauto import Desktop

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = []
        for window in Desktop(backend="win32").windows():
            try:
                if not window.is_visible() or window.class_name() != "#32770" or window.handle == exclude_handle:
                    continue
                if any(item.control_id() == control_id for item in window.descendants()):
                    matches.append(window)
            except Exception:
                continue
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LookupError(f"Expected one visible dialog containing control id {control_id}, found {len(matches)}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for dialog containing control id {control_id}")


def set_combo(root: Any, control_id: int, label: str) -> None:
    control = control_by_id(root, control_id)
    options = [normalized(item) for item in control.item_texts()]
    if normalized(label) not in options:
        raise ValueError(f"Unsupported option for control {control_id}: {label}")
    control.select(label)
    if normalized(control.window_text()) != normalized(label):
        raise RuntimeError(f"XQ did not retain option for control {control_id}")


def set_edit(root: Any, control_id: int, value: int | str) -> None:
    control = control_by_id(root, control_id)
    expected = str(value)
    control.set_edit_text(expected)
    if normalized(control.window_text()) != normalized(expected):
        raise RuntimeError(f"XQ did not retain value for control {control_id}")


def set_checked(root: Any, control_id: int, expected: bool) -> None:
    control = control_by_id(root, control_id)
    current = bool(control.get_check_state())
    if current != expected:
        if not control.is_enabled():
            raise RuntimeError(f"Control {control_id} is disabled and cannot be changed")
        control.click_input()
    if bool(control.get_check_state()) != expected:
        raise RuntimeError(f"XQ did not retain checkbox state for control {control_id}")


def set_radio(root: Any, target_id: int, other_id: int) -> None:
    target = control_by_id(root, target_id)
    if target.get_check_state() != 1:
        target.click_input()
    if target.get_check_state() != 1 or control_by_id(root, other_id).get_check_state() != 0:
        raise RuntimeError(f"XQ did not retain radio selection for control {target_id}")


def set_date(root: Any, control_id: int, value: date) -> None:
    control = control_by_id(root, control_id)
    control.set_time(year=value.year, month=value.month, day=value.day)
    actual = control.get_time()
    if (actual.wYear, actual.wMonth, actual.wDay) != (value.year, value.month, value.day):
        raise RuntimeError(f"XQ did not retain date for control {control_id}")


def choose_products(settings_window: Any, products: Sequence[str], timeout: float) -> None:
    product_dialog = None
    try:
        source = control_by_id(settings_window, 2092)
        if normalized(source.window_text()) == "商品":
            control_by_id(settings_window, 2031).click_input()
        else:
            options = [normalized(item) for item in source.item_texts()]
            if "商品" not in options:
                raise ValueError("The XQ backtest dialog does not offer the product source")
            source.select("商品")
        product_dialog = visible_dialog_with_control(782, timeout, exclude_handle=settings_window.handle)
        control_by_id(product_dialog, 805).click_input()
        query = control_by_id(product_dialog, 741)
        result_list = control_by_id(product_dialog, 782)
        for product in products:
            query.set_edit_text(product)
            control_by_id(product_dialog, 802).click_input()
            deadline = time.monotonic() + timeout
            exact_rows: list[int] = []
            while time.monotonic() < deadline:
                exact_rows = []
                for row in range(result_list.item_count()):
                    if normalized(result_list.get_item(row, 0).text()) == product:
                        exact_rows.append(row)
                if exact_rows:
                    break
                time.sleep(0.1)
            if len(exact_rows) != 1:
                raise LookupError(f"Expected one exact XQ product match for {product!r}, found {len(exact_rows)}")
            result_list.get_item(exact_rows[0]).select()
            control_by_id(product_dialog, 803).click_input()

        selected = [normalized(item) for item in control_by_id(product_dialog, 781).item_texts() if normalized(item)]
        selected_codes = [item.split(maxsplit=1)[0] for item in selected]
        if len(selected_codes) != len(products) or set(selected_codes) != set(products):
            raise RuntimeError("XQ product selection verification failed")
        control_by_id(product_dialog, 1).click_input()
        product_dialog = None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not settings_window.is_enabled():
            time.sleep(0.1)
        summary = normalized(control_by_id(settings_window, 2001).window_text())
        if not settings_window.is_enabled() or not summary:
            raise RuntimeError("XQ did not apply the selected product")
    except Exception:
        if product_dialog is not None:
            try:
                control_by_id(product_dialog, 806).click_input()
            except Exception:
                pass
        raise


def open_backtest_settings(config: dict[str, Any]) -> Any:
    from pywinauto import Desktop

    timeout = float(config.get("connect_timeout_seconds", 15))
    xscript = Desktop(backend="uia").window(title_re="^XScript.*")
    xscript.wait("visible enabled ready", timeout=timeout)
    root = xscript.wrapper_object()
    active_title = root.window_text()
    expected = config.get("active_type_title_regex", {}).get("autotrade", r"\((?:自動交易|交易)\)")
    if not re.search(expected, active_title):
        raise RuntimeError("The active XScript document is not an autotrade script")
    buttons = [
        item
        for item in root.descendants()
        if item.element_info.control_type == "Button" and normalized(item.element_info.name) == "回測"
    ]
    if len(buttons) != 1:
        raise LookupError(f"Expected one XScript backtest button, found {len(buttons)}")
    buttons[0].click_input()
    return visible_dialog_with_control(2033, timeout)


def apply_preload_records(window: Any, preload_records: int) -> dict[str, Any]:
    control = control_by_id(window, 2007)
    enabled = bool(control.is_enabled())
    if enabled:
        set_edit(window, 2007, preload_records)
    return {
        "preload_control_enabled": enabled,
        "preload_records_requested": preload_records,
        "preload_records_applied": enabled,
    }


def apply_settings(window: Any, settings: BacktestSettings, timeout: float) -> dict[str, Any]:
    choose_products(window, settings.products, timeout)
    frequency_label = "日" if settings.frequency == "day" else f"{settings.frequency}分鐘"
    set_combo(window, 2091, frequency_label)
    set_radio(window, 2069 if settings.price_basis == "original" else 2070, 2070 if settings.price_basis == "original" else 2069)
    set_date(window, 2200, settings.start_date)
    set_date(window, 2201, settings.end_date)
    settings_evidence = apply_preload_records(window, settings.preload_records)

    for checkbox_id, edit_id, value in (
        (2124, 2004, settings.max_position),
        (2125, 2005, settings.max_entries_per_day),
        (2126, 2006, settings.max_trades_per_minute),
    ):
        set_checked(window, checkbox_id, True)
        set_edit(window, edit_id, value)

    set_combo(window, 2093, PRICE_MODES[settings.buy_price])
    set_combo(window, 2094, PRICE_MODES[settings.sell_price])
    if settings.buy_price == "trigger":
        set_edit(window, 2009, settings.buy_offset)
    if settings.sell_price == "trigger":
        set_edit(window, 2010, settings.sell_offset)
    set_edit(window, 2016, settings.initial_capital_wan)
    set_edit(window, 2014, settings.stock_fee_percent)
    set_edit(window, 2015, settings.futures_fee)

    for control_id, expected in (
        (2121, settings.simulate_ticks),
        (2122, settings.daily_position_reset),
        (2123, settings.fill_on_trigger),
        (2131, settings.enable_print),
        (2127, settings.us_all_sessions),
        (2128, settings.direct_order),
    ):
        set_checked(window, control_id, expected)

    return settings_evidence


def report_elements(window: Any) -> list[tuple[str, str]] | None:
    try:
        descendants = window.descendants()
    except Exception:
        return None
    documents = [
        item
        for item in descendants
        if item.element_info.control_type == "Document"
        and item.element_info.class_name == "Chrome_RenderWidgetHostHWND"
        and normalized(item.element_info.name) == "XS回測報告"
    ]
    if not documents:
        return None
    return [(str(item.element_info.control_type or ""), str(item.element_info.name or "")) for item in descendants]


def failure_table(window: Any) -> Any | None:
    for table in window.descendants(control_type="Table"):
        children = table.children()
        if not children:
            continue
        headers = [normalized(item.element_info.name) for item in children[0].children()]
        if headers == ["商品名稱", "狀態", "說明"]:
            return table
    return None


def parse_failure_table(table: Any) -> list[FailureDetail]:
    rows: list[FailureDetail] = []
    children = table.children()
    for row in children[1:]:
        cells = [normalized(item.element_info.name) for item in row.children() if item.element_info.control_type == "DataItem"]
        if len(cells) != 3:
            raise RuntimeError(f"Expected three failure-detail cells, found {len(cells)}")
        rows.append(failure_detail(cells[0], cells[1], cells[2]))
    return rows


def extract_failure_details(window: Any, expected_count: int, timeout: float = 5.0) -> list[FailureDetail]:
    links = []
    for item in window.descendants(control_type="Hyperlink"):
        match = re.fullmatch(r"(\d+)\s*\(失敗\)", normalized(item.element_info.name))
        if match and int(match.group(1)) > 0:
            links.append(item)
    if len(links) != 1:
        raise LookupError(f"Expected one failed-product hyperlink, found {len(links)}")

    overlay_open = False
    try:
        links[0].iface_invoke.Invoke()
        overlay_open = True
        deadline = time.monotonic() + timeout
        table = None
        while time.monotonic() < deadline:
            table = failure_table(window)
            if table is not None:
                break
            time.sleep(0.1)
        if table is None:
            raise TimeoutError("Timed out waiting for the failed-product detail table")
        details = parse_failure_table(table)
        if len(details) != expected_count:
            raise RuntimeError(f"Expected {expected_count} failed-product rows, found {len(details)}")
        return details
    finally:
        if overlay_open:
            try:
                close_buttons = [
                    item
                    for item in window.descendants(control_type="Button")
                    if normalized(item.element_info.name) == "Close"
                ]
                if len(close_buttons) == 1:
                    close_buttons[0].iface_invoke.Invoke()
            except Exception:
                pass


def current_top_level_handles() -> set[int]:
    from pywinauto import Desktop

    result: set[int] = set()
    for window in Desktop(backend="uia").windows():
        try:
            if window.is_visible():
                result.add(window.handle)
        except Exception:
            continue
    return result


def visible_progress_window(exclude_handles: set[int] | None = None) -> Any | None:
    from pywinauto import Desktop

    excluded = exclude_handles or set()
    matches = []
    for window in Desktop(backend="win32").windows():
        try:
            if (
                window.handle not in excluded
                and window.is_visible()
                and window.class_name() == "#32770"
                and any(item.control_id() == 3002 for item in window.descendants())
            ):
                matches.append(window)
        except Exception:
            continue
    return matches[0] if len(matches) == 1 else None


def progress_product_states(progress: Any, timeout: float = 1.0) -> list[str]:
    details = control_by_id(progress, 3002)
    if not details.is_visible():
        content = control_by_id(progress, 3001)
        buttons = [
            item
            for item in content.descendants()
            if item.class_name() == "Button" and item.is_visible() and item.is_enabled()
        ]
        if len(buttons) != 2:
            raise LookupError(f"Expected two progress-row action buttons, found {len(buttons)}")
        buttons.sort(key=lambda item: item.rectangle().left)
        buttons[0].click_input()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not details.is_visible():
            time.sleep(0.05)
    if not details.is_visible():
        raise RuntimeError("XQ did not expose the per-product progress list")
    return [
        normalized(details.get_item(row, 1).text())
        for row in range(details.item_count())
    ]


def completed_product_count(states: Sequence[str]) -> int:
    terminal = re.compile(r"完成|成功|失敗|錯誤|終止|取消")
    return sum(1 for state in states if terminal.search(normalized(state)))


def new_report_window(existing_handles: set[int]) -> Any | None:
    from pywinauto import Desktop

    for window in Desktop(backend="uia").windows():
        try:
            if (
                window.handle not in existing_handles
                and window.is_visible()
                and window.class_name() == "#32770"
                and report_elements(window) is not None
            ):
                return window
        except Exception:
            continue
    return None


def new_report_seen(existing_handles: set[int]) -> bool:
    return new_report_window(existing_handles) is not None


def visible_report_windows() -> list[Any]:
    from pywinauto import Desktop

    reports = []
    for window in Desktop(backend="uia").windows():
        try:
            if not window.is_visible() or window.class_name() != "#32770":
                continue
            elements = report_elements(window)
            if elements is None:
                continue
            reports.append(window)
        except Exception:
            continue
    return reports


def visible_report_handles() -> set[int]:
    return {int(window.handle) for window in visible_report_windows()}


def visible_report_evidence() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for window in visible_report_windows():
        try:
            elements = report_elements(window)
            if elements is None:
                continue
            summary = report_summary(elements)
            reports.append(
                {
                    "window_handle": int(window.handle),
                    "summary_available": summary is not None,
                    "classification": classify_report(summary) if summary is not None else None,
                    "success_count": summary.success_count if summary is not None else None,
                    "failure_count": summary.failure_count if summary is not None else None,
                    "total_trades": summary.total_trades if summary is not None else None,
                }
            )
        except Exception:
            continue
    return reports


def inspect_recovery_status(
    config_path: Path,
    config: dict[str, Any],
    runtime_probe: Callable[[dict[str, Any], int | None], RuntimeSnapshot] = capture_runtime_snapshot,
    progress_probe: Callable[[], Any | None] = visible_progress_window,
    report_probe: Callable[[], list[dict[str, Any]]] = visible_report_evidence,
    process_probe: Callable[[int | None], bool] = process_is_running,
) -> dict[str, Any]:
    checkpoint_file = recovery_path(config_path)
    checkpoint = None
    checkpoint_error = None
    inspection_errors: list[str] = []
    try:
        checkpoint = load_checkpoint(checkpoint_file)
    except Exception as exc:
        checkpoint_error = f"{type(exc).__name__}: {exc}"

    expected_process_id = checkpoint.xq_process_id if checkpoint is not None else None
    try:
        snapshot = runtime_probe(config, expected_process_id)
    except Exception as exc:
        inspection_errors.append(f"runtime: {type(exc).__name__}: {exc}")
        snapshot = RuntimeSnapshot(
            captured_at=utc_timestamp(),
            expected_xq_process_id=expected_process_id,
            xq_process_id=None,
            xq_process_exists=False,
            xq_window_handle=None,
            xq_window_exists=False,
            xq_window_visible=False,
            xq_window_enabled=False,
            xq_window_hung=None,
            xscript_window_handle=None,
            xscript_window_exists=False,
            xscript_window_visible=False,
            xscript_window_enabled=False,
            xscript_window_hung=None,
        )

    try:
        progress = progress_probe()
        progress_visible = progress is not None
        progress_handle = int(progress.handle) if progress is not None else None
    except Exception as exc:
        inspection_errors.append(f"progress: {type(exc).__name__}: {exc}")
        progress_visible = False
        progress_handle = None

    try:
        reports = report_probe()
    except Exception as exc:
        inspection_errors.append(f"reports: {type(exc).__name__}: {exc}")
        reports = []

    saved_process_running = None
    if checkpoint is not None:
        try:
            saved_process_running = process_probe(checkpoint.xq_process_id)
        except Exception as exc:
            inspection_errors.append(f"process: {type(exc).__name__}: {exc}")

    assessment = assess_recovery_state(
        checkpoint=checkpoint,
        checkpoint_error=checkpoint_error,
        snapshot=snapshot,
        visible_progress=progress_visible,
        saved_process_running=saved_process_running,
        inspection_errors=inspection_errors,
    )
    return {
        "mode": "recovery_status",
        "read_only": True,
        "evaluated_at": utc_timestamp(),
        "decision": assessment.decision,
        "reason_codes": list(assessment.reason_codes),
        "recommended_action": assessment.recommended_action,
        "checkpoint_present": checkpoint_file.exists(),
        "checkpoint_valid": checkpoint is not None if checkpoint_file.exists() else None,
        "checkpoint": asdict(checkpoint) if checkpoint is not None else None,
        "checkpoint_error": checkpoint_error,
        "saved_process_running": saved_process_running,
        "visible_progress": progress_visible,
        "progress_window_handle": progress_handle,
        "visible_report_count": len(reports),
        "visible_reports": reports,
        "report_checkpoint_association_proven": False,
        "runtime": runtime_evidence(snapshot),
        "inspection_errors": inspection_errors,
        "automatic_replay_allowed": False,
    }


def xscript_is_ready() -> bool:
    from pywinauto import Desktop

    try:
        window = Desktop(backend="uia").window(title_re="^XScript.*")
        return window.exists(timeout=0.2) and window.is_visible() and window.is_enabled()
    except Exception:
        return False


def cancellation_recovery_complete(evidence: CancellationEvidence) -> bool:
    return (
        evidence.progress_closed
        and evidence.xscript_ready
        and evidence.partial_results_request_succeeded
        and evidence.partial_report_seen == evidence.partial_results_requested
    )


def cancellation_recovery_timeout(show_partial_results: bool) -> float:
    if show_partial_results:
        return PARTIAL_REPORT_RECOVERY_TIMEOUT_SECONDS
    return CANCELLATION_RECOVERY_TIMEOUT_SECONDS


def cancel_progress(
    progress: Any,
    existing_handles: set[int],
    timeout: float,
    show_partial_results: bool,
) -> CancellationEvidence:
    content = control_by_id(progress, 3001)
    buttons = [item for item in content.descendants() if item.class_name() == "Button" and item.is_visible() and item.is_enabled()]
    if len(buttons) != 2:
        raise LookupError(f"Expected two progress-row action buttons, found {len(buttons)}")
    buttons.sort(key=lambda item: item.rectangle().left)
    buttons[-1].click_input()

    confirmation = visible_dialog_with_control(3003, timeout, exclude_handle=progress.handle)
    partial_results = control_by_id(confirmation, 3003)
    desired_state = 1 if show_partial_results else 0
    if partial_results.get_check_state() != desired_state:
        partial_results.click_input()
    actual_state = partial_results.get_check_state()
    request_succeeded = actual_state == desired_state
    if not request_succeeded and not show_partial_results:
        raise RuntimeError("XQ did not retain the requested partial-result display state")
    control_by_id(confirmation, 1).click_input()

    deadline = time.monotonic() + timeout
    progress_closed = False
    ready = False
    while time.monotonic() < deadline:
        try:
            progress_closed = not progress.is_visible()
        except Exception:
            progress_closed = True
        ready = xscript_is_ready()
        if progress_closed and ready:
            break
        time.sleep(0.1)
    partial_report = None
    grace_deadline = time.monotonic() + (timeout if show_partial_results else 1.0)
    while time.monotonic() < grace_deadline:
        partial_report = new_report_window(existing_handles)
        if partial_report is not None:
            break
        time.sleep(0.1)
    summary = None
    if partial_report is not None:
        elements = report_elements(partial_report)
        if elements is not None:
            summary = report_summary(elements)
    return CancellationEvidence(
        confirmation_seen=True,
        partial_results_requested=bool(actual_state),
        partial_results_request_succeeded=request_succeeded,
        progress_closed=progress_closed,
        xscript_ready=ready,
        partial_report_seen=partial_report is not None,
        partial_report_summary_available=summary is not None,
        partial_success_count=summary.success_count if summary is not None else None,
        partial_failure_count=summary.failure_count if summary is not None else None,
        partial_total_trades=summary.total_trades if summary is not None else None,
    )


def run_and_monitor(
    settings_window: Any,
    timeout: float,
    cancel_on_timeout: bool,
    cancel_after_seconds: float | None = None,
    show_partial_results_on_cancel: bool = False,
    cancel_after_completed_products: int | None = None,
    runtime_probe: Callable[[], RuntimeSnapshot] | None = None,
    checkpoint_callback: Callable[[str, int | None, bool], None] | None = None,
    baseline_report_handles: set[int] | None = None,
) -> tuple[str, dict[str, Any]]:
    from pywinauto import Desktop

    existing_handles = current_top_level_handles()
    report_baseline = set(baseline_report_handles or ())
    if not report_baseline:
        report_baseline = visible_report_handles()
    existing_handles.update(report_baseline)
    progress_seen = False
    control_by_id(settings_window, 2033).click_input()
    if checkpoint_callback is not None:
        checkpoint_callback("running", None, False)
    started_at = time.monotonic()
    deadline = time.monotonic() + timeout
    next_runtime_heartbeat = started_at
    checkpoint_progress_handle = None
    while time.monotonic() < deadline:
        now = time.monotonic()
        if runtime_probe is not None and now >= next_runtime_heartbeat:
            snapshot = runtime_probe()
            failure_kind = classify_runtime_interruption(snapshot)
            if failure_kind is not None:
                if checkpoint_callback is not None:
                    checkpoint_callback("interrupted", checkpoint_progress_handle, False)
                return "environment_interruption", {
                    "failure_kind": failure_kind,
                    "last_safe_stage": "running",
                    "progress_seen": progress_seen,
                    "recovery_checkpoint_retained": True,
                    "runtime": runtime_evidence(snapshot),
                }
            next_runtime_heartbeat = now + RUNTIME_HEARTBEAT_SECONDS
        progress = visible_progress_window(existing_handles)
        progress_seen = progress_seen or progress is not None
        if progress is not None and checkpoint_progress_handle is None:
            checkpoint_progress_handle = int(progress.handle)
            if checkpoint_callback is not None:
                checkpoint_callback("running", checkpoint_progress_handle, False)
        for window in Desktop(backend="uia").windows():
            try:
                if window.handle in existing_handles or not window.is_visible() or window.class_name() != "#32770":
                    continue
                elements = report_elements(window)
                if elements is not None:
                    summary = report_summary(elements)
                    if summary is None:
                        continue
                    status = classify_report(summary)
                    evidence: dict[str, Any] = {
                        "report_window_handle": int(window.handle),
                        "success_count": summary.success_count,
                        "failure_count": summary.failure_count,
                        "total_trades": summary.total_trades,
                        "progress_seen": progress_seen,
                    }
                    if summary.failure_count > 0:
                        try:
                            details = extract_failure_details(window, summary.failure_count)
                            evidence["failure_details"] = [asdict(item) for item in details]
                        except Exception as exc:
                            evidence["failure_details"] = []
                            evidence["failure_detail_capture_error"] = f"{type(exc).__name__}: {exc}"
                    return status, evidence
                names = [normalized(item.element_info.name) for item in window.descendants()]
                if any(re.search(r"錯誤|失敗|無法|異常", name) for name in names):
                    return "failure", {"progress_seen": progress_seen, "error_dialog_seen": True}
            except Exception:
                continue
        elapsed = time.monotonic() - started_at
        completed_before_cancel = None
        cancel_for_completed_products = False
        progress_states_before_cancel = None
        if cancel_after_completed_products is not None and progress is not None:
            states = progress_product_states(progress)
            progress_states_before_cancel = states
            completed_before_cancel = completed_product_count(states)
            cancel_for_completed_products = (
                completed_before_cancel >= cancel_after_completed_products
                and completed_before_cancel < len(states)
            )
        if progress is not None and (
            (cancel_after_seconds is not None and elapsed >= cancel_after_seconds)
            or cancel_for_completed_products
        ):
            if progress_states_before_cancel is None:
                progress_states_before_cancel = progress_product_states(progress)
                completed_before_cancel = completed_product_count(progress_states_before_cancel)
            if checkpoint_callback is not None:
                checkpoint_callback("cancelling", checkpoint_progress_handle, False)
            cancellation = cancel_progress(
                progress,
                existing_handles,
                cancellation_recovery_timeout(show_partial_results_on_cancel),
                show_partial_results_on_cancel,
            )
            cancellation_data = asdict(cancellation)
            cancellation_data["recovery_complete"] = cancellation_recovery_complete(cancellation)
            if checkpoint_callback is not None:
                checkpoint_callback("cancelling", checkpoint_progress_handle, True)
            return "cancelled", {
                "progress_seen": progress_seen,
                "cancelled_by_tool": True,
                "cancel_reason": "requested",
                "cancel_after_seconds": cancel_after_seconds,
                "cancel_after_completed_products": cancel_after_completed_products,
                "completed_products_before_cancel": completed_before_cancel,
                "progress_states_before_cancel": progress_states_before_cancel,
                **cancellation_data,
            }
        time.sleep(0.2)

    progress = visible_progress_window(existing_handles)
    if cancel_on_timeout and progress is not None:
        if checkpoint_callback is not None:
            checkpoint_callback("cancelling", int(progress.handle), False)
        cancellation = cancel_progress(
            progress,
            existing_handles,
            cancellation_recovery_timeout(show_partial_results_on_cancel),
            show_partial_results_on_cancel,
        )
        cancellation_data = asdict(cancellation)
        cancellation_data["recovery_complete"] = cancellation_recovery_complete(cancellation)
        if checkpoint_callback is not None:
            checkpoint_callback("cancelling", int(progress.handle), True)
        return "cancelled", {
            "progress_seen": progress_seen,
            "cancelled_by_tool": True,
            "cancel_reason": "timeout",
            "timeout_seconds": timeout,
            **cancellation_data,
        }
    return "indeterminate_timeout", {
        "progress_seen": progress_seen,
        "cancelled_by_tool": False,
        "timeout_seconds": timeout,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--recovery-status", action="store_true")
    parser.add_argument("--product", action="append")
    parser.add_argument("--frequency", choices=FREQUENCIES)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--preload-records", type=int, default=1)
    parser.add_argument("--initial-capital-wan", default="100")
    parser.add_argument("--max-position", type=int, default=1)
    parser.add_argument("--max-entries-per-day", type=int, default=1)
    parser.add_argument("--max-trades-per-minute", type=int, default=1)
    parser.add_argument("--price-basis", choices=PRICE_BASES, default="original")
    parser.add_argument("--buy-price", choices=PRICE_MODES, default="trigger")
    parser.add_argument("--sell-price", choices=PRICE_MODES, default="trigger")
    parser.add_argument("--buy-offset", type=int, default=0)
    parser.add_argument("--sell-offset", type=int, default=0)
    parser.add_argument("--stock-fee-percent", default="0.2")
    parser.add_argument("--futures-fee", default="100")
    parser.add_argument("--simulate-ticks", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--daily-position-reset", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fill-on-trigger", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-print", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--us-all-sessions", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--direct-order", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--cancel-on-timeout", action="store_true")
    parser.add_argument("--cancel-after-seconds", type=float)
    parser.add_argument("--cancel-after-completed-products", type=int)
    parser.add_argument("--show-partial-results-on-cancel", action="store_true")
    parser.add_argument("--acknowledge-stale-checkpoint", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> BacktestSettings:
    missing = [
        label
        for label, value in (
            ("--product", args.product),
            ("--frequency", args.frequency),
            ("--start-date", args.start_date),
            ("--end-date", args.end_date),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"Required backtest arguments are missing: {', '.join(missing)}")
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date)
    if start_date > end_date:
        raise ValueError("--start-date must not be later than --end-date")
    if args.preload_records < 0:
        raise ValueError("--preload-records must not be negative")
    for label, value in (
        ("--max-position", args.max_position),
        ("--max-entries-per-day", args.max_entries_per_day),
        ("--max-trades-per-minute", args.max_trades_per_minute),
    ):
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.cancel_after_seconds is not None and args.cancel_after_seconds < 0:
        raise ValueError("--cancel-after-seconds must not be negative")
    if args.cancel_after_seconds is not None and args.cancel_after_seconds >= args.timeout_seconds:
        raise ValueError("--cancel-after-seconds must be less than --timeout-seconds")
    if args.cancel_after_seconds is not None and args.cancel_on_timeout:
        raise ValueError("--cancel-after-seconds and --cancel-on-timeout are mutually exclusive")
    if args.cancel_after_completed_products is not None and args.cancel_after_completed_products <= 0:
        raise ValueError("--cancel-after-completed-products must be positive")
    cancellation_choices = sum(
        option is not None
        for option in (args.cancel_after_seconds, args.cancel_after_completed_products)
    ) + int(args.cancel_on_timeout)
    if cancellation_choices > 1:
        raise ValueError("Choose only one cancellation trigger")
    if args.dry_run and cancellation_choices:
        raise ValueError("Cancellation options are not valid with --dry-run")
    if args.show_partial_results_on_cancel and not cancellation_choices:
        raise ValueError("--show-partial-results-on-cancel requires a cancellation option")
    products = tuple(validate_product(product) for product in args.product)
    if len(products) > 20:
        raise ValueError("At most 20 --product values are supported")
    if len(set(products)) != len(products):
        raise ValueError("Duplicate --product values are not allowed")
    return BacktestSettings(
        products=products,
        frequency=args.frequency,
        start_date=start_date,
        end_date=end_date,
        preload_records=args.preload_records,
        initial_capital_wan=decimal_text(args.initial_capital_wan, "--initial-capital-wan"),
        max_position=args.max_position,
        max_entries_per_day=args.max_entries_per_day,
        max_trades_per_minute=args.max_trades_per_minute,
        price_basis=args.price_basis,
        buy_price=args.buy_price,
        sell_price=args.sell_price,
        buy_offset=args.buy_offset,
        sell_offset=args.sell_offset,
        stock_fee_percent=decimal_text(args.stock_fee_percent, "--stock-fee-percent"),
        futures_fee=decimal_text(args.futures_fee, "--futures-fee"),
        simulate_ticks=args.simulate_ticks,
        daily_position_reset=args.daily_position_reset,
        fill_on_trigger=args.fill_on_trigger,
        enable_print=args.enable_print,
        us_all_sessions=args.us_all_sessions,
        direct_order=args.direct_order,
    )


def validate_recovery_status_args(args: argparse.Namespace) -> None:
    incompatible = []
    for label, present in (
        ("--product", args.product is not None),
        ("--frequency", args.frequency is not None),
        ("--start-date", args.start_date is not None),
        ("--end-date", args.end_date is not None),
        ("--dry-run", args.dry_run),
        ("--acknowledge-stale-checkpoint", args.acknowledge_stale_checkpoint),
        ("--cancel-on-timeout", args.cancel_on_timeout),
        ("--cancel-after-seconds", args.cancel_after_seconds is not None),
        ("--cancel-after-completed-products", args.cancel_after_completed_products is not None),
        ("--show-partial-results-on-cancel", args.show_partial_results_on_cancel),
    ):
        if present:
            incompatible.append(label)
    if incompatible:
        raise ValueError(
            "--recovery-status is read-only and cannot be combined with: " + ", ".join(incompatible)
        )


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    config = None
    tracked_xq_process_id = None
    checkpoint = None
    checkpoint_file = None
    try:
        args = parse_args(argv)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if args.recovery_status:
            validate_recovery_status_args(args)
            evidence = inspect_recovery_status(args.config, config)
            return emit("success", "XQ recovery status inspected without changing XQ or local state", **evidence)
        settings = settings_from_args(args)
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")

        checkpoint_file = recovery_path(args.config)
        stale_checkpoint_cleared = False
        try:
            stale_checkpoint = load_checkpoint(checkpoint_file)
        except Exception as exc:
            return emit(
                "environment_interruption",
                "The local XQ recovery checkpoint is invalid and must be inspected",
                failure_kind="checkpoint_invalid",
                recovery_checkpoint_retained=True,
                checkpoint_error=f"{type(exc).__name__}: {exc}",
            )
        if stale_checkpoint is not None:
            progress_visible = visible_progress_window() is not None
            stale_action = reconcile_stale_checkpoint(
                stale_checkpoint,
                process_is_running(stale_checkpoint.xq_process_id),
                progress_visible,
            )
            if stale_action == "block" and not (
                args.acknowledge_stale_checkpoint and not progress_visible
            ):
                return emit(
                    "environment_interruption",
                    "A previous XQ backtest recovery checkpoint still requires reconciliation",
                    failure_kind="stale_checkpoint",
                    recovery_checkpoint_retained=True,
                    recovery_run_id=stale_checkpoint.run_id,
                    checkpoint_stage=stale_checkpoint.stage,
                    checkpoint_backtest_started=stale_checkpoint.backtest_started,
                    saved_process_running=process_is_running(stale_checkpoint.xq_process_id),
                    visible_progress=progress_visible,
                )
            remove_checkpoint(checkpoint_file)
            stale_checkpoint_cleared = True

        baseline_snapshot = capture_runtime_snapshot(config)
        tracked_xq_process_id = baseline_snapshot.expected_xq_process_id
        baseline_failure = classify_runtime_interruption(baseline_snapshot)
        if baseline_failure is not None:
            return emit(
                "environment_interruption",
                "XQ is not in a safe state for a new backtest",
                failure_kind=baseline_failure,
                last_safe_stage="preflight",
                recovery_checkpoint_retained=False,
                runtime=runtime_evidence(baseline_snapshot),
            )

        settings_window = open_backtest_settings(config)
        settings_evidence = apply_settings(
            settings_window,
            settings,
            float(config.get("connect_timeout_seconds", 15)),
        )
        if args.dry_run:
            control_by_id(settings_window, 2034).click_input()
            settings_window = None
            return emit(
                "success",
                "XQ backtest settings verified and cancelled",
                dry_run=True,
                stale_checkpoint_cleared=stale_checkpoint_cleared,
                settings_evidence=settings_evidence,
            )

        if visible_progress_window() is not None:
            raise RuntimeError("A visible XQ backtest job already exists")
        start_snapshot = capture_runtime_snapshot(config, tracked_xq_process_id)
        start_failure = classify_runtime_interruption(start_snapshot)
        if start_failure is not None:
            control_by_id(settings_window, 2034).click_input()
            settings_window = None
            return emit(
                "environment_interruption",
                "XQ changed state before the backtest could start",
                failure_kind=start_failure,
                last_safe_stage="settings_ready",
                recovery_checkpoint_retained=False,
                runtime=runtime_evidence(start_snapshot),
            )
        baseline_report_handles = visible_report_handles()
        checkpoint = create_checkpoint(start_snapshot, baseline_report_handles)
        write_checkpoint(checkpoint_file, checkpoint)

        def checkpoint_callback(stage: str, progress_handle: int | None, cancellation_confirmed: bool) -> None:
            nonlocal checkpoint
            if checkpoint is None or checkpoint_file is None:
                raise RuntimeError("Recovery checkpoint was not initialized")
            checkpoint = update_checkpoint(
                checkpoint,
                stage=stage,
                progress_window_handle=progress_handle,
                cancellation_confirmed=cancellation_confirmed,
            )
            write_checkpoint(checkpoint_file, checkpoint)

        active_settings_window = settings_window
        settings_window = None
        status, evidence = run_and_monitor(
            active_settings_window,
            args.timeout_seconds,
            args.cancel_on_timeout,
            args.cancel_after_seconds,
            args.show_partial_results_on_cancel,
            args.cancel_after_completed_products,
            runtime_probe=lambda: capture_runtime_snapshot(config, tracked_xq_process_id),
            checkpoint_callback=checkpoint_callback,
            baseline_report_handles=baseline_report_handles,
        )
        if status in {"success", "failure", "partial_failure", "cancelled"}:
            remove_checkpoint(checkpoint_file)
            evidence["recovery_checkpoint_retained"] = False
        else:
            evidence["recovery_checkpoint_retained"] = True
            evidence["recovery_run_id"] = checkpoint.run_id
        evidence["stale_checkpoint_cleared"] = stale_checkpoint_cleared
        evidence["settings_evidence"] = settings_evidence
        messages = {
            "success": "XQ backtest report classified as successful",
            "failure": "XQ backtest report contains only failed products",
            "partial_failure": "XQ backtest report contains successful and failed products",
            "indeterminate_timeout": "Backtest did not reach a conclusive report before the timeout",
            "cancelled": "Backtest was cancelled and the XQ UI recovery state was checked",
            "environment_interruption": "The XQ runtime changed state while the backtest was running",
        }
        return emit(status, messages[status], **evidence)
    except Exception as exc:
        if settings_window is not None:
            try:
                control_by_id(settings_window, 2034).click_input()
            except Exception:
                pass
        runtime = None
        failure_kind = None
        if config is not None and tracked_xq_process_id is not None:
            try:
                runtime = capture_runtime_snapshot(config, tracked_xq_process_id)
                failure_kind = classify_runtime_interruption(runtime)
            except Exception:
                runtime = None
        if checkpoint is not None and checkpoint_file is not None:
            last_safe_stage = checkpoint.stage
            try:
                checkpoint = update_checkpoint(checkpoint, stage="interrupted")
                write_checkpoint(checkpoint_file, checkpoint)
            except Exception:
                pass
        else:
            last_safe_stage = "preflight"
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "The XQ runtime was interrupted during backtest automation",
                failure_kind=failure_kind,
                last_safe_stage=last_safe_stage,
                recovery_checkpoint_retained=checkpoint is not None,
                recovery_run_id=checkpoint.run_id if checkpoint is not None else None,
                runtime=runtime_evidence(runtime) if runtime is not None else None,
                automation_exception=f"{type(exc).__name__}: {exc}",
            )
        return emit(
            "automation_error",
            f"XQ backtest automation failed: {type(exc).__name__}: {exc}",
            recovery_checkpoint_retained=checkpoint is not None,
            recovery_run_id=checkpoint.run_id if checkpoint is not None else None,
        )


if __name__ == "__main__":
    sys.exit(main())
