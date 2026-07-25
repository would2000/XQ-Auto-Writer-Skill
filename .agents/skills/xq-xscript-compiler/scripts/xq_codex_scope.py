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


class CodexScopeWaitError(CodexScopeError):
    """A late or timed-out XQ dialog after which no further input is allowed."""


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


@dataclass(frozen=True)
class NewScriptStorageContract:
    folder_name: str
    expected_location: str
    storage_control_id: int
    folder_button_control_id: int
    folder_dialog_title: str
    folder_dialog_class_name: str
    folder_tree_control_id: int
    folder_confirm_control_id: int
    folder_cancel_control_id: int
    custom_root_title: str
    context_menu_class_name: str
    new_folder_menu_title: str
    creation_dialog_title: str
    creation_dialog_class_name: str
    creation_name_control_id: int
    creation_confirm_control_id: int
    creation_cancel_control_id: int
    action_settle_seconds: float
    poll_seconds: float
    dialog_timeout_seconds: float


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


def _required_text(value: Any, label: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise CodexScopeError(f"{label} must be non-empty text")
    return text


def _required_control_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CodexScopeError(f"{label} must be a positive control id")
    return value


def load_new_script_storage_contract(
    config: dict[str, Any],
    folder_name: str = CODEX_FOLDER_NAME,
) -> NewScriptStorageContract:
    if folder_name != CODEX_FOLDER_NAME:
        raise CodexScopeError("Only the exact CODEX folder is authorized")
    root = config.get("new_script_storage_scope")
    if not isinstance(root, dict):
        raise CodexScopeError(
            "New-script CODEX storage scope is not calibrated; refusing to touch XQ"
        )
    if root.get("folder_name") != CODEX_FOLDER_NAME:
        raise CodexScopeError("New-script storage folder_name must be exactly CODEX")
    expected_location = normalize_location(root.get("expected_location"))
    if expected_location != EXPECTED_SCRIPT_LOCATION:
        raise CodexScopeError(
            f"New-script storage expected_location must be exactly {EXPECTED_SCRIPT_LOCATION}"
        )

    folder_dialog = root.get("folder_dialog")
    context_menu = root.get("context_menu")
    creation_dialog = root.get("creation_dialog")
    if not isinstance(folder_dialog, dict):
        raise CodexScopeError("new_script_storage_scope.folder_dialog must be an object")
    if not isinstance(context_menu, dict):
        raise CodexScopeError("new_script_storage_scope.context_menu must be an object")
    if not isinstance(creation_dialog, dict):
        raise CodexScopeError("new_script_storage_scope.creation_dialog must be an object")

    action_settle = root.get("action_settle_seconds", 2.0)
    poll_seconds = root.get("poll_seconds", 0.5)
    dialog_timeout = root.get("dialog_timeout_seconds", 15.0)
    for value, label, minimum in (
        (action_settle, "action_settle_seconds", 1.0),
        (poll_seconds, "poll_seconds", 0.25),
        (dialog_timeout, "dialog_timeout_seconds", 1.0),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or float(value) < minimum
        ):
            raise CodexScopeError(
                f"New-script storage {label} must be at least {minimum:g} seconds"
            )
    if float(dialog_timeout) <= float(action_settle):
        raise CodexScopeError(
            "New-script storage dialog_timeout_seconds must exceed action_settle_seconds"
        )

    return NewScriptStorageContract(
        folder_name=folder_name,
        expected_location=expected_location,
        storage_control_id=_required_control_id(
            root.get("storage_control_id"), "storage_control_id",
        ),
        folder_button_control_id=_required_control_id(
            root.get("folder_button_control_id"), "folder_button_control_id",
        ),
        folder_dialog_title=_required_text(folder_dialog.get("title"), "folder dialog title"),
        folder_dialog_class_name=_required_text(
            folder_dialog.get("class_name"), "folder dialog class_name",
        ),
        folder_tree_control_id=_required_control_id(
            folder_dialog.get("tree_control_id"), "folder dialog tree_control_id",
        ),
        folder_confirm_control_id=_required_control_id(
            folder_dialog.get("confirm_control_id"), "folder dialog confirm_control_id",
        ),
        folder_cancel_control_id=_required_control_id(
            folder_dialog.get("cancel_control_id"), "folder dialog cancel_control_id",
        ),
        custom_root_title=_required_text(
            folder_dialog.get("custom_root_title"), "folder dialog custom_root_title",
        ),
        context_menu_class_name=_required_text(
            context_menu.get("class_name"), "context menu class_name",
        ),
        new_folder_menu_title=_required_text(
            context_menu.get("new_folder_title"), "context menu new_folder_title",
        ),
        creation_dialog_title=_required_text(
            creation_dialog.get("title"), "creation dialog title",
        ),
        creation_dialog_class_name=_required_text(
            creation_dialog.get("class_name"), "creation dialog class_name",
        ),
        creation_name_control_id=_required_control_id(
            creation_dialog.get("name_control_id"), "creation dialog name_control_id",
        ),
        creation_confirm_control_id=_required_control_id(
            creation_dialog.get("confirm_control_id"), "creation dialog confirm_control_id",
        ),
        creation_cancel_control_id=_required_control_id(
            creation_dialog.get("cancel_control_id"), "creation dialog cancel_control_id",
        ),
        action_settle_seconds=float(action_settle),
        poll_seconds=float(poll_seconds),
        dialog_timeout_seconds=float(dialog_timeout),
    )


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


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _control_by_id(
    root: Any,
    control_id: int,
    label: str,
    *,
    require_enabled: bool = True,
) -> Any:
    matches = [
        item for item in root.descendants()
        if int(item.control_id()) == control_id
    ]
    if len(matches) != 1:
        raise CodexScopeError(f"Expected one {label}, found {len(matches)}")
    control = matches[0]
    if not control.is_visible() or (require_enabled and not control.is_enabled()):
        raise CodexScopeError(f"{label} is not visible and enabled")
    return control


def _wrapper_process_id(wrapper: Any) -> int:
    value = wrapper.process_id
    return int(value() if callable(value) else value)


def _matching_windows(
    desktop: Any,
    *,
    process_id: int,
    class_name: str,
    title: str | None,
) -> list[Any]:
    matches: list[Any] = []
    for item in desktop.windows(class_name=class_name, visible_only=True):
        try:
            if _wrapper_process_id(item) != process_id:
                continue
            if title is not None and _normalize_text(item.window_text()) != title:
                continue
            matches.append(item)
        except Exception:
            continue
    return matches


def _wait_for_unique_window(
    desktop: Any,
    *,
    process_id: int,
    class_name: str,
    title: str | None,
    timeout_seconds: float,
    poll_seconds: float,
    monotonic: Any,
    sleeper: Any,
    label: str,
) -> Any:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        matches = _matching_windows(
            desktop,
            process_id=process_id,
            class_name=class_name,
            title=title,
        )
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CodexScopeError(f"Expected one {label}, found {len(matches)}")
        sleeper(poll_seconds)
    raise CodexScopeWaitError(f"Timed out waiting for {label}")


def _custom_root_and_codex_children(
    tree: Any,
    contract: NewScriptStorageContract,
) -> tuple[Any, list[Any]]:
    roots = [
        item for item in tree.roots()
        if _normalize_text(item.text()) == contract.custom_root_title
    ]
    if len(roots) != 1:
        raise CodexScopeError(
            f"Expected one {contract.custom_root_title} root, found {len(roots)}"
        )
    codex_children = [
        item for item in roots[0].children()
        if _normalize_text(item.text()) == contract.folder_name
    ]
    if len(codex_children) > 1:
        raise CodexScopeError(
            f"Expected at most one direct CODEX child, found {len(codex_children)}"
        )
    return roots[0], codex_children


def ensure_new_script_codex_storage(
    new_script_dialog: Any,
    contract: NewScriptStorageContract,
    *,
    desktop_win32: Any | None = None,
    desktop_uia: Any | None = None,
    sleeper: Any = time.sleep,
    monotonic: Any = time.monotonic,
) -> dict[str, Any]:
    """Open the type-scoped folder browser, create/select CODEX, and verify readback."""
    if desktop_win32 is None or desktop_uia is None:
        from pywinauto import Desktop

        desktop_win32 = desktop_win32 or Desktop(backend="win32")
        desktop_uia = desktop_uia or Desktop(backend="uia")

    process_id = _wrapper_process_id(new_script_dialog)
    storage = _control_by_id(
        new_script_dialog,
        contract.storage_control_id,
        "new-script storage readback",
        require_enabled=False,
    )
    folder_button = _control_by_id(
        new_script_dialog,
        contract.folder_button_control_id,
        "new-script folder button",
    )
    folder_button.click()
    sleeper(contract.action_settle_seconds)

    folder_dialog = _wait_for_unique_window(
        desktop_win32,
        process_id=process_id,
        class_name=contract.folder_dialog_class_name,
        title=contract.folder_dialog_title,
        timeout_seconds=contract.dialog_timeout_seconds,
        poll_seconds=contract.poll_seconds,
        monotonic=monotonic,
        sleeper=sleeper,
        label="type-scoped folder dialog",
    )
    tree = _control_by_id(
        folder_dialog,
        contract.folder_tree_control_id,
        "type-scoped folder tree",
    )
    custom_root, codex_children = _custom_root_and_codex_children(tree, contract)
    created_folder = False

    if not codex_children:
        custom_root.select()
        sleeper(contract.action_settle_seconds)
        if not custom_root.is_selected():
            raise CodexScopeError("Custom root selection was not verified")
        custom_root.click_input(button="right")
        sleeper(contract.action_settle_seconds)
        popup = _wait_for_unique_window(
            desktop_uia,
            process_id=process_id,
            class_name=contract.context_menu_class_name,
            title=None,
            timeout_seconds=contract.dialog_timeout_seconds,
            poll_seconds=contract.poll_seconds,
            monotonic=monotonic,
            sleeper=sleeper,
            label="new-folder context menu",
        )
        allowed_titles = {
            contract.new_folder_menu_title,
            contract.new_folder_menu_title + "...",
            contract.new_folder_menu_title + "…",
        }
        menu_items = [
            item for item in popup.descendants(control_type="MenuItem")
            if _normalize_text(item.window_text()).replace("&", "") in allowed_titles
        ]
        if len(menu_items) != 1:
            raise CodexScopeError(
                f"Expected one new-folder command, found {len(menu_items)}"
            )
        menu_items[0].invoke()
        sleeper(contract.action_settle_seconds)
        creation_dialog = _wait_for_unique_window(
            desktop_win32,
            process_id=process_id,
            class_name=contract.creation_dialog_class_name,
            title=contract.creation_dialog_title,
            timeout_seconds=contract.dialog_timeout_seconds,
            poll_seconds=contract.poll_seconds,
            monotonic=monotonic,
            sleeper=sleeper,
            label="new-folder creation dialog",
        )
        name_control = _control_by_id(
            creation_dialog,
            contract.creation_name_control_id,
            "new-folder name control",
        )
        creation_confirm = _control_by_id(
            creation_dialog,
            contract.creation_confirm_control_id,
            "new-folder confirm",
            require_enabled=False,
        )
        name_control.set_edit_text(contract.folder_name)
        sleeper(contract.action_settle_seconds)
        if _normalize_text(name_control.window_text()) != contract.folder_name:
            raise CodexScopeError("New-folder name readback mismatch")
        if not creation_confirm.is_enabled():
            raise CodexScopeError("New-folder confirm did not become enabled")
        creation_confirm.click()
        sleeper(contract.action_settle_seconds)
        tree = _control_by_id(
            folder_dialog,
            contract.folder_tree_control_id,
            "type-scoped folder tree after creation",
        )
        _, codex_children = _custom_root_and_codex_children(tree, contract)
        if len(codex_children) != 1:
            raise CodexScopeError(
                f"Expected one direct CODEX child after creation, found {len(codex_children)}"
            )
        created_folder = True

    codex_folder = codex_children[0]
    codex_folder.select()
    sleeper(contract.action_settle_seconds)
    if not codex_folder.is_selected():
        raise CodexScopeError("CODEX folder selection was not verified")
    folder_confirm = _control_by_id(
        folder_dialog,
        contract.folder_confirm_control_id,
        "type-scoped folder confirm",
    )
    folder_confirm.click()
    sleeper(contract.action_settle_seconds)
    observed = normalize_location(storage.window_text())
    if observed != contract.expected_location:
        raise CodexScopeError(
            f"CODEX location readback mismatch: expected {contract.expected_location}, got {observed}"
        )
    return {
        "folder_name": contract.folder_name,
        "location": observed,
        "readback_verified": True,
        "created_folder": created_folder,
        "custom_root_count": 1,
        "codex_direct_child_count": 1,
        "coordinate_use": False,
        "selection_source": "new_script_type_scoped_storage_dialog",
    }


def cancel_new_script_storage_dialogs(
    new_script_dialog: Any,
    contract: NewScriptStorageContract,
    *,
    desktop_win32: Any | None = None,
    sleeper: Any = time.sleep,
) -> list[str]:
    """Close only uniquely identified storage dialogs after a non-timeout failure."""
    if desktop_win32 is None:
        from pywinauto import Desktop

        desktop_win32 = Desktop(backend="win32")

    process_id = _wrapper_process_id(new_script_dialog)
    closed: list[str] = []
    dialog_specs = (
        (
            contract.creation_dialog_class_name,
            contract.creation_dialog_title,
            contract.creation_cancel_control_id,
            "new-folder creation dialog",
        ),
        (
            contract.folder_dialog_class_name,
            contract.folder_dialog_title,
            contract.folder_cancel_control_id,
            "type-scoped folder dialog",
        ),
    )
    for class_name, title, cancel_control_id, label in dialog_specs:
        matches = _matching_windows(
            desktop_win32,
            process_id=process_id,
            class_name=class_name,
            title=title,
        )
        if len(matches) > 1:
            raise CodexScopeError(
                f"Refusing cleanup because {label} is not unique: found {len(matches)}"
            )
        if not matches:
            continue
        cancel = _control_by_id(
            matches[0],
            cancel_control_id,
            f"{label} cancel",
        )
        cancel.click()
        sleeper(contract.action_settle_seconds)
        closed.append(label)
    return closed


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
