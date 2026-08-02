#!/usr/bin/env python3
"""Run a red/green XQ integration test for a reusable XScript function."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")
MARKER_RE = re.compile(r"^[A-Z][A-Z0-9_]{7,79}$")


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return {"success": 0, "compile_error": 2, "automation_error": 3}[status]


def run_json_tool(script_name: str, arguments: list[str], timeout: float) -> dict[str, Any]:
    command = [sys.executable, str(SCRIPT_DIR / script_name), *arguments]
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
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{script_name} did not emit one valid JSON object: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise RuntimeError(f"{script_name} returned an invalid result object")
    return {
        "script": script_name,
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": completed.stderr.strip(),
    }


def evaluate_red_result(payload: dict[str, Any], marker: str) -> dict[str, Any]:
    details = payload.get("failure_details")
    matching = []
    if isinstance(details, list):
        matching = [
            item
            for item in details
            if isinstance(item, dict)
            and str(item.get("error_code", "")) == "1301"
            and marker in str(item.get("description", ""))
        ]
    passed = (
        payload.get("status") == "failure"
        and int(payload.get("success_count", -1)) == 0
        and int(payload.get("failure_count", 0)) >= 1
        and bool(matching)
        and payload.get("recovery_checkpoint_retained") is False
    )
    return {
        "passed": passed,
        "classification": payload.get("status"),
        "success_count": payload.get("success_count"),
        "failure_count": payload.get("failure_count"),
        "total_trades": payload.get("total_trades"),
        "expected_error_code": "1301",
        "expected_marker": marker,
        "matching_failure_count": len(matching),
        "checkpoint_cleared": payload.get("recovery_checkpoint_retained") is False,
    }


def evaluate_green_result(payload: dict[str, Any]) -> dict[str, Any]:
    passed = (
        payload.get("status") == "success"
        and int(payload.get("success_count", 0)) >= 1
        and int(payload.get("failure_count", -1)) == 0
        and payload.get("recovery_checkpoint_retained") is False
    )
    return {
        "passed": passed,
        "classification": payload.get("status"),
        "success_count": payload.get("success_count"),
        "failure_count": payload.get("failure_count"),
        "total_trades": payload.get("total_trades"),
        "checkpoint_cleared": payload.get("recovery_checkpoint_retained") is False,
    }


def require_success(result: dict[str, Any], stage: str) -> dict[str, Any]:
    payload = result["payload"]
    if payload.get("status") != "success" or result["returncode"] != 0:
        status = "compile_error" if payload.get("status") == "compile_error" else "automation_error"
        raise StageError(status, stage, payload)
    return payload


class StageError(RuntimeError):
    def __init__(self, status: str, stage: str, payload: dict[str, Any]):
        super().__init__(f"{stage} failed")
        self.status = status
        self.stage = stage
        self.payload = payload


def compile_document(
    args: argparse.Namespace,
    *,
    script_type: str,
    name: str,
    source: Path,
    function_return_type: str | None = None,
) -> dict[str, Any]:
    prepare_args = [
        "--config",
        str(args.config),
        "--script-type",
        script_type,
        "--name",
        name,
        "--folder",
        "CODEX",
    ]
    compile_args = [
        "--config",
        str(args.config),
        "--source",
        str(source),
        "--script-type",
        script_type,
        "--script-name",
        name,
    ]
    if function_return_type:
        prepare_args.extend(["--function-return-type", function_return_type])
        compile_args.extend(["--function-return-type", function_return_type])
    require_success(
        run_json_tool("xq_prepare_script.py", [*prepare_args, "--dry-run"], 45),
        f"preflight_{name}",
    )
    require_success(
        run_json_tool("xq_prepare_script.py", prepare_args, 45),
        f"prepare_{name}",
    )
    compiled = require_success(
        run_json_tool("xq_compile.py", compile_args, 60),
        f"compile_{name}",
    )
    return {
        "name": name,
        "script_type": script_type,
        "function_return_type": function_return_type,
        "compiled": True,
        "compiler_message": compiled.get("message"),
    }


def require_safe_recovery(args: argparse.Namespace, stage: str) -> None:
    result = run_json_tool(
        "xq_backtest.py",
        ["--config", str(args.config), "--recovery-status"],
        30,
    )
    payload = require_success(result, stage)
    if payload.get("decision") != "safe_to_start":
        raise StageError("automation_error", stage, payload)


def backtest_arguments(args: argparse.Namespace) -> list[str]:
    return [
        "--config", str(args.config),
        "--product", args.product,
        "--frequency", args.frequency,
        "--start-date", args.start_date,
        "--end-date", args.end_date,
        "--preload-records", str(args.preload_records),
        "--initial-capital-wan", args.initial_capital_wan,
        "--max-position", "1",
        "--max-entries-per-day", "1",
        "--max-trades-per-minute", "1",
        "--price-basis", "original",
        "--buy-price", "trigger",
        "--sell-price", "trigger",
        "--buy-offset", "0",
        "--sell-offset", "0",
        "--stock-fee-percent", "0.2",
        "--futures-fee", "100",
        "--simulate-ticks",
        "--no-daily-position-reset",
        "--fill-on-trigger",
        "--no-enable-print",
        "--no-us-all-sessions",
        "--no-direct-order",
        "--timeout-seconds", str(args.timeout_seconds),
    ]


def validate_args(args: argparse.Namespace) -> None:
    for label, value in (
        ("function name", args.function_name),
        ("red caller name", args.red_name),
        ("green caller name", args.green_name),
    ):
        if not SAFE_NAME_RE.fullmatch(value):
            raise ValueError(f"{label} must be an ASCII XScript identifier")
    if len({args.function_name.casefold(), args.red_name.casefold(), args.green_name.casefold()}) != 3:
        raise ValueError("function and caller document names must be unique")
    if not MARKER_RE.fullmatch(args.expected_red_marker):
        raise ValueError("--expected-red-marker must be 8-80 uppercase ASCII characters")
    if args.preload_records < 1:
        raise ValueError("--preload-records must be at least 1 for series tests")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--function-source", type=Path, required=True)
    parser.add_argument("--function-return-type", choices=("number", "boolean", "string"), required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--red-source", type=Path, required=True)
    parser.add_argument("--red-name", required=True)
    parser.add_argument("--green-source", type=Path, required=True)
    parser.add_argument("--green-name", required=True)
    parser.add_argument("--expected-red-marker", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--frequency", choices=("1", "2", "3", "5", "10", "15", "20", "30", "45", "60", "day"), required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--preload-records", type=int, default=5)
    parser.add_argument("--initial-capital-wan", default="100")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--confirm-historical-backtest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_historical_backtest:
        return emit(
            "automation_error",
            "Explicit --confirm-historical-backtest is required before touching XQ",
            xq_touched=False,
            backtest_started=False,
        )
    try:
        validate_args(args)
        for path in (args.function_source, args.red_source, args.green_source):
            if not path.is_file():
                raise ValueError(f"Source file does not exist: {path}")

        preflight = require_success(
            run_json_tool(
                "xq_function_preflight.py",
                [
                    "--source", str(args.function_source),
                    "--function-return-type", args.function_return_type,
                ],
                20,
            ),
            "function_preflight",
        )
        documents = [
            compile_document(
                args,
                script_type="function",
                name=args.function_name,
                source=args.function_source,
                function_return_type=args.function_return_type,
            )
        ]
        documents.append(
            compile_document(
                args,
                script_type="autotrade",
                name=args.red_name,
                source=args.red_source,
            )
        )
        require_safe_recovery(args, "recovery_before_red")
        red_raw = run_json_tool(
            "xq_backtest.py",
            backtest_arguments(args),
            args.timeout_seconds + 60,
        )["payload"]
        red = evaluate_red_result(red_raw, args.expected_red_marker)
        if not red["passed"]:
            raise StageError("automation_error", "red_control", red_raw)

        documents.append(
            compile_document(
                args,
                script_type="autotrade",
                name=args.green_name,
                source=args.green_source,
            )
        )
        require_safe_recovery(args, "recovery_before_green")
        green_raw = run_json_tool(
            "xq_backtest.py",
            backtest_arguments(args),
            args.timeout_seconds + 60,
        )["payload"]
        green = evaluate_green_result(green_raw)
        if not green["passed"]:
            raise StageError("automation_error", "green_control", green_raw)

        return emit(
            "success",
            "Function red/green integration contract passed in XQ",
            function_preflight_passed=preflight.get("valid") is True,
            documents=documents,
            red_control=red,
            green_control=green,
            test_scope={
                "product": args.product,
                "frequency": args.frequency,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "preload_records": args.preload_records,
                "historical_only": True,
                "account_selected": False,
                "live_strategy_started": False,
            },
        )
    except StageError as exc:
        return emit(
            exc.status,
            f"Function integration stage failed: {exc.stage}",
            failed_stage=exc.stage,
            stage_result=exc.payload,
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"Function integration failed: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    sys.exit(main())
