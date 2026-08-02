#!/usr/bin/env python3
"""Distill one private XQ runtime suite manifest into a public release attestation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

import xq_runtime_evidence_suite as runtime_suite


ATTESTATION_SCHEMA_VERSION = 1
ATTESTATION_CONTRACT_VERSION = "1"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
PRIVATE_ROOT = (PROJECT_ROOT / ".xq-auto-writer").resolve()
RELEASE_ROOT = (PROJECT_ROOT / "release").resolve()


class AttestationError(RuntimeError):
    pass


def _inside(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise AttestationError(f"Path must stay inside {resolved_root}: {resolved}") from exc
    return resolved


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AttestationError(f"Unable to read JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AttestationError("JSON root must be an object")
    return value


def source_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _settings_evidence(case: runtime_suite.RuntimeCase, runtime: dict[str, Any]) -> dict[str, Any]:
    settings = runtime.get("settings_evidence")
    if not isinstance(settings, dict):
        return {
            "settings_evidence_present": False,
            "active_script_bound": runtime.get("script_name") == case.caller_name,
            "preload_control_enabled": None,
            "preload_records_applied": None,
            "preload_records_requested": None,
        }
    active = settings.get("active_script")
    active_bound = isinstance(active, dict) and (
        active.get("script_name") == case.caller_name
        and active.get("script_type") == case.caller_type
        and active.get("location") == "自訂/CODEX/"
    )
    return {
        "settings_evidence_present": True,
        "active_script_bound": active_bound,
        "preload_control_enabled": settings.get("preload_control_enabled"),
        "preload_records_applied": settings.get("preload_records_applied"),
        "preload_records_requested": settings.get("preload_records_requested"),
    }


def build_attestation(
    manifest: dict[str, Any], cases: list[runtime_suite.RuntimeCase], digest: str, xq_version: str
) -> dict[str, Any]:
    if manifest.get("manifest_schema_version") != runtime_suite.MANIFEST_SCHEMA_VERSION:
        raise AttestationError("Private manifest schema does not match")
    if manifest.get("runner_contract_version") != runtime_suite.RUNNER_CONTRACT_VERSION:
        raise AttestationError("Private runner contract does not match")
    if manifest.get("suite_digest") != digest:
        raise AttestationError("Private suite digest does not match the tracked case file")
    states = manifest.get("cases")
    if not isinstance(states, dict) or set(states) != {case.case_id for case in cases}:
        raise AttestationError("Private manifest case set does not match")

    public_cases: list[dict[str, Any]] = []
    for case in cases:
        state = states[case.case_id]
        if not isinstance(state, dict) or state.get("status") != "completed":
            raise AttestationError(f"Case is not completed: {case.case_id}")
        result = state.get("result")
        if not isinstance(result, dict):
            raise AttestationError(f"Case result is missing: {case.case_id}")
        normalized = result.get("normalized")
        runtime = result.get("runtime")
        post_recovery = result.get("post_recovery")
        if not isinstance(normalized, dict) or not isinstance(runtime, dict) or not isinstance(post_recovery, dict):
            raise AttestationError(f"Case evidence is incomplete: {case.case_id}")
        if normalized.get("function_source_sha256") != source_sha256(case.function_source):
            raise AttestationError(f"Function source changed after evidence: {case.case_id}")
        if normalized.get("caller_source_sha256") != source_sha256(case.caller_source):
            raise AttestationError(f"Caller source changed after evidence: {case.case_id}")
        if post_recovery.get("decision") != "safe_to_start" or post_recovery.get("checkpoint_present") is not False:
            raise AttestationError(f"Post-run recovery is not clean: {case.case_id}")

        actual_error_present = "actual_error_code" in runtime
        public_cases.append(
            {
                "case_id": case.case_id,
                "caller_type": case.caller_type,
                "compile": {
                    "function_status": normalized.get("function_compile_status"),
                    "caller_status": normalized.get("caller_compile_status"),
                    "function_source_sha256": normalized.get("function_source_sha256"),
                    "caller_source_sha256": normalized.get("caller_source_sha256"),
                },
                "runtime": {
                    "status": normalized.get("runtime_status"),
                    "success_count": normalized.get("success_count"),
                    "failure_count": normalized.get("failure_count"),
                    "total_trades": normalized.get("total_trades"),
                    "row_count": normalized.get("row_count"),
                    "actual_error_code": runtime.get("actual_error_code") if actual_error_present else None,
                    "actual_error_code_observed": actual_error_present,
                    "progress_seen": runtime.get("progress_seen"),
                    "new_report_count": runtime.get("new_report_count"),
                    "marker_matched": runtime.get("marker_matched"),
                    "report_decision": runtime.get("report_decision"),
                    "report_cleanup_complete": normalized.get("report_cleanup_complete"),
                    "chart_recovery_complete": (
                        runtime.get("recovery", {}).get("complete")
                        if isinstance(runtime.get("recovery"), dict)
                        else None
                    ),
                    "recovery_checkpoint_retained": normalized.get("recovery_checkpoint_retained"),
                },
                "settings": _settings_evidence(case, runtime),
                "post_recovery_clean": True,
            }
        )

    return {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "contract_version": ATTESTATION_CONTRACT_VERSION,
        "xq_version": xq_version,
        "case_schema_version": runtime_suite.CASE_SCHEMA_VERSION,
        "runner_contract_version": runtime_suite.RUNNER_CONTRACT_VERSION,
        "suite_digest": digest,
        "contains_private_data": False,
        "proof_scope": "current-source compile plus representative XQ runtime smoke",
        "cases": public_cases,
        "limitations": [
            "Representative smoke evidence is not strategy-performance evidence.",
            "A null actual_error_code means XQ did not report one; no code was inferred.",
            "Products, dates, report handles, window titles, raw compiler output, and exported rows are excluded.",
        ],
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    output = _inside(path, RELEASE_ROOT)
    if output.exists():
        raise AttestationError(f"Refusing to overwrite existing attestation: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--xq-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-public-attestation", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def execute(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _inside(args.manifest, PRIVATE_ROOT)
    _raw, cases, digest = runtime_suite.load_cases(args.cases)
    payload = build_attestation(_load_object(manifest_path), cases, digest, args.xq_version)
    if args.dry_run:
        return {"status": "success", "message": "Public attestation validated without writing", "dry_run": True, **payload}
    if not args.confirm_public_attestation:
        raise AttestationError("Explicit --confirm-public-attestation is required")
    write_new_json(args.output, payload)
    return {
        "status": "success",
        "message": "Public XQ runtime attestation written",
        "dry_run": False,
        "output": str(args.output.resolve()),
        "suite_digest": digest,
        "case_count": len(cases),
        "contains_private_data": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = execute(parse_args(argv))
    except AttestationError as exc:
        print(json.dumps({"status": "automation_error", "message": str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
