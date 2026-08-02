#!/usr/bin/env python3
"""Open, compile, and optionally execute one exact existing CODEX XScript."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import xq_category_selector


SCRIPT_TYPES = {"indicator", "screener", "alert", "function", "autotrade"}
FUNCTION_RETURN_TYPES = {"number", "boolean", "string"}
RUNTIME_TOOLS = {
    "indicator": "xq_indicator.py",
    "screener": "xq_screener.py",
    "alert": "xq_alert.py",
    "autotrade": "xq_backtest.py",
}
RESERVED_RUNTIME_OPTIONS = {
    "--config",
    "--script-name",
    "--source",
    "--script-type",
    "--function-return-type",
    "--calibration-mode",
    "--recovery-status",
}


class PipelineError(RuntimeError):
    def __init__(self, stage: str, message: str, *, child: dict[str, Any] | None = None):
        super().__init__(message)
        self.stage = stage
        self.child = child


@dataclass(frozen=True)
class DocumentRequest:
    source: Path
    script_type: str
    script_name: str
    function_return_type: str | None = None


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    if status == "success":
        return 0
    if status in {"compile_error", "runtime_failure"}:
        return 2
    return 3


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    parser.add_argument("--script-name", required=True)
    parser.add_argument("--function-return-type", choices=sorted(FUNCTION_RETURN_TYPES))
    parser.add_argument("--caller-source", type=Path)
    parser.add_argument("--caller-type", choices=sorted(SCRIPT_TYPES))
    parser.add_argument("--caller-name")
    parser.add_argument("--caller-function-return-type", choices=sorted(FUNCTION_RETURN_TYPES))
    parser.add_argument("--runtime-tool", choices=["none", *sorted(RUNTIME_TOOLS)], default="none")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("runtime_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _read_source(path: Path, label: str) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PipelineError("validation", f"Unable to read {label}: {exc}") from exc
    if not text.strip():
        raise PipelineError("validation", f"{label} is empty")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_document(request: DocumentRequest, label: str) -> dict[str, Any]:
    if request.script_type not in SCRIPT_TYPES:
        raise PipelineError("validation", f"Unsupported {label} type: {request.script_type}")
    name = xq_category_selector.validate_script_name(request.script_name)
    _, digest = _read_source(request.source, f"{label} source")
    if request.script_type == "function" and not request.function_return_type:
        raise PipelineError("validation", f"{label} function return type is required")
    if request.script_type != "function" and request.function_return_type:
        raise PipelineError(
            "validation", f"{label} function return type is valid only for function scripts"
        )
    return {
        "script_name": name,
        "script_type": request.script_type,
        "source_sha256": digest,
        "function_return_type": request.function_return_type,
    }


def validate_request(args: argparse.Namespace) -> dict[str, Any]:
    main = DocumentRequest(
        args.source, args.script_type, args.script_name, args.function_return_type
    )
    main_evidence = _validate_document(main, "main")

    caller_values = (args.caller_source, args.caller_type, args.caller_name)
    has_any_caller = any(value is not None for value in caller_values)
    has_all_caller = all(value is not None for value in caller_values)
    if has_any_caller != has_all_caller:
        raise PipelineError(
            "validation", "caller-source, caller-type, and caller-name must be provided together"
        )
    if has_all_caller and args.script_type != "function":
        raise PipelineError("validation", "A caller may be chained only after a function")
    if args.caller_function_return_type and args.caller_type != "function":
        raise PipelineError(
            "validation", "caller-function-return-type is valid only for a function caller"
        )

    caller_evidence = None
    if has_all_caller:
        caller_evidence = _validate_document(
            DocumentRequest(
                args.caller_source,
                args.caller_type,
                args.caller_name,
                args.caller_function_return_type,
            ),
            "caller",
        )

    runtime_args = list(args.runtime_args)
    if runtime_args and runtime_args[0] == "--":
        runtime_args = runtime_args[1:]
    if args.runtime_tool == "none" and runtime_args:
        raise PipelineError("validation", "runtime arguments require a runtime tool")
    if args.runtime_tool != "none" and args.runtime_tool != args.script_type:
        raise PipelineError(
            "validation", "runtime-tool must match the main script type"
        )
    if args.runtime_tool != "none" and args.script_type == "function":
        raise PipelineError(
            "validation", "Function execution must be proven through an explicit caller"
        )
    for token in runtime_args:
        option = token.split("=", 1)[0]
        if option in RESERVED_RUNTIME_OPTIONS:
            raise PipelineError(
                "validation", f"Runtime option {option} is owned by the pipeline"
            )
    return {
        "main": main_evidence,
        "caller": caller_evidence,
        "runtime_tool": args.runtime_tool,
        "runtime_args": runtime_args,
    }


def run_json_tool(script: str, arguments: list[str], timeout: float) -> tuple[int, dict[str, Any]]:
    command = [sys.executable, str(Path(__file__).with_name(script)), *arguments]
    completed = subprocess.run(
        command,
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
        raise PipelineError(
            script,
            f"Child tool returned {len(lines)} non-empty stdout lines",
            child={"stderr": completed.stderr.strip(), "returncode": completed.returncode},
        )
    try:
        payload = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise PipelineError(
            script,
            "Child tool did not return one JSON object",
            child={"stdout": lines[0], "stderr": completed.stderr.strip()},
        ) from exc
    if not isinstance(payload, dict):
        raise PipelineError(script, "Child tool JSON must be an object")
    return completed.returncode, payload


Runner = Callable[[str, list[str], float], tuple[int, dict[str, Any]]]


def _require_success(
    stage: str, result: tuple[int, dict[str, Any]]
) -> dict[str, Any]:
    code, payload = result
    if code == 0 and payload.get("status") == "success":
        return payload
    status = str(payload.get("status") or "automation_error")
    if status == "compile_error":
        raise PipelineError(stage, "XQ compilation failed", child=payload)
    raise PipelineError(stage, f"Child stage did not succeed: {status}", child=payload)


def _open_arguments(config: Path, evidence: dict[str, Any], dry_run: bool = False) -> list[str]:
    result = [
        "--config", str(config),
        "--script-type", evidence["script_type"],
        "--script-name", evidence["script_name"],
    ]
    if dry_run:
        result.append("--dry-run")
    return result


def _compile_arguments(config: Path, source: Path, evidence: dict[str, Any]) -> list[str]:
    result = [
        "--config", str(config),
        "--source", str(source),
        "--script-type", evidence["script_type"],
        "--script-name", evidence["script_name"],
    ]
    if evidence.get("function_return_type"):
        result.extend(["--function-return-type", evidence["function_return_type"]])
    return result


def _runtime_arguments(args: argparse.Namespace, validated: dict[str, Any]) -> list[str]:
    tool = args.runtime_tool
    result: list[str] = []
    if tool in {"indicator", "screener", "autotrade"}:
        result.extend(["--config", str(args.config)])
    if tool in {"indicator", "screener", "alert"}:
        result.extend(["--script-name", validated["main"]["script_name"]])
    result.extend(validated["runtime_args"])
    return result


def execute(args: argparse.Namespace, *, runner: Runner = run_json_tool) -> dict[str, Any]:
    validated = validate_request(args)
    stages: dict[str, Any] = {}

    main_open = _require_success(
        "open_main",
        runner(
            "xq_open_existing_script.py",
            _open_arguments(args.config, validated["main"], args.dry_run),
            60,
        ),
    )
    stages["open_main"] = main_open
    if args.dry_run:
        return {
            "status": "success",
            "message": "Existing CODEX pipeline plan inspected without compilation or runtime input",
            "dry_run": True,
            "input_sent": False,
            "validated": validated,
            "stages": stages,
        }

    main_compile = _require_success(
        "compile_main",
        runner(
            "xq_compile.py",
            _compile_arguments(args.config, args.source, validated["main"]),
            90,
        ),
    )
    stages["compile_main"] = main_compile

    if validated["caller"] is not None:
        caller_open = _require_success(
            "open_caller",
            runner(
                "xq_open_existing_script.py",
                _open_arguments(args.config, validated["caller"]),
                60,
            ),
        )
        stages["open_caller"] = caller_open
        caller_compile = _require_success(
            "compile_caller",
            runner(
                "xq_compile.py",
                _compile_arguments(args.config, args.caller_source, validated["caller"]),
                90,
            ),
        )
        stages["compile_caller"] = caller_compile

    if args.runtime_tool != "none":
        # A caller compile may have changed the active document; re-open the main
        # script before delegating to the category-specific runtime tool.
        stages["runtime_open_main"] = _require_success(
            "runtime_open_main",
            runner(
                "xq_open_existing_script.py",
                _open_arguments(args.config, validated["main"]),
                60,
            ),
        )
        runtime_script = RUNTIME_TOOLS[args.runtime_tool]
        code, runtime_payload = runner(
            runtime_script, _runtime_arguments(args, validated), 900
        )
        stages["runtime"] = runtime_payload
        if code != 0 or runtime_payload.get("status") != "success":
            raise PipelineError(
                "runtime",
                f"Runtime stage returned {runtime_payload.get('status', 'unknown')}",
                child=runtime_payload,
            )

    return {
        "status": "success",
        "message": "Exact CODEX document compilation pipeline completed",
        "dry_run": False,
        "validated": validated,
        "stages": stages,
        "current_task_compiler_success": True,
        "runtime_executed": args.runtime_tool != "none",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = execute(args)
        return emit(result.pop("status"), result.pop("message"), **result)
    except PipelineError as exc:
        status = "compile_error" if exc.stage.startswith("compile") and exc.child and exc.child.get("status") == "compile_error" else "automation_error"
        if exc.stage == "runtime" and exc.child and exc.child.get("status") not in {None, "automation_error"}:
            status = "runtime_failure"
        return emit(
            status,
            str(exc),
            failed_stage=exc.stage,
            child=exc.child,
            further_runtime_input_sent=False if exc.stage != "runtime" else None,
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"Unexpected existing-script pipeline failure: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    sys.exit(main())
