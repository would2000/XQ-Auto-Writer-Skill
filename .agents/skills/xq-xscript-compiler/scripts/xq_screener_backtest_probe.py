#!/usr/bin/env python3
"""Open if requested, then read an XQ screener backtest dialog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import xq_backtest
import xq_screener_backtest


CONTROL_IDS = (
    2003,
    2004,
    2005,
    2014,
    2033,
    2034,
    2061,
    2062,
    2063,
    2064,
    2065,
    2066,
    2091,
    2092,
    2093,
    2094,
    2095,
    2121,
    2122,
    2123,
    2124,
    2131,
    2200,
    2201,
)
PRIVATE_SCOPE_CONTROL_ID = 2094


def emit(status: str, message: str, **extra: Any) -> int:
    print(
        json.dumps(
            {"status": status, "message": message, **extra},
            ensure_ascii=False,
        )
    )
    return 0 if status == "success" else 3


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--open-settings", action="store_true")
    return parser.parse_args(argv)


def public_control_text(control_id: int, text: str) -> tuple[str, bool]:
    normalized = xq_backtest.normalized(text)
    if control_id != PRIVATE_SCOPE_CONTROL_ID:
        return normalized, False
    if not normalized or normalized.endswith("(系統)"):
        return normalized, False
    return "<private-scope-redacted>", True


def control_evidence(window: Any, control_id: int) -> dict[str, Any]:
    matches = [
        item for item in window.descendants() if item.control_id() == control_id
    ]
    if len(matches) != 1:
        return {"control_id": control_id, "match_count": len(matches)}
    control = matches[0]
    text, redacted = public_control_text(control_id, control.window_text())
    evidence: dict[str, Any] = {
        "control_id": control_id,
        "match_count": 1,
        "class_name": control.class_name(),
        "visible": bool(control.is_visible()),
        "enabled": bool(control.is_enabled()),
        "text": text,
        "private_text_redacted": redacted,
    }
    try:
        evidence["check_state"] = int(control.get_check_state())
    except Exception:
        evidence["check_state"] = None
    try:
        value = control.get_time()
        evidence["date"] = (
            f"{value.wYear:04d}-{value.wMonth:02d}-{value.wDay:02d}"
        )
    except Exception:
        evidence["date"] = None
    return evidence


def active_screener_title() -> dict[str, Any]:
    from pywinauto import Desktop

    xscript = Desktop(backend="win32").window(
        title_re="^XScript.*"
    ).wrapper_object()
    title = xq_backtest.normalized(xscript.window_text())
    if re.search(r"\((?:選股)\)", title) is None:
        raise RuntimeError("The active XScript document is not a screener script")
    if "未編譯" in title:
        raise RuntimeError("The active screener script is uncompiled")
    match = re.search(r"\[([^\[\]]+?)\(選股\)", title)
    if match is None:
        raise RuntimeError("The active screener script name could not be read")
    return {
        "script_name": xq_backtest.normalized(match.group(1)),
        "active_title": title,
        "uncompiled_marker_present": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        runtime = xq_backtest.capture_runtime_snapshot(config)
        failure_kind = xq_backtest.classify_runtime_interruption(runtime)
        if failure_kind is not None:
            return emit(
                "automation_error",
                "XQ is not healthy enough for read-only screener calibration",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(runtime),
            )
        foreground_records: list[dict[str, Any]] = []
        if args.open_settings:
            window = xq_screener_backtest.open_screener_backtest_settings(
                config,
                foreground_records=foreground_records,
            )
        else:
            window = xq_screener_backtest.preopened_screener_settings()
        return emit(
            "success",
            "Screener backtest settings inspected after the requested open action",
            read_only_after_open=True,
            settings_opened_by_tool=bool(args.open_settings),
            foreground_guard=xq_backtest.summarize_foreground_guards(
                foreground_records
            ) if args.open_settings else None,
            private_scope_text_persisted=False,
            active_script=active_screener_title(),
            settings_window={
                "window_handle": int(window.handle),
                "visible": bool(window.is_visible()),
                "enabled": bool(window.is_enabled()),
                "hung": xq_backtest.window_is_hung(int(window.handle)),
            },
            controls=[control_evidence(window, value) for value in CONTROL_IDS],
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"Screener backtest inspection failed: {type(exc).__name__}: {exc}",
            read_only_after_open=True,
            private_scope_text_persisted=False,
        )


if __name__ == "__main__":
    sys.exit(main())
