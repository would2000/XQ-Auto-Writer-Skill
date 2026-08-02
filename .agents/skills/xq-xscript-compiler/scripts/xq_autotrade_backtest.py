#!/usr/bin/env python3
"""Safely verify transient product scope in an XQ autotrade backtest window.

This adapter is deliberately scope-only and dry-run-only.  It opens the
active verified autotrade document's backtest settings, replaces only the
public per-product list, proves the final exact set, and cancels.  It never
starts a backtest or touches accounts, live orders, reports, or checkpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import xq_backtest
from xq_backtest_scope import BacktestScopeError, validate_explicit_products


EXIT_CODES = {"success": 0, "automation_error": 3, "environment_interruption": 3}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--product", action="append", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def open_autotrade_backtest_settings(
    config: dict[str, Any],
    *,
    foreground_records: list[dict[str, Any]] | None = None,
) -> Any:
    return xq_backtest.open_backtest_settings(
        config,
        foreground_records=foreground_records,
    )


def main(argv: Iterable[str] | None = None) -> int:
    settings_window = None
    input_stop_required = False
    foreground_records: list[dict[str, Any]] = []
    try:
        args = parse_args(argv)
        if not args.dry_run:
            raise ValueError(
                "Autotrade backtest scope verification currently requires --dry-run"
            )
        products = validate_explicit_products(args.product)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        recovery = xq_backtest.inspect_recovery_status(args.config, config)
        if recovery["decision"] != "safe_to_start":
            return emit(
                "environment_interruption",
                "A current XQ backtest recovery state blocks autotrade scope verification",
                recovery=recovery,
            )
        xq_backtest.configure_ui_pacing(config)
        runtime = xq_backtest.capture_runtime_snapshot(config)
        failure_kind = xq_backtest.classify_runtime_interruption(runtime)
        if failure_kind is not None:
            return emit(
                "environment_interruption",
                "XQ is not in a safe state for autotrade scope verification",
                failure_kind=failure_kind,
                runtime=xq_backtest.runtime_evidence(runtime),
            )
        settings_window = open_autotrade_backtest_settings(
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
            "XQ autotrade backtest product scope verified and cancelled",
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
        return emit("automation_error", f"Autotrade backtest scope validation failed: {exc}")
    except Exception as exc:
        input_stop_required = xq_backtest.input_must_stop(exc)
        return emit(
            "automation_error",
            f"XQ autotrade backtest scope automation failed: {type(exc).__name__}: {exc}",
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
