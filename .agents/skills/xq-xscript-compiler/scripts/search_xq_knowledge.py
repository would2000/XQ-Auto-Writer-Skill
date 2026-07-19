#!/usr/bin/env python3
"""Search locally cloned sysjust-xq examples and emit ranked, bounded JSON results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_TYPES = {"indicator", "screener", "alert", "function", "autotrade"}
FUNCTION_RETURN_TYPES = {"number", "boolean", "string"}
MARKETS = {"tw", "cn", "hk", "us"}

PRESET_CATEGORY = {
    "指標": "indicator",
    "選股": "screener",
    "警示": "alert",
    "函數": "function",
    "自動交易": "autotrade",
}
STRATEGY_MARKET = {
    "01台股的選股條件": "tw",
    "02陸股的選股條件": "cn",
    "03港股的選股條件": "hk",
    "04美股的選股條件": "us",
}
HEADER_RETURN_TYPE = {
    "function": "number",
    "function_bool": "boolean",
    "function_string": "string",
}


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def decode_source(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def header_type(text: str) -> str:
    match = re.search(r"\{@type:([^}]+)\}", text, re.I)
    return match.group(1).strip().lower() if match else ""


def classify(path: Path, source_root: Path, text: str) -> dict[str, str | None]:
    relative = path.relative_to(source_root)
    repository = relative.parts[0]
    within_repo = Path(*relative.parts[1:])
    top = within_repo.parts[0] if within_repo.parts else ""
    header = header_type(text)
    if repository == "XScript_Preset":
        script_type = PRESET_CATEGORY.get(top)
        market = None
    elif repository == "XQStrategy":
        script_type = "screener"
        market = STRATEGY_MARKET.get(top)
    else:
        script_type = None
        market = None
    return {
        "repository": repository,
        "path": relative.as_posix(),
        "script_type": script_type,
        "market": market,
        "header": header,
        "function_return_type": HEADER_RETURN_TYPE.get(header),
    }


def make_snippet(text: str, terms: list[str], max_chars: int = 600) -> str:
    lines = text.replace("\r\n", "\n").splitlines()
    lowered = [line.casefold() for line in lines]
    index = 0
    for idx, line in enumerate(lowered):
        if any(term in line for term in terms):
            index = idx
            break
    start = max(0, index - 2)
    end = min(len(lines), index + 4)
    snippet = "\n".join(lines[start:end]).strip()
    return snippet[:max_chars]


def score_match(path_text: str, source_text: str, terms: list[str], match_mode: str) -> int | None:
    path_folded = path_text.casefold()
    source_folded = source_text.casefold()
    presence = [term in path_folded or term in source_folded for term in terms]
    if match_mode == "all" and not all(presence):
        return None
    if match_mode == "any" and not any(presence):
        return None
    score = 0
    filename = Path(path_text).stem.casefold()
    for term in terms:
        score += 8 if term in filename else 0
        score += 4 if term in path_folded else 0
        score += min(source_folded.count(term), 5)
    return score


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[4] / "third_party" / "sysjust-xq"
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=default_root)
    parser.add_argument("--script-type", choices=sorted(SCRIPT_TYPES), required=True)
    parser.add_argument("--function-return-type", choices=sorted(FUNCTION_RETURN_TYPES))
    parser.add_argument("--market", choices=sorted(MARKETS))
    parser.add_argument("--query", required=True)
    parser.add_argument("--match", choices=("all", "any"), default="all")
    parser.add_argument("--limit", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.script_type == "function" and not args.function_return_type:
            return emit("automation_error", "--function-return-type is required for function searches")
        if args.script_type != "function" and args.function_return_type:
            return emit("automation_error", "--function-return-type is only valid for function searches")
        if args.market and args.script_type != "screener":
            return emit("automation_error", "--market is currently supported only for screener searches")
        if args.limit < 1 or args.limit > 50:
            return emit("automation_error", "--limit must be between 1 and 50")
        terms = [term.casefold() for term in args.query.split() if term.strip()]
        if not terms:
            return emit("automation_error", "--query must contain at least one term")
        source_root = args.source_root.resolve()
        required = [source_root / "XScript_Preset", source_root / "XQStrategy"]
        missing = [str(path) for path in required if not path.is_dir()]
        if missing:
            return emit("automation_error", "XQ knowledge source is missing", missing=missing)

        matches: list[dict[str, Any]] = []
        scanned = 0
        for repository in required:
            for path in repository.rglob("*.xs"):
                scanned += 1
                text = decode_source(path)
                metadata = classify(path, source_root, text)
                if metadata["script_type"] != args.script_type:
                    continue
                if args.market and metadata["market"] != args.market:
                    continue
                if args.function_return_type and metadata["function_return_type"] != args.function_return_type:
                    continue
                score = score_match(str(metadata["path"]), text, terms, args.match)
                if score is None:
                    continue
                matches.append(
                    {
                        **metadata,
                        "score": score,
                        "snippet": make_snippet(text, terms),
                    }
                )

        matches.sort(key=lambda item: (-int(item["score"]), str(item["path"])))
        selected = matches[: args.limit]
        return emit(
            "success",
            "XQ knowledge search completed",
            query=args.query,
            terms=terms,
            match_mode=args.match,
            scanned_files=scanned,
            total_matches=len(matches),
            returned_matches=len(selected),
            matches=selected,
        )
    except Exception as exc:
        return emit("automation_error", f"XQ knowledge search failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
