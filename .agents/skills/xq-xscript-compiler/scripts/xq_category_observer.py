#!/usr/bin/env python3
"""Observe user-driven XScript formula-category changes without sending UI input."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORMULA_CONTAINER_ID = 1100
FORMULA_TAB_HOST_ID = 1000
FORMULA_PANE_IDS = {1, 2, 3, 4, 7}
TREE_CONTROL_ID = 45242
CUSTOM_PATTERN = re.compile(r"^自訂 \(\d+\)$")
CODEX_PATTERN = re.compile(r"^CODEX \(\d+\)$")
EXPECTED_MANUAL_ORDER = ["indicator", "screener", "alert", "autotrade", "function"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_event(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def ancestor_ids(control: Any, limit: int = 8) -> list[int]:
    values: list[int] = []
    current = control
    for _ in range(limit):
        current = current.parent()
        if current is None:
            break
        values.append(int(current.control_id()))
    return values


def is_formula_pane(control: Any) -> bool:
    if control.class_name() != "AfxWnd140":
        return False
    if int(control.control_id()) not in FORMULA_PANE_IDS:
        return False
    parent = control.parent()
    grandparent = parent.parent() if parent is not None else None
    return (
        parent is not None
        and int(parent.control_id()) == FORMULA_TAB_HOST_ID
        and grandparent is not None
        and int(grandparent.control_id()) == FORMULA_CONTAINER_ID
    )


def inspect_codex_scope(tree: Any) -> dict[str, Any]:
    custom_roots = [
        item for item in tree.roots()
        if CUSTOM_PATTERN.fullmatch(normalize(item.text()))
    ]
    codex_children: list[str] = []
    if len(custom_roots) == 1:
        codex_children = [
            normalize(child.text())
            for child in custom_roots[0].children()
            if CODEX_PATTERN.fullmatch(normalize(child.text()))
        ]
    return {
        "custom_root_count": len(custom_roots),
        "codex_direct_child_count": len(codex_children),
        "codex_readback": codex_children[0] if len(codex_children) == 1 else None,
    }


def inspect_xscript(window: Any) -> dict[str, Any]:
    panes = [
        item for item in window.descendants()
        if is_formula_pane(item) and item.is_visible()
    ]
    evidence: dict[str, Any] = {
        "visible_formula_pane_count": len(panes),
        "formula_pane_control_id": None,
        "visible_tree_count": 0,
        "tree_handle": None,
        "custom_root_count": 0,
        "codex_direct_child_count": 0,
        "codex_readback": None,
    }
    if len(panes) != 1:
        return evidence
    pane = panes[0]
    trees = [
        item for item in pane.descendants(class_name="SysTreeView32")
        if int(item.control_id()) == TREE_CONTROL_ID and item.is_visible()
    ]
    evidence["formula_pane_control_id"] = int(pane.control_id())
    evidence["visible_tree_count"] = len(trees)
    if len(trees) != 1:
        return evidence
    tree = trees[0]
    evidence["tree_handle"] = int(tree.handle)
    evidence.update(inspect_codex_scope(tree))
    return evidence


def find_xscript(desktop: Any) -> list[Any]:
    matches: list[Any] = []
    for window in desktop.windows():
        try:
            if window.is_visible() and normalize(window.window_text()).startswith("XScript"):
                matches.append(window)
        except Exception:
            continue
    return matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    parser.add_argument("--stable-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.poll_seconds < 0.25:
        parser.error("--poll-seconds must be at least 0.25")
    if args.stable_seconds < args.poll_seconds:
        parser.error("--stable-seconds must be at least --poll-seconds")

    events_path = args.events.resolve()
    status_path = args.status.resolve()
    if events_path.exists() or status_path.exists():
        raise SystemExit("observer output paths must not already exist")

    from pywinauto import Desktop

    desktop = Desktop(backend="win32")
    started = time.monotonic()
    candidate_signature = ""
    candidate_since = started
    recorded_signature = ""
    transition_count = 0
    status: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": utc_now(),
        "read_only": True,
        "coordinate_use": False,
        "private_text_storage": False,
        "expected_manual_order": EXPECTED_MANUAL_ORDER,
        "timeout_seconds": args.timeout_seconds,
        "poll_seconds": args.poll_seconds,
        "stable_seconds": args.stable_seconds,
        "transition_count": 0,
    }
    atomic_write_json(status_path, status)

    while time.monotonic() - started < args.timeout_seconds:
        windows = find_xscript(desktop)
        if len(windows) == 1:
            window = windows[0]
            evidence = inspect_xscript(window)
            signature = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
            if signature != candidate_signature:
                candidate_signature = signature
                candidate_since = time.monotonic()
            elif (
                signature != recorded_signature
                and time.monotonic() - candidate_since >= args.stable_seconds
            ):
                transition_count += 1
                append_event(events_path, {
                    "captured_at_utc": utc_now(),
                    "kind": "stable_formula_category_state",
                    "sequence": transition_count,
                    "xq_process_id": int(window.process_id()),
                    "xscript_handle": int(window.handle),
                    "xscript_enabled": bool(window.is_enabled()),
                    "xscript_hung": bool(
                        ctypes.windll.user32.IsHungAppWindow(int(window.handle))
                    ),
                    "evidence": evidence,
                })
                recorded_signature = signature
                status["transition_count"] = transition_count
                status["last_evidence"] = evidence
                atomic_write_json(status_path, status)
        time.sleep(args.poll_seconds)

    status["status"] = "completed"
    status["completed_at_utc"] = utc_now()
    atomic_write_json(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
