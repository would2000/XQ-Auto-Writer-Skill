#!/usr/bin/env python3
"""Compile one XScript function and indicator/screener/alert callers in XQ."""

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
CALLER_TYPES = ("indicator", "screener", "alert")


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return {"success": 0, "compile_error": 2, "automation_error": 3}[status]


def run_json_tool(script_name: str, arguments: list[str], timeout: float) -> dict[str, Any]:
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
        raise RuntimeError(
            f"{script_name} did not emit one valid JSON object: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
        raise RuntimeError(f"{script_name} returned an invalid result object")
    return {
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": completed.stderr.strip(),
    }


class StageError(RuntimeError):
    def __init__(self, status: str, stage: str, payload: dict[str, Any]):
        super().__init__(f"{stage} failed")
        self.status = status
        self.stage = stage
        self.payload = payload


def require_success(result: dict[str, Any], stage: str) -> dict[str, Any]:
    payload = result["payload"]
    if result["returncode"] != 0 or payload.get("status") != "success":
        status = (
            "compile_error"
            if payload.get("status") == "compile_error"
            else "automation_error"
        )
        raise StageError(status, stage, payload)
    return payload


def compile_document(
    args: argparse.Namespace,
    *,
    script_type: str,
    name: str,
    source: Path,
    function_return_type: str | None = None,
) -> dict[str, Any]:
    prepare_args = [
        "--config", str(args.config),
        "--script-type", script_type,
        "--name", name,
        "--folder", "CODEX",
    ]
    compile_args = [
        "--config", str(args.config),
        "--source", str(source),
        "--script-type", script_type,
    ]
    if function_return_type is not None:
        prepare_args.extend(["--function-return-type", function_return_type])
        compile_args.extend(["--function-return-type", function_return_type])
    require_success(
        run_json_tool("xq_prepare_script.py", prepare_args, 45),
        f"prepare_{script_type}",
    )
    compiled = require_success(
        run_json_tool("xq_compile.py", compile_args, 60),
        f"compile_{script_type}",
    )
    return {
        "name": name,
        "script_type": script_type,
        "function_return_type": function_return_type,
        "compiled": True,
        "compiler_message": compiled.get("message"),
    }


def validate_args(args: argparse.Namespace) -> None:
    named_sources = [("function", args.function_name, args.function_source)]
    for script_type in CALLER_TYPES:
        named_sources.append(
            (
                script_type,
                getattr(args, f"{script_type}_name"),
                getattr(args, f"{script_type}_source"),
            )
        )
    names = []
    for label, name, source in named_sources:
        if not SAFE_NAME_RE.fullmatch(name):
            raise ValueError(f"{label} name must be an ASCII XScript identifier")
        if not source.is_file():
            raise ValueError(f"{label} source file does not exist: {source}")
        names.append(name.casefold())
    if len(set(names)) != len(names):
        raise ValueError("function and caller document names must be unique")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--function-source", type=Path, required=True)
    parser.add_argument(
        "--function-return-type",
        choices=("number", "boolean", "string"),
        required=True,
    )
    parser.add_argument("--function-name", required=True)
    for script_type in CALLER_TYPES:
        parser.add_argument(f"--{script_type}-source", type=Path, required=True)
        parser.add_argument(f"--{script_type}-name", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
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
        for script_type in CALLER_TYPES:
            documents.append(
                compile_document(
                    args,
                    script_type=script_type,
                    name=getattr(args, f"{script_type}_name"),
                    source=getattr(args, f"{script_type}_source"),
                )
            )
        return emit(
            "success",
            "Function caller compile matrix passed in XQ",
            function_preflight_passed=preflight.get("valid") is True,
            documents=documents,
            caller_types=list(CALLER_TYPES),
            proof_scope="compile_only",
            runtime_result_proven=False,
        )
    except StageError as exc:
        return emit(
            exc.status,
            f"Function caller matrix stage failed: {exc.stage}",
            failed_stage=exc.stage,
            stage_result=exc.payload,
        )
    except Exception as exc:
        return emit(
            "automation_error",
            f"Function caller matrix failed: {type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    sys.exit(main())
