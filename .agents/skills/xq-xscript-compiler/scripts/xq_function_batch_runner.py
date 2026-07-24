#!/usr/bin/env python3
"""Run function-boundary pairs one at a time with resumable health gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4
from xml.etree import ElementTree


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import xq_codex_scope  # noqa: E402
import xq_function_boundary_runner as boundary  # noqa: E402


BATCH_SCHEMA_VERSION = 1
BATCH_CONTRACT_VERSION = "1"
RUNNER_CONTRACT_VERSION = boundary.RUNNER_CONTRACT_VERSION
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}$")
PAIR_RUN_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class BatchError(RuntimeError):
    def __init__(self, message: str, *, evidence: Any = None):
        super().__init__(message)
        self.evidence = evidence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def stable_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def unique_pair_ids(cases: Sequence[boundary.BoundaryCase]) -> list[str]:
    return list(dict.fromkeys(case.pair_id for case in cases))


def select_pairs(
    all_pair_ids: Sequence[str],
    requested: Sequence[str],
) -> list[str]:
    available = set(all_pair_ids)
    if not requested:
        return list(all_pair_ids)
    selected: list[str] = []
    for pair_id in requested:
        if pair_id not in available:
            raise BatchError(f"Unknown pair id: {pair_id}")
        if pair_id in selected:
            raise BatchError(f"Duplicate pair selection: {pair_id}")
        selected.append(pair_id)
    return selected


def initialize_pair_states(pair_ids: Sequence[str]) -> dict[str, Any]:
    return {
        pair_id: {
            "status": "pending",
            "pair_run_id": str(uuid4()),
            "attempts": 0,
            "child_manifest_path": None,
            "result_json": None,
            "result_sha256": None,
            "recovery_before": None,
            "recovery_after": None,
            "started_at_utc": None,
            "completed_at_utc": None,
            "last_error": None,
        }
        for pair_id in pair_ids
    }


def validate_pair_result(
    payload: Any,
    *,
    suite_id: str,
    case_digest: str,
    pair_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise BatchError("Pair result must be a JSON object")
    if payload.get("suite_id") != suite_id:
        raise BatchError(f"Pair {pair_id} suite id mismatch")
    if payload.get("case_digest") != case_digest:
        raise BatchError(f"Pair {pair_id} case digest mismatch")
    if str(payload.get("runner_contract_version")) != RUNNER_CONTRACT_VERSION:
        raise BatchError(f"Pair {pair_id} runner contract mismatch")
    if payload.get("selected_pair_ids") != [pair_id]:
        raise BatchError(f"Pair {pair_id} selection evidence is not exact")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise BatchError(f"Pair {pair_id} must contain exactly two cases")
    case_ids: set[str] = set()
    roles: set[str] = set()
    for row in cases:
        if not isinstance(row, dict) or row.get("status") != "completed":
            raise BatchError(f"Pair {pair_id} contains an incomplete case")
        case_id = row.get("case_id")
        case = row.get("case")
        if not isinstance(case_id, str) or case_id in case_ids or not isinstance(case, dict):
            raise BatchError(f"Pair {pair_id} contains a duplicate or invalid case")
        if case.get("pair_id") != pair_id or case.get("role") not in {"control", "shortage"}:
            raise BatchError(f"Pair {pair_id} case metadata mismatch")
        case_ids.add(case_id)
        roles.add(case["role"])
    if roles != {"control", "shortage"}:
        raise BatchError(f"Pair {pair_id} must contain one control and one shortage case")
    counts = payload.get("counts")
    if not isinstance(counts, dict) or counts != {
        "total": 2, "completed": 2, "failed": 0, "pending": 0,
    }:
        raise BatchError(f"Pair {pair_id} completion counts are invalid")
    if payload.get("active_case_id") is not None:
        raise BatchError(f"Pair {pair_id} still has an active case")
    if payload.get("active_cleanup_document_id") is not None:
        raise BatchError(f"Pair {pair_id} still has active cleanup")
    cleanup = payload.get("cleanup_states")
    if not isinstance(cleanup, dict) or len(cleanup) != 4:
        raise BatchError(f"Pair {pair_id} must prove four document cleanups")
    if any(
        not isinstance(state, dict)
        or state.get("status") != "completed"
        or state.get("stage") != "completed"
        or state.get("last_evidence", {}).get("absence_verified") is not True
        for state in cleanup.values()
    ):
        raise BatchError(f"Pair {pair_id} cleanup evidence is incomplete")
    if payload.get("windows_wait_incidents") not in ([], None):
        raise BatchError(f"Pair {pair_id} has a Windows wait incident")
    if payload.get("last_error") is not None:
        raise BatchError(f"Pair {pair_id} retains an error")
    return cases


def aggregate_pair_results(
    *,
    suite_id: str,
    case_digest: str,
    pair_ids: Sequence[str],
    pair_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if set(pair_payloads) != set(pair_ids):
        missing = sorted(set(pair_ids) - set(pair_payloads))
        extra = sorted(set(pair_payloads) - set(pair_ids))
        raise BatchError("Aggregate pair set mismatch", evidence={"missing": missing, "extra": extra})
    rows: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    for pair_id in pair_ids:
        pair_rows = validate_pair_result(
            pair_payloads[pair_id],
            suite_id=suite_id,
            case_digest=case_digest,
            pair_id=pair_id,
        )
        for row in pair_rows:
            if row["case_id"] in case_ids:
                raise BatchError(f"Duplicate aggregate case: {row['case_id']}")
            case_ids.add(row["case_id"])
            rows.append(row)
    return {
        "schema_version": boundary.SUMMARY_SCHEMA_VERSION,
        "suite_id": suite_id,
        "case_digest": case_digest,
        "runner_contract_version": RUNNER_CONTRACT_VERSION,
        "selected_pair_ids": list(pair_ids),
        "counts": {
            "total": len(rows),
            "completed": len(rows),
            "failed": 0,
            "pending": 0,
        },
        "active_case_id": None,
        "active_cleanup_document_id": None,
        "cleanup_states": {},
        "pacing": None,
        "windows_wait_incidents": [],
        "cases": rows,
        "last_error": None,
    }


def aggregate_junit(payload: dict[str, Any]) -> str:
    suite = ElementTree.Element("testsuite", {
        "name": f"{payload['suite_id']}-batch",
        "tests": str(len(payload["cases"])),
        "failures": "0",
        "errors": "0",
        "skipped": "0",
    })
    properties = ElementTree.SubElement(suite, "properties")
    ElementTree.SubElement(
        properties,
        "property",
        {"name": "runner_contract_version", "value": payload["runner_contract_version"]},
    )
    ElementTree.SubElement(
        properties,
        "property",
        {"name": "case_digest", "value": payload["case_digest"]},
    )
    for row in payload["cases"]:
        case = row["case"]
        ElementTree.SubElement(
            suite,
            "testcase",
            {"classname": case["pair_id"], "name": row["case_id"]},
        )
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True)


def validate_resume_manifest(
    path: Path,
    *,
    suite_id: str,
    case_digest: str,
    xq_version: str,
    pair_ids: Sequence[str],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "batch_contract_version", "batch_id", "suite_id",
        "case_digest", "case_schema_version", "runner_contract_version", "xq_version",
        "required_pair_ids", "cooldown_seconds", "pacing", "pair_states",
        "output_json", "output_junit", "created_at_utc", "last_completed_at_utc",
        "last_error",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise BatchError("Batch resume manifest fields do not match schema")
    if payload["schema_version"] != BATCH_SCHEMA_VERSION:
        raise BatchError("Unsupported batch resume manifest schema")
    if payload["batch_contract_version"] != BATCH_CONTRACT_VERSION:
        raise BatchError("Batch contract version mismatch")
    if payload["suite_id"] != suite_id or payload["case_digest"] != case_digest:
        raise BatchError("Batch resume manifest suite mismatch")
    if payload["xq_version"] != xq_version:
        raise BatchError("Batch resume manifest XQ version mismatch")
    if payload["case_schema_version"] != boundary.CASE_SCHEMA_VERSION:
        raise BatchError("Batch resume manifest case schema mismatch")
    if payload["runner_contract_version"] != RUNNER_CONTRACT_VERSION:
        raise BatchError("Batch resume manifest runner contract mismatch")
    if payload["required_pair_ids"] != list(pair_ids):
        raise BatchError("Batch resume manifest pair plan mismatch")
    states = payload["pair_states"]
    if not isinstance(states, dict) or set(states) != set(pair_ids):
        raise BatchError("Batch resume manifest pair states mismatch")
    incomplete_seen = False
    for pair_id in pair_ids:
        state = states[pair_id]
        if not isinstance(state, dict) or state.get("status") not in {
            "pending", "running", "completed", "failed",
        }:
            raise BatchError(f"Invalid batch state for {pair_id}")
        run_id = state.get("pair_run_id")
        if not isinstance(run_id, str) or not PAIR_RUN_ID_RE.fullmatch(run_id):
            raise BatchError(f"Invalid child run id for {pair_id}")
        if state["status"] == "completed":
            if incomplete_seen:
                raise BatchError("Completed batch pairs are not a contiguous prefix")
            result_path = state.get("result_json")
            if not isinstance(result_path, str) or not Path(result_path).is_file():
                raise BatchError(f"Completed pair result is missing: {pair_id}")
            if file_sha256(Path(result_path)) != state.get("result_sha256"):
                raise BatchError(f"Completed pair result digest changed: {pair_id}")
        else:
            incomplete_seen = True
    return payload


def next_pair_id(manifest: dict[str, Any]) -> str | None:
    for pair_id in manifest["required_pair_ids"]:
        if manifest["pair_states"][pair_id]["status"] != "completed":
            return pair_id
    return None


def parse_json_output(completed: subprocess.CompletedProcess[str], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(completed.stdout.strip())
    except Exception as exc:
        raise BatchError(
            f"{label} did not return one JSON object",
            evidence={"returncode": completed.returncode, "stderr": completed.stderr[-2000:]},
        ) from exc
    if not isinstance(payload, dict):
        raise BatchError(f"{label} output is not an object")
    return payload


def run_command(command: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def recovery_status(config: Path, executor: Callable[..., subprocess.CompletedProcess[str]]) -> dict[str, Any]:
    completed = executor([
        sys.executable,
        str(SCRIPT_DIR / "xq_backtest.py"),
        "--config", str(config),
        "--recovery-status",
    ], 45)
    payload = parse_json_output(completed, "recovery-status")
    if completed.returncode != 0 or payload.get("status") != "success":
        raise BatchError("Read-only recovery-status failed", evidence=payload)
    if payload.get("decision") != "safe_to_start":
        raise BatchError("Batch health gate is not safe_to_start", evidence=payload)
    return payload


def discover_child_manifest(config: Path, pair_run_id: str) -> Path | None:
    base = config.resolve().parent / "function-boundary-runs"
    matches = list(base.glob(f"{pair_run_id}-*/manifest.json"))
    if len(matches) > 1:
        raise BatchError(f"Multiple child manifests found for run {pair_run_id}")
    return matches[0].resolve() if matches else None


def discover_completed_child_result(
    config: Path,
    suite_id: str,
    pair_run_id: str,
) -> Path | None:
    base = config.resolve().parent / "function-boundary-results"
    matches = list(base.glob(f"{suite_id}-{pair_run_id}.json"))
    if len(matches) > 1:
        raise BatchError(f"Multiple child results found for run {pair_run_id}")
    return matches[0].resolve() if matches else None


def boundary_command(
    args: argparse.Namespace,
    *,
    pair_id: str,
    pair_run_id: str,
    child_manifest: Path | None,
) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "xq_function_boundary_runner.py"),
        "--config", str(args.config),
        "--cases", str(args.cases),
        "--only-pair", pair_id,
        "--run-id", pair_run_id,
        "--timeout-seconds", str(args.timeout_seconds),
        "--late-report-seconds", str(args.late_report_seconds),
        "--ui-action-settle-seconds", str(args.ui_action_settle_seconds),
        "--ui-poll-initial-seconds", str(args.ui_poll_initial_seconds),
        "--ui-poll-max-seconds", str(args.ui_poll_max_seconds),
        "--ui-poll-backoff", str(args.ui_poll_backoff),
        "--ui-dialog-late-after-seconds", str(args.ui_dialog_late_after_seconds),
        "--ui-dialog-timeout-seconds", str(args.ui_dialog_timeout_seconds),
        "--ui-state-timeout-seconds", str(args.ui_state_timeout_seconds),
        "--inter-case-seconds", str(args.inter_case_seconds),
        "--confirm-historical-backtest",
    ]
    if child_manifest is not None:
        command.extend(["--resume-manifest", str(child_manifest)])
    return command


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--xq-version", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--resume-manifest", type=Path)
    parser.add_argument("--only-pair", action="append", default=[])
    parser.add_argument("--cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--late-report-seconds", type=float, default=20.0)
    parser.add_argument("--ui-action-settle-seconds", type=float, default=3.0)
    parser.add_argument("--ui-poll-initial-seconds", type=float, default=0.25)
    parser.add_argument("--ui-poll-max-seconds", type=float, default=1.0)
    parser.add_argument("--ui-poll-backoff", type=float, default=1.5)
    parser.add_argument("--ui-dialog-late-after-seconds", type=float, default=5.0)
    parser.add_argument("--ui-dialog-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--ui-state-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--inter-case-seconds", type=float, default=8.0)
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    parser.add_argument("--dry-run-plan", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    executor: Callable[..., subprocess.CompletedProcess[str]] = run_command,
) -> int:
    args = parse_args(argv)
    manifest: dict[str, Any] | None = None
    manifest_path: Path | None = None
    xq_touched = False
    try:
        if not VERSION_RE.fullmatch(args.xq_version):
            raise BatchError("--xq-version must be dotted numeric")
        if args.cooldown_seconds < 1:
            raise BatchError("--cooldown-seconds must be at least 1")
        suite, cases = boundary.load_case_file(args.cases)
        all_pair_ids = unique_pair_ids(cases)
        pair_ids = select_pairs(all_pair_ids, args.only_pair)
        case_digest = boundary.case_file_digest(suite)
        if args.dry_run_plan:
            return emit(
                "success",
                "Batch plan validated without touching XQ",
                xq_touched=False,
                suite_id=suite["suite_id"],
                case_digest=case_digest,
                runner_contract_version=RUNNER_CONTRACT_VERSION,
                pair_ids=pair_ids,
            )
        if not args.confirm_historical_backtest:
            raise BatchError("Explicit --confirm-historical-backtest is required")
        config = json.loads(args.config.read_text(encoding="utf-8"))
        for script_type in ("function", "autotrade"):
            xq_codex_scope.load_script_scope_contract(config, script_type)
        args.output_directory.mkdir(parents=True, exist_ok=True)
        if args.resume_manifest is not None:
            manifest_path = args.resume_manifest.resolve()
            manifest = validate_resume_manifest(
                manifest_path,
                suite_id=suite["suite_id"],
                case_digest=case_digest,
                xq_version=args.xq_version,
                pair_ids=pair_ids,
            )
            manifest["cooldown_seconds"] = max(
                float(manifest["cooldown_seconds"]), float(args.cooldown_seconds),
            )
        else:
            batch_id = str(uuid4())
            manifest_path = args.output_directory.resolve() / f"{suite['suite_id']}-{batch_id}-batch.json"
            if manifest_path.exists():
                raise BatchError("Refusing to overwrite an existing batch manifest")
            manifest = {
                "schema_version": BATCH_SCHEMA_VERSION,
                "batch_contract_version": BATCH_CONTRACT_VERSION,
                "batch_id": batch_id,
                "suite_id": suite["suite_id"],
                "case_digest": case_digest,
                "case_schema_version": boundary.CASE_SCHEMA_VERSION,
                "runner_contract_version": RUNNER_CONTRACT_VERSION,
                "xq_version": args.xq_version,
                "required_pair_ids": pair_ids,
                "cooldown_seconds": float(args.cooldown_seconds),
                "pacing": {
                    "ui_action_settle_seconds": args.ui_action_settle_seconds,
                    "ui_poll_initial_seconds": args.ui_poll_initial_seconds,
                    "ui_poll_max_seconds": args.ui_poll_max_seconds,
                    "ui_poll_backoff": args.ui_poll_backoff,
                    "ui_dialog_late_after_seconds": args.ui_dialog_late_after_seconds,
                    "ui_dialog_timeout_seconds": args.ui_dialog_timeout_seconds,
                    "ui_state_timeout_seconds": args.ui_state_timeout_seconds,
                    "inter_case_seconds": args.inter_case_seconds,
                },
                "pair_states": initialize_pair_states(pair_ids),
                "output_json": str(
                    (args.output_directory / f"{suite['suite_id']}-{batch_id}-aggregate.json").resolve()
                ),
                "output_junit": str(
                    (args.output_directory / f"{suite['suite_id']}-{batch_id}-aggregate.xml").resolve()
                ),
                "created_at_utc": utc_now(),
                "last_completed_at_utc": None,
                "last_error": None,
            }
        atomic_write_json(manifest_path, manifest)
        while (pair_id := next_pair_id(manifest)) is not None:
            state = manifest["pair_states"][pair_id]
            if manifest["last_completed_at_utc"] is not None:
                elapsed = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(manifest["last_completed_at_utc"])
                ).total_seconds()
                remaining = manifest["cooldown_seconds"] - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            xq_touched = True
            state["recovery_before"] = recovery_status(args.config, executor)
            previous_status = state["status"]
            child_manifest = discover_child_manifest(args.config, state["pair_run_id"])
            completed_result = discover_completed_child_result(
                args.config, suite["suite_id"], state["pair_run_id"],
            )
            if previous_status != "pending" and child_manifest is None:
                if completed_result is None:
                    raise BatchError(
                        f"Interrupted pair has neither a child manifest nor a completed result: {pair_id}"
                    )
                pair_payload = json.loads(completed_result.read_text(encoding="utf-8"))
                validate_pair_result(
                    pair_payload,
                    suite_id=suite["suite_id"],
                    case_digest=case_digest,
                    pair_id=pair_id,
                )
                state["recovery_after"] = recovery_status(args.config, executor)
                state["status"] = "completed"
                state["result_json"] = str(completed_result)
                state["result_sha256"] = file_sha256(completed_result)
                state["child_manifest_path"] = None
                state["completed_at_utc"] = utc_now()
                state["last_error"] = None
                manifest["last_completed_at_utc"] = state["completed_at_utc"]
                manifest["last_error"] = None
                atomic_write_json(manifest_path, manifest)
                continue
            state["status"] = "running"
            state["attempts"] += 1
            state["started_at_utc"] = utc_now()
            state["last_error"] = None
            atomic_write_json(manifest_path, manifest)
            state["child_manifest_path"] = str(child_manifest) if child_manifest else None
            completed = executor(
                boundary_command(
                    args,
                    pair_id=pair_id,
                    pair_run_id=state["pair_run_id"],
                    child_manifest=child_manifest,
                ),
                None,
            )
            child = parse_json_output(completed, f"boundary pair {pair_id}")
            if completed.returncode != 0 or child.get("status") != "success":
                state["status"] = "failed"
                state["child_manifest_path"] = child.get("manifest_path") or state["child_manifest_path"]
                state["last_error"] = child
                manifest["last_error"] = {"pair_id": pair_id, "child": child}
                atomic_write_json(manifest_path, manifest)
                raise BatchError(f"Boundary pair failed: {pair_id}", evidence=child)
            result_path = Path(str(child.get("progress_json", ""))).resolve()
            pair_payload = json.loads(result_path.read_text(encoding="utf-8"))
            validate_pair_result(
                pair_payload,
                suite_id=suite["suite_id"],
                case_digest=case_digest,
                pair_id=pair_id,
            )
            state["recovery_after"] = recovery_status(args.config, executor)
            state["status"] = "completed"
            state["result_json"] = str(result_path)
            state["result_sha256"] = file_sha256(result_path)
            state["child_manifest_path"] = None
            state["completed_at_utc"] = utc_now()
            manifest["last_completed_at_utc"] = state["completed_at_utc"]
            manifest["last_error"] = None
            atomic_write_json(manifest_path, manifest)
        pair_payloads = {
            pair_id: json.loads(
                Path(manifest["pair_states"][pair_id]["result_json"]).read_text(encoding="utf-8")
            )
            for pair_id in pair_ids
        }
        aggregate = aggregate_pair_results(
            suite_id=suite["suite_id"],
            case_digest=case_digest,
            pair_ids=pair_ids,
            pair_payloads=pair_payloads,
        )
        atomic_write_json(Path(manifest["output_json"]), aggregate)
        atomic_write_text(Path(manifest["output_junit"]), aggregate_junit(aggregate))
        return emit(
            "success",
            "All required pairs completed one at a time with health gates",
            batch_manifest=str(manifest_path),
            aggregate_json=manifest["output_json"],
            aggregate_junit=manifest["output_junit"],
            pair_ids=pair_ids,
            completed_pairs=len(pair_ids),
            xq_version=args.xq_version,
        )
    except (
        BatchError,
        xq_codex_scope.CodexScopeError,
        ValueError,
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        if manifest is not None and manifest_path is not None:
            manifest["last_error"] = {
                "message": str(exc),
                "evidence": getattr(exc, "evidence", None),
                "recorded_at_utc": utc_now(),
            }
            atomic_write_json(manifest_path, manifest)
        return emit(
            "automation_error",
            str(exc),
            xq_touched=xq_touched,
            batch_manifest=str(manifest_path) if manifest_path else None,
            evidence=getattr(exc, "evidence", None),
        )


if __name__ == "__main__":
    sys.exit(main())
