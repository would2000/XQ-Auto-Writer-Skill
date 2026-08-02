#!/usr/bin/env python3
"""Switch to one XScript category and open an exact existing CODEX document."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path
from typing import Any

import xq_backtest
import xq_category_observer
import xq_category_selector as selector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(selector.SCRIPT_TYPES), required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--pace-level", type=int, choices=range(1, 11))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config: dict[str, Any] = {}
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            raise selector.CategorySelectorError("XQ UI configuration is not calibrated")
        name = selector.validate_script_name(args.script_name)
        contract = selector.load_contract(config, args.pace_level)

        from pywinauto import Desktop, mouse

        xq_backtest.configure_ui_pacing(config)
        windows = xq_category_observer.find_xscript(Desktop(backend="win32"))
        if len(windows) != 1:
            raise selector.CategorySelectorError(
                f"Expected one visible XScript window, found {len(windows)}"
            )
        window = windows[0]
        if not window.is_enabled() or ctypes.windll.user32.IsHungAppWindow(int(window.handle)):
            raise selector.CategorySelectorWaitError(
                "window_disabled_or_hung",
                "initial_health",
                evidence={"window_handle": int(window.handle)},
            )
        initial = selector.inspect_formula_context(window)
        initial_type = selector.active_type(initial.evidence, contract.pane_control_ids)
        if args.dry_run:
            if initial_type is None:
                raise selector.CategorySelectorError(
                    "The active category could not be read for dry-run"
                )
            pane_rect = initial.pane.rectangle()
            host_rect = initial.host.rectangle()
            visual = selector.detect_formula_tabs(
                initial.host.capture_as_image(),
                int(pane_rect.top - host_rect.top),
                contract.tab_order.index(initial_type),
                contract,
            )
            return selector.emit(
                "success",
                "XScript category switch/open plan inspected without input",
                dry_run=True,
                requested_type=args.script_type,
                requested_script_name=name,
                active_type=initial_type,
                would_switch=initial_type != args.script_type,
                would_open=not selector.verify_active_document(
                    window, name, args.script_type
                ),
                automatic_switch_available=True,
                input_sent=False,
                screenshot_persisted=False,
                visual_detection=visual,
                ui_pacing=contract.ui_pacing.evidence(),
            )
        switched = selector.switch_category(
            window,
            args.script_type,
            contract,
            foreground_guard=xq_backtest.ensure_window_foreground,
            clicker=mouse.click,
        )
        opened = selector.open_existing_codex_script(
            window,
            args.script_type,
            name,
            contract,
            foreground_guard=xq_backtest.ensure_window_foreground,
            double_clicker=mouse.double_click,
        )
        return selector.emit(
            "success",
            "Requested existing CODEX script is active",
            requested_type=args.script_type,
            category=switched,
            document=opened,
            screenshot_persisted=False,
            ui_pacing=contract.ui_pacing.evidence(),
        )
    except selector.CategorySelectorWaitError as exc:
        incident = None
        try:
            incident = selector.save_wait_incident(
                args.config, config, exc, args.script_type, args.script_name
            )
        except Exception:
            incident = None
        return selector.emit(
            "automation_error",
            str(exc),
            incident_path=str(incident) if incident is not None else None,
            further_input_sent=False,
        )
    except (OSError, json.JSONDecodeError, selector.CategorySelectorError) as exc:
        return selector.emit("automation_error", str(exc))
    except Exception as exc:
        return selector.emit(
            "automation_error",
            f"Unexpected open-script failure before verified completion: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    sys.exit(main())
