#!/usr/bin/env python3
"""Generate one minimal XScript source file for a requested script category.

The command never opens XQ.  It writes exactly one new UTF-8 `.xs` file and
prints one JSON object so callers can pass the result to the normal prepare and
compile workflow.  It refuses to overwrite an existing file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Final


SCRIPT_TYPES: Final = ["indicator", "screener", "alert", "function", "autotrade"]
FUNCTION_CALLER_TYPES: Final = ["indicator", "screener", "alert", "autotrade"]
SAFE_FUNCTION_NAME_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")


def render_basic_script(script_type: str, function_name: str | None = None) -> str:
    """Return a compiler-oriented minimal source for one XScript category."""
    if script_type not in SCRIPT_TYPES:
        raise ValueError(f"unsupported_script_type:{script_type}")
    if function_name is not None and script_type not in FUNCTION_CALLER_TYPES:
        raise ValueError("function_template_cannot_depend_on_another_function")
    if function_name is not None and not SAFE_FUNCTION_NAME_RE.fullmatch(function_name):
        raise ValueError("function_name_must_be_an_ascii_xscript_identifier")

    if script_type == "function":
        return """{@type:function}

input: Offset(NumericSimple);

retval = Close - Open + Offset;
"""
    if function_name is None:
        return {
            "indicator": """{@type:indicator}

Plot1(Close, "BasicClose");
""",
            "screener": """{@type:filter}

ret = 0;

if Close >= Open then
    ret = 1;

OutputField(1, Close, 2, "Close");
""",
            "alert": """{@type:sensor}

ret = 0;

if Close > Open then
    ret = 1;
""",
            "autotrade": """{@type:autotrade}

variable: BasicValue(0);

BasicValue = Close;
""",
        }[script_type]

    if script_type == "indicator":
        return f'''{{@type:indicator}}

variable: BasicValue(0);

BasicValue = {function_name}(0);
Plot1(BasicValue, "FunctionDelta");
'''
    if script_type == "screener":
        return f'''{{@type:filter}}

variable: BasicValue(0);

BasicValue = {function_name}(0);
ret = 0;

if BasicValue >= 0 then
    ret = 1;

OutputField(1, BasicValue, 4, "FunctionDelta");
'''
    if script_type == "alert":
        return f'''{{@type:sensor}}

variable: BasicValue(0);

BasicValue = {function_name}(0);
ret = 0;

if BasicValue > 0 then
    ret = 1;
'''
    return f'''{{@type:autotrade}}

variable: BasicValue(0);

BasicValue = {function_name}(0);
'''


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script-type", choices=SCRIPT_TYPES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--with-function",
        action="store_true",
        help="Render a caller for the function named by --function-name.",
    )
    parser.add_argument("--function-name")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.output.suffix.casefold() != ".xs":
        raise ValueError("output_must_have_xs_extension")
    if args.output.exists():
        raise ValueError(f"output_already_exists:{args.output}")
    if args.with_function != (args.function_name is not None):
        raise ValueError("with_function_and_function_name_must_be_supplied_together")
    if args.with_function and args.script_type == "function":
        raise ValueError("function_template_cannot_depend_on_another_function")
    if args.function_name is not None and not SAFE_FUNCTION_NAME_RE.fullmatch(args.function_name):
        raise ValueError("function_name_must_be_an_ascii_xscript_identifier")


def emit(status: str, message: str, **extra: object) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_args(args)
        source = render_basic_script(
            args.script_type,
            args.function_name if args.with_function else None,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(source, encoding="utf-8", newline="\n")
        return emit(
            "success",
            "Basic XScript source generated; XQ compilation has not yet been run",
            script_type=args.script_type,
            output=str(args.output),
            function_dependency=args.function_name if args.with_function else None,
            xq_compilation_proven=False,
        )
    except (OSError, ValueError) as exc:
        return emit("automation_error", f"Basic XScript generation refused: {exc}")


if __name__ == "__main__":
    sys.exit(main())
