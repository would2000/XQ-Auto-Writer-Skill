#!/usr/bin/env python3
"""Perform conservative, offline checks for a generated XScript function."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


HEADER_BY_RETURN_TYPE = {
    "number": "function",
    "boolean": "function_bool",
    "string": "function_string",
}

FORBIDDEN_PATTERNS = {
    "SetPosition": r"\bsetposition\s*\(",
    "CancelAllOrders": r"\bcancelallorders\b",
    "Plot": r"\bplot\d*\s*\(",
    "OutputField": r"\boutputfield\s*\(",
}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def strip_comments_preserving_strings(source: str) -> str:
    """Remove // and {...} comments without treating quoted content as comments."""

    output: list[str] = []
    index = 0
    in_string = False
    in_line_comment = False
    brace_depth = 0
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
                output.append(char)
            index += 1
            continue

        if brace_depth:
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
            elif char in "\r\n":
                output.append(char)
            index += 1
            continue

        if in_string:
            output.append(char)
            if char == '"':
                if next_char == '"':
                    output.append(next_char)
                    index += 2
                    continue
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "{":
            pragma = re.match(r"\{@type\s*:\s*[^}]+\}", source[index:], re.IGNORECASE)
            if pragma:
                output.append(pragma.group(0))
                index += len(pragma.group(0))
                continue
            brace_depth = 1
            index += 1
            continue

        output.append(char)
        index += 1

    return "".join(output)


def strip_string_contents(source: str) -> str:
    """Replace quoted content so syntax-like text inside strings is not classified."""

    return re.sub(r'"(?:""|[^"])*"', '""', source)


def inspect_function(source: str, return_type: str) -> dict[str, Any]:
    expected_header = HEADER_BY_RETURN_TYPE[return_type]
    uncommented = strip_comments_preserving_strings(source)
    header_syntax = strip_string_contents(uncommented)
    headers = [
        match.casefold()
        for match in re.findall(
            r"\{@type\s*:\s*([^}\s]+)\s*\}", header_syntax, re.IGNORECASE
        )
    ]
    errors: list[str] = []

    if not headers:
        errors.append(f"Missing canonical header: {{@type:{expected_header}}}")
    elif len(headers) != 1:
        errors.append(f"Expected exactly one type header, found {len(headers)}")
    elif headers[0] != expected_header:
        errors.append(
            f"Header {headers[0]!r} does not match requested return type {return_type!r}; "
            f"expected {expected_header!r}"
        )

    executable = re.sub(
        r"\{@type\s*:\s*[^}]+\}", "", uncommented, flags=re.IGNORECASE
    )
    syntax_only = strip_string_contents(executable)
    if not executable.strip():
        errors.append("Function body is empty after comments and the type header are removed")

    if not re.search(r"\bretval\s*=", executable, re.IGNORECASE):
        errors.append("Generated functions must assign their return value through retval")

    if re.search(r"\bret\s*=", executable, re.IGNORECASE):
        errors.append("ret is for filter/sensor output; function scripts must use retval")

    forbidden = [
        name
        for name, pattern in FORBIDDEN_PATTERNS.items()
        if re.search(pattern, syntax_only, re.IGNORECASE)
    ]
    if forbidden:
        errors.append(
            "Reusable functions must not contain chart/report/order side effects: "
            + ", ".join(forbidden)
        )

    return {
        "valid": not errors,
        "function_return_type": return_type,
        "expected_header": expected_header,
        "observed_headers": headers,
        "retval_assignment_found": bool(
            re.search(r"\bretval\s*=", executable, re.IGNORECASE)
        ),
        "forbidden_constructs": forbidden,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--function-return-type",
        choices=sorted(HEADER_BY_RETURN_TYPE),
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source = args.source.read_text(encoding="utf-8")
    except Exception as exc:
        return emit("automation_error", f"Unable to read function source: {exc}")

    inspection = inspect_function(source, args.function_return_type)
    if not inspection["valid"]:
        return emit(
            "automation_error",
            "Function preflight failed",
            source=str(args.source),
            **inspection,
        )
    return emit(
        "success",
        "Function preflight passed; real XQ compilation is still required",
        source=str(args.source),
        **inspection,
    )


if __name__ == "__main__":
    sys.exit(main())
