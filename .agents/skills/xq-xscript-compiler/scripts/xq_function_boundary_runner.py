#!/usr/bin/env python3
"""Run manifest-scoped XQ function data-boundary cases safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from uuid import UUID, uuid4
from xml.etree import ElementTree


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import xq_backtest  # noqa: E402
import xq_category_selector  # noqa: E402
import xq_codex_scope  # noqa: E402
import xq_ui_pacing  # noqa: E402


CASE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
MARKER_RE = re.compile(r"^[A-Z][A-Z0-9_]{7,79}$")
SOURCE_FREQUENCIES = {"D", "W", "M"}
CALLER_FREQUENCIES = set(xq_backtest.FREQUENCIES)
EXPECTED_RESULTS = {"sentinel_failure", "no_execution_evidence"}
EXPECTED_PRELOAD_STATES = {"enabled", "disabled"}
MANIFEST_SCHEMA_VERSION = 5
CASE_SCHEMA_VERSION = 2
SUMMARY_SCHEMA_VERSION = 1
RUNNER_CONTRACT_VERSION = "7"
UI_ACTION_SETTLE_SECONDS = 2.0
DEFAULT_INTER_CASE_SECONDS = 5.0
DEFAULT_UI_POLL_INITIAL_SECONDS = 0.25
DEFAULT_UI_POLL_MAX_SECONDS = 1.0
DEFAULT_UI_POLL_BACKOFF = 1.5
DEFAULT_UI_DIALOG_LATE_AFTER_SECONDS = 4.0
DEFAULT_UI_DIALOG_TIMEOUT_SECONDS = 15.0
DEFAULT_UI_STATE_TIMEOUT_SECONDS = 15.0
WINDOWS_WAIT_ERROR_RE = re.compile(
    r"not responding|沒有回應|waitguithreadidle|window[^\n]{0,80}hung|"
    r"xscript_window_hung|dialog_late|dialog_timeout|window_disabled|"
    r"timed out waiting for xscript open dialog"
)


@dataclass(frozen=True)
class BoundaryCase:
    case_id: str
    pair_id: str
    role: str
    product: str
    start_date: str
    end_date: str
    caller_frequency: str
    source_frequency: str
    index: int
    caller_index: int
    default_value: int | float | None
    set_total_bar: int | None
    set_bar_back_count: int | None
    set_bar_back_frequency: str | None
    preload_records: int
    expected_sentinel: str
    expected_result: str
    expected_preload_state: str
    expect_default_value: bool
    access_mode: str


class RunnerError(RuntimeError):
    def __init__(self, message: str, *, status: str = "automation_error", evidence: Any = None):
        super().__init__(message)
        self.status = status
        self.evidence = evidence


class UiWaitIncident(RunnerError):
    """A UI wait boundary that forbids any further desktop input."""

    def __init__(self, kind: str, stage: str, *, evidence: Any = None):
        super().__init__(
            f"{kind} at {stage}",
            evidence={"incident_kind": kind, "stage": stage, "wait_evidence": evidence},
        )
        self.kind = kind
        self.stage = stage


@dataclass(frozen=True)
class UiWaitPolicy:
    action_settle_seconds: float = UI_ACTION_SETTLE_SECONDS
    poll_initial_seconds: float = DEFAULT_UI_POLL_INITIAL_SECONDS
    poll_max_seconds: float = DEFAULT_UI_POLL_MAX_SECONDS
    poll_backoff: float = DEFAULT_UI_POLL_BACKOFF
    dialog_late_after_seconds: float = DEFAULT_UI_DIALOG_LATE_AFTER_SECONDS
    dialog_timeout_seconds: float = DEFAULT_UI_DIALOG_TIMEOUT_SECONDS
    state_timeout_seconds: float = DEFAULT_UI_STATE_TIMEOUT_SECONDS
    inter_case_seconds: float = DEFAULT_INTER_CASE_SECONDS

    def validate(self) -> "UiWaitPolicy":
        values = asdict(self)
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not float(value) > 0
            for value in values.values()
        ):
            raise ValueError("All UI wait values must be positive numbers")
        if self.poll_initial_seconds > self.poll_max_seconds:
            raise ValueError("UI initial poll interval cannot exceed the maximum poll interval")
        if self.poll_backoff < 1:
            raise ValueError("UI poll backoff must be at least 1")
        if self.dialog_late_after_seconds > self.dialog_timeout_seconds:
            raise ValueError("UI dialog late threshold cannot exceed its timeout")
        return self


ACTIVE_UI_WAIT_POLICY = UiWaitPolicy()


def set_ui_wait_policy(policy: UiWaitPolicy) -> None:
    global ACTIVE_UI_WAIT_POLICY
    ACTIVE_UI_WAIT_POLICY = policy.validate()


def adaptive_wait_for(
    probe: Callable[[], Any],
    *,
    timeout_seconds: float,
    late_after_seconds: float | None = None,
    policy: UiWaitPolicy | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Poll without UI input, backing off and reporting normal/late/timeout."""
    policy = (policy or ACTIVE_UI_WAIT_POLICY).validate()
    started = clock()
    deadline = started + timeout_seconds
    interval = policy.poll_initial_seconds
    attempts = 0
    while True:
        attempts += 1
        value = probe()
        elapsed = max(0.0, clock() - started)
        if value:
            return {
                "status": (
                    "late"
                    if late_after_seconds is not None and elapsed > late_after_seconds
                    else "ready"
                ),
                "value": value,
                "elapsed_seconds": elapsed,
                "attempts": attempts,
            }
        remaining = deadline - clock()
        if remaining <= 0:
            return {
                "status": "timeout",
                "value": None,
                "elapsed_seconds": max(0.0, clock() - started),
                "attempts": attempts,
            }
        sleeper(min(interval, remaining))
        interval = min(policy.poll_max_seconds, interval * policy.poll_backoff)


def ui_action_pause() -> None:
    time.sleep(ACTIVE_UI_WAIT_POLICY.action_settle_seconds)


def wait_for_window_enabled(window: Any, stage: str) -> dict[str, Any]:
    import ctypes

    def probe() -> Any:
        handle = int(window.handle)
        if ctypes.windll.user32.IsHungAppWindow(handle):
            raise UiWaitIncident("window_hung", stage, evidence={"window_handle": handle})
        try:
            return window if window.is_visible() and window.is_enabled() else None
        except UiWaitIncident:
            raise
        except Exception as exc:
            if "WaitGuiThreadIdle" in str(exc):
                raise UiWaitIncident(
                    "WaitGuiThreadIdle", stage, evidence={"window_handle": handle},
                ) from exc
            raise

    outcome = adaptive_wait_for(
        probe,
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
        late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
    )
    if outcome["status"] == "late":
        raise UiWaitIncident("window_disabled_late", stage, evidence=outcome)
    if outcome["status"] == "timeout":
        raise UiWaitIncident("window_disabled_timeout", stage, evidence=outcome)
    return outcome


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def desktop_windows(backend: str, attempts: int = 5) -> list[Any]:
    from pywinauto import Desktop

    error = None
    for _ in range(attempts):
        try:
            return list(Desktop(backend=backend).windows())
        except Exception as exc:
            error = exc
            time.sleep(ACTIVE_UI_WAIT_POLICY.poll_initial_seconds)
    raise RuntimeError(f"Could not enumerate {backend} desktop windows: {error}")


def run_json_tool(script_name: str, arguments: Sequence[str], timeout: float) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script_name), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RunnerError(f"{script_name} did not emit one JSON object: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise RunnerError(f"{script_name} returned an invalid result object")
    return {
        "script": script_name,
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": completed.stderr.strip(),
    }


def require_tool_success(result: dict[str, Any], stage: str) -> dict[str, Any]:
    payload = result["payload"]
    if result["returncode"] != 0 or payload.get("status") != "success":
        status = "compile_error" if payload.get("status") == "compile_error" else "automation_error"
        raise RunnerError(f"Stage failed: {stage}", status=status, evidence=payload)
    return payload


def record_windows_wait_incident(
    config_path: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    error: BaseException,
    evidence: Any = None,
) -> dict[str, Any] | None:
    combined = f"{type(error).__name__}: {error} {evidence!r}"
    if not isinstance(error, UiWaitIncident) and WINDOWS_WAIT_ERROR_RE.search(combined.lower()) is None:
        return None
    incident: dict[str, Any] = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "error_type": type(error).__name__,
        "error": str(error),
        "incident_kind": getattr(error, "kind", None),
        "active_case_id": manifest.get("active_case_id"),
        "active_case_stage": None,
        "active_document_id": manifest.get("active_cleanup_document_id"),
        "active_document": None,
        "cleanup_stage": None,
        "xq_process_id": None,
        "window_health": None,
        "checkpoint": None,
        "visible_reports": [],
        "recovery_status": None,
    }
    active_case_id = manifest.get("active_case_id")
    if isinstance(active_case_id, str):
        state = manifest.get("case_states", {}).get(active_case_id)
        if isinstance(state, dict):
            incident["active_case_stage"] = state.get("stage")
    active_document_id = manifest.get("active_cleanup_document_id")
    if isinstance(active_document_id, str):
        cleanup_state = manifest.get("cleanup_states", {}).get(active_document_id)
        if isinstance(cleanup_state, dict):
            incident["cleanup_stage"] = cleanup_state.get("stage")
            incident["active_document"] = {
                "name": cleanup_state.get("name"),
                "script_type": cleanup_state.get("script_type"),
            }
    try:
        recovery = run_json_tool(
            "xq_backtest.py",
            ["--config", str(config_path), "--recovery-status"],
            30,
        )["payload"]
        incident["recovery_status"] = recovery
        runtime = recovery.get("runtime")
        if isinstance(runtime, dict):
            incident["xq_process_id"] = runtime.get("xq_process_id")
            incident["window_health"] = {
                key: runtime.get(key)
                for key in (
                    "xq_process_exists", "xq_window_exists", "xq_window_visible",
                    "xq_window_enabled", "xq_window_hung", "xscript_window_exists",
                    "xscript_window_visible", "xscript_window_enabled",
                    "xscript_window_hung",
                )
            }
        incident["checkpoint"] = recovery.get("checkpoint")
        incident["visible_reports"] = recovery.get("visible_reports", [])
    except Exception as capture_error:
        incident["recovery_capture_error"] = (
            f"{type(capture_error).__name__}: {capture_error}"
        )
    manifest.setdefault("windows_wait_incidents", []).append(incident)
    atomic_write_json(manifest_path, manifest)
    return incident


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ValueError(f"{label} must be {'a non-negative' if allow_zero else 'a positive'} integer")
    return value


def _optional_positive_int(value: Any, label: str) -> int | None:
    return None if value is None else _positive_int(value, label)


def parse_shortage_case(raw: Any, schema_version: int = CASE_SCHEMA_VERSION) -> tuple[BoundaryCase, BoundaryCase]:
    if not isinstance(raw, dict):
        raise ValueError("Each boundary case must be an object")
    if schema_version == 1:
        raw = {
            **raw,
            "caller_index": 0,
            "control_caller_index": 0,
            "expected_preload_state": "disabled" if raw.get("set_total_bar") is not None else "enabled",
        }
    required = {
        "id", "product", "start_date", "end_date", "caller_frequency",
        "source_frequency", "index", "control_index",
        "caller_index", "control_caller_index", "default",
        "set_total_bar", "set_bar_back", "preload_records",
        "expected_sentinel", "control_sentinel", "expected_result",
        "expected_preload_state",
    }
    optional = {"access_mode", "expect_default_value"}
    if set(raw) - required - optional or required - set(raw):
        raise ValueError(f"Boundary case fields do not match schema: {raw.get('id', '<unknown>')}")
    case_id = str(raw["id"])
    if not CASE_ID_RE.fullmatch(case_id):
        raise ValueError(f"Invalid boundary case id: {case_id}")
    product = str(raw["product"])
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,20}", product):
        raise ValueError(f"Invalid public product code in {case_id}")
    caller_frequency = str(raw["caller_frequency"])
    source_frequency = str(raw["source_frequency"]).upper()
    if caller_frequency not in CALLER_FREQUENCIES:
        raise ValueError(f"Unsupported caller frequency in {case_id}")
    if source_frequency not in SOURCE_FREQUENCIES:
        raise ValueError(f"Unsupported source frequency in {case_id}")
    start_date = date.fromisoformat(str(raw["start_date"]))
    end_date = date.fromisoformat(str(raw["end_date"]))
    if start_date > end_date:
        raise ValueError(f"{case_id} start_date must not be later than end_date")
    index = _positive_int(raw["index"], f"{case_id}.index")
    control_index = _positive_int(raw["control_index"], f"{case_id}.control_index")
    caller_index = _positive_int(raw["caller_index"], f"{case_id}.caller_index", allow_zero=True)
    control_caller_index = _positive_int(
        raw["control_caller_index"], f"{case_id}.control_caller_index", allow_zero=True,
    )
    if control_index > index or control_caller_index > caller_index:
        raise ValueError(f"{case_id} control indices must not exceed shortage indices")
    if control_index == index and control_caller_index == caller_index:
        raise ValueError(f"{case_id} control must shorten the source index or caller index")
    default_value = raw["default"]
    if default_value is not None and (isinstance(default_value, bool) or not isinstance(default_value, (int, float))):
        raise ValueError(f"{case_id}.default must be null or numeric")
    set_total_bar = _optional_positive_int(raw["set_total_bar"], f"{case_id}.set_total_bar")
    set_bar_back = raw["set_bar_back"]
    if set_bar_back is None:
        set_bar_back_count = None
        set_bar_back_frequency = None
    elif isinstance(set_bar_back, dict) and set(set_bar_back) == {"count", "frequency"}:
        set_bar_back_count = _positive_int(set_bar_back["count"], f"{case_id}.set_bar_back.count")
        set_bar_back_frequency = str(set_bar_back["frequency"]).upper()
        if set_bar_back_frequency not in SOURCE_FREQUENCIES:
            raise ValueError(f"Unsupported SetBarBack frequency in {case_id}")
    else:
        raise ValueError(f"{case_id}.set_bar_back must be null or count/frequency object")
    preload_records = _positive_int(raw["preload_records"], f"{case_id}.preload_records", allow_zero=True)
    shortage_marker = str(raw["expected_sentinel"])
    control_marker = str(raw["control_sentinel"])
    if not MARKER_RE.fullmatch(shortage_marker) or not MARKER_RE.fullmatch(control_marker):
        raise ValueError(f"{case_id} markers must be 8-80 uppercase ASCII characters")
    if shortage_marker == control_marker:
        raise ValueError(f"{case_id} shortage and control markers must be unique")
    expected_result = str(raw["expected_result"])
    if expected_result not in EXPECTED_RESULTS:
        raise ValueError(f"Unsupported expected_result in {case_id}")
    expected_preload_state = str(raw["expected_preload_state"])
    if expected_preload_state not in EXPECTED_PRELOAD_STATES:
        raise ValueError(f"Unsupported expected_preload_state in {case_id}")
    expect_default_value = raw.get("expect_default_value", True)
    if not isinstance(expect_default_value, bool):
        raise ValueError(f"{case_id}.expect_default_value must be boolean")
    access_mode = str(raw.get("access_mode", "dynamic"))
    if access_mode not in {"dynamic", "fixed"}:
        raise ValueError(f"Unsupported access_mode in {case_id}")

    common = dict(
        pair_id=case_id,
        product=product,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        caller_frequency=caller_frequency,
        source_frequency=source_frequency,
        default_value=default_value,
        set_total_bar=set_total_bar,
        set_bar_back_count=set_bar_back_count,
        set_bar_back_frequency=set_bar_back_frequency,
        preload_records=preload_records,
        expected_preload_state=expected_preload_state,
        expect_default_value=expect_default_value,
        access_mode=access_mode,
    )
    control = BoundaryCase(
        case_id=f"{case_id}-control", role="control", index=control_index,
        caller_index=control_caller_index,
        expected_sentinel=control_marker, expected_result="sentinel_failure", **common,
    )
    shortage = BoundaryCase(
        case_id=f"{case_id}-shortage", role="shortage", index=index,
        caller_index=caller_index,
        expected_sentinel=shortage_marker, expected_result=expected_result, **common,
    )
    return control, shortage


def load_case_file(path: Path) -> tuple[dict[str, Any], list[BoundaryCase]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "suite_id", "cases"}:
        raise ValueError("Boundary case file fields do not match schema")
    if payload["schema_version"] not in {1, CASE_SCHEMA_VERSION}:
        raise ValueError("Unsupported boundary case schema version")
    if not CASE_ID_RE.fullmatch(str(payload["suite_id"])):
        raise ValueError("Invalid suite_id")
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        raise ValueError("Boundary case file must contain at least one shortage case")
    expanded: list[BoundaryCase] = []
    pair_ids: set[str] = set()
    markers: set[str] = set()
    for raw in payload["cases"]:
        control, shortage = parse_shortage_case(raw, int(payload["schema_version"]))
        if shortage.pair_id in pair_ids:
            raise ValueError(f"Duplicate case id: {shortage.pair_id}")
        pair_ids.add(shortage.pair_id)
        for item in (control, shortage):
            if item.expected_sentinel in markers:
                raise ValueError(f"Duplicate expected sentinel: {item.expected_sentinel}")
            markers.add(item.expected_sentinel)
            expanded.append(item)
    return payload, expanded


def select_case_pairs(
    cases: Sequence[BoundaryCase],
    requested_pair_ids: Sequence[str] | None,
) -> tuple[list[BoundaryCase], list[str]]:
    available = list(dict.fromkeys(case.pair_id for case in cases))
    if not requested_pair_ids:
        return list(cases), available
    requested = list(dict.fromkeys(requested_pair_ids))
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown boundary pair id(s): {', '.join(unknown)}")
    selected = [case for case in cases if case.pair_id in set(requested)]
    for pair_id in requested:
        roles = {case.role for case in selected if case.pair_id == pair_id}
        if roles != {"control", "shortage"}:
            raise ValueError(f"Selected pair is incomplete: {pair_id}")
    return selected, requested


def case_file_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def initialize_case_states(cases: Sequence[BoundaryCase]) -> dict[str, dict[str, Any]]:
    return {
        case.case_id: {
            "ordinal": ordinal,
            "status": "pending",
            "stage": "pending",
            "attempts": 0,
            "case": asdict(case),
            "compile": {},
            "result": None,
            "late_recovery": None,
        }
        for ordinal, case in enumerate(cases, start=1)
    }


def pending_cases(cases: Sequence[BoundaryCase], manifest: dict[str, Any]) -> list[BoundaryCase]:
    states = manifest["case_states"]
    return [case for case in cases if states[case.case_id]["status"] == "pending"]


def progress_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    states = manifest["case_states"]
    case_rows = []
    completed = failed = pending = 0
    for case_id, state in sorted(states.items(), key=lambda item: item[1]["ordinal"]):
        status = state["status"]
        if status == "completed":
            completed += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1
        case_rows.append({
            "case_id": case_id,
            "ordinal": state["ordinal"],
            "status": status,
            "stage": state["stage"],
            "attempts": state["attempts"],
            "case": state["case"],
            "compile": state["compile"],
            "result": state["result"],
            "late_recovery": state["late_recovery"],
        })
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "run_id": manifest["run_id"],
        "case_digest": manifest["case_digest"],
        "runner_contract_version": manifest["runner_contract_version"],
        "selected_pair_ids": manifest["selected_pair_ids"],
        "counts": {
            "total": len(states),
            "completed": completed,
            "failed": failed,
            "pending": pending,
        },
        "active_case_id": manifest.get("active_case_id"),
        "active_cleanup_document_id": manifest.get("active_cleanup_document_id"),
        "cleanup_states": manifest.get("cleanup_states", {}),
        "pacing": manifest.get("pacing"),
        "windows_wait_incidents": manifest.get("windows_wait_incidents", []),
        "cases": case_rows,
        "last_error": manifest.get("last_error"),
    }


def junit_summary(manifest: dict[str, Any]) -> str:
    states = manifest["case_states"]
    failures = sum(1 for state in states.values() if state["status"] == "failed")
    skipped = sum(1 for state in states.values() if state["status"] not in {"completed", "failed"})
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": manifest["suite_id"],
            "tests": str(len(states)),
            "failures": str(failures),
            "errors": "0",
            "skipped": str(skipped),
        },
    )
    properties = ElementTree.SubElement(suite, "properties")
    ElementTree.SubElement(properties, "property", {"name": "run_id", "value": manifest["run_id"]})
    ElementTree.SubElement(properties, "property", {"name": "case_digest", "value": manifest["case_digest"]})
    for case_id, state in sorted(states.items(), key=lambda item: item[1]["ordinal"]):
        testcase = ElementTree.SubElement(
            suite,
            "testcase",
            {"classname": manifest["suite_id"], "name": case_id},
        )
        if state["status"] == "failed":
            failure = ElementTree.SubElement(testcase, "failure", {"message": "case failed"})
            failure.text = json.dumps(state.get("result"), ensure_ascii=False, sort_keys=True)
        elif state["status"] != "completed":
            ElementTree.SubElement(testcase, "skipped", {"message": state["status"]})
        if state.get("result") is not None:
            output = ElementTree.SubElement(testcase, "system-out")
            output.text = json.dumps(
                {
                    "classification": state["result"].get("result", {}).get("classification"),
                    "success_count": state["result"].get("result", {}).get("success_count"),
                    "failure_count": state["result"].get("result", {}).get("failure_count"),
                    "total_trades": state["result"].get("result", {}).get("total_trades"),
                    "actual_error_code": state["result"].get("result", {}).get("actual_error_code"),
                    "actual_marker": state["result"].get("result", {}).get("actual_marker"),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True)


def write_progress_outputs(manifest: dict[str, Any]) -> None:
    atomic_write_json(Path(manifest["output_json"]), progress_summary(manifest))
    atomic_write_text(Path(manifest["output_junit"]), junit_summary(manifest))


def validate_output_directory(config_path: Path, requested: Path | None) -> Path:
    private_root = config_path.resolve().parent
    output = (
        requested.resolve()
        if requested is not None
        else (private_root / "function-boundary-results").resolve()
    )
    if output == private_root or private_root not in output.parents:
        raise ValueError("Output directory must be below the private XQ configuration directory")
    output.mkdir(parents=True, exist_ok=True)
    return output


def validate_resume_manifest(
    manifest_path: Path,
    base: Path,
    suite: dict[str, Any],
    cases: Sequence[BoundaryCase],
) -> dict[str, Any]:
    resolved = manifest_path.resolve()
    base = base.resolve()
    if base not in resolved.parents or resolved.name != "manifest.json":
        raise ValueError("Resume manifest must be a manifest.json below function-boundary-runs")
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    required = {
        "schema_version", "run_id", "suite_id", "case_file", "case_digest",
        "documents", "report_handles", "temp_paths", "completed_case_ids",
        "case_states", "active_case_id", "output_json", "output_junit",
        "late_recovery_probe", "runner_contract_version", "selected_pair_ids",
        "cleanup_states", "active_cleanup_document_id", "pacing",
    }
    optional = {"last_error", "windows_wait_incidents"}
    if not isinstance(manifest, dict) or set(manifest) - required - optional or required - set(manifest):
        raise ValueError("Resume manifest fields do not match schema")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported resume manifest schema")
    if manifest["runner_contract_version"] != RUNNER_CONTRACT_VERSION:
        raise ValueError("Resume manifest runner contract version mismatch")
    try:
        UiWaitPolicy(**manifest["pacing"]).validate()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Resume manifest pacing contract is invalid: {exc}") from exc
    expected_pairs = list(dict.fromkeys(case.pair_id for case in cases))
    if manifest["selected_pair_ids"] != expected_pairs:
        raise ValueError("Resume manifest selected pair set does not match the supplied selection")
    if manifest["suite_id"] != suite["suite_id"] or manifest["case_digest"] != case_file_digest(suite):
        raise ValueError("Resume manifest does not match the supplied case suite")
    expected_states = initialize_case_states(cases)
    if set(manifest["case_states"]) != set(expected_states):
        raise ValueError("Resume manifest case set does not match the supplied suite")
    for case_id, expected in expected_states.items():
        state = manifest["case_states"][case_id]
        if not isinstance(state, dict) or state.get("case") != expected["case"]:
            raise ValueError(f"Resume manifest case contract mismatch: {case_id}")
        if state.get("status") not in {"pending", "running", "completed", "failed"}:
            raise ValueError(f"Invalid resume case status: {case_id}")
    completed = sorted(
        case_id for case_id, state in manifest["case_states"].items()
        if state["status"] == "completed"
    )
    if sorted(manifest["completed_case_ids"]) != completed:
        raise ValueError("Resume manifest completed-case index is inconsistent")
    active = manifest["active_case_id"]
    if active is not None and active not in manifest["case_states"]:
        raise ValueError("Resume manifest active_case_id is invalid")
    running = [
        case_id for case_id, state in manifest["case_states"].items()
        if state["status"] == "running"
    ]
    if running != ([] if active is None else [active]):
        raise ValueError("Resume manifest running-case state is inconsistent")
    expected_cleanup_ids = {
        cleanup_document_id(record) for record in manifest["documents"]
    }
    if set(manifest["cleanup_states"]) != expected_cleanup_ids:
        raise ValueError("Resume manifest cleanup state set is inconsistent")
    for document_id, cleanup_state in manifest["cleanup_states"].items():
        if (
            not isinstance(cleanup_state, dict)
            or cleanup_state.get("document_id") != document_id
            or cleanup_state.get("status") not in {"pending", "in_progress", "refused", "completed"}
            or cleanup_state.get("stage") not in {
                "pending", "open_requested", "identity_readback_verified",
                "delete_confirmation_verified", "absence_verified", "completed",
            }
        ):
            raise ValueError(f"Resume manifest cleanup state is invalid: {document_id}")
    active_cleanup = manifest["active_cleanup_document_id"]
    if active_cleanup is not None and active_cleanup not in manifest["cleanup_states"]:
        raise ValueError("Resume manifest active cleanup document is invalid")
    probe = manifest["late_recovery_probe"]
    if (
        not isinstance(probe, dict)
        or set(probe) != {"case_id", "required", "observed"}
        or not isinstance(probe["required"], bool)
        or not isinstance(probe["observed"], bool)
        or (probe["case_id"] is not None and probe["case_id"] not in manifest["case_states"])
    ):
        raise ValueError("Resume manifest late-recovery probe is invalid")
    private_root = base.parent.resolve()
    for key in ("output_json", "output_junit"):
        output = Path(manifest[key]).resolve()
        if private_root not in output.parents:
            raise ValueError("Resume output path is outside the private XQ directory")
    return manifest


def xscript_number(value: int | float) -> str:
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return format(float(value), ".15g")


def render_sources(case: BoundaryCase, function_name: str) -> tuple[str, str]:
    if case.access_mode == "dynamic":
        function_source = (
            "{@type:function}\nSetBarMode(1);\n\n"
            "input:\n    SourceSeries(NumericSeries),\n    LookbackBars(NumericSimple);\n\n"
            "retval = SourceSeries[LookbackBars];\n"
        )
        field = f'GetField("Close", "{case.source_frequency}"'
        if case.default_value is not None:
            field += f", Default := {xscript_number(case.default_value)}"
        field += ")"
        expression = f"{function_name}({field}, {case.index})"
    else:
        field = f'GetField("Close", "{case.source_frequency}"'
        if case.default_value is not None:
            field += f", Default := {xscript_number(case.default_value)}"
        field += ")"
        function_source = (
            "{@type:function}\nSetBarMode(1);\n\n"
            f"retval = {field}[{case.index}];\n"
        )
        expression = f"{function_name}()"

    directives = ["{@type:autotrade}", ""]
    if case.set_total_bar is not None:
        directives.append(f"SetTotalBar({case.set_total_bar});")
    if case.set_bar_back_count is not None and case.set_bar_back_frequency is not None:
        directives.append(f'SetBarBack({case.set_bar_back_count}, "{case.set_bar_back_frequency}");')
    directives.extend([
        "",
        "variables: BoundaryValue(0), BoundaryObserved(0);",
        "",
        f"BoundaryValue = {expression};",
        (
            f"BoundaryObserved = BoundaryValue[{case.caller_index}];"
            if case.caller_index > 0
            else "BoundaryObserved = BoundaryValue;"
        ),
        "",
    ])
    if case.default_value is None or case.role == "control":
        directives.append(f'RaiseRunTimeError("{case.expected_sentinel}");')
    else:
        alternate_suffix = "OTHER" if case.expect_default_value else "DEFAULT"
        alternate = f"{case.expected_sentinel}_{alternate_suffix}"
        if len(alternate) > 80:
            alternate = f"{alternate_suffix}_{case.expected_sentinel[:72]}"
        directives.extend([
            f"if BoundaryObserved = {xscript_number(case.default_value)} then",
            (
                f'    RaiseRunTimeError("{case.expected_sentinel}")'
                if case.expect_default_value
                else f'    RaiseRunTimeError("{alternate}")'
            ),
            "else",
            (
                f'    RaiseRunTimeError("{alternate}");'
                if case.expect_default_value
                else f'    RaiseRunTimeError("{case.expected_sentinel}");'
            ),
        ])
    return function_source, "\n".join(directives) + "\n"


def document_names(run_id: str, ordinal: int, attempt: int = 1) -> tuple[str, str]:
    token = run_id.replace("-", "")[:8]
    suffix = "" if attempt == 1 else f"A{attempt}"
    return f"CodexB5{token}{ordinal}{suffix}Fn", f"CodexB5{token}{ordinal}{suffix}Caller"


def manifest_document(
    manifest: dict[str, Any], name: str, script_type: str, case_id: str,
) -> dict[str, Any]:
    record = {
        "case_id": case_id,
        "name": name,
        "script_type": script_type,
        "function_return_type": "number" if script_type == "function" else None,
        "creation_attempted": True,
        "created": False,
        "type_readback": None,
        "storage_location": xq_codex_scope.EXPECTED_SCRIPT_LOCATION,
        "deleted": False,
    }
    manifest["documents"].append(record)
    if "cleanup_states" in manifest:
        manifest["cleanup_states"] = initialize_cleanup_states(
            manifest["documents"], manifest["cleanup_states"],
        )
    return record


def compile_document(
    config: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    name: str,
    script_type: str,
    source: Path,
    case_id: str,
) -> dict[str, Any]:
    record = manifest_document(manifest, name, script_type, case_id)
    atomic_write_json(manifest_path, manifest)
    prepare_args = [
        "--config", str(config), "--script-type", script_type, "--name", name,
        "--folder", xq_codex_scope.CODEX_FOLDER_NAME,
    ]
    compile_args = [
        "--config", str(config), "--source", str(source),
        "--script-type", script_type, "--script-name", name,
    ]
    if script_type == "function":
        prepare_args.extend(["--function-return-type", "number"])
        compile_args.extend(["--function-return-type", "number"])
    try:
        require_tool_success(
            run_json_tool("xq_prepare_script.py", [*prepare_args, "--dry-run"], 45),
            f"preflight_{name}",
        )
        prepared = require_tool_success(
            run_json_tool("xq_prepare_script.py", prepare_args, 45), f"prepare_{name}",
        )
    except RunnerError as exc:
        record["prepare_error"] = exc.evidence
        message = exc.evidence.get("message", "") if isinstance(exc.evidence, dict) else ""
        record["creation_disproven"] = "did not select" in str(message)
        atomic_write_json(manifest_path, manifest)
        raise
    record["created"] = True
    record["type_readback"] = prepared.get("script_type")
    atomic_write_json(manifest_path, manifest)
    compiled = require_tool_success(run_json_tool("xq_compile.py", compile_args, 60), f"compile_{name}")
    return {
        "name": name,
        "script_type": script_type,
        "compiler_message": compiled.get("message"),
        "compiler_output": compiled.get("compiler_output"),
    }


def backtest_arguments(config: Path, case: BoundaryCase, timeout_seconds: float) -> list[str]:
    return [
        "--config", str(config), "--product", case.product,
        "--frequency", case.caller_frequency,
        "--start-date", case.start_date, "--end-date", case.end_date,
        "--preload-records", str(case.preload_records), "--initial-capital-wan", "100",
        "--max-position", "1", "--max-entries-per-day", "1",
        "--max-trades-per-minute", "1", "--price-basis", "original",
        "--buy-price", "trigger", "--sell-price", "trigger",
        "--buy-offset", "0", "--sell-offset", "0",
        "--stock-fee-percent", "0.2", "--futures-fee", "100",
        "--simulate-ticks", "--no-daily-position-reset", "--fill-on-trigger",
        "--no-enable-print", "--no-us-all-sessions", "--no-direct-order",
        "--timeout-seconds", str(timeout_seconds),
    ]


def actual_marker_and_code(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    details = payload.get("failure_details")
    if not isinstance(details, list):
        return None, None
    first_error_code = None
    for item in details:
        if not isinstance(item, dict):
            continue
        code = item.get("error_code")
        if first_error_code is None and code not in (None, ""):
            first_error_code = str(code)
        description = str(item.get("description", ""))
        marker = None
        for candidate in re.findall(r"[A-Z][A-Z0-9_]{7,79}", description):
            if candidate.startswith("CODEX_"):
                marker = candidate
                break
        if marker is not None:
            return marker, str(code) if code not in (None, "") else None
    return None, first_error_code


def evaluate_case_result(case: BoundaryCase, payload: dict[str, Any]) -> dict[str, Any]:
    marker, error_code = actual_marker_and_code(payload)
    success_count = payload.get("success_count")
    failure_count = payload.get("failure_count")
    total_trades = payload.get("total_trades")
    marker_matches = marker == case.expected_sentinel
    settings = payload.get("settings_evidence") if isinstance(payload.get("settings_evidence"), dict) else {}
    preload_control_enabled = settings.get("preload_control_enabled")
    expected_preload_enabled = case.expected_preload_state == "enabled"
    preload_state_matches = preload_control_enabled is expected_preload_enabled
    if case.expected_result == "sentinel_failure":
        passed = (
            payload.get("status") == "failure"
            and success_count == 0 and isinstance(failure_count, int) and failure_count >= 1
            and marker_matches
            and preload_state_matches
        )
        observed = "sentinel_failure" if passed else "unexpected_result"
    else:
        passed = (
            payload.get("status") == "success"
            and isinstance(success_count, int) and success_count >= 1
            and failure_count == 0 and total_trades == 0 and marker is None
            and preload_state_matches
        )
        observed = "no_execution_evidence" if passed else "unexpected_result"
    return {
        "passed": passed,
        "classification": payload.get("status"),
        "expected_result": case.expected_result,
        "observed_result": observed,
        "success_count": success_count,
        "failure_count": failure_count,
        "total_trades": total_trades,
        "actual_error_code": error_code,
        "actual_marker": marker,
        "expected_marker": case.expected_sentinel,
        "marker_matches": marker_matches,
        "execution_evidence": {
            "formal_execution_proven": marker is not None,
            "path_sentinel_observed": marker is not None,
            "no_execution_evidence": observed == "no_execution_evidence",
        },
        "settings_applied": {
            "preload_control_enabled": preload_control_enabled,
            "expected_preload_state": case.expected_preload_state,
            "preload_state_matches": preload_state_matches,
            "preload_records_requested": settings.get("preload_records_requested"),
            "preload_records_applied": settings.get("preload_records_applied"),
        },
        "report_window_handle": payload.get("report_window_handle", payload.get("window_handle")),
    }


def merge_late_report_evidence(
    late_report: dict[str, Any],
    backtest_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep report facts and add only settings that XQ already read back before start."""
    merged = dict(late_report)
    if isinstance(backtest_evidence, dict):
        settings = backtest_evidence.get("settings_evidence")
        if isinstance(settings, dict):
            merged["settings_evidence"] = settings
    handle = merged.get("window_handle")
    if isinstance(handle, int) and handle > 0:
        merged["report_window_handle"] = handle
    return merged


def backtest_requires_reconciliation(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "indeterminate_timeout"
        or payload.get("recovery_checkpoint_retained") is True
    )


def evaluate_late_report_recovery(
    checkpoint: xq_backtest.RecoveryCheckpoint,
    reports: Sequence[dict[str, Any]],
    expected_marker: str,
) -> dict[str, Any]:
    return evaluate_late_report_baseline(checkpoint.baseline_report_handles, reports, expected_marker)


def evaluate_late_report_baseline(
    baseline_report_handles: Iterable[int],
    reports: Sequence[dict[str, Any]],
    expected_marker: str,
) -> dict[str, Any]:
    baseline = set(baseline_report_handles)
    candidates = [item for item in reports if item.get("window_handle") not in baseline]
    if len(candidates) != 1:
        return {
            "decision": "manual_review_required",
            "reason": "new_report_not_unique",
            "new_report_count": len(candidates),
            "checkpoint_may_be_cleared": False,
        }
    candidate = candidates[0]
    marker, error_code = actual_marker_and_code(candidate)
    if marker != expected_marker:
        return {
            "decision": "manual_review_required",
            "reason": "marker_mismatch",
            "new_report_count": 1,
            "report_window_handle": candidate.get("window_handle"),
            "expected_marker": expected_marker,
            "actual_marker": marker,
            "actual_error_code": error_code,
            "checkpoint_may_be_cleared": False,
        }
    return {
        "decision": "recovered",
        "reason": "unique_new_report_and_marker_match",
        "new_report_count": 1,
        "report_window_handle": candidate.get("window_handle"),
        "actual_marker": marker,
        "actual_error_code": error_code,
        "checkpoint_may_be_cleared": True,
        "report": candidate,
    }


def capture_visible_reports_with_details() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for window in xq_backtest.visible_report_windows():
        elements = xq_backtest.report_elements(window)
        summary = xq_backtest.report_summary(elements or [])
        if summary is None:
            continue
        record: dict[str, Any] = {
            "window_handle": int(window.handle),
            "status": xq_backtest.classify_report(summary),
            "success_count": summary.success_count,
            "failure_count": summary.failure_count,
            "total_trades": summary.total_trades,
            "failure_details": [],
        }
        if summary.failure_count > 0:
            try:
                record["failure_details"] = [
                    asdict(item) for item in xq_backtest.extract_failure_details(window, summary.failure_count)
                ]
            except Exception as exc:
                record["failure_detail_capture_error"] = f"{type(exc).__name__}: {exc}"
        results.append(record)
    return results


def reconcile_timeout(
    config: Path,
    expected_marker: str,
    wait_seconds: float,
    report_probe: Callable[[], list[dict[str, Any]]] = capture_visible_reports_with_details,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    checkpoint_path = xq_backtest.recovery_path(config)
    checkpoint = xq_backtest.load_checkpoint(checkpoint_path)
    if checkpoint is None:
        return ({"decision": "manual_review_required", "reason": "checkpoint_missing"}, None)
    deadline = time.monotonic() + wait_seconds
    assessment: dict[str, Any] = {"decision": "manual_review_required", "reason": "no_late_report"}
    while True:
        reports = report_probe()
        assessment = evaluate_late_report_recovery(checkpoint, reports, expected_marker)
        if assessment["decision"] == "recovered" or len([
            item for item in reports if item.get("window_handle") not in set(checkpoint.baseline_report_handles)
        ]) > 1:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(ACTIVE_UI_WAIT_POLICY.poll_initial_seconds)
    if assessment.get("checkpoint_may_be_cleared") is True:
        xq_backtest.remove_checkpoint(checkpoint_path)
        return assessment, assessment.get("report")
    return assessment, None


def authorize_document_cleanup(
    record: dict[str, Any],
    readback_name: str,
    readback_type: str,
    readback_location: str = xq_codex_scope.EXPECTED_SCRIPT_LOCATION,
) -> bool:
    return xq_codex_scope.authorize_manifest_document(
        record,
        readback_name=readback_name,
        readback_type=readback_type,
        readback_location=readback_location,
    )


def cleanup_document_id(record: dict[str, Any]) -> str:
    identity = {
        "case_id": record.get("case_id"),
        "name": record.get("name"),
        "script_type": record.get("script_type"),
    }
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    ).hexdigest()[:24]


def initialize_cleanup_states(
    documents: Sequence[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    states = dict(existing or {})
    for record in documents:
        document_id = cleanup_document_id(record)
        states.setdefault(document_id, {
            "document_id": document_id,
            "case_id": record.get("case_id"),
            "name": record.get("name"),
            "script_type": record.get("script_type"),
            "status": "pending",
            "stage": "pending",
            "attempts": 0,
            "opened_at_utc": None,
            "identity_readback_at_utc": None,
            "delete_confirmation_at_utc": None,
            "absence_verified_at_utc": None,
            "completed_at_utc": None,
            "last_evidence": None,
        })
    return states


def advance_cleanup_state(
    manifest: dict[str, Any],
    manifest_path: Path,
    record: dict[str, Any],
    stage: str,
    *,
    evidence: Any = None,
) -> dict[str, Any]:
    allowed = {
        "pending", "open_requested", "identity_readback_verified",
        "delete_confirmation_verified", "absence_verified", "completed",
    }
    if stage not in allowed:
        raise ValueError(f"Unknown cleanup stage: {stage}")
    document_id = cleanup_document_id(record)
    manifest["cleanup_states"] = initialize_cleanup_states(
        manifest.get("documents", []), manifest.get("cleanup_states"),
    )
    state = manifest["cleanup_states"][document_id]
    now = datetime.now(timezone.utc).isoformat()
    if stage == "open_requested":
        state["attempts"] += 1
        state["opened_at_utc"] = now
    elif stage == "identity_readback_verified":
        state["identity_readback_at_utc"] = now
    elif stage == "delete_confirmation_verified":
        state["delete_confirmation_at_utc"] = now
    elif stage == "absence_verified":
        state["absence_verified_at_utc"] = now
    elif stage == "completed":
        state["completed_at_utc"] = now
    state["stage"] = stage
    state["status"] = "completed" if stage == "completed" else "in_progress"
    state["last_evidence"] = evidence
    manifest["active_cleanup_document_id"] = None if stage == "completed" else document_id
    atomic_write_json(manifest_path, manifest)
    return state


def _open_xscript_open_dialog(config: dict[str, Any]) -> tuple[Any, Any]:
    import ctypes
    from pywinauto import keyboard

    win32_matches = [
        window for window in desktop_windows("win32")
        if window.window_text().startswith("XScript")
    ]
    if len(win32_matches) != 1:
        raise LookupError(f"Expected one XScript window, found {len(win32_matches)}")
    xscript = win32_matches[0]
    existing_dialogs = [
        window for window in desktop_windows("win32")
        if window.is_visible() and window.is_enabled() and window.class_name() == "#32770"
        and any(item.control_id() == 30007 for item in window.descendants())
        and any(item.control_id() == 30008 for item in window.descendants())
    ]
    if len(existing_dialogs) == 1:
        return xscript, existing_dialogs[0]
    if len(existing_dialogs) > 1:
        raise LookupError("XScript open dialog is ambiguous")
    ctypes.windll.user32.ShowWindow(int(xscript.handle), 9)
    wait_for_window_enabled(xscript, "xscript_open_before_ctrl_o")
    xscript.set_focus()
    ui_action_pause()
    keyboard.send_keys("^o")

    def dialog_probe() -> Any:
        matches = [
            window for window in desktop_windows("win32")
            if window.is_visible() and window.class_name() == "#32770"
            and any(item.control_id() == 30007 for item in window.descendants())
            and any(item.control_id() == 30008 for item in window.descendants())
        ]
        if len(matches) > 1:
            raise LookupError("XScript open dialog is ambiguous")
        return matches[0] if len(matches) == 1 else None

    outcome = adaptive_wait_for(
        dialog_probe,
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.dialog_timeout_seconds,
        late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
    )
    if outcome["status"] == "late":
        raise UiWaitIncident("ctrl_o_dialog_late", "xscript_open_dialog", evidence=outcome)
    if outcome["status"] == "timeout":
        raise UiWaitIncident("ctrl_o_dialog_timeout", "xscript_open_dialog", evidence=outcome)
    return xscript, outcome["value"]


def _select_exact_open_dialog_row(
    dialog: Any,
    script_type: str,
    name: str,
    *,
    allow_absent: bool = False,
) -> tuple[Any | None, Any]:
    type_ids = {"indicator": 30001, "alert": 30002, "function": 30003, "screener": 30004, "autotrade": 30005}
    wait_for_window_enabled(dialog, "xscript_open_select_type")
    [item for item in dialog.descendants() if item.control_id() == type_ids[script_type]][0].click_input()
    ui_action_pause()
    edits = [
        item for item in dialog.descendants()
        if item.control_id() == 45041 and item.is_visible()
    ]
    lists = [
        item for item in dialog.descendants()
        if item.class_name() == "SysListView32" and item.is_visible()
    ]
    if not lists:
        list_mode_buttons = [
            item for item in dialog.descendants()
            if item.control_id() == 45002 and item.is_visible()
        ]
        if len(list_mode_buttons) != 1:
            raise LookupError(f"Expected one visible XScript list-mode button, found {len(list_mode_buttons)}")
        list_mode_buttons[0].click_input()
        ui_action_pause()

        def list_mode_probe() -> Any:
            nonlocal edits, lists
            edits = [
                item for item in dialog.descendants()
                if item.control_id() == 45041 and item.is_visible()
            ]
            lists = [
                item for item in dialog.descendants()
                if item.class_name() == "SysListView32" and item.is_visible()
            ]
            return lists if lists else None

        outcome = adaptive_wait_for(
            list_mode_probe,
            timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
            late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
        )
        if outcome["status"] != "ready":
            raise UiWaitIncident(
                f"xscript_list_mode_{outcome['status']}",
                "xscript_open_list_mode",
                evidence=outcome,
            )
    if len(edits) != 1 or len(lists) != 1:
        raise LookupError(
            f"Expected one visible XScript filter/list, found edits={len(edits)}, lists={len(lists)}"
        )
    edit = edits[0]
    listing = lists[0]
    edit.set_edit_text(name)
    ui_action_pause()
    outcome = adaptive_wait_for(
        lambda: (
            {"item_count": listing.item_count()}
            if listing.item_count() in ({0, 1} if allow_absent else {1})
            else None
        ),
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
        late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
        policy=ACTIVE_UI_WAIT_POLICY,
    )
    if outcome["status"] == "late":
        raise UiWaitIncident("xscript_filter_late", "cleanup_open_filter", evidence=outcome)
    if allow_absent and listing.item_count() == 0:
        return None, edit
    if listing.item_count() != 1:
        raise LookupError(f"Expected one exact-filter XScript row for {name!r}, found {listing.item_count()}")
    listing.get_item(0).select()
    if listing.get_selected_count() != 1:
        raise RuntimeError("XScript did not select the filtered document")
    return listing, edit


def _read_active_document(xscript: Any, expected_name: str, expected_type: str) -> tuple[str, str]:
    from pywinauto import Desktop

    type_labels = {"indicator": "指標", "screener": "選股", "alert": "警示", "autotrade": "交易", "function": "函數"}
    expected_fragment = f"{expected_name}({type_labels[expected_type]})"
    title = ""

    def probe() -> Any:
        nonlocal title
        current = Desktop(backend="win32").window(handle=int(xscript.handle)).wrapper_object()
        title = " ".join(current.window_text().split())
        if expected_fragment in title:
            return (expected_name, expected_type)
        return None

    outcome = adaptive_wait_for(
        probe,
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
        late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
    )
    if outcome["status"] == "ready":
        return outcome["value"]
    if outcome["status"] == "late":
        raise UiWaitIncident("active_document_readback_late", "cleanup_identity_readback", evidence=outcome)
    raise RuntimeError(f"XScript document readback mismatch: {title}")


def _formula_area_controls(xscript_handle: int) -> tuple[Any, Any, Any]:
    from pywinauto import Desktop, keyboard

    def candidates(root: Any) -> tuple[list[Any], list[Any]]:
        edits = [
            item for item in root.descendants(control_type="Edit")
            if item.element_info.automation_id == "45041" and item.is_visible()
        ]
        listings = [
            item for item in root.descendants(control_type="List")
            if item.element_info.automation_id == "45241" and item.is_visible()
        ]
        return edits, listings

    uia_root = Desktop(backend="uia").window(handle=xscript_handle).wrapper_object()
    edits, listings = candidates(uia_root)
    compact_edits = [item for item in edits if item.rectangle().height() <= 60]
    formula_edits = (
        [min(compact_edits, key=lambda item: item.rectangle().top)]
        if compact_edits
        else []
    )
    if not formula_edits:
        win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
        win32_root.set_focus()
        keyboard.send_keys("%v")
        time.sleep(ACTIVE_UI_WAIT_POLICY.poll_initial_seconds)
        popups = [
            window for window in desktop_windows("win32")
            if window.is_visible() and window.class_name() == "XTPPopupBar"
        ]
        if len(popups) != 1:
            raise LookupError("XScript View menu is ambiguous")
        popup = Desktop(backend="uia").window(handle=int(popups[0].handle)).wrapper_object()
        items = popup.descendants(control_type="MenuItem")
        formula_items = [
            item for item in items
            if " ".join(str(item.element_info.name or "").split()) == "公式區"
        ]
        if len(formula_items) != 1:
            keyboard.send_keys("{ESC}")
            raise LookupError("XScript formula-area menu item was not found")
        formula_items[0].invoke()
        ui_action_pause()
        uia_root = Desktop(backend="uia").window(handle=xscript_handle).wrapper_object()
        edits, listings = candidates(uia_root)
        compact_edits = [item for item in edits if item.rectangle().height() <= 60]
        formula_edits = (
            [min(compact_edits, key=lambda item: item.rectangle().top)]
            if compact_edits
            else []
        )
    if len(formula_edits) != 1:
        raise LookupError(f"Expected one visible formula search edit, found {len(formula_edits)}")
    edit = formula_edits[0]
    direct_lists = [
        listing for listing in listings
        if listing.rectangle().top >= edit.rectangle().bottom
        and listing.rectangle().left <= edit.rectangle().left
        and listing.rectangle().right >= edit.rectangle().right
    ]
    if len(direct_lists) == 1:
        return edit.parent(), edit, direct_lists[0]
    panes = [
        item for item in uia_root.descendants(control_type="Pane")
        if item.element_info.automation_id == "1000"
        and item.rectangle().left <= edit.rectangle().left
        and item.rectangle().right >= edit.rectangle().right
        and item.rectangle().top <= edit.rectangle().top
        and item.rectangle().bottom > edit.rectangle().bottom
    ]
    if len(panes) != 1:
        raise LookupError(f"Expected one formula-area pane, found {len(panes)}")
    pane = panes[0]
    pane_rectangle = pane.rectangle()
    lower_lists = [
        listing for listing in listings
        if listing.rectangle().top > edit.rectangle().top
        and listing.rectangle().left >= pane_rectangle.left
        and listing.rectangle().right <= pane_rectangle.right
        and listing.rectangle().bottom <= pane_rectangle.bottom
    ]
    if not lower_lists:
        win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
        list_mode_buttons = [
            item for item in win32_root.descendants()
            if item.class_name() == "Button" and item.control_id() == 45002 and item.is_visible()
            and item.rectangle().left >= pane_rectangle.left
            and item.rectangle().right <= pane_rectangle.right
            and item.rectangle().top >= pane_rectangle.top
            and item.rectangle().bottom <= pane_rectangle.bottom
        ]
        if len(list_mode_buttons) != 1:
            raise LookupError(
                f"Expected one formula-area list-mode button, found {len(list_mode_buttons)}"
            )
        list_mode_buttons[0].click_input()
        ui_action_pause()
        uia_root = Desktop(backend="uia").window(handle=xscript_handle).wrapper_object()
        edits, listings = candidates(uia_root)
        edit = min(edits, key=lambda item: item.rectangle().top)
        panes = [
            item for item in uia_root.descendants(control_type="Pane")
            if item.element_info.automation_id == "1000"
            and item.rectangle().left <= edit.rectangle().left
            and item.rectangle().right >= edit.rectangle().right
            and item.rectangle().top <= edit.rectangle().top
            and item.rectangle().bottom > edit.rectangle().bottom
        ]
        if len(panes) != 1:
            raise LookupError(f"Expected one formula-area pane after list-mode switch, found {len(panes)}")
        pane = panes[0]
        pane_rectangle = pane.rectangle()
        lower_lists = [
            listing for listing in listings
            if listing.rectangle().top > edit.rectangle().top
            and listing.rectangle().left >= pane_rectangle.left
            and listing.rectangle().right <= pane_rectangle.right
            and listing.rectangle().bottom <= pane_rectangle.bottom
        ]
        if not lower_lists:
            raise LookupError("Formula script list was not found after list-mode switch")
    listing = min(lower_lists, key=lambda item: item.rectangle().top)
    return pane, edit, listing


def _select_formula_document(
    xscript_handle: int,
    script_type: str,
    name: str,
    config: dict[str, Any],
) -> tuple[Any, Any]:
    from pywinauto import Desktop, mouse

    win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
    xq_backtest.configure_ui_pacing(config)
    xq_category_selector.switch_category(
        win32_root,
        script_type,
        xq_category_selector.load_contract(config),
        foreground_guard=xq_backtest.ensure_window_foreground,
        clicker=mouse.click,
    )
    win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
    panes = [
        item for item in win32_root.descendants()
        if item.class_name() == "AfxWnd140"
        and item.control_id() == 1000
        and item.is_visible()
        and item.rectangle().width() == 300
        and item.rectangle().height() > 500
    ]
    if len(panes) != 1:
        raise LookupError(f"Expected one visible formula content pane, found {len(panes)}")
    pane_rectangle = panes[0].rectangle()
    list_mode_buttons = [
        item for item in win32_root.descendants()
        if item.class_name() == "Button"
        and item.control_id() == 45002
        and item.is_visible()
        and item.rectangle().bottom <= pane_rectangle.bottom
    ]
    visible_formula_lists = [
        item for item in win32_root.descendants()
        if item.class_name() == "SysListView32"
        and item.control_id() == 45241
        and item.is_visible()
        and item.rectangle().bottom <= pane_rectangle.bottom
    ]
    if not visible_formula_lists:
        if len(list_mode_buttons) != 1:
            raise LookupError(
                f"Expected one visible formula list-mode button, found {len(list_mode_buttons)}"
            )
        list_mode_buttons[0].click_input()
        ui_action_pause()
        win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
    win32_edits = [
        item for item in win32_root.descendants()
        if item.class_name() == "Edit" and item.control_id() == 45041 and item.is_visible()
        and item.rectangle().height() <= 60
        and item.rectangle().bottom <= pane_rectangle.bottom
    ]
    win32_lists = [
        item for item in win32_root.descendants()
        if item.class_name() == "SysListView32" and item.control_id() == 45241 and item.is_visible()
        and item.rectangle().bottom <= pane_rectangle.bottom
    ]
    if len(win32_edits) != 1 or len(win32_lists) != 1:
        raise LookupError(
            "Expected one in-pane formula filter/list, "
            f"found edits={len(win32_edits)}, lists={len(win32_lists)}"
        )
    win32_edit = win32_edits[0]
    listing = win32_lists[0]
    win32_edit.set_edit_text(name)
    ui_action_pause()
    outcome = adaptive_wait_for(
        lambda: listing if listing.item_count() == 1 else None,
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
        late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
    )
    if outcome["status"] == "late":
        raise UiWaitIncident("formula_filter_late", "cleanup_identity_readback", evidence=outcome)
    if listing.item_count() != 1:
        raise LookupError(f"Expected one formula row for {name!r}, found {listing.item_count()}")
    win32_root.set_focus()
    ui_action_pause()
    listing.get_item(0).select()
    selected_listing = listing

    def selection_probe() -> Any:
        nonlocal selected_listing
        selected_listing = Desktop(backend="win32").window(
            handle=int(listing.handle),
        ).wrapper_object()
        return selected_listing if selected_listing.get_selected_count() == 1 else None

    adaptive_wait_for(
        selection_probe,
        timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
    )
    if selected_listing.get_selected_count() != 1:
        raise RuntimeError("Formula area did not select the exact filtered document")
    return selected_listing, win32_edit


def _verify_formula_property_readback(xscript_handle: int, name: str, script_type: str) -> bool:
    from pywinauto import Desktop
    from pywinauto.uia_defines import IUIA

    labels = {"indicator": "指標", "screener": "選股", "alert": "警示", "autotrade": "交易", "function": "函數"}
    win32_root = Desktop(backend="win32").window(handle=xscript_handle).wrapper_object()
    title = " ".join(win32_root.window_text().split())
    # A pywinauto wrapper traversal of the complete XScript UIA tree can block
    # for minutes on an otherwise healthy local window.  Query the native UIA
    # element array once; XQ exposes the property-grid values as element names.
    # This keeps the exact name/type/CODEX readback while avoiding repeated
    # cross-process wrapper calls for every descendant.
    uia = IUIA()
    root = uia.iuia.ElementFromHandle(xscript_handle)
    elements = root.FindAll(uia.tree_scope["descendants"], uia.true_condition)
    texts = []
    for index in range(elements.Length):
        value = " ".join(str(elements.GetElement(index).CurrentName or "").split())
        if value:
            texts.append(value)
    return (
        f"{name}({labels[script_type]})" in title
        and name in texts
        and xq_codex_scope.EXPECTED_SCRIPT_LOCATION in texts
    )


def delete_manifest_document(
    config: dict[str, Any],
    record: dict[str, Any],
    *,
    on_stage: Callable[[str, Any], None] | None = None,
) -> dict[str, Any]:
    from pywinauto import Desktop, keyboard

    def stage(name: str, evidence: Any = None) -> None:
        if on_stage is not None:
            on_stage(name, evidence)

    if record.get("deleted") is True:
        stage("absence_verified", {"source": "manifest_deleted_flag"})
        return {
            "name": record.get("name"),
            "script_type": record.get("script_type"),
            "deleted": True,
            "already_deleted": True,
        }
    if record.get("created") is not True:
        if record.get("creation_disproven") is not True:
            return {
                "name": record.get("name"),
                "script_type": record.get("script_type"),
                "deleted": False,
                "reason": "manifest_creation_state_unconfirmed",
            }
        stage("absence_verified", {"source": "manifest_creation_disproven"})
        return {
            "name": record.get("name"),
            "script_type": record.get("script_type"),
            "deleted": True,
            "not_created": True,
            "xq_delete_attempted": False,
        }
    name = str(record["name"])
    script_type = str(record["script_type"])
    stage("open_requested", {"name": name, "script_type": script_type})
    xscript, dialog = _open_xscript_open_dialog(config)
    listing, edit = _select_exact_open_dialog_row(
        dialog, script_type, name, allow_absent=True,
    )
    if listing is None:
        stage("absence_verified", {
            "method": "open_dialog_exact_type_filter_zero_rows",
        })
        edit.set_edit_text("")
        [item for item in dialog.descendants() if item.control_id() == 30008][0].click_input()
        ui_action_pause()
        return {
            "name": name,
            "script_type": script_type,
            "deleted": True,
            "already_absent": True,
            "absence_verified": True,
            "readback_method": "open_dialog_exact_type_filter_zero_rows",
        }
    [item for item in dialog.descendants() if item.control_id() == 30007][0].click_input()
    ui_action_pause()
    wait_for_window_enabled(xscript, "cleanup_after_open")
    readback_name, readback_type = _read_active_document(xscript, name, script_type)
    if not authorize_document_cleanup(record, readback_name, readback_type):
        return {"name": name, "deleted": False, "reason": "manifest_readback_mismatch"}
    listing, edit = _select_formula_document(int(xscript.handle), script_type, name, config)
    if not _verify_formula_property_readback(int(xscript.handle), name, script_type):
        return {"name": name, "deleted": False, "reason": "formula_property_readback_mismatch"}
    if edit.window_text() != name or listing.item_count() != 1:
        return {"name": name, "deleted": False, "reason": "formula_filter_changed"}
    stage("identity_readback_verified", {
        "name": readback_name,
        "script_type": readback_type,
        "location": xq_codex_scope.EXPECTED_SCRIPT_LOCATION,
    })
    listing.get_item(0).select()
    ui_action_pause()
    if listing.get_selected_count() != 1:
        return {"name": name, "deleted": False, "reason": "formula_selection_lost"}
    listing.set_focus()
    keyboard.send_keys("{DELETE}")
    ui_action_pause()
    type_labels = {
        "indicator": "\u6307\u6a19",
        "screener": "\u9078\u80a1",
        "alert": "\u8b66\u793a",
        "autotrade": "\u4ea4\u6613",
        "function": "\u51fd\u6578",
    }
    expected_signature = f"{name}({type_labels[script_type]})"
    confirmation = None
    for candidate in desktop_windows("win32"):
        try:
            if candidate.handle != dialog.handle and candidate.is_visible() and candidate.class_name() == "#32770":
                text = " ".join(item.window_text() for item in candidate.descendants())
                if expected_signature not in text:
                    continue
                if name in text and re.search(r"刪除|確定", text):
                    confirmation = candidate
                    break
        except Exception:
            continue
    if confirmation is None:
        raise LookupError("XScript delete confirmation with the exact document name was not found")
    buttons = [
        item for item in confirmation.descendants()
        if item.class_name() == "Button" and item.is_visible() and item.is_enabled()
    ]
    affirmative = [item for item in buttons if item.control_id() == 6]
    if len(affirmative) != 1:
        raise LookupError("XScript delete confirmation was ambiguous")
    stage("delete_confirmation_verified", {
        "expected_signature": expected_signature,
        "affirmative_control_id": 6,
    })
    affirmative[0].click_input()
    ui_action_pause()
    _, verification_dialog = _open_xscript_open_dialog(config)
    verification_listing, verification_edit = _select_exact_open_dialog_row(
        verification_dialog, script_type, name, allow_absent=True,
    )
    deleted = verification_listing is None
    verification_edit.set_edit_text("")
    [item for item in verification_dialog.descendants() if item.control_id() == 30008][0].click_input()
    ui_action_pause()
    if not deleted:
        raise RuntimeError(f"XScript document still exists after delete: {name}")
    stage("absence_verified", {
        "method": "open_dialog_exact_type_filter_zero_rows",
    })
    return {
        "name": name,
        "script_type": script_type,
        "deleted": True,
        "readback_verified": True,
        "readback_method": "active_document_and_formula_property",
    }


def cleanup_one_manifest_document(
    config: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    document_id = cleanup_document_id(record)
    manifest["cleanup_states"] = initialize_cleanup_states(
        manifest["documents"], manifest.get("cleanup_states"),
    )
    state = manifest["cleanup_states"][document_id]
    if state.get("status") == "completed" and state.get("stage") == "completed":
        return {
            "name": record.get("name"),
            "script_type": record.get("script_type"),
            "deleted": True,
            "cleanup_state_skipped": True,
            "absence_verified": True,
        }
    manifest["active_cleanup_document_id"] = document_id
    atomic_write_json(manifest_path, manifest)

    def on_stage(stage_name: str, evidence: Any) -> None:
        advance_cleanup_state(
            manifest, manifest_path, record, stage_name, evidence=evidence,
        )

    outcome = delete_manifest_document(config, record, on_stage=on_stage)
    if outcome.get("deleted") is not True:
        state["status"] = "refused"
        state["last_evidence"] = outcome
        atomic_write_json(manifest_path, manifest)
        return outcome
    record["deleted"] = True
    if state.get("stage") != "absence_verified":
        advance_cleanup_state(
            manifest, manifest_path, record, "absence_verified",
            evidence={"source": "delete_outcome", "outcome": outcome},
        )
    advance_cleanup_state(
        manifest, manifest_path, record, "completed",
        evidence={"deleted": True, "absence_verified": True},
    )
    return {
        **outcome,
        "cleanup_document_id": document_id,
        "cleanup_stage": "completed",
        "absence_verified": True,
    }


def recover_attempted_active_document(record: dict[str, Any]) -> bool:
    from pywinauto import Desktop

    if record.get("creation_attempted") is not True or record.get("created") is True:
        return False
    xscript_matches = [
        window for window in desktop_windows("win32")
        if window.window_text().startswith("XScript")
    ]
    if len(xscript_matches) != 1:
        return False
    try:
        readback_name, readback_type = _read_active_document(
            xscript_matches[0], str(record["name"]), str(record["script_type"]),
        )
    except Exception:
        return False
    if readback_name != record.get("name") or readback_type != record.get("script_type"):
        return False
    record["created"] = True
    record["type_readback"] = readback_type
    record["creation_recovered_from_active_readback"] = True
    return True


def report_close_wait_outcome(close_wait: dict[str, Any]) -> dict[str, bool]:
    content_closed = bool(close_wait.get("value"))
    late = close_wait.get("status") == "late"
    if late and not content_closed:
        raise UiWaitIncident(
            "report_close_late", "cleanup_report_close", evidence=close_wait,
        )
    return {
        "closed": content_closed,
        "late_wait_observed": late,
    }


def close_manifest_reports(report_handles: Iterable[int]) -> list[dict[str, Any]]:
    from pywinauto import Desktop, mouse

    def discard_unsaved_report(window: Any) -> dict[str, Any]:
        uia_window = Desktop(backend="uia").window(handle=int(window.handle)).wrapper_object()
        visible_text = {
            " ".join(str(item.window_text()).split())
            for item in uia_window.descendants()
            if item.is_visible()
        }
        semantic_buttons = [
            item for item in uia_window.descendants(control_type="Button")
            if item.is_visible() and item.is_enabled() and item.window_text() == "不儲存"
        ]
        if "是否要儲存回測報告?" in visible_text and len(semantic_buttons) == 1:
            semantic_buttons[0].invoke()
            return {
                "discard_selected": True,
                "discard_method": "semantic_exact_prompt_and_invoke",
            }
        image = window.capture_as_image().convert("RGB")
        width, height = image.size
        points = []
        for y in range(int(height * 0.10), int(height * 0.38)):
            for x in range(int(width * 0.30), int(width * 0.70)):
                red, green, blue = image.getpixel((x, y))
                if red >= 180 and green <= 130 and blue <= 130 and red - green >= 60:
                    points.append((x, y))
        if not points:
            return {"discard_selected": False, "reason": "discard_button_not_found"}
        left = min(x for x, _ in points)
        right = max(x for x, _ in points)
        top = min(y for _, y in points)
        bottom = max(y for _, y in points)
        if not (40 <= right - left <= 120 and 20 <= bottom - top <= 60):
            return {
                "discard_selected": False,
                "reason": "discard_button_geometry_rejected",
                "bounds": [left, top, right, bottom],
            }
        rectangle = window.rectangle()
        window.set_focus()
        time.sleep(ACTIVE_UI_WAIT_POLICY.poll_initial_seconds)
        mouse.click(coords=(
            rectangle.left + (left + right) // 2,
            rectangle.top + (top + bottom) // 2,
        ))
        return {
            "discard_selected": True,
            "bounds": [left, top, right, bottom],
        }

    results = []
    for handle in sorted(set(report_handles)):
        try:
            window = Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
            if not window.is_visible():
                results.append({
                    "window_handle": handle,
                    "closed": True,
                    "already_closed": True,
                    "discard_selected": False,
                })
                continue
            wait_for_window_enabled(window, "cleanup_report_close")
            if xq_backtest.report_elements(window) is not None:
                window.close()
                ui_action_pause()
            try:
                after_close = Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
                content_closed = not after_close.is_visible()
            except Exception:
                content_closed = True
            if content_closed:
                results.append({"window_handle": handle, "closed": True, "discard_selected": False})
                continue
            discard = discard_unsaved_report(Desktop(backend="win32").window(handle=int(handle)).wrapper_object())
            def report_closed_probe() -> Any:
                try:
                    current = Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
                    return (
                        True
                        if not current.is_visible() or xq_backtest.report_elements(current) is None
                        else None
                    )
                except Exception:
                    return True

            close_wait = adaptive_wait_for(
                report_closed_probe,
                timeout_seconds=ACTIVE_UI_WAIT_POLICY.state_timeout_seconds,
                late_after_seconds=ACTIVE_UI_WAIT_POLICY.dialog_late_after_seconds,
            )
            close_outcome = report_close_wait_outcome(close_wait)
            content_closed = close_outcome["closed"]
            results.append({
                "window_handle": handle,
                "closed": content_closed,
                "late_wait_observed": close_outcome["late_wait_observed"],
                **discard,
                **({} if content_closed else {"reason": "report_content_still_visible"}),
            })
        except UiWaitIncident:
            raise
        except Exception as exc:
            import ctypes

            if not ctypes.windll.user32.IsWindow(int(handle)):
                results.append({
                    "window_handle": handle,
                    "closed": True,
                    "already_closed": True,
                    "discard_selected": False,
                })
            else:
                results.append({
                    "window_handle": handle,
                    "closed": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                })
    return results


def cleanup_temp_paths(temp_root: Path, paths: Iterable[str]) -> list[dict[str, Any]]:
    root = temp_root.resolve()
    results = []
    for raw in paths:
        path = Path(raw).resolve()
        if path == root or root not in path.parents:
            results.append({"path": str(path), "removed": False, "reason": "outside_manifest_temp_root"})
            continue
        if path.is_file():
            path.unlink()
            results.append({"path": str(path), "removed": True})
        elif path.is_dir():
            shutil.rmtree(path)
            results.append({"path": str(path), "removed": True})
        else:
            results.append({"path": str(path), "removed": True, "already_absent": True})
    return results


def require_safe_recovery(config: Path) -> dict[str, Any]:
    result = require_tool_success(
        run_json_tool("xq_backtest.py", ["--config", str(config), "--recovery-status"], 30),
        "recovery_status",
    )
    if result.get("decision") != "safe_to_start":
        raise RunnerError("Recovery status does not allow a new backtest", evidence=result)
    return result


def completed_results(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        state["result"]
        for _, state in sorted(
            manifest["case_states"].items(), key=lambda item: item[1]["ordinal"],
        )
        if state["status"] == "completed" and isinstance(state.get("result"), dict)
    ]


def record_recovered_case(
    manifest: dict[str, Any],
    manifest_path: Path,
    case: BoundaryCase,
    report: dict[str, Any],
    late_recovery: dict[str, Any],
) -> dict[str, Any]:
    state = manifest["case_states"][case.case_id]
    report = merge_late_report_evidence(report, state.get("backtest_evidence"))
    evaluated = evaluate_case_result(case, report)
    if not evaluated["passed"]:
        raise RunnerError(
            "Recovered report did not match the active case contract",
            evidence={"case": asdict(case), "report": report, "evaluation": evaluated},
        )
    result = {
        "case": asdict(case),
        "compile": state.get("compile", {}),
        "result": evaluated,
        "late_recovery": late_recovery,
        "resumed_without_rerun": True,
    }
    handle = evaluated.get("report_window_handle")
    if isinstance(handle, int) and handle > 0 and handle not in manifest["report_handles"]:
        manifest["report_handles"].append(handle)
    if case.case_id not in manifest["completed_case_ids"]:
        manifest["completed_case_ids"].append(case.case_id)
    state["result"] = result
    state["late_recovery"] = late_recovery
    state["status"] = "completed"
    state["stage"] = "result_captured"
    manifest["active_case_id"] = None
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    return result


def reset_pre_backtest_active_case(
    config: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    case_id: str,
) -> list[dict[str, Any]]:
    cleanup = []
    for record in reversed(manifest["documents"]):
        if record.get("case_id") != case_id or record.get("deleted") is True:
            continue
        if (
            record.get("created") is not True
            and record.get("creation_disproven") is not True
            and not recover_attempted_active_document(record)
        ):
            raise RunnerError(
                "Attempted document creation could not be proven absent or read back exactly",
                evidence={"case_id": case_id, "record": record},
            )
        atomic_write_json(manifest_path, manifest)
        outcome = cleanup_one_manifest_document(
            config, manifest, manifest_path, record,
        )
        cleanup.append(outcome)
        if outcome.get("deleted") is not True:
            raise RunnerError(
                "Incomplete pre-backtest case documents could not be safely reset",
                evidence={"case_id": case_id, "cleanup": cleanup},
            )
        record["deleted"] = True
        atomic_write_json(manifest_path, manifest)
    state = manifest["case_states"][case_id]
    state["status"] = "pending"
    state["stage"] = "reset_after_interruption"
    state["compile"] = {}
    state["result"] = None
    state["late_recovery"] = None
    manifest["active_case_id"] = None
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    return cleanup


def reconcile_active_case_on_resume(
    config_path: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    cases: Sequence[BoundaryCase],
    late_report_seconds: float,
) -> dict[str, Any] | None:
    active_case_id = manifest.get("active_case_id")
    if active_case_id is None:
        return None
    case = next(item for item in cases if item.case_id == active_case_id)
    state = manifest["case_states"][active_case_id]
    if state["status"] == "completed":
        manifest["active_case_id"] = None
        atomic_write_json(manifest_path, manifest)
        write_progress_outputs(manifest)
        return state["result"]
    if state["stage"] != "backtest_started":
        require_safe_recovery(config_path)
        reset_pre_backtest_active_case(config, manifest, manifest_path, active_case_id)
        return None
    if case.expected_result != "sentinel_failure":
        raise RunnerError(
            "An interrupted no-marker case cannot be resumed automatically",
            evidence={"case_id": active_case_id, "decision": "manual_review_required"},
        )
    checkpoint = xq_backtest.load_checkpoint(xq_backtest.recovery_path(config_path))
    if checkpoint is not None:
        assessment, report = reconcile_timeout(
            config_path, case.expected_sentinel, late_report_seconds,
        )
    else:
        reports = capture_visible_reports_with_details()
        assessment = evaluate_late_report_baseline(
            state.get("baseline_report_handles", []), reports, case.expected_sentinel,
        )
        report = assessment.get("report") if assessment.get("decision") == "recovered" else None
    if assessment.get("decision") != "recovered" or not isinstance(report, dict):
        raise RunnerError(
            "Interrupted backtest requires manual review and must not be rerun",
            evidence={"case_id": active_case_id, "late_recovery": assessment},
        )
    return record_recovered_case(
        manifest, manifest_path, case, report, {**assessment, "resume_reconciliation": True},
    )


def run_case(
    config: Path,
    case: BoundaryCase,
    ordinal: int,
    manifest: dict[str, Any],
    manifest_path: Path,
    temp_root: Path,
    timeout_seconds: float,
    late_report_seconds: float,
) -> dict[str, Any]:
    state = manifest["case_states"][case.case_id]
    state["attempts"] += 1
    state["status"] = "running"
    state["stage"] = "sources_written"
    state["compile"] = {}
    state["result"] = None
    state["late_recovery"] = None
    manifest["active_case_id"] = case.case_id
    manifest.pop("last_error", None)
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    function_name, caller_name = document_names(manifest["run_id"], ordinal, state["attempts"])
    function_text, caller_text = render_sources(case, function_name)
    function_path = temp_root / f"{case.case_id}-function.xs"
    caller_path = temp_root / f"{case.case_id}-caller.xs"
    function_path.write_text(function_text, encoding="utf-8")
    caller_path.write_text(caller_text, encoding="utf-8")
    manifest["temp_paths"].extend([str(function_path), str(caller_path)])
    atomic_write_json(manifest_path, manifest)
    function_compile = compile_document(
        config, manifest, manifest_path, name=function_name, script_type="function",
        source=function_path, case_id=case.case_id,
    )
    state["compile"]["function"] = function_compile
    state["stage"] = "function_compiled"
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    caller_compile = compile_document(
        config, manifest, manifest_path, name=caller_name, script_type="autotrade",
        source=caller_path, case_id=case.case_id,
    )
    state["compile"]["caller"] = caller_compile
    state["stage"] = "caller_compiled"
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    require_safe_recovery(config)
    state["baseline_report_handles"] = sorted(xq_backtest.visible_report_handles())
    state["stage"] = "backtest_started"
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    raw = run_json_tool(
        "xq_backtest.py", backtest_arguments(config, case, timeout_seconds), timeout_seconds + 90,
    )["payload"]
    state["backtest_evidence"] = raw
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    late_recovery = None
    if backtest_requires_reconciliation(raw):
        if case.expected_result != "sentinel_failure":
            raise RunnerError(
                "Started backtest cannot be reconciled without an expected marker",
                evidence={"case_id": case.case_id, "result": raw, "decision": "manual_review_required"},
            )
        late_recovery, recovered_report = reconcile_timeout(
            config, case.expected_sentinel, late_report_seconds,
        )
        if late_recovery.get("decision") != "recovered" or recovered_report is None:
            raise RunnerError(
                "Interrupted backtest requires manual review",
                evidence={"case_id": case.case_id, "result": raw, "late_recovery": late_recovery},
            )
        raw = merge_late_report_evidence(recovered_report, state["backtest_evidence"])
        raw["recovery_checkpoint_retained"] = False
    evaluated = evaluate_case_result(case, raw)
    if not evaluated["passed"]:
        raise RunnerError("Boundary case result did not match its contract", evidence={"case": asdict(case), "result": raw, "evaluation": evaluated})
    handle = evaluated.get("report_window_handle")
    if isinstance(handle, int) and handle > 0:
        manifest["report_handles"].append(handle)
    manifest["completed_case_ids"].append(case.case_id)
    completed_result = {
        "case": asdict(case),
        "compile": {"function": function_compile, "caller": caller_compile},
        "result": evaluated,
        "late_recovery": late_recovery,
    }
    state["result"] = completed_result
    state["late_recovery"] = late_recovery
    state["status"] = "completed"
    state["stage"] = "result_captured"
    manifest["active_case_id"] = None
    atomic_write_json(manifest_path, manifest)
    write_progress_outputs(manifest)
    return completed_result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--late-report-seconds", type=float, default=30)
    parser.add_argument(
        "--inter-case-seconds",
        type=float,
        default=DEFAULT_INTER_CASE_SECONDS,
        help="Minimum idle time between XQ cases; use a larger value on slower desktops",
    )
    parser.add_argument(
        "--ui-action-settle-seconds", type=float, default=UI_ACTION_SETTLE_SECONDS,
    )
    parser.add_argument(
        "--ui-poll-initial-seconds", type=float, default=DEFAULT_UI_POLL_INITIAL_SECONDS,
    )
    parser.add_argument(
        "--ui-poll-max-seconds", type=float, default=DEFAULT_UI_POLL_MAX_SECONDS,
    )
    parser.add_argument(
        "--ui-poll-backoff", type=float, default=DEFAULT_UI_POLL_BACKOFF,
    )
    parser.add_argument(
        "--ui-dialog-late-after-seconds",
        type=float,
        default=DEFAULT_UI_DIALOG_LATE_AFTER_SECONDS,
    )
    parser.add_argument(
        "--ui-dialog-timeout-seconds",
        type=float,
        default=DEFAULT_UI_DIALOG_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--ui-state-timeout-seconds",
        type=float,
        default=DEFAULT_UI_STATE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--late-recovery-probe-case")
    parser.add_argument("--late-recovery-timeout-seconds", type=float, default=0.05)
    parser.add_argument("--require-late-recovery-probe", action="store_true")
    parser.add_argument("--resume-manifest", type=Path)
    parser.add_argument(
        "--run-id",
        help="Caller-stable UUID used to discover an interrupted child manifest",
    )
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument(
        "--only-pair",
        action="append",
        default=[],
        help="Run both control and shortage cases for this exact pair id; repeatable",
    )
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    parser.add_argument("--keep-test-artifacts", action="store_true")
    return parser.parse_args(argv)


def wait_policy_from_args(args: argparse.Namespace, config: dict[str, Any] | None = None) -> UiWaitPolicy:
    pacing = xq_ui_pacing.load_ui_pacing(config)
    return UiWaitPolicy(
        action_settle_seconds=max(
            UI_ACTION_SETTLE_SECONDS,
            pacing.action_interval(args.ui_action_settle_seconds),
        ),
        poll_initial_seconds=args.ui_poll_initial_seconds,
        poll_max_seconds=args.ui_poll_max_seconds,
        poll_backoff=args.ui_poll_backoff,
        dialog_late_after_seconds=args.ui_dialog_late_after_seconds,
        dialog_timeout_seconds=args.ui_dialog_timeout_seconds,
        state_timeout_seconds=args.ui_state_timeout_seconds,
        inter_case_seconds=pacing.scale(args.inter_case_seconds, floor_seconds=1.0),
    ).validate()


def slower_resume_policy(recorded: UiWaitPolicy, requested: UiWaitPolicy) -> UiWaitPolicy:
    """Never make a resumed desktop run faster than its persisted contract."""
    return UiWaitPolicy(**{
        field: max(getattr(recorded, field), getattr(requested, field))
        for field in asdict(recorded)
    }).validate()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_historical_backtest:
        return emit(
            "automation_error", "Explicit --confirm-historical-backtest is required before reading cases or touching XQ",
            xq_touched=False, backtest_started=False,
        )
    if (
        args.timeout_seconds <= 0
        or args.late_report_seconds < 0
        or args.late_recovery_timeout_seconds <= 0
    ):
        return emit("automation_error", "Timeout values are invalid", xq_touched=False, backtest_started=False)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        requested_wait_policy = wait_policy_from_args(args, config)
    except ValueError as exc:
        return emit(
            "automation_error", str(exc), xq_touched=False, backtest_started=False,
        )
    if args.require_late_recovery_probe and not args.late_recovery_probe_case:
        return emit(
            "automation_error",
            "--require-late-recovery-probe requires --late-recovery-probe-case",
            xq_touched=False,
            backtest_started=False,
        )
    if args.resume_manifest is not None and args.output_directory is not None:
        return emit(
            "automation_error",
            "--output-directory cannot replace the paths recorded by a resume manifest",
            xq_touched=False,
            backtest_started=False,
        )
    if args.run_id is not None:
        try:
            parsed_run_id = UUID(args.run_id, version=4)
        except (ValueError, AttributeError):
            return emit(
                "automation_error", "--run-id must be a canonical UUIDv4",
                xq_touched=False, backtest_started=False,
            )
        if str(parsed_run_id) != args.run_id.lower():
            return emit(
                "automation_error", "--run-id must be a canonical UUIDv4",
                xq_touched=False, backtest_started=False,
            )
    manifest: dict[str, Any] | None = None
    manifest_path: Path | None = None
    temp_root: Path | None = None
    results: list[dict[str, Any]] = []
    cleanup: dict[str, Any] = {}
    try:
        suite, all_cases = load_case_file(args.cases)
        cases, selected_pair_ids = select_case_pairs(all_cases, args.only_pair)
        if not config.get("calibrated"):
            raise RunnerError("XQ UI configuration is not calibrated")
        for required_type in ("function", "autotrade"):
            try:
                xq_codex_scope.load_script_scope_contract(config, required_type)
            except xq_codex_scope.CodexScopeError as exc:
                raise RunnerError(
                    str(exc),
                    evidence={
                        "xq_touched": False,
                        "codex_scope_verified": False,
                        "script_type": required_type,
                    },
                ) from exc
        base = args.config.resolve().parent / "function-boundary-runs"
        base.mkdir(parents=True, exist_ok=True)
        probe_case = None
        if args.late_recovery_probe_case:
            probe_case = next(
                (case for case in cases if case.case_id == args.late_recovery_probe_case),
                None,
            )
            if probe_case is None:
                raise RunnerError("Late-recovery probe case was not found in the expanded suite")
            if probe_case.expected_result != "sentinel_failure":
                raise RunnerError("Late-recovery probe case must expect a unique sentinel failure")
        if args.resume_manifest is not None:
            manifest_path = args.resume_manifest.resolve()
            manifest = validate_resume_manifest(manifest_path, base, suite, cases)
            recorded_wait_policy = UiWaitPolicy(**manifest["pacing"]).validate()
            effective_wait_policy = slower_resume_policy(
                recorded_wait_policy, requested_wait_policy,
            )
            set_ui_wait_policy(effective_wait_policy)
            manifest["pacing"] = asdict(effective_wait_policy)
            atomic_write_json(manifest_path, manifest)
            temp_root = manifest_path.parent
            run_id = manifest["run_id"]
            if args.run_id is not None and args.run_id.lower() != run_id:
                raise RunnerError("Resume --run-id does not match the manifest")
            if (
                args.late_recovery_probe_case is not None
                and args.late_recovery_probe_case != manifest["late_recovery_probe"].get("case_id")
            ):
                raise RunnerError("Resume probe case does not match the manifest")
            write_progress_outputs(manifest)
            reconcile_active_case_on_resume(
                args.config, config, manifest, manifest_path, cases, args.late_report_seconds,
            )
        else:
            effective_wait_policy = requested_wait_policy
            set_ui_wait_policy(effective_wait_policy)
            require_safe_recovery(args.config)
            run_id = args.run_id.lower() if args.run_id is not None else str(uuid4())
            if list(base.glob(f"{run_id}-*/manifest.json")):
                raise RunnerError(
                    "A manifest already exists for --run-id; resume the exact manifest instead",
                )
            temp_root = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=base))
            manifest_path = temp_root / "manifest.json"
            output_directory = validate_output_directory(args.config, args.output_directory)
            manifest = {
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "run_id": run_id,
                "suite_id": suite["suite_id"],
                "case_file": str(args.cases.resolve()),
                "case_digest": case_file_digest(suite),
                "runner_contract_version": RUNNER_CONTRACT_VERSION,
                "selected_pair_ids": selected_pair_ids,
                "documents": [],
                "report_handles": [],
                "temp_paths": [],
                "completed_case_ids": [],
                "case_states": initialize_case_states(cases),
                "active_case_id": None,
                "cleanup_states": {},
                "active_cleanup_document_id": None,
                "output_json": str(output_directory / f"{suite['suite_id']}-{run_id}.json"),
                "output_junit": str(output_directory / f"{suite['suite_id']}-{run_id}.xml"),
                "late_recovery_probe": {
                    "case_id": args.late_recovery_probe_case,
                    "required": args.require_late_recovery_probe,
                    "observed": False,
                },
                "pacing": asdict(effective_wait_policy),
                "windows_wait_incidents": [],
            }
            atomic_write_json(manifest_path, manifest)
            write_progress_outputs(manifest)
        require_safe_recovery(args.config)
        effective_probe_case_id = manifest["late_recovery_probe"].get("case_id")
        pending = pending_cases(cases, manifest)
        for pending_index, case in enumerate(pending):
            if pending_index > 0:
                time.sleep(ACTIVE_UI_WAIT_POLICY.inter_case_seconds)
                require_safe_recovery(args.config)
            state = manifest["case_states"][case.case_id]
            case_timeout = (
                args.late_recovery_timeout_seconds
                if case.case_id == effective_probe_case_id
                else args.timeout_seconds
            )
            result = run_case(
                args.config, case, state["ordinal"], manifest, manifest_path, temp_root,
                case_timeout, args.late_report_seconds,
            )
            results.append(result)
            if case.case_id == effective_probe_case_id:
                observed = (
                    isinstance(result.get("late_recovery"), dict)
                    and result["late_recovery"].get("decision") == "recovered"
                )
                manifest["late_recovery_probe"]["observed"] = observed
                atomic_write_json(manifest_path, manifest)
                write_progress_outputs(manifest)
        results = completed_results(manifest)
        if (
            manifest["late_recovery_probe"].get("required") is True
            and manifest["late_recovery_probe"].get("observed") is not True
        ):
            raise RunnerError(
                "The required real late-recovery probe was not observed",
                evidence=manifest["late_recovery_probe"],
            )

        time.sleep(max(
            ACTIVE_UI_WAIT_POLICY.inter_case_seconds,
            ACTIVE_UI_WAIT_POLICY.action_settle_seconds,
        ))
        require_safe_recovery(args.config)
        cleanup["reports"] = close_manifest_reports(manifest["report_handles"])
        cleanup["documents"] = []
        for record in reversed(manifest["documents"]):
            outcome = cleanup_one_manifest_document(
                config, manifest, manifest_path, record,
            )
            cleanup["documents"].append(outcome)
        if not all(item.get("closed") is True for item in cleanup["reports"]):
            raise RunnerError("One or more manifest reports could not be closed", evidence=cleanup)
        if not all(item.get("deleted") is True for item in cleanup["documents"]):
            raise RunnerError("One or more manifest documents could not be safely deleted", evidence=cleanup)
        if xq_backtest.recovery_path(args.config).exists():
            raise RunnerError("A recovery checkpoint remains after completed cases", evidence=cleanup)
        cleanup["checkpoint_removed"] = True
        manifest["last_error"] = None
        write_progress_outputs(manifest)
        if not args.keep_test_artifacts:
            cleanup["temp"] = cleanup_temp_paths(temp_root, manifest["temp_paths"])
            manifest_path.unlink(missing_ok=True)
            temp_root.rmdir()
            cleanup["manifest_removed"] = True
        return emit(
            "success", "Function data-boundary suite passed and manifest-scoped artifacts were cleaned",
            suite_id=suite["suite_id"], run_id=run_id, case_count=len(results),
            cases=results,
            progress_json=manifest["output_json"],
            junit_xml=manifest["output_junit"],
            late_recovery_probe=manifest["late_recovery_probe"],
            resumed=args.resume_manifest is not None,
            cleanup=cleanup,
        )
    except RunnerError as exc:
        if manifest is not None and manifest_path is not None:
            wait_incident = record_windows_wait_incident(
                args.config, manifest, manifest_path, exc, exc.evidence,
            )
            manifest["last_error"] = {
                "status": exc.status,
                "message": str(exc),
                "evidence": exc.evidence,
                "windows_wait_incident": wait_incident,
            }
            atomic_write_json(manifest_path, manifest)
            write_progress_outputs(manifest)
            results = completed_results(manifest)
        return emit(
            exc.status, str(exc), cases=results, failed_evidence=exc.evidence,
            manifest_path=str(manifest_path) if manifest_path is not None else None,
            progress_json=manifest.get("output_json") if manifest is not None else None,
            junit_xml=manifest.get("output_junit") if manifest is not None else None,
            cleanup=cleanup,
        )
    except Exception as exc:
        if manifest is not None and manifest_path is not None:
            wait_incident = record_windows_wait_incident(
                args.config, manifest, manifest_path, exc,
            )
            manifest["last_error"] = {
                "status": "automation_error",
                "message": f"{type(exc).__name__}: {exc}",
                "windows_wait_incident": wait_incident,
            }
            atomic_write_json(manifest_path, manifest)
            write_progress_outputs(manifest)
            results = completed_results(manifest)
        return emit(
            "automation_error", f"Function boundary runner failed: {type(exc).__name__}: {exc}",
            cases=results, manifest_path=str(manifest_path) if manifest_path is not None else None,
            progress_json=manifest.get("output_json") if manifest is not None else None,
            junit_xml=manifest.get("output_junit") if manifest is not None else None,
            cleanup=cleanup,
        )


if __name__ == "__main__":
    sys.exit(main())
