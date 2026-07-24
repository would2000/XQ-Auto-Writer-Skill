#!/usr/bin/env python3
"""Search locally distilled XSHelp facts without loading official page bodies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xshelp_common import configure_utf8_stdio, project_root


def default_knowledge_path() -> Path:
    return (
        project_root()
        / ".agents"
        / "skills"
        / "xq-xscript-compiler"
        / "references"
        / "xshelp-distilled"
        / "quote-fields.json"
    )


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge", type=Path, default=default_knowledge_path())
    parser.add_argument("--query", required=True)
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=8)
    return parser.parse_args()


def searchable_text(record: dict[str, Any]) -> str:
    values: list[str] = []
    for value in record.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return " ".join(values).casefold()


def score_record(record: dict[str, Any], query: str) -> int:
    haystack = searchable_text(record)
    phrase = " ".join(query.split()).casefold()
    tokens = [token.casefold() for token in query.split() if token]
    score = 8 if phrase and phrase in haystack else 0
    score += sum(3 for token in tokens if token in str(record.get("name", "")).casefold())
    score += sum(1 for token in tokens if token in haystack)
    return score if all(token in haystack for token in tokens) else 0


def load_knowledge(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("records"), list):
        raise ValueError(f"Unsupported distilled knowledge format: {path}")
    if data.get("body_text_stored") is not False:
        raise ValueError("Distilled knowledge must declare body_text_stored=false")
    return data


def main() -> int:
    args = parse_args()
    try:
        if args.limit < 1 or args.limit > 50:
            return emit("automation_error", "--limit must be between 1 and 50")
        data = load_knowledge(args.knowledge)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for record in data["records"]:
            if args.category and args.category.casefold() not in str(record.get("category", "")).casefold():
                continue
            score = score_record(record, args.query)
            if score:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("name", ""))))
        matches = []
        for score, record in ranked[: args.limit]:
            matches.append(
                {
                    "source_id": record.get("source_id"),
                    "name": record.get("name"),
                    "category": record.get("category"),
                    "score": score,
                    "access_names": record.get("access_names", []),
                    "q_identifier": record.get("q_identifier"),
                    "q_identifier_aliases": record.get("q_identifier_aliases", []),
                    "book_side": record.get("book_side"),
                    "level": record.get("level"),
                    "value_kind": record.get("value_kind"),
                    "tick_offset": record.get("tick_offset"),
                    "lookback": record.get("lookback"),
                    "adjusted_for_stocks": record.get("adjusted_for_stocks"),
                    "market_period_basis": record.get("market_period_basis"),
                    "revenue_cadence": record.get("revenue_cadence"),
                    "direction": record.get("direction"),
                    "unit": record.get("unit"),
                    "format": record.get("format"),
                    "supported_scripts": record.get("supported_scripts", []),
                    "supported_products": record.get("supported_products", []),
                    "timing": record.get("timing"),
                    "meaning": record.get("meaning"),
                    "usage": record.get("usage"),
                    "formula": record.get("formula"),
                    "caveats": record.get("caveats", []),
                    "verification_status": record.get("verification_status"),
                    "url": record.get("url"),
                }
            )
        return emit(
            "success",
            "Distilled XSHelp knowledge searched",
            query=args.query,
            total_records=len(data["records"]),
            match_count=len(matches),
            matches=matches,
        )
    except Exception as exc:
        return emit("automation_error", f"Search failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main())
