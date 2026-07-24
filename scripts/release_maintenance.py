#!/usr/bin/env python3
"""Manage a private, fail-closed release-candidate maintenance-mode state."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_STATE = Path(".xq-auto-writer/release-candidate/maintenance.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("maintenance_state_invalid")
    if value.get("mode") != "active":
        raise ValueError("maintenance_state_mode_invalid")
    return value


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def maintenance_status(path: Path) -> dict[str, Any]:
    try:
        state = _read_state(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "automation_error",
            "mode": "unknown",
            "state_path": str(path.resolve()),
            "error": str(exc),
        }
    return {
        "status": "success",
        "mode": "active" if state else "inactive",
        "state_path": str(path.resolve()),
        "state": state,
    }


def enter_maintenance(
    path: Path, *, reason: str, current_version: str, target_version: str, confirmed: bool
) -> dict[str, Any]:
    if not confirmed:
        return {"status": "confirmation_required", "mode": "inactive", "state_path": str(path.resolve())}
    existing = maintenance_status(path)
    if existing["status"] != "success":
        return existing
    if existing["mode"] == "active":
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": "maintenance_already_active",
        }
    state = {
        "schema_version": SCHEMA_VERSION,
        "mode": "active",
        "entered_at_utc": _utc_now(),
        "reason": reason,
        "current_version": current_version,
        "target_version": target_version,
    }
    try:
        _atomic_write(path, state)
    except OSError as exc:
        return {
            "status": "automation_error",
            "mode": "unknown",
            "state_path": str(path.resolve()),
            "error": str(exc),
        }
    return {"status": "success", "mode": "active", "state_path": str(path.resolve()), "state": state}


def leave_maintenance(path: Path, *, confirmed: bool, rc_evidence: Path | None) -> dict[str, Any]:
    if not confirmed:
        return {"status": "confirmation_required", "mode": "unknown", "state_path": str(path.resolve())}
    current = maintenance_status(path)
    if current["status"] != "success":
        return current
    if current["mode"] != "active":
        return {
            "status": "automation_error",
            "mode": "inactive",
            "state_path": str(path.resolve()),
            "error": "maintenance_not_active",
        }
    if rc_evidence is None:
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": "release_candidate_evidence_required",
        }
    try:
        evidence = json.loads(rc_evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": f"release_candidate_evidence_invalid:{exc}",
        }
    if not isinstance(evidence, dict) or evidence.get("ready") is not True or evidence.get("status") != "success":
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": "release_candidate_evidence_not_ready",
        }
    state = current["state"]
    if evidence.get("current_stable_version") != state.get("current_version") or evidence.get(
        "target_release_version"
    ) != state.get("target_version"):
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": "release_candidate_evidence_version_mismatch",
        }
    try:
        path.unlink()
    except OSError as exc:
        return {
            "status": "automation_error",
            "mode": "active",
            "state_path": str(path.resolve()),
            "error": str(exc),
        }
    return {
        "status": "success",
        "mode": "inactive",
        "state_path": str(path.resolve()),
        "release_candidate_evidence": str(rc_evidence.resolve()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    enter = subparsers.add_parser("enter")
    enter.add_argument("--reason", required=True)
    enter.add_argument("--current-version", required=True)
    enter.add_argument("--target-version", required=True)
    enter.add_argument("--confirm-maintenance-mode", action="store_true")
    leave = subparsers.add_parser("leave")
    leave.add_argument("--rc-evidence", type=Path)
    leave.add_argument("--confirm-leave-maintenance", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        result = maintenance_status(args.state)
    elif args.command == "enter":
        result = enter_maintenance(
            args.state,
            reason=args.reason,
            current_version=args.current_version,
            target_version=args.target_version,
            confirmed=args.confirm_maintenance_mode,
        )
    else:
        result = leave_maintenance(
            args.state,
            confirmed=args.confirm_leave_maintenance,
            rc_evidence=args.rc_evidence,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "success" else 3


if __name__ == "__main__":
    sys.exit(main())
