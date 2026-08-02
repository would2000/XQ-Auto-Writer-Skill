#!/usr/bin/env python3
"""Safely switch an XScript formula category and open one CODEX document.

XQ 3.19.03 does not expose the five owner-drawn category tabs through UIA,
MSAA, a native command, or a documented keyboard shortcut.  This module uses
an in-memory screenshot of the current formula host to locate the five tab
fills afresh on every switch.  The screenshot supplies only a local click
point; native control-tree readback remains the authority for the category and
the exact ``自訂/CODEX/`` scope.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

import xq_category_observer
import xq_ui_pacing


SCRIPT_TYPES = {"indicator", "screener", "alert", "autotrade", "function"}
TAB_ORDER = ("indicator", "screener", "alert", "autotrade", "function")
TYPE_LABELS = {
    "indicator": "指標",
    "screener": "選股",
    "alert": "警示",
    "autotrade": "交易",
    "function": "函數",
}
SCRIPT_NAME_RE = re.compile(r"^[^\\/:*?\"<>|\r\n]{1,80}$")


class CategorySelectorError(RuntimeError):
    """A selector contract or readback that is unsafe to use."""


class CategorySelectorWaitError(CategorySelectorError):
    """A late/timeout/health boundary after which no input may continue."""

    def __init__(self, kind: str, stage: str, *, evidence: Any = None):
        super().__init__(f"{kind} at {stage}")
        self.kind = kind
        self.stage = stage
        self.evidence = evidence


@dataclass(frozen=True)
class CategorySwitchContract:
    method: str
    pane_control_ids: dict[str, int]
    tab_order: tuple[str, ...]
    minimum_tab_width_ratio: float
    maximum_tab_width_ratio: float
    maximum_gap_pixels: int
    boundary_tolerance_pixels: int
    required_stable_rows: int
    inactive_color_tolerance: float
    active_color_minimum_distance: float
    poll_seconds: float
    late_after_seconds: float
    state_timeout_seconds: float
    action_settle_seconds: float
    ui_pacing: xq_ui_pacing.UiPacing


@dataclass(frozen=True)
class FormulaContext:
    window: Any
    pane: Any
    host: Any
    tree: Any
    custom_root: Any | None
    codex_root: Any | None
    evidence: dict[str, Any]


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def _number(value: Any, label: str, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CategorySelectorError(f"{label} must be numeric")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        suffix = f" and at most {maximum:g}" if maximum is not None else ""
        raise CategorySelectorError(f"{label} must be at least {minimum:g}{suffix}")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CategorySelectorError(f"{label} must be a positive integer")
    return value


def load_contract(config: dict[str, Any], requested_pace_level: int | None = None) -> CategorySwitchContract:
    root = config.get("formula_category_switch")
    if not isinstance(root, dict):
        raise CategorySelectorError("formula_category_switch is not calibrated")
    if root.get("method") != "screenshot_formula_tabs_v1":
        raise CategorySelectorError(
            "Only the calibrated screenshot_formula_tabs_v1 method is authorized"
        )
    if root.get("automatic_switch_available") is not True:
        raise CategorySelectorError("Automatic category switching is not enabled")
    raw_map = root.get("pane_control_ids")
    if not isinstance(raw_map, dict) or set(raw_map) != SCRIPT_TYPES:
        raise CategorySelectorError("pane_control_ids must contain exactly five script types")
    pane_control_ids = {
        key: _positive_int(value, f"pane_control_ids.{key}")
        for key, value in raw_map.items()
    }
    if len(set(pane_control_ids.values())) != len(SCRIPT_TYPES):
        raise CategorySelectorError("Formula pane control ids must be unique")
    tab_order = root.get("tab_order")
    if not isinstance(tab_order, list) or tuple(tab_order) != TAB_ORDER:
        raise CategorySelectorError("tab_order must be the verified five-category order")
    detection = root.get("screenshot_detection")
    if not isinstance(detection, dict):
        raise CategorySelectorError("screenshot_detection must be an object")
    pacing = xq_ui_pacing.load_ui_pacing(config, requested_pace_level)
    baseline_action = _number(root.get("action_settle_seconds", 2.5), "action_settle_seconds", 1)
    poll = _number(root.get("poll_seconds", 0.25), "poll_seconds", 0.25)
    late = _number(root.get("late_after_seconds", 4), "late_after_seconds", poll)
    timeout = _number(root.get("state_timeout_seconds", 15), "state_timeout_seconds", late)
    return CategorySwitchContract(
        method="screenshot_formula_tabs_v1",
        pane_control_ids=pane_control_ids,
        tab_order=TAB_ORDER,
        minimum_tab_width_ratio=_number(
            detection.get("minimum_tab_width_ratio", 0.10),
            "minimum_tab_width_ratio", 0.05, 0.25,
        ),
        maximum_tab_width_ratio=_number(
            detection.get("maximum_tab_width_ratio", 0.22),
            "maximum_tab_width_ratio", 0.10, 0.35,
        ),
        maximum_gap_pixels=_positive_int(
            detection.get("maximum_gap_pixels", 4), "maximum_gap_pixels"
        ),
        boundary_tolerance_pixels=_positive_int(
            detection.get("boundary_tolerance_pixels", 3),
            "boundary_tolerance_pixels",
        ),
        required_stable_rows=_positive_int(
            detection.get("required_stable_rows", 2), "required_stable_rows"
        ),
        inactive_color_tolerance=_number(
            detection.get("inactive_color_tolerance", 18),
            "inactive_color_tolerance", 1, 80,
        ),
        active_color_minimum_distance=_number(
            detection.get("active_color_minimum_distance", 30),
            "active_color_minimum_distance", 5, 255,
        ),
        poll_seconds=poll,
        late_after_seconds=late,
        state_timeout_seconds=timeout,
        action_settle_seconds=pacing.action_interval(baseline_action),
        ui_pacing=pacing,
    )


def validate_script_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    if SCRIPT_NAME_RE.fullmatch(name) is None:
        raise CategorySelectorError("Script name is empty, unsafe, or longer than 80 characters")
    return name


def active_type(evidence: dict[str, Any], pane_control_ids: dict[str, int]) -> str | None:
    inverse = {value: key for key, value in pane_control_ids.items()}
    return inverse.get(evidence.get("formula_pane_control_id"))


def evaluate_category_request(
    evidence: dict[str, Any], requested_type: str, pane_control_ids: dict[str, int]
) -> dict[str, Any]:
    current = active_type(evidence, pane_control_ids)
    common = {
        "requested_type": requested_type,
        "active_type": current,
        "active_pane_control_id": evidence.get("formula_pane_control_id"),
        "automatic_switch_available": True,
        "input_sent": False,
        "coordinate_use": False,
    }
    if (
        evidence.get("visible_formula_pane_count") != 1
        or evidence.get("visible_tree_count") != 1
        or current is None
    ):
        return {**common, "status": "automation_error", "reason_code": "active_category_readback_not_unique"}
    if current != requested_type:
        return {**common, "status": "switch_required", "reason_code": "target_category_not_active"}
    if evidence.get("custom_root_count") != 1 or evidence.get("codex_direct_child_count") != 1:
        return {**common, "status": "automation_error", "reason_code": "codex_scope_readback_not_unique"}
    return {
        **common,
        "status": "success",
        "reason_code": "requested_category_already_active",
        "codex_scope_verified": True,
        "codex_location": "自訂/CODEX/",
    }


def inspect_formula_context(window: Any) -> FormulaContext:
    panes = [
        item for item in window.descendants()
        if xq_category_observer.is_formula_pane(item) and item.is_visible()
    ]
    evidence = xq_category_observer.inspect_xscript(window)
    if len(panes) != 1:
        raise CategorySelectorError("The visible formula category pane is not unique")
    pane = panes[0]
    host = pane.parent()
    container = host.parent() if host is not None else None
    if (
        host is None or int(host.control_id()) != xq_category_observer.FORMULA_TAB_HOST_ID
        or container is None
        or int(container.control_id()) != xq_category_observer.FORMULA_CONTAINER_ID
    ):
        raise CategorySelectorError("Formula category host hierarchy changed")
    trees = [
        item for item in pane.descendants(class_name="SysTreeView32")
        if int(item.control_id()) == xq_category_observer.TREE_CONTROL_ID and item.is_visible()
    ]
    if len(trees) != 1:
        raise CategorySelectorError("The visible formula tree is not unique")
    tree = trees[0]
    custom = [
        item for item in tree.roots()
        if xq_category_observer.CUSTOM_PATTERN.fullmatch(
            xq_category_observer.normalize(item.text())
        )
    ]
    codex: list[Any] = []
    if len(custom) == 1:
        codex = [
            item for item in custom[0].children()
            if xq_category_observer.CODEX_PATTERN.fullmatch(
                xq_category_observer.normalize(item.text())
            )
        ]
    return FormulaContext(
        window=window,
        pane=pane,
        host=host,
        tree=tree,
        custom_root=custom[0] if len(custom) == 1 else None,
        codex_root=codex[0] if len(codex) == 1 else None,
        evidence=evidence,
    )


def _color_distance(first: Sequence[int], second: Sequence[int]) -> float:
    return math.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(first, second)))


def _active_fill_index(
    colors: Sequence[Sequence[int]], inactive_tolerance: float, active_minimum: float
) -> int | None:
    matches: list[int] = []
    for candidate in range(len(colors)):
        inactive = [colors[index] for index in range(len(colors)) if index != candidate]
        if max(
            _color_distance(first, second)
            for offset, first in enumerate(inactive)
            for second in inactive[offset + 1:]
        ) > inactive_tolerance:
            continue
        centroid = tuple(sum(color[channel] for color in inactive) / len(inactive) for channel in range(3))
        if _color_distance(colors[candidate], centroid) >= active_minimum:
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _solid_runs(image: Any, y: int, minimum_length: int) -> list[tuple[int, int, tuple[int, int, int]]]:
    width = int(image.width)
    runs: list[tuple[int, int, tuple[int, int, int]]] = []
    start = 0
    color = tuple(image.getpixel((0, y)))
    for x in range(1, width + 1):
        current = tuple(image.getpixel((x, y))) if x < width else None
        if current != color:
            if x - start >= minimum_length:
                runs.append((start, x - 1, color))
            start = x
            color = current
    return runs


def _png_sha256(image: Any) -> str:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return hashlib.sha256(stream.getvalue()).hexdigest()


def detect_formula_tabs(
    image: Any,
    tab_strip_height: int,
    expected_active_index: int,
    contract: CategorySwitchContract,
) -> dict[str, Any]:
    """Locate exactly five tabs from stable solid-fill rows in a local image."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 150 or tab_strip_height < 12 or tab_strip_height > min(80, height):
        raise CategorySelectorError("Formula tab screenshot geometry is implausible")
    minimum_length = max(8, round(width * contract.minimum_tab_width_ratio * 0.8))
    minimum_tab_width = width * contract.minimum_tab_width_ratio
    maximum_tab_width = width * contract.maximum_tab_width_ratio
    row_candidates: list[dict[str, Any]] = []
    for y in range(max(1, tab_strip_height // 2), tab_strip_height - 1):
        runs = _solid_runs(rgb, y, minimum_length)
        windows: list[tuple[float, list[tuple[int, int, tuple[int, int, int]]]]] = []
        for index in range(max(0, len(runs) - 4)):
            group = runs[index:index + 5]
            if len(group) != 5:
                continue
            widths = [end - start + 1 for start, end, _ in group]
            gaps = [group[pos + 1][0] - group[pos][1] - 1 for pos in range(4)]
            if (
                group[0][0] < width * 0.08
                or min(widths) < minimum_tab_width
                or max(widths) > maximum_tab_width
                or max(gaps) > contract.maximum_gap_pixels
            ):
                continue
            variation = statistics.pstdev(widths) / statistics.mean(widths)
            windows.append((variation, group))
        if not windows:
            continue
        _, group = min(windows, key=lambda value: value[0])
        colors = [color for _, _, color in group]
        observed_active = _active_fill_index(
            colors,
            contract.inactive_color_tolerance,
            contract.active_color_minimum_distance,
        )
        if observed_active != expected_active_index:
            continue
        row_candidates.append({"y": y, "bounds": [(start, end) for start, end, _ in group]})
    if len(row_candidates) < contract.required_stable_rows:
        raise CategorySelectorError("Screenshot did not yield enough stable five-tab rows")

    stable: list[dict[str, Any]] = []
    for candidate in row_candidates:
        peers = [
            other for other in row_candidates
            if all(
                abs(candidate["bounds"][index][0] - other["bounds"][index][0])
                <= contract.boundary_tolerance_pixels
                and abs(candidate["bounds"][index][1] - other["bounds"][index][1])
                <= contract.boundary_tolerance_pixels
                for index in range(5)
            )
        ]
        if len(peers) >= contract.required_stable_rows:
            stable = peers
            break
    if len(stable) < contract.required_stable_rows:
        raise CategorySelectorError("Five-tab screenshot boundaries were not stable across rows")
    stable = sorted(stable, key=lambda item: item["y"])
    bounds = [
        (
            round(statistics.median(item["bounds"][index][0] for item in stable)),
            round(statistics.median(item["bounds"][index][1] for item in stable)),
        )
        for index in range(5)
    ]
    click_y = round(statistics.median(item["y"] for item in stable))
    return {
        "detector": "solid_fill_stable_rows_v1",
        "image_width": width,
        "image_height": height,
        "tab_strip_height": tab_strip_height,
        "stable_row_count": len(stable),
        "relative_tab_bounds": [[start, end] for start, end in bounds],
        "relative_click_y": click_y,
        "visual_active_index": expected_active_index,
        "image_sha256": _png_sha256(rgb),
        "image_persisted": False,
        "fixed_screen_coordinates": False,
    }


def _adaptive_wait(
    probe: Callable[[], Any],
    contract: CategorySwitchContract,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    started = clock()
    attempts = 0
    while True:
        attempts += 1
        value = probe()
        elapsed = max(0.0, clock() - started)
        if value:
            return {
                "status": "late" if elapsed > contract.late_after_seconds else "ready",
                "value": value,
                "elapsed_seconds": elapsed,
                "attempts": attempts,
            }
        if elapsed >= contract.state_timeout_seconds:
            return {"status": "timeout", "value": None, "elapsed_seconds": elapsed, "attempts": attempts}
        sleeper(min(contract.poll_seconds, contract.state_timeout_seconds - elapsed))


def switch_category(
    window: Any,
    requested_type: str,
    contract: CategorySwitchContract,
    *,
    foreground_guard: Callable[[Any], dict[str, Any]],
    clicker: Callable[..., Any],
    inspect_context: Callable[[Any], FormulaContext] = inspect_formula_context,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    initial = inspect_context(window)
    decision = evaluate_category_request(
        initial.evidence, requested_type, contract.pane_control_ids
    )
    if decision["status"] == "success":
        return {
            **decision,
            "method": contract.method,
            "category_switch_input_sent": False,
            "coordinate_mode": None,
            "foreground_guard": None,
        }
    if decision["status"] != "switch_required":
        raise CategorySelectorError(decision["reason_code"])

    guard = foreground_guard(window)
    before_click = inspect_context(window)
    before_type = active_type(before_click.evidence, contract.pane_control_ids)
    if before_type != decision["active_type"]:
        raise CategorySelectorError("The active category changed before the planned click")
    pane_rect = before_click.pane.rectangle()
    host_rect = before_click.host.rectangle()
    tab_strip_height = int(pane_rect.top - host_rect.top)
    expected_active_index = contract.tab_order.index(before_type)
    image = before_click.host.capture_as_image()
    visual = detect_formula_tabs(image, tab_strip_height, expected_active_index, contract)
    target_index = contract.tab_order.index(requested_type)
    target_start, target_end = visual["relative_tab_bounds"][target_index]
    relative_x = round((target_start + target_end) / 2)
    relative_y = int(visual["relative_click_y"])
    if not (0 <= relative_x < host_rect.width() and 0 <= relative_y < tab_strip_height):
        raise CategorySelectorError("Screenshot-derived click point is outside the formula tab strip")
    clicker(coords=(host_rect.left + relative_x, host_rect.top + relative_y))

    def target_probe() -> FormulaContext | None:
        current = inspect_context(window)
        current_type = active_type(current.evidence, contract.pane_control_ids)
        return current if current_type == requested_type else None

    outcome = _adaptive_wait(target_probe, contract, clock=clock, sleeper=sleeper)
    if outcome["status"] != "ready":
        raise CategorySelectorWaitError(
            f"category_switch_{outcome['status']}", "category_readback", evidence=outcome
        )
    final: FormulaContext = outcome["value"]
    final_decision = evaluate_category_request(
        final.evidence, requested_type, contract.pane_control_ids
    )
    if final_decision["status"] != "success":
        raise CategorySelectorError(final_decision["reason_code"])
    return {
        **final_decision,
        "reason_code": "category_switched_and_codex_verified",
        "method": contract.method,
        "input_sent": True,
        "coordinate_use": True,
        "coordinate_mode": "screenshot_derived_formula_host_local",
        "category_switch_input_sent": True,
        "foreground_guard": guard,
        "visual_detection": visual,
        "relative_click_point": {"x": relative_x, "y": relative_y},
        "screen_click_point_persisted": False,
        "readback_elapsed_seconds": outcome["elapsed_seconds"],
    }


def _active_title_matches(window: Any, name: str, script_type: str) -> bool:
    title = xq_category_observer.normalize(window.window_text())
    return f"{name}({TYPE_LABELS[script_type]})" in title


def verify_active_document(window: Any, name: str, script_type: str) -> bool:
    if not _active_title_matches(window, name, script_type):
        return False
    from pywinauto.uia_defines import IUIA

    uia = IUIA()
    root = uia.iuia.ElementFromHandle(int(window.handle))
    elements = root.FindAll(uia.tree_scope["descendants"], uia.true_condition)
    required = {name, "自訂/CODEX/"}
    found: set[str] = set()
    for index in range(elements.Length):
        value = xq_category_observer.normalize(elements.GetElement(index).CurrentName)
        if value in required:
            found.add(value)
            if found == required:
                return True
    return False


def detect_tree_item_target(tree: Any, item: Any) -> dict[str, Any]:
    """Validate an exact semantic TreeItem against a fresh local screenshot."""
    tree_rect = tree.client_rect()
    item_rect = item.client_rect()
    visible_left = max(item_rect.left, tree_rect.left)
    visible_top = max(item_rect.top, tree_rect.top)
    visible_right = min(item_rect.right, tree_rect.right)
    visible_bottom = min(item_rect.bottom, tree_rect.bottom)
    if visible_right - visible_left < 8 or visible_bottom - visible_top < 8:
        raise CategorySelectorError("The exact CODEX item is outside the visible formula tree")
    image = tree.capture_as_image().convert("RGB")
    relative = (
        int(visible_left - tree_rect.left),
        int(visible_top - tree_rect.top),
        int(visible_right - tree_rect.left),
        int(visible_bottom - tree_rect.top),
    )
    if (
        relative[0] < 0 or relative[1] < 0
        or relative[2] > image.width or relative[3] > image.height
    ):
        raise CategorySelectorError("The CODEX item screenshot bounds are invalid")
    crop = image.crop(relative)
    colors = crop.getcolors(maxcolors=max(256, crop.width * crop.height))
    if colors is None or len(colors) < 2:
        raise CategorySelectorError("The exact CODEX item screenshot is visually empty")
    relative_x = round((visible_left + visible_right) / 2 - tree_rect.left)
    relative_y = round((visible_top + visible_bottom) / 2 - tree_rect.top)
    return {
        "detector": "semantic_tree_item_local_screenshot_v1",
        "tree_image_width": image.width,
        "tree_image_height": image.height,
        "relative_item_bounds": list(relative),
        "item_was_partially_clipped": (
            visible_left != item_rect.left or visible_top != item_rect.top
            or visible_right != item_rect.right or visible_bottom != item_rect.bottom
        ),
        "relative_click_point": {"x": relative_x, "y": relative_y},
        "image_sha256": _png_sha256(image),
        "image_persisted": False,
        "fixed_screen_coordinates": False,
    }


def tree_client_point_to_screen(tree: Any, x: int, y: int) -> tuple[int, int]:
    import ctypes

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    point = Point(int(x), int(y))
    if not ctypes.windll.user32.ClientToScreen(int(tree.handle), ctypes.byref(point)):
        raise CategorySelectorError("Windows could not map the screenshot point to the tree")
    return int(point.x), int(point.y)


def open_existing_codex_script(
    window: Any,
    script_type: str,
    script_name: str,
    contract: CategorySwitchContract,
    *,
    foreground_guard: Callable[[Any], dict[str, Any]],
    double_clicker: Callable[..., Any],
    point_to_screen: Callable[[Any, int, int], tuple[int, int]] = tree_client_point_to_screen,
    inspect_context: Callable[[Any], FormulaContext] = inspect_formula_context,
    verify_active: Callable[[Any, str, str], bool] = verify_active_document,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    name = validate_script_name(script_name)
    if verify_active(window, name, script_type):
        return {
            "script_name": name,
            "script_type": script_type,
            "location": "自訂/CODEX/",
            "open_input_sent": False,
            "reason_code": "requested_document_already_active",
            "readback_verified": True,
        }
    context = inspect_context(window)
    if active_type(context.evidence, contract.pane_control_ids) != script_type:
        raise CategorySelectorError("The target category changed before document selection")
    if context.custom_root is None or context.codex_root is None:
        raise CategorySelectorError("The target category does not have one exact 自訂/CODEX scope")
    matches = [
        item for item in context.codex_root.children()
        if xq_category_observer.normalize(item.text()) == name
    ]
    if len(matches) != 1:
        raise CategorySelectorError(
            f"Expected one exact direct CODEX document named {name!r}, found {len(matches)}"
        )
    item = matches[0]
    guards = [foreground_guard(window)]
    if not item.is_selected():
        item.select()
        sleeper(contract.action_settle_seconds)
    if not item.is_selected():
        raise CategorySelectorError("The exact CODEX document could not be selected")
    guards.append(foreground_guard(window))
    visual_target = detect_tree_item_target(context.tree, item)
    point = visual_target["relative_click_point"]
    screen_point = point_to_screen(context.tree, point["x"], point["y"])
    double_clicker(coords=screen_point)
    open_input = {
        "command": "screenshot_derived_atomic_double_click",
        "sent_once": True,
        "screen_click_point_persisted": False,
    }

    outcome = _adaptive_wait(
        lambda: window if _active_title_matches(window, name, script_type) else None,
        contract,
        clock=clock,
        sleeper=sleeper,
    )
    if outcome["status"] != "ready":
        raise CategorySelectorWaitError(
            f"document_open_{outcome['status']}", "active_document_readback", evidence=outcome
        )
    if not verify_active(window, name, script_type):
        raise CategorySelectorError("Active document name, type, or 自訂/CODEX location did not match")
    final = inspect_context(window)
    final_decision = evaluate_category_request(
        final.evidence, script_type, contract.pane_control_ids
    )
    if final_decision["status"] != "success":
        raise CategorySelectorError("Opening the document did not preserve category/CODEX readback")
    return {
        "script_name": name,
        "script_type": script_type,
        "location": "自訂/CODEX/",
        "open_input_sent": True,
        "open_input": open_input,
        "visual_target": visual_target,
        "selection_count": 1,
        "readback_verified": True,
        "foreground_guards": guards,
        "readback_elapsed_seconds": outcome["elapsed_seconds"],
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_wait_incident(
    config_path: Path,
    config: dict[str, Any],
    error: CategorySelectorWaitError,
    script_type: str,
    script_name: str | None,
) -> Path:
    import xq_backtest

    recovery: dict[str, Any]
    try:
        recovery = xq_backtest.inspect_recovery_status(config_path, config)
    except Exception as exc:  # incident capture must preserve the original failure
        recovery = {"status": "capture_error", "error": f"{type(exc).__name__}: {exc}"}
    runtime = recovery.get("runtime") if isinstance(recovery, dict) else None
    payload = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "xscript_category_switch_and_open",
        "script_type": script_type,
        "script_name": script_name,
        "stage": error.stage,
        "incident_kind": error.kind,
        "wait_evidence": error.evidence,
        "xq_process_id": runtime.get("xq_process_id") if isinstance(runtime, dict) else None,
        "window_health": runtime,
        "checkpoint": recovery.get("checkpoint") if isinstance(recovery, dict) else None,
        "visible_reports": recovery.get("visible_reports", []) if isinstance(recovery, dict) else [],
        "recovery_status": recovery,
        "further_input_sent": False,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    path = config_path.resolve().parent / "incidents" / f"category-selector-{stamp}.json"
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite incident: {path}")
    _atomic_write_json(path, payload)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config: dict[str, Any] = {}
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            raise CategorySelectorError("XQ UI configuration is not calibrated")
        contract = load_contract(config)

        from pywinauto import Desktop, mouse
        import xq_backtest

        xq_backtest.configure_ui_pacing(config)
        windows = xq_category_observer.find_xscript(Desktop(backend="win32"))
        if len(windows) != 1:
            raise CategorySelectorError(f"Expected one visible XScript window, found {len(windows)}")
        window = windows[0]
        if not window.is_enabled() or __import__("ctypes").windll.user32.IsHungAppWindow(int(window.handle)):
            raise CategorySelectorWaitError(
                "window_disabled_or_hung", "initial_health", evidence={"window_handle": int(window.handle)}
            )
        switch = switch_category(
            window,
            args.script_type,
            contract,
            foreground_guard=xq_backtest.ensure_window_foreground,
            clicker=mouse.click,
        )
        return emit(
            "success",
            "Requested XScript category and CODEX scope were verified",
            requested_type=args.script_type,
            category=switch,
            screenshot_persisted=False,
            ui_pacing=contract.ui_pacing.evidence(),
        )
    except CategorySelectorWaitError as exc:
        incident = None
        try:
            incident = save_wait_incident(
                args.config, config, exc, args.script_type, None
            )
        except Exception:
            incident = None
        return emit(
            "automation_error",
            str(exc),
            incident_path=str(incident) if incident is not None else None,
            further_input_sent=False,
        )
    except (OSError, json.JSONDecodeError, CategorySelectorError) as exc:
        return emit(
            "automation_error",
            str(exc),
            automatic_switch_available=config.get("formula_category_switch", {}).get(
                "automatic_switch_available", False
            ) if isinstance(config.get("formula_category_switch"), dict) else False,
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"Unexpected category-selector failure before verified completion: {type(exc).__name__}: {exc}",
            automatic_switch_available=False,
        )


if __name__ == "__main__":
    sys.exit(main())
