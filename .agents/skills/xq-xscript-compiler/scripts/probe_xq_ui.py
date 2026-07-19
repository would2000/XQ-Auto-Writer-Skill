#!/usr/bin/env python3
"""Dump a visible XQ/XScript UI Automation control tree for calibration."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, TextIO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title-re", default=r"^XScript.*")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-depth", type=int, default=30)
    return parser.parse_args()


def clean(value: Any) -> str:
    """Return a compact, single-line representation for a UIA property."""
    return " ".join(str(value or "").split())


def describe(wrapper: Any) -> tuple[str, dict[str, str]]:
    """Describe a UIAWrapper and provide reusable child_window selector fields."""
    info = wrapper.element_info
    title = clean(info.name)
    auto_id = clean(info.automation_id)
    control_type = clean(info.control_type)
    class_name = clean(info.class_name)
    selector = {
        key: value
        for key, value in {
            "title": title,
            "auto_id": auto_id,
            "control_type": control_type,
            "class_name": class_name,
        }.items()
        if value
    }
    properties = (
        f"title={title!r} auto_id={auto_id!r} control_type={control_type!r} "
        f"class_name={class_name!r} rectangle={info.rectangle!s}"
    )
    return properties, selector


def dump_tree(wrapper: Any, stream: TextIO, max_depth: int, depth: int = 0) -> None:
    """Recursively dump wrappers; UIAWrapper itself has no print_control_identifiers."""
    properties, selector = describe(wrapper)
    indent = "  " * depth
    stream.write(f"{indent}- {properties}\n")
    stream.write(f"{indent}  selector={json.dumps(selector, ensure_ascii=False)}\n")
    if depth >= max_depth:
        stream.write(f"{indent}  [maximum depth reached]\n")
        return
    try:
        children = wrapper.children()
    except Exception as exc:
        stream.write(f"{indent}  [children unavailable: {type(exc).__name__}: {exc}]\n")
        return
    for child in children:
        dump_tree(child, stream, max_depth, depth + 1)


def main() -> int:
    args = parse_args()
    try:
        from pywinauto import Desktop
    except ImportError:
        print(json.dumps({"status": "automation_error", "message": "pywinauto is not installed"}, ensure_ascii=False))
        return 3

    desktop = Desktop(backend="uia")
    windows = [window for window in desktop.windows() if window.is_visible()]
    try:
        title_pattern = re.compile(args.title_re, re.I)
    except re.error as exc:
        print(json.dumps({"status": "automation_error", "message": f"Invalid --title-re: {exc}"}, ensure_ascii=False))
        return 3
    matches = [window for window in windows if title_pattern.search(window.window_text())]
    if not matches:
        titles = [window.window_text() for window in windows if window.window_text()]
        print(json.dumps({"status": "automation_error", "message": "No matching visible window", "visible_titles": titles}, ensure_ascii=False))
        return 3

    if args.max_depth < 0:
        print(json.dumps({"status": "automation_error", "message": "--max-depth must be zero or greater"}, ensure_ascii=False))
        return 3

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        stream: TextIO = args.output.open("w", encoding="utf-8")
    else:
        stream = sys.stdout

    try:
        for index, window in enumerate(matches, start=1):
            stream.write(f"===== WINDOW {index}: {window.window_text()} =====\n")
            dump_tree(window, stream, args.max_depth)
    finally:
        if args.output:
            stream.close()

    if args.output:
        print(json.dumps({"status": "success", "output": str(args.output.resolve()), "windows": len(matches)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
