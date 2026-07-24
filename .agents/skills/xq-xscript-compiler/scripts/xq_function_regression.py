#!/usr/bin/env python3
"""Normalize function-boundary evidence and compare versioned regression baselines."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4
from xml.etree import ElementTree


BASELINE_SCHEMA_VERSION = 1
DIFF_SCHEMA_VERSION = 2
DEFAULT_RUNNER_CONTRACT_VERSION = "7"
VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}$")


class RegressionError(RuntimeError):
    def __init__(self, message: str, *, status: str = "automation_error", evidence: Any = None):
        super().__init__(message)
        self.status = status
        self.evidence = evidence


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    if status == "success":
        return 0
    if status in {"regression", "version_mismatch", "evidence_insufficient"}:
        return 2
    return 3


def atomic_write_text(path: Path, content: str, *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace and path.exists():
        raise RegressionError(f"Refusing to overwrite existing file: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        if not replace and path.exists():
            raise RegressionError(f"Refusing to overwrite existing file: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: dict[str, Any], *, replace: bool = True) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        replace=replace,
    )


def stable_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RegressionError(f"{label} must be an integer >= {minimum}")
    return value


def normalize_compile(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"status": "missing", "error_count": None, "warning_count": None}
    text = "\n".join(
        str(payload.get(key, "")) for key in ("compiler_message", "compiler_output")
    )
    error_matches = re.findall(r"(\d+)\s*項錯誤", text)
    warning_matches = re.findall(r"(\d+)\s*項警告", text)
    error_count = int(error_matches[-1]) if error_matches else None
    warning_count = int(warning_matches[-1]) if warning_matches else None
    success = "編譯成功" in text and error_count == 0 and warning_count == 0
    return {
        "status": "success" if success else "not_proven",
        "error_count": error_count,
        "warning_count": warning_count,
    }


def normalize_case(row: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(row, dict):
        raise RegressionError("Each result case must be an object")
    case_id = row.get("case_id")
    case = row.get("case")
    if not isinstance(case_id, str) or not case_id or not isinstance(case, dict):
        raise RegressionError("Result case is missing case_id or case contract")
    pair_id = case.get("pair_id")
    role = case.get("role")
    if not isinstance(pair_id, str) or role not in {"control", "shortage"}:
        raise RegressionError(f"Invalid pair metadata for {case_id}")
    compile_payload = row.get("compile")
    compile_payload = compile_payload if isinstance(compile_payload, dict) else {}
    completed = row.get("result")
    evaluated = completed.get("result") if isinstance(completed, dict) else None
    evaluated = evaluated if isinstance(evaluated, dict) else {}
    execution = evaluated.get("execution_evidence")
    execution = execution if isinstance(execution, dict) else {}
    settings = evaluated.get("settings_applied")
    settings = settings if isinstance(settings, dict) else {}
    default_configured = case.get("default_value") is not None
    expected_default = case.get("expect_default_value") if default_configured else None
    marker_matches = evaluated.get("marker_matches") is True
    if not default_configured:
        default_path = "not_configured"
    elif not marker_matches:
        default_path = "not_observed"
    else:
        default_path = "default_equal" if expected_default is True else "default_not_equal"
    normalized = {
        "case_contract_sha256": stable_digest(case),
        "pair_id": pair_id,
        "role": role,
        "state": row.get("status"),
        "compile": {
            "function": normalize_compile(compile_payload.get("function")),
            "caller": normalize_compile(compile_payload.get("caller")),
        },
        "outcome": {
            "classification": evaluated.get("classification"),
            "success_count": evaluated.get("success_count"),
            "failure_count": evaluated.get("failure_count"),
            "total_trades": evaluated.get("total_trades"),
            "actual_error_code": evaluated.get("actual_error_code"),
            "actual_marker": evaluated.get("actual_marker"),
            "marker_matches": evaluated.get("marker_matches"),
        },
        "execution_evidence": {
            "formal_execution_proven": execution.get("formal_execution_proven"),
            "path_sentinel_observed": execution.get("path_sentinel_observed"),
            "no_execution_evidence": execution.get("no_execution_evidence"),
        },
        "settings_applied": {
            "preload_control_enabled": settings.get("preload_control_enabled"),
            "expected_preload_state": settings.get("expected_preload_state"),
            "preload_state_matches": settings.get("preload_state_matches"),
            "preload_records_requested": settings.get("preload_records_requested"),
            "preload_records_applied": settings.get("preload_records_applied"),
        },
        "default_branch": {
            "configured": default_configured,
            "expected_default_value": expected_default,
            "observed_path": default_path,
        },
    }
    return case_id, normalized


def normalize_result(
    payload: Any,
    *,
    xq_version: str,
    case_schema_version: int,
    runner_contract_version: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RegressionError("Result JSON must contain an object")
    suite_id = payload.get("suite_id")
    cases = payload.get("cases")
    if not isinstance(suite_id, str) or not suite_id or not isinstance(cases, list):
        raise RegressionError("Result JSON is missing suite_id or cases")
    normalized_cases: dict[str, Any] = {}
    for row in cases:
        case_id, normalized = normalize_case(row)
        if case_id in normalized_cases:
            raise RegressionError(f"Duplicate result case: {case_id}")
        normalized_cases[case_id] = normalized
    if not normalized_cases:
        raise RegressionError("Result JSON contains no cases")
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "suite_id": suite_id,
        "case_schema_version": case_schema_version,
        "runner_contract_version": runner_contract_version,
        "xq_version": xq_version,
        "cases": dict(sorted(normalized_cases.items())),
    }


def load_baseline(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "baseline_version", "suite_id", "case_schema_version",
        "runner_contract_version", "xq_version", "cases",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise RegressionError("Baseline fields do not match schema")
    if payload["schema_version"] != BASELINE_SCHEMA_VERSION:
        raise RegressionError("Unsupported regression baseline schema")
    _integer(payload["baseline_version"], "baseline_version", minimum=1)
    if not isinstance(payload["cases"], dict) or not payload["cases"]:
        raise RegressionError("Baseline must contain normalized cases")
    return payload


def metadata_differences(current: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("suite_id", "case_schema_version", "runner_contract_version", "xq_version")
    return [
        {"field": field, "baseline": baseline.get(field), "current": current.get(field)}
        for field in fields
        if baseline.get(field) != current.get(field)
    ]


def _flatten_differences(baseline: Any, current: Any, prefix: str = "") -> list[dict[str, Any]]:
    if isinstance(baseline, dict) and isinstance(current, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(baseline) | set(current)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in baseline:
                differences.append({"field": path, "baseline": None, "current": current[key]})
            elif key not in current:
                differences.append({"field": path, "baseline": baseline[key], "current": None})
            else:
                differences.extend(_flatten_differences(baseline[key], current[key], path))
        return differences
    if baseline != current:
        return [{"field": prefix, "baseline": baseline, "current": current}]
    return []


def compare_normalized(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata_differences(current, baseline)
    case_rows = []
    affected_case_ids: list[str] = []
    affected_pair_ids: list[str] = []
    current_cases = current["cases"]
    baseline_cases = baseline["cases"]
    for case_id in sorted(set(current_cases) | set(baseline_cases)):
        if case_id not in current_cases:
            status = "missing_current"
            differences = [{"field": "case", "baseline": "present", "current": "missing"}]
            pair_id = baseline_cases[case_id].get("pair_id")
        elif case_id not in baseline_cases:
            status = "new_case"
            differences = [{"field": "case", "baseline": "missing", "current": "present"}]
            pair_id = current_cases[case_id].get("pair_id")
        else:
            differences = _flatten_differences(baseline_cases[case_id], current_cases[case_id])
            status = "changed" if differences else "unchanged"
            pair_id = current_cases[case_id].get("pair_id")
        if status != "unchanged":
            affected_case_ids.append(case_id)
            if isinstance(pair_id, str) and pair_id not in affected_pair_ids:
                affected_pair_ids.append(pair_id)
        case_rows.append({
            "case_id": case_id,
            "pair_id": pair_id,
            "status": status,
            "differences": differences,
        })
    incomplete = any(
        case.get("state") != "completed"
        or case["compile"]["function"]["status"] != "success"
        or case["compile"]["caller"]["status"] != "success"
        for case in current_cases.values()
    )
    if metadata:
        classification = "version_mismatch"
    elif incomplete or any(row["status"] == "missing_current" for row in case_rows):
        classification = "evidence_insufficient"
    elif affected_case_ids:
        classification = "regression"
    else:
        classification = "unchanged"
    diff = {
        "schema_version": DIFF_SCHEMA_VERSION,
        "classification": classification,
        "metadata_differences": metadata,
        "summary": {
            "total_cases": len(case_rows),
            "unchanged_cases": sum(row["status"] == "unchanged" for row in case_rows),
            "affected_cases": len(affected_case_ids),
        },
        "affected_case_ids": affected_case_ids,
        "affected_pair_ids": affected_pair_ids,
        "runner_only_pair_arguments": (
            [
                value
                for pair_id in affected_pair_ids
                for value in ("--only-pair", pair_id)
            ]
            if classification == "regression"
            else []
        ),
        "cases": case_rows,
    }
    diff["incremental_plan"] = incremental_plan(diff, current_cases)
    return diff


def incremental_plan(
    diff: dict[str, Any],
    current_cases: dict[str, Any],
) -> dict[str, Any]:
    classification = diff["classification"]
    pair_ids = list(diff["affected_pair_ids"])
    if classification == "regression" and pair_ids:
        return {
            "mode": "only_pair",
            "safe_to_execute": True,
            "pair_ids": pair_ids,
            "runner_arguments": [
                value for pair_id in pair_ids for value in ("--only-pair", pair_id)
            ],
            "reason": "normalized_case_difference",
        }
    if classification == "unchanged":
        return {
            "mode": "none",
            "safe_to_execute": True,
            "pair_ids": [],
            "runner_arguments": [],
            "reason": "baseline_unchanged",
        }
    if classification == "version_mismatch":
        all_pairs = list(dict.fromkeys(
            case.get("pair_id")
            for case in current_cases.values()
            if isinstance(case.get("pair_id"), str)
        ))
        return {
            "mode": "full_matrix_required",
            "safe_to_execute": False,
            "pair_ids": all_pairs,
            "runner_arguments": [],
            "reason": "version_contract_mismatch_blocks_incremental_selection",
        }
    return {
        "mode": "manual_review",
        "safe_to_execute": False,
        "pair_ids": pair_ids,
        "runner_arguments": [],
        "reason": "evidence_insufficient",
    }


def junit_report(diff: dict[str, Any], suite_id: str) -> str:
    failures = sum(case["status"] != "unchanged" for case in diff["cases"])
    suite = ElementTree.Element("testsuite", {
        "name": f"{suite_id}-regression",
        "tests": str(len(diff["cases"])),
        "failures": str(failures),
        "errors": "0",
        "skipped": "0",
    })
    properties = ElementTree.SubElement(suite, "properties")
    ElementTree.SubElement(
        properties, "property", {"name": "classification", "value": diff["classification"]},
    )
    for case in diff["cases"]:
        node = ElementTree.SubElement(
            suite, "testcase", {"classname": suite_id, "name": case["case_id"]},
        )
        if case["status"] != "unchanged":
            failure = ElementTree.SubElement(
                node, "failure", {"message": case["status"]},
            )
            failure.text = json.dumps(case["differences"], ensure_ascii=False, sort_keys=True)
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True)


def markdown_report(diff: dict[str, Any], current: dict[str, Any], baseline_version: int) -> str:
    lines = [
        f"# {current['suite_id']} regression",
        "",
        f"- Classification: `{diff['classification']}`",
        f"- Baseline version: `{baseline_version}`",
        f"- XQ version: `{current['xq_version']}`",
        f"- Case schema: `{current['case_schema_version']}`",
        f"- Runner contract: `{current['runner_contract_version']}`",
        f"- Cases: {diff['summary']['total_cases']}",
        f"- Affected: {diff['summary']['affected_cases']}",
        "",
        "| Case | Pair | Status | Changed fields |",
        "| --- | --- | --- | --- |",
    ]
    for case in diff["cases"]:
        fields = ", ".join(item["field"] for item in case["differences"]) or "—"
        lines.append(
            f"| `{case['case_id']}` | `{case.get('pair_id') or '—'}` | "
            f"`{case['status']}` | {fields} |"
        )
    if diff["metadata_differences"]:
        lines.extend(["", "## Metadata differences", ""])
        for item in diff["metadata_differences"]:
            lines.append(
                f"- `{item['field']}`: `{item['baseline']}` → `{item['current']}`"
            )
    plan = diff["incremental_plan"]
    lines.extend([
        "",
        "## Incremental plan",
        "",
        f"- Mode: `{plan['mode']}`",
        f"- Safe to execute automatically: `{str(plan['safe_to_execute']).lower()}`",
        f"- Reason: `{plan['reason']}`",
        "- Runner arguments: "
        + (
            "`" + " ".join(plan["runner_arguments"]) + "`"
            if plan["runner_arguments"]
            else "—"
        ),
    ])
    return "\n".join(lines) + "\n"


def write_reports(
    output_directory: Path,
    diff: dict[str, Any],
    current: dict[str, Any],
    baseline_version: int,
) -> dict[str, str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    stem = f"{current['suite_id']}-regression"
    paths = {
        "json": output_directory / f"{stem}.json",
        "junit": output_directory / f"{stem}.xml",
        "markdown": output_directory / f"{stem}.md",
        "plan": output_directory / f"{stem}-plan.json",
    }
    atomic_write_json(paths["json"], diff)
    atomic_write_json(paths["plan"], diff["incremental_plan"])
    atomic_write_text(paths["junit"], junit_report(diff, current["suite_id"]))
    atomic_write_text(
        paths["markdown"], markdown_report(diff, current, baseline_version),
    )
    return {key: str(path.resolve()) for key, path in paths.items()}


def baseline_from_current(current: dict[str, Any], baseline_version: int) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "baseline_version": baseline_version,
        "suite_id": current["suite_id"],
        "case_schema_version": current["case_schema_version"],
        "runner_contract_version": current["runner_contract_version"],
        "xq_version": current["xq_version"],
        "cases": copy.deepcopy(current["cases"]),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-json", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--xq-version", required=True)
    parser.add_argument("--case-schema-version", type=int, required=True)
    parser.add_argument(
        "--runner-contract-version", default=DEFAULT_RUNNER_CONTRACT_VERSION,
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--write-baseline", type=Path)
    parser.add_argument("--baseline-version", type=int)
    parser.add_argument("--confirm-baseline-update", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not VERSION_RE.fullmatch(args.xq_version):
            raise RegressionError("--xq-version must be a dotted numeric version")
        if args.case_schema_version < 1:
            raise RegressionError("--case-schema-version must be positive")
        if not str(args.runner_contract_version).strip():
            raise RegressionError("--runner-contract-version must not be empty")
        if args.write_baseline is not None:
            if not args.confirm_baseline_update:
                raise RegressionError(
                    "Writing a baseline requires explicit --confirm-baseline-update",
                )
            if args.baseline_version is None or args.baseline_version < 1:
                raise RegressionError("Writing a baseline requires a positive --baseline-version")
            if args.write_baseline.exists():
                raise RegressionError("Baseline destination already exists; old baselines are immutable")
            if args.baseline is not None and args.write_baseline.resolve() == args.baseline.resolve():
                raise RegressionError("A baseline update must use a new path and preserve the old baseline")
        elif args.baseline_version is not None or args.confirm_baseline_update:
            raise RegressionError("Baseline update flags require --write-baseline")
        current_payload = json.loads(args.result_json.read_text(encoding="utf-8"))
        current = normalize_result(
            current_payload,
            xq_version=args.xq_version,
            case_schema_version=args.case_schema_version,
            runner_contract_version=str(args.runner_contract_version),
        )
        if args.baseline is None:
            if args.write_baseline is None:
                raise RegressionError("--baseline is required unless creating the first baseline")
            baseline = baseline_from_current(current, args.baseline_version)
            diff = compare_normalized(current, baseline)
            old_version = args.baseline_version
        else:
            baseline = load_baseline(args.baseline)
            old_version = baseline["baseline_version"]
            diff = compare_normalized(current, baseline)
            if args.write_baseline is not None and args.baseline_version <= old_version:
                raise RegressionError("New baseline version must be greater than the old version")
        reports = write_reports(args.output_directory, diff, current, old_version)
        baseline_written = None
        if args.write_baseline is not None:
            new_baseline = baseline_from_current(current, args.baseline_version)
            atomic_write_json(args.write_baseline, new_baseline, replace=False)
            baseline_written = str(args.write_baseline.resolve())
        status = "success" if diff["classification"] == "unchanged" else diff["classification"]
        message = (
            "Regression evidence matches the versioned baseline"
            if status == "success"
            else f"Regression comparison classified as {status}"
        )
        if baseline_written is not None:
            status = "success"
            message = "New immutable regression baseline written with explicit confirmation"
        return emit(
            status,
            message,
            classification=diff["classification"],
            reports=reports,
            baseline_written=baseline_written,
            previous_baseline_preserved=args.baseline is not None,
            affected_case_ids=diff["affected_case_ids"],
            affected_pair_ids=diff["affected_pair_ids"],
            runner_only_pair_arguments=diff["runner_only_pair_arguments"],
            incremental_plan=diff["incremental_plan"],
            contains_private_data=False,
        )
    except RegressionError as exc:
        return emit(exc.status, str(exc), evidence=exc.evidence, xq_touched=False)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return emit("automation_error", f"{type(exc).__name__}: {exc}", xq_touched=False)


if __name__ == "__main__":
    sys.exit(main())
