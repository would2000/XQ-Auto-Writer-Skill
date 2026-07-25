#!/usr/bin/env python3
"""Fail closed unless the requested XScript formula category is already active."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path
from typing import Any

import xq_category_observer


SCRIPT_TYPES = {"indicator", "screener", "alert", "autotrade", "function"}


class CategorySelectorError(RuntimeError):
    """A category selector contract or readback that is unsafe to use."""


def emit(status: str, message: str, **extra: Any) -> int:
    payload = {"status": status, "message": message, **extra}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if status == "success" else 3


def load_contract(config: dict[str, Any]) -> dict[str, Any]:
    root = config.get("formula_category_switch")
    if not isinstance(root, dict):
        raise CategorySelectorError(
            "formula_category_switch is not calibrated; refusing category input"
        )
    method = root.get("method")
    if method != "manual_only":
        raise CategorySelectorError(
            "Only the verified manual_only category method is authorized"
        )
    raw_map = root.get("pane_control_ids")
    if not isinstance(raw_map, dict) or set(raw_map) != SCRIPT_TYPES:
        raise CategorySelectorError(
            "pane_control_ids must contain exactly the five script types"
        )
    pane_control_ids: dict[str, int] = {}
    for script_type, value in raw_map.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise CategorySelectorError(
                f"Invalid pane control id for {script_type}"
            )
        pane_control_ids[script_type] = value
    if len(set(pane_control_ids.values())) != len(SCRIPT_TYPES):
        raise CategorySelectorError("Formula pane control ids must be unique")
    if root.get("automatic_switch_available") is not False:
        raise CategorySelectorError(
            "automatic_switch_available must remain false without a semantic command"
        )
    return {
        "method": method,
        "pane_control_ids": pane_control_ids,
        "automatic_switch_available": False,
    }


def evaluate_category_request(
    evidence: dict[str, Any],
    requested_type: str,
    pane_control_ids: dict[str, int],
) -> dict[str, Any]:
    inverse = {value: key for key, value in pane_control_ids.items()}
    pane_id = evidence.get("formula_pane_control_id")
    active_type = inverse.get(pane_id)
    common = {
        "requested_type": requested_type,
        "active_type": active_type,
        "active_pane_control_id": pane_id,
        "automatic_switch_available": False,
        "input_sent": False,
        "coordinate_use": False,
    }
    if (
        evidence.get("visible_formula_pane_count") != 1
        or evidence.get("visible_tree_count") != 1
        or active_type is None
    ):
        return {
            **common,
            "status": "automation_error",
            "reason_code": "active_category_readback_not_unique",
            "manual_switch_required": True,
        }
    if active_type != requested_type:
        return {
            **common,
            "status": "automation_error",
            "reason_code": "manual_switch_required",
            "manual_switch_required": True,
        }
    if (
        evidence.get("custom_root_count") != 1
        or evidence.get("codex_direct_child_count") != 1
    ):
        return {
            **common,
            "status": "automation_error",
            "reason_code": "codex_scope_readback_not_unique",
            "manual_switch_required": False,
        }
    return {
        **common,
        "status": "success",
        "reason_code": "requested_category_already_active",
        "manual_switch_required": False,
        "codex_scope_verified": True,
        "codex_location": "自訂/CODEX/",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            raise CategorySelectorError(
                "XQ UI configuration is not calibrated"
            )
        contract = load_contract(config)

        from pywinauto import Desktop

        windows = xq_category_observer.find_xscript(Desktop(backend="win32"))
        if len(windows) != 1:
            raise CategorySelectorError(
                f"Expected one visible XScript window, found {len(windows)}"
            )
        window = windows[0]
        if (
            not window.is_enabled()
            or ctypes.windll.user32.IsHungAppWindow(int(window.handle))
        ):
            raise CategorySelectorError(
                "XScript is disabled or not responding; no input was sent"
            )
        evidence = xq_category_observer.inspect_xscript(window)
        result = evaluate_category_request(
            evidence,
            args.script_type,
            contract["pane_control_ids"],
        )
        if result["status"] == "success":
            return emit(
                "success",
                "Requested XScript category and CODEX scope are already active",
                **{key: value for key, value in result.items() if key != "status"},
            )
        return emit(
            "automation_error",
            (
                "Manual XScript category switch is required; no stable semantic "
                "switch command is exposed by the current XQ version"
                if result["reason_code"] == "manual_switch_required"
                else "XScript category or CODEX scope readback is not unique"
            ),
            **{key: value for key, value in result.items() if key != "status"},
        )
    except (OSError, json.JSONDecodeError, CategorySelectorError) as exc:
        return emit(
            "automation_error",
            str(exc),
            automatic_switch_available=False,
            input_sent=False,
            coordinate_use=False,
        )


if __name__ == "__main__":
    sys.exit(main())
