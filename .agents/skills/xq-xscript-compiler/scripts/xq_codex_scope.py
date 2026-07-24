#!/usr/bin/env python3
"""Fail-closed helpers for selecting a verified feature-specific XQ CODEX folder."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any


CODEX_FOLDER_NAME = "CODEX"
SCRIPT_TYPES = {"indicator", "screener", "alert", "function", "autotrade"}
EXPECTED_SCRIPT_LOCATION = "自訂/CODEX/"
SELECTOR_KEYS = {"title", "title_re", "auto_id", "control_type", "class_name"}


class CodexScopeError(RuntimeError):
    """A missing or ambiguous CODEX scope that must stop XQ mutation."""


@dataclass(frozen=True)
class CodexScopeContract:
    script_type: str
    folder_name: str
    expected_location: str
    category_selector: dict[str, Any]
    folder_selector: dict[str, Any]
    location_readback_selector: dict[str, Any]
    action_settle_seconds: float
    state_timeout_seconds: float


def normalize_location(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    if text and not text.endswith("/"):
        text += "/"
    return text


def location_is_codex_scope(value: Any) -> bool:
    return normalize_location(value) == EXPECTED_SCRIPT_LOCATION


def _selector(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise CodexScopeError(f"{label} must be a non-empty selector object")
    unknown = set(value) - SELECTOR_KEYS
    if unknown:
        raise CodexScopeError(f"{label} contains unsupported selector fields: {sorted(unknown)}")
    selector = {key: item for key, item in value.items() if item not in (None, "")}
    if not selector:
        raise CodexScopeError(f"{label} is empty")
    return selector


def load_script_scope_contract(
    config: dict[str, Any],
    script_type: str,
    folder_name: str = CODEX_FOLDER_NAME,
) -> CodexScopeContract:
    if script_type not in SCRIPT_TYPES:
        raise CodexScopeError(f"Unsupported XScript type for CODEX scope: {script_type}")
    if folder_name != CODEX_FOLDER_NAME:
        raise CodexScopeError("Only the exact CODEX folder is authorized")
    root = config.get("codex_scope")
    if not isinstance(root, dict):
        raise CodexScopeError(
            "CODEX scope is not calibrated; refusing to touch XQ before a verified folder selector exists"
        )
    if root.get("folder_name") != CODEX_FOLDER_NAME:
        raise CodexScopeError("CODEX scope folder_name must be exactly CODEX")
    scripts = root.get("script_types")
    entry = scripts.get(script_type) if isinstance(scripts, dict) else None
    if not isinstance(entry, dict):
        raise CodexScopeError(f"CODEX scope is not calibrated for script type {script_type}")
    expected_location = normalize_location(entry.get("expected_location"))
    if expected_location != EXPECTED_SCRIPT_LOCATION:
        raise CodexScopeError(
            f"CODEX scope expected_location must be exactly {EXPECTED_SCRIPT_LOCATION}"
        )
    action_settle = entry.get("action_settle_seconds", root.get("action_settle_seconds", 2.0))
    state_timeout = entry.get("state_timeout_seconds", root.get("state_timeout_seconds", 15.0))
    if (
        isinstance(action_settle, bool)
        or not isinstance(action_settle, (int, float))
        or action_settle < 1.0
    ):
        raise CodexScopeError("CODEX scope action_settle_seconds must be at least 1 second")
    if (
        isinstance(state_timeout, bool)
        or not isinstance(state_timeout, (int, float))
        or state_timeout <= 0
    ):
        raise CodexScopeError("CODEX scope state_timeout_seconds must be positive")
    return CodexScopeContract(
        script_type=script_type,
        folder_name=folder_name,
        expected_location=expected_location,
        category_selector=_selector(entry.get("category_selector"), "category_selector"),
        folder_selector=_selector(entry.get("folder_selector"), "folder_selector"),
        location_readback_selector=_selector(
            entry.get("location_readback_selector"), "location_readback_selector",
        ),
        action_settle_seconds=float(action_settle),
        state_timeout_seconds=float(state_timeout),
    )


def _unique_descendant(root: Any, selector: dict[str, Any], label: str) -> Any:
    matches = list(root.descendants(**selector))
    if len(matches) != 1:
        raise CodexScopeError(f"Expected one {label}, found {len(matches)}")
    match = matches[0]
    if not match.is_visible() or not match.is_enabled():
        raise CodexScopeError(f"{label} is not visible and enabled")
    return match


def select_verified_script_scope(xscript: Any, contract: CodexScopeContract) -> dict[str, Any]:
    """Select and read back an already calibrated CODEX folder without fallbacks."""
    category = _unique_descendant(
        xscript, contract.category_selector, f"{contract.script_type} CODEX category selector",
    )
    category.click_input()
    time.sleep(contract.action_settle_seconds)
    folder = _unique_descendant(
        xscript, contract.folder_selector, f"{contract.script_type} CODEX folder",
    )
    folder.select()
    time.sleep(contract.action_settle_seconds)
    readback = _unique_descendant(
        xscript,
        contract.location_readback_selector,
        f"{contract.script_type} CODEX location readback",
    )
    observed = normalize_location(readback.window_text())
    if observed != contract.expected_location:
        raise CodexScopeError(
            f"CODEX location readback mismatch: expected {contract.expected_location}, got {observed}"
        )
    return {
        "folder_name": contract.folder_name,
        "script_type": contract.script_type,
        "location": observed,
        "readback_verified": True,
    }


def authorize_manifest_document(
    record: dict[str, Any],
    *,
    readback_name: str,
    readback_type: str,
    readback_location: str,
) -> bool:
    return (
        record.get("created") is True
        and record.get("name") == readback_name
        and record.get("script_type") == readback_type
        and record.get("type_readback") == readback_type
        and normalize_location(record.get("storage_location")) == EXPECTED_SCRIPT_LOCATION
        and normalize_location(readback_location) == EXPECTED_SCRIPT_LOCATION
    )
