#!/usr/bin/env python3
"""Observe a user-driven XScript folder flow without sending UI input."""

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


TREE_CONTROL_ID = 45242
CUSTOM_PREFIX = "自訂 "
CODEX_PATTERN = re.compile(r"^CODEX(?:\s+\(\d+\))?$")
POPUP_CLASSES = {"XTPPopupBar", "#32768"}
PUBLIC_TEXTS = {
    "自訂",
    "系統",
    "CODEX",
    "新增",
    "新增資料夾",
    "刪除資料夾",
    "重新命名資料夾",
    "資料夾",
    "資料夾名稱",
    "名稱",
    "確定",
    "取消",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def public_text(value: Any) -> str:
    text = normalize(value)
    compact = re.sub(r"\(&.\)", "", text)
    compact = compact.replace("...", "").strip()
    if compact in PUBLIC_TEXTS:
        return compact
    if CODEX_PATTERN.fullmatch(compact):
        return compact
    if compact.startswith("新增資料夾"):
        return "新增資料夾"
    return ""


def is_exact_codex_tree_label(value: Any) -> bool:
    return CODEX_PATTERN.fullmatch(normalize(value)) is not None


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


def xscript_windows(desktop: Any) -> list[Any]:
    matches: list[Any] = []
    for window in desktop.windows():
        try:
            if normalize(window.window_text()).startswith("XScript"):
                matches.append(window)
        except Exception:
            continue
    return matches


def inspect_tree(window: Any) -> dict[str, Any]:
    trees = [
        item
        for item in window.descendants(class_name="SysTreeView32")
        if item.control_id() == TREE_CONTROL_ID and item.is_visible()
    ]
    evidence: dict[str, Any] = {
        "tree_control_id": TREE_CONTROL_ID,
        "visible_tree_count": len(trees),
        "custom_root_count": 0,
        "codex_direct_child_count": 0,
        "codex_readback": None,
    }
    if len(trees) != 1:
        return evidence
    roots = trees[0].roots()
    custom = [
        item for item in roots
        if normalize(item.text()).startswith(CUSTOM_PREFIX)
    ]
    evidence["custom_root_count"] = len(custom)
    if len(custom) != 1:
        return evidence
    matches = []
    for child in custom[0].children():
        text = normalize(child.text())
        if is_exact_codex_tree_label(text):
            matches.append(text)
    evidence["codex_direct_child_count"] = len(matches)
    evidence["codex_readback"] = matches[0] if len(matches) == 1 else None
    return evidence


def inspect_popup(window: Any) -> dict[str, Any]:
    from pywinauto import Desktop

    labels: list[str] = []
    item_count = 0
    try:
        root = Desktop(backend="uia").window(
            handle=int(window.handle),
        ).wrapper_object()
        items = root.descendants(control_type="MenuItem")
        item_count = len(items)
        for item in items:
            label = public_text(item.element_info.name)
            if label and label not in labels:
                labels.append(label)
    except Exception:
        pass
    return {
        "kind": "context_menu",
        "handle": int(window.handle),
        "class_name": window.class_name(),
        "menu_item_count": item_count,
        "public_menu_items": labels,
    }


def inspect_dialog(window: Any) -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    for item in window.descendants():
        try:
            text = normalize(item.window_text())
            controls.append({
                "class_name": item.class_name(),
                "control_id": item.control_id(),
                "visible": bool(item.is_visible()),
                "enabled": bool(item.is_enabled()),
                "public_text": public_text(text),
                "value_is_codex": bool(
                    item.class_name() == "Edit" and text == "CODEX"
                ),
            })
        except Exception:
            continue
    return {
        "kind": "dialog",
        "handle": int(window.handle),
        "class_name": window.class_name(),
        "public_title": public_text(window.window_text()),
        "controls": controls,
    }


def visible_transients(desktop: Any, xq_pid: int) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for window in desktop.windows():
        try:
            if not window.is_visible():
                continue
            class_name = window.class_name()
            if class_name in POPUP_CLASSES:
                snapshot = inspect_popup(window)
                if snapshot["public_menu_items"]:
                    snapshots.append(snapshot)
            elif class_name == "#32770" and window.process_id() == xq_pid:
                snapshot = inspect_dialog(window)
                if snapshot["public_title"] or any(
                    control["public_text"] or control["value_is_codex"]
                    for control in snapshot["controls"]
                ):
                    snapshots.append(snapshot)
        except Exception:
            continue
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    if args.poll_seconds < 0.1:
        parser.error("--poll-seconds must be at least 0.1")

    from pywinauto import Desktop

    events_path = Path(args.events).resolve()
    status_path = Path(args.status).resolve()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    if events_path.exists() or status_path.exists():
        raise SystemExit("observer output paths must not already exist")

    desktop = Desktop(backend="win32")
    started = time.monotonic()
    last_signature = ""
    last_tree_signature = ""
    codex_seen_at: float | None = None
    status: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": utc_now(),
        "read_only": True,
        "coordinate_use": False,
        "private_text_storage": False,
        "timeout_seconds": args.timeout_seconds,
        "poll_seconds": args.poll_seconds,
        "event_count": 0,
        "codex_verified": False,
    }
    atomic_write_json(status_path, status)

    while time.monotonic() - started < args.timeout_seconds:
        windows = xscript_windows(desktop)
        if len(windows) == 1:
            xscript = windows[0]
            xq_pid = xscript.process_id()
            tree = inspect_tree(xscript)
            tree_signature = json.dumps(tree, sort_keys=True, ensure_ascii=False)
            if tree_signature != last_tree_signature:
                append_event(events_path, {
                    "captured_at_utc": utc_now(),
                    "kind": "tree_state",
                    "evidence": tree,
                })
                status["event_count"] += 1
                last_tree_signature = tree_signature
            transients = visible_transients(desktop, xq_pid)
            signature = json.dumps(transients, sort_keys=True, ensure_ascii=False)
            if signature != last_signature and transients:
                append_event(events_path, {
                    "captured_at_utc": utc_now(),
                    "kind": "transient_state",
                    "windows": transients,
                })
                status["event_count"] += 1
                last_signature = signature
            if tree["codex_direct_child_count"] == 1:
                if codex_seen_at is None:
                    codex_seen_at = time.monotonic()
                status["codex_verified"] = True
                status["codex_readback"] = tree["codex_readback"]
                if time.monotonic() - codex_seen_at >= 3.0:
                    status["status"] = "success"
                    status["completed_at_utc"] = utc_now()
                    atomic_write_json(status_path, status)
                    return 0
            else:
                codex_seen_at = None
        time.sleep(args.poll_seconds)

    status["status"] = "timeout"
    status["completed_at_utc"] = utc_now()
    atomic_write_json(status_path, status)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
