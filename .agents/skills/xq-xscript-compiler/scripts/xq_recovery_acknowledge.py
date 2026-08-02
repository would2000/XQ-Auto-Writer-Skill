#!/usr/bin/env python3
"""Archive and clear one XQ recovery checkpoint after explicit manual review.

This command never opens a backtest dialog, starts a backtest, or sends XQ
input.  It is the only supported manual-clear path for a checkpoint whose
saved XQ process remains alive.  The caller must supply the exact run ID and
an explicit confirmation after inspecting XQ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import UUID

import xq_backtest


ARCHIVE_SCHEMA_VERSION = 1
ARCHIVE_DIRECTORY_NAME = "recovery-archive"
EXIT_CODES = {"success": 0, "automation_error": 3, "environment_interruption": 3}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def archive_directory(config_path: Path) -> Path:
    return xq_backtest.recovery_path(config_path).parent / ARCHIVE_DIRECTORY_NAME


def read_checkpoint_snapshot(path: Path) -> tuple[bytes, xq_backtest.RecoveryCheckpoint]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("No XQ recovery checkpoint is present") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Recovery checkpoint is not valid UTF-8 JSON: {exc}") from exc
    return raw, xq_backtest.validate_checkpoint_payload(payload)


def archive_record(
    checkpoint: xq_backtest.RecoveryCheckpoint,
    *,
    checkpoint_sha256: str,
    recovery: dict[str, Any],
    acknowledged_at: str,
) -> dict[str, Any]:
    """Return a privacy-safe, audit-only record for a manual acknowledgement."""

    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "event": "manual_recovery_acknowledged",
        "acknowledged_at": acknowledged_at,
        "acknowledged_run_id": checkpoint.run_id,
        "checkpoint_sha256": checkpoint_sha256,
        "recovery_decision": recovery["decision"],
        "recovery_reason_codes": list(recovery.get("reason_codes", [])),
        "saved_process_running": recovery.get("saved_process_running"),
        "visible_progress": recovery.get("visible_progress"),
        "report_checkpoint_association_proven": recovery.get(
            "report_checkpoint_association_proven"
        ),
        "previous_checkpoint": asdict(checkpoint),
    }


def write_new_archive(path: Path, payload: dict[str, Any]) -> None:
    """Write an archive once, refusing overwrite and verifying its contents."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise ValueError("Recovery acknowledgement archive already exists") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if path.read_bytes() != encoded:
        path.unlink(missing_ok=True)
        raise RuntimeError("Recovery acknowledgement archive read-back failed")


def runtime_is_healthy_for_manual_clear(
    recovery: dict[str, Any],
    checkpoint: xq_backtest.RecoveryCheckpoint,
) -> bool:
    runtime = recovery.get("runtime")
    if not isinstance(runtime, dict):
        return False
    if not (
        runtime.get("xq_window_exists") is True
        and runtime.get("xq_window_visible") is True
        and runtime.get("xq_window_enabled") is True
        and runtime.get("xq_window_hung") is False
    ):
        return False

    if recovery.get("decision") == "safe_to_clear_checkpoint":
        reason_codes = set(recovery.get("reason_codes", []))
        current_process_id = runtime.get("xq_process_id")
        xscript_exists = runtime.get("xscript_window_exists")
        xscript_absent = (
            xscript_exists is False
            and runtime.get("xscript_window_visible") is False
            and runtime.get("xscript_window_enabled") is False
            and runtime.get("xscript_window_hung") is None
        )
        xscript_healthy = (
            xscript_exists is True
            and runtime.get("xscript_window_visible") is True
            and runtime.get("xscript_window_enabled") is True
            and runtime.get("xscript_window_hung") is False
        )
        return (
            recovery.get("saved_process_running") is False
            and runtime.get("xq_process_exists") is False
            and isinstance(current_process_id, int)
            and current_process_id > 0
            and current_process_id != checkpoint.xq_process_id
            and {"xq_process_exited", "saved_process_not_running"}.issubset(
                reason_codes
            )
            and (xscript_absent or xscript_healthy)
        )

    required_true = (
        "xq_process_exists",
        "xq_window_exists",
        "xq_window_visible",
        "xq_window_enabled",
        "xscript_window_exists",
        "xscript_window_visible",
        "xscript_window_enabled",
    )
    return (
        all(runtime.get(field) is True for field in required_true)
        and runtime.get("xq_window_hung") is False
        and runtime.get("xscript_window_hung") is False
    )


def acknowledgement_archive_path(config_path: Path, run_id: str, acknowledged_at: str) -> Path:
    safe_timestamp = acknowledged_at.replace("-", "").replace(":", "").replace("+", "_")
    safe_timestamp = safe_timestamp.replace(".", "_")
    return archive_directory(config_path) / f"{run_id}-{safe_timestamp}.json"


def acknowledge_manual_recovery(
    config_path: Path,
    config: dict[str, Any],
    expected_run_id: str,
    *,
    inspect: Callable[[Path, dict[str, Any]], dict[str, Any]] = xq_backtest.inspect_recovery_status,
    now: Callable[[], str] = utc_timestamp,
) -> dict[str, Any]:
    """Archive and remove one unchanged checkpoint after an explicit review.

    This function intentionally accepts only the decisions requiring human
    involvement.  It refuses a live progress job, incomplete read-only
    evidence, invalid checkpoints, unhealthy XQ windows, and any checkpoint
    replacement observed before deletion.
    """

    UUID(expected_run_id)
    checkpoint_path = xq_backtest.recovery_path(config_path)
    original_bytes, checkpoint = read_checkpoint_snapshot(checkpoint_path)
    if checkpoint.run_id != expected_run_id:
        raise ValueError("The supplied run ID does not match the current recovery checkpoint")

    recovery = inspect(config_path, config)
    if recovery.get("checkpoint_present") is not True or recovery.get("checkpoint_valid") is not True:
        raise RuntimeError("Recovery inspection no longer confirms the current checkpoint")
    if recovery.get("visible_progress") is not False:
        raise RuntimeError("A visible XQ progress job prevents manual checkpoint acknowledgement")
    if recovery.get("inspection_errors"):
        raise RuntimeError("Recovery inspection is incomplete; retain the checkpoint for manual review")
    if recovery.get("decision") not in {"manual_review_required", "safe_to_clear_checkpoint"}:
        raise RuntimeError("Recovery decision does not permit a manual checkpoint acknowledgement")
    if not runtime_is_healthy_for_manual_clear(recovery, checkpoint):
        raise RuntimeError("XQ runtime health is insufficient to manually clear the checkpoint")

    # A report is deliberately not treated as automatic proof.  The user
    # supplied the confirmation outside this tool; keep the tool's evidence
    # explicit about that limitation.
    if recovery.get("report_checkpoint_association_proven") is not False:
        raise RuntimeError("Unexpected report-association evidence requires manual inspection")

    if checkpoint_path.read_bytes() != original_bytes:
        raise RuntimeError("Recovery checkpoint changed during inspection; it was not cleared")

    acknowledged_at = now()
    record = archive_record(
        checkpoint,
        checkpoint_sha256=hashlib.sha256(original_bytes).hexdigest(),
        recovery=recovery,
        acknowledged_at=acknowledged_at,
    )
    archive_path = acknowledgement_archive_path(config_path, checkpoint.run_id, acknowledged_at)
    write_new_archive(archive_path, record)

    if checkpoint_path.read_bytes() != original_bytes:
        raise RuntimeError(
            "Recovery checkpoint changed after archive creation; it was retained for manual review"
        )
    checkpoint_path.unlink()
    if checkpoint_path.exists():
        raise RuntimeError("Recovery checkpoint removal could not be verified")
    return {
        "run_id": checkpoint.run_id,
        "checkpoint_cleared": True,
        "archive_path": str(archive_path.resolve()),
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "recovery_decision": recovery["decision"],
        "report_checkpoint_association_proven": False,
        "manual_confirmation_required": True,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm-manual-recovery", action="store_true")
    return parser.parse_args(argv)


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return EXIT_CODES[status]


def main(argv: Iterable[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if not args.confirm_manual_recovery:
            raise ValueError("Manual recovery acknowledgement requires --confirm-manual-recovery")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not config.get("calibrated"):
            return emit("automation_error", "XQ UI configuration is not calibrated")
        evidence = acknowledge_manual_recovery(args.config, config, args.run_id)
        return emit(
            "success",
            "XQ recovery checkpoint was manually acknowledged, archived, and cleared",
            **evidence,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return emit("automation_error", f"Manual recovery acknowledgement failed: {exc}")
    except Exception as exc:
        return emit(
            "environment_interruption",
            f"Manual recovery acknowledgement was not completed: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    sys.exit(main())
