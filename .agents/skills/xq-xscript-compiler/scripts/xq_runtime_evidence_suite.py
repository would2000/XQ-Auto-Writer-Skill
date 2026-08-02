#!/usr/bin/env python3
"""Run a resumable four-caller XQ runtime evidence suite with function gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
from xml.etree import ElementTree

import xq_category_selector


CASE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
RUNNER_CONTRACT_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
CALLER_TYPES = {"indicator", "screener", "alert", "autotrade"}
RUNTIME_SCRIPTS = {
    "indicator": "xq_indicator.py",
    "screener": "xq_screener_backtest_run.py",
    "alert": "xq_alert_backtest_run.py",
    "autotrade": "xq_backtest.py",
}
BACKTEST_TYPES = {"screener", "alert", "autotrade"}
OWNED_RUNTIME_OPTIONS = {
    "--config",
    "--script-name",
    "--confirm-historical-backtest",
    "--dry-run",
    "--recovery-status",
}
PROJECT_ROOT = Path(__file__).resolve().parents[4]
PRIVATE_ROOT = (PROJECT_ROOT / ".xq-auto-writer").resolve()


class SuiteError(RuntimeError):
    def __init__(self, stage: str, message: str, *, child: dict[str, Any] | None = None):
        super().__init__(message)
        self.stage = stage
        self.child = child


@dataclass(frozen=True)
class RuntimeCase:
    case_id: str
    caller_type: str
    function_source: Path
    function_name: str
    function_return_type: str
    caller_source: Path
    caller_name: str
    runtime_args: tuple[str, ...]


Runner = Callable[[str, list[str], float], tuple[int, dict[str, Any]]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--resume-manifest", type=Path)
    parser.add_argument("--only-case", action="append", default=[])
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project_source(raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise SuiteError("validation", f"{label} must be a non-empty project-relative path")
    candidate = (PROJECT_ROOT / raw).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise SuiteError("validation", f"{label} must stay inside the project") from exc
    if not candidate.is_file():
        raise SuiteError("validation", f"{label} does not exist: {raw}")
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SuiteError("validation", f"Unable to read {label}: {exc}") from exc
    if not text.strip():
        raise SuiteError("validation", f"{label} is empty")
    return candidate


def _runtime_arguments(raw: Any, case_id: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise SuiteError("validation", f"{case_id} runtime_args must be a string array")
    arguments = tuple(raw)
    for token in arguments:
        option = token.split("=", 1)[0]
        if option in OWNED_RUNTIME_OPTIONS:
            raise SuiteError("validation", f"{case_id} runtime option {option} is runner-owned")
    return arguments


def load_cases(path: Path) -> tuple[dict[str, Any], list[RuntimeCase], str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuiteError("validation", f"Unable to read cases: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != CASE_SCHEMA_VERSION:
        raise SuiteError("validation", f"case schema must be {CASE_SCHEMA_VERSION}")
    items = raw.get("cases")
    if not isinstance(items, list) or not items:
        raise SuiteError("validation", "cases must be a non-empty array")
    cases: list[RuntimeCase] = []
    identifiers: set[str] = set()
    caller_types: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise SuiteError("validation", "each case must be an object")
        case_id = str(item.get("id") or "")
        if not case_id or case_id in identifiers:
            raise SuiteError("validation", f"case id is empty or duplicated: {case_id!r}")
        identifiers.add(case_id)
        caller_type = str(item.get("caller_type") or "")
        if caller_type not in CALLER_TYPES or caller_type in caller_types:
            raise SuiteError("validation", f"caller_type must be unique and supported: {caller_type}")
        caller_types.add(caller_type)
        function = item.get("function")
        caller = item.get("caller")
        if not isinstance(function, dict) or not isinstance(caller, dict):
            raise SuiteError("validation", f"{case_id} requires function and caller objects")
        function_name = xq_category_selector.validate_script_name(str(function.get("name") or ""))
        caller_name = xq_category_selector.validate_script_name(str(caller.get("name") or ""))
        return_type = str(function.get("return_type") or "")
        if return_type not in {"number", "boolean", "string"}:
            raise SuiteError("validation", f"{case_id} has invalid function return type")
        cases.append(RuntimeCase(
            case_id=case_id,
            caller_type=caller_type,
            function_source=_project_source(function.get("source"), f"{case_id} function source"),
            function_name=function_name,
            function_return_type=return_type,
            caller_source=_project_source(caller.get("source"), f"{case_id} caller source"),
            caller_name=caller_name,
            runtime_args=_runtime_arguments(item.get("runtime_args"), case_id),
        ))
    if caller_types != CALLER_TYPES:
        raise SuiteError("validation", "suite must contain exactly indicator, screener, alert, and autotrade")
    return raw, cases, _canonical_digest(raw)


def run_json_tool(script: str, arguments: list[str], timeout: float) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).with_name(script)), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SuiteError(
            script,
            f"child returned {len(lines)} non-empty stdout lines",
            child={"returncode": completed.returncode, "stderr": completed.stderr.strip()},
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise SuiteError(script, "child did not return one JSON object") from exc
    if not isinstance(payload, dict):
        raise SuiteError(script, "child JSON must be an object")
    return completed.returncode, payload


def _require_success(stage: str, result: tuple[int, dict[str, Any]]) -> dict[str, Any]:
    code, payload = result
    if code == 0 and payload.get("status") == "success":
        return payload
    raise SuiteError(stage, f"child stage returned {payload.get('status', 'unknown')}", child=payload)


def _recovery(config: Path, runner: Runner) -> dict[str, Any]:
    payload = _require_success(
        "recovery_status",
        runner("xq_backtest.py", ["--config", str(config), "--recovery-status"], 60),
    )
    if payload.get("decision") != "safe_to_start":
        raise SuiteError("recovery_status", f"recovery decision is {payload.get('decision')}", child=payload)
    return payload


def _compile_arguments(config: Path, case: RuntimeCase) -> list[str]:
    return [
        "--config", str(config),
        "--source", str(case.function_source),
        "--script-type", "function",
        "--script-name", case.function_name,
        "--function-return-type", case.function_return_type,
        "--caller-source", str(case.caller_source),
        "--caller-type", case.caller_type,
        "--caller-name", case.caller_name,
    ]


def _runtime_command(config: Path, case: RuntimeCase) -> tuple[str, list[str]]:
    script = RUNTIME_SCRIPTS[case.caller_type]
    arguments: list[str] = []
    if case.caller_type != "alert" or script != "xq_alert.py":
        arguments.extend(["--config", str(config)])
    arguments.extend(["--script-name", case.caller_name, *case.runtime_args])
    if case.caller_type in {"screener", "alert"}:
        arguments.append("--confirm-historical-backtest")
    return script, arguments


def normalized_evidence(case: RuntimeCase, compile_payload: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    stages = compile_payload.get("stages") if isinstance(compile_payload.get("stages"), dict) else {}
    function_compile = stages.get("compile_main") if isinstance(stages.get("compile_main"), dict) else {}
    caller_compile = stages.get("compile_caller") if isinstance(stages.get("compile_caller"), dict) else {}
    return {
        "case_id": case.case_id,
        "caller_type": case.caller_type,
        "function_compile_status": function_compile.get("status"),
        "caller_compile_status": caller_compile.get("status"),
        "function_source_sha256": compile_payload.get("validated", {}).get("main", {}).get("source_sha256"),
        "caller_source_sha256": compile_payload.get("validated", {}).get("caller", {}).get("source_sha256"),
        "runtime_status": runtime.get("status"),
        "row_count": runtime.get("row_count"),
        "mismatch_count": (runtime.get("comparison") or {}).get("mismatch_count") if isinstance(runtime.get("comparison"), dict) else None,
        "success_count": runtime.get("success_count"),
        "failure_count": runtime.get("failure_count"),
        "total_trades": runtime.get("total_trades"),
        "report_cleanup_complete": runtime.get("report_cleanup_complete"),
        "recovery_checkpoint_retained": runtime.get("recovery_checkpoint_retained"),
    }


def execute_case(config: Path, case: RuntimeCase, runner: Runner = run_json_tool) -> dict[str, Any]:
    pre_recovery = _recovery(config, runner)
    compile_payload = _require_success(
        "compile_pair",
        runner("xq_existing_script_pipeline.py", _compile_arguments(config, case), 240),
    )
    _require_success(
        "open_runtime_caller",
        runner(
            "xq_open_existing_script.py",
            ["--config", str(config), "--script-type", case.caller_type, "--script-name", case.caller_name],
            60,
        ),
    )
    runtime_script, runtime_arguments = _runtime_command(config, case)
    runtime = _require_success("runtime", runner(runtime_script, runtime_arguments, 900))
    post_recovery = _recovery(config, runner)
    return {
        "status": "completed",
        "completed_at": utc_now(),
        "pre_recovery": pre_recovery,
        "compile": compile_payload,
        "runtime": runtime,
        "post_recovery": post_recovery,
        "normalized": normalized_evidence(case, compile_payload, runtime),
    }


def _private_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PRIVATE_ROOT)
    except ValueError as exc:
        raise SuiteError("validation", f"{label} must stay below {PRIVATE_ROOT}") from exc
    return resolved


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def _new_manifest(output: Path, digest: str, cases: list[RuntimeCase]) -> dict[str, Any]:
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "runner_contract_version": RUNNER_CONTRACT_VERSION,
        "suite_digest": digest,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "active_case": None,
        "cases": {case.case_id: {"status": "pending", "caller_type": case.caller_type} for case in cases},
        "output_directory": str(output),
    }


def _load_manifest(path: Path, digest: str, cases: list[RuntimeCase]) -> tuple[Path, dict[str, Any]]:
    manifest_path = _private_path(path, "resume manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuiteError("validation", f"Unable to read resume manifest: {exc}") from exc
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION or manifest.get("runner_contract_version") != RUNNER_CONTRACT_VERSION:
        raise SuiteError("validation", "resume manifest contract does not match")
    if manifest.get("suite_digest") != digest:
        raise SuiteError("validation", "resume manifest suite digest does not match")
    if set(manifest.get("cases", {})) != {case.case_id for case in cases}:
        raise SuiteError("validation", "resume manifest case set does not match")
    output = _private_path(Path(str(manifest.get("output_directory") or "")), "manifest output")
    if manifest_path != output / "manifest.json":
        raise SuiteError("validation", "resume manifest is not the declared output manifest")
    return output, manifest


def _archive_stale_failure(state: dict[str, Any]) -> None:
    if "error" not in state and "child" not in state:
        return
    attempt = {
        "status": "failed",
        "started_at": state.get("started_at"),
        "stage": (
            state.get("stage")
            if state.get("status") == "failed"
            else "prior_failure_unclassified"
        ),
        "error": state.get("error"),
        "child": state.get("child"),
    }
    attempts = state.setdefault("attempts", [])
    if not attempts or attempts[-1] != attempt:
        attempts.append(attempt)
    state.pop("error", None)
    state.pop("child", None)


def _write_summaries(output: Path, manifest: dict[str, Any], cases: list[RuntimeCase]) -> None:
    results = []
    suite = ElementTree.Element("testsuite", name="xq-runtime-evidence", tests=str(len(cases)))
    failures = 0
    skipped = 0
    rows = ["# XQ runtime evidence summary", "", "| Case | Caller | Status | Success | Failure | Trades | Rows | Cleanup |", "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for case in cases:
        state = manifest["cases"][case.case_id]
        normalized = state.get("result", {}).get("normalized", {}) if isinstance(state.get("result"), dict) else {}
        results.append({"case_id": case.case_id, "caller_type": case.caller_type, "status": state.get("status"), "normalized": normalized})
        test = ElementTree.SubElement(suite, "testcase", classname="xq.runtime", name=case.case_id)
        if state.get("status") == "failed":
            failures += 1
            failure = ElementTree.SubElement(test, "failure", message=str(state.get("error", "failed")))
            failure.text = str(state.get("stage", "unknown"))
        elif state.get("status") != "completed":
            skipped += 1
            ElementTree.SubElement(test, "skipped", message=str(state.get("status")))
        rows.append(
            f"| {case.case_id} | {case.caller_type} | {state.get('status')} | {normalized.get('success_count')} | {normalized.get('failure_count')} | {normalized.get('total_trades')} | {normalized.get('row_count')} | {normalized.get('report_cleanup_complete')} |"
        )
    suite.set("failures", str(failures))
    suite.set("errors", "0")
    suite.set("skipped", str(skipped))
    summary = {
        "summary_schema_version": SUMMARY_SCHEMA_VERSION,
        "schema_version": 1,
        "runner_contract_version": RUNNER_CONTRACT_VERSION,
        "suite_digest": manifest["suite_digest"],
        "generated_at": utc_now(),
        "completed": sum(item["status"] == "completed" for item in results),
        "failed": failures,
        "pending_or_skipped": skipped,
        "results": results,
        "contains_private_xq_evidence": True,
    }
    _atomic_json(output / "summary.json", summary)
    _atomic_text(output / "junit.xml", ElementTree.tostring(suite, encoding="unicode") + "\n")
    _atomic_text(output / "summary.md", "\n".join(rows) + "\n")


def run_suite(args: argparse.Namespace, runner: Runner = run_json_tool) -> dict[str, Any]:
    raw, cases, digest = load_cases(args.cases)
    selected = set(args.only_case)
    unknown = selected - {case.case_id for case in cases}
    if unknown:
        raise SuiteError("validation", f"unknown --only-case values: {sorted(unknown)}")
    cases = [case for case in cases if not selected or case.case_id in selected]
    if args.dry_run:
        return {
            "status": "success",
            "message": "Runtime evidence suite validated without XQ input",
            "dry_run": True,
            "xq_touched": False,
            "suite_digest": digest,
            "cases": [{"id": case.case_id, "caller_type": case.caller_type} for case in cases],
        }
    if any(case.caller_type in BACKTEST_TYPES for case in cases) and not args.confirm_historical_backtest:
        raise SuiteError("validation", "--confirm-historical-backtest is required before XQ input")
    if args.resume_manifest and args.output_directory:
        raise SuiteError("validation", "resume-manifest and output-directory are mutually exclusive")
    if args.resume_manifest:
        output, manifest = _load_manifest(args.resume_manifest, digest, load_cases(args.cases)[1])
    else:
        output = args.output_directory or (PRIVATE_ROOT / "runtime-evidence-results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
        output = _private_path(output, "output directory")
        if output.exists():
            raise SuiteError("validation", f"output directory already exists: {output}")
        output.mkdir(parents=True)
        all_cases = load_cases(args.cases)[1]
        manifest = _new_manifest(output, digest, all_cases)
        _atomic_json(output / "manifest.json", manifest)
    for existing_state in manifest["cases"].values():
        if existing_state.get("status") == "completed":
            _archive_stale_failure(existing_state)
    case_map = {case.case_id: case for case in load_cases(args.cases)[1]}
    for selected_case in cases:
        case = case_map[selected_case.case_id]
        state = manifest["cases"][case.case_id]
        if state.get("status") == "completed":
            continue
        if state.get("status") == "failed" and not args.retry_failed:
            raise SuiteError("resume", f"{case.case_id} is failed; explicit --retry-failed is required")
        if state.get("status") == "failed":
            _archive_stale_failure(state)
        state.pop("result", None)
        manifest["active_case"] = case.case_id
        state.update({"status": "running", "started_at": utc_now(), "stage": "starting"})
        manifest["updated_at"] = utc_now()
        _atomic_json(output / "manifest.json", manifest)
        try:
            result = execute_case(args.config, case, runner)
            state.update({"status": "completed", "result": result, "stage": "completed"})
        except SuiteError as exc:
            state.update({"status": "failed", "stage": exc.stage, "error": str(exc), "child": exc.child})
            manifest["active_case"] = None
            manifest["updated_at"] = utc_now()
            _atomic_json(output / "manifest.json", manifest)
            _write_summaries(output, manifest, list(case_map.values()))
            raise
        except Exception as exc:
            wrapped = SuiteError("unexpected_exception", f"{type(exc).__name__}: {exc}")
            state.update({"status": "failed", "stage": wrapped.stage, "error": str(wrapped), "child": None})
            manifest["active_case"] = None
            manifest["updated_at"] = utc_now()
            _atomic_json(output / "manifest.json", manifest)
            _write_summaries(output, manifest, list(case_map.values()))
            raise wrapped from exc
        manifest["active_case"] = None
        manifest["updated_at"] = utc_now()
        _atomic_json(output / "manifest.json", manifest)
        _write_summaries(output, manifest, list(case_map.values()))
    _write_summaries(output, manifest, list(case_map.values()))
    return {
        "status": "success",
        "message": "XQ runtime evidence suite completed",
        "dry_run": False,
        "suite_digest": digest,
        "completed_case_ids": [case_id for case_id, state in manifest["cases"].items() if state.get("status") == "completed"],
        "output_directory": str(output),
        "manifest": str(output / "manifest.json"),
        "summary_json": str(output / "summary.json"),
        "junit_xml": str(output / "junit.xml"),
        "summary_markdown": str(output / "summary.md"),
        "contains_private_xq_evidence": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run_suite(parse_args(argv))
        return emit(result.pop("status"), result.pop("message"), **result)
    except SuiteError as exc:
        return emit("automation_error", str(exc), failed_stage=exc.stage, child=exc.child)
    except Exception as exc:
        return emit("automation_error", f"Unexpected runtime suite failure: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
