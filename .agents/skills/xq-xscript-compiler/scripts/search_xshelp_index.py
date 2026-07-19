#!/usr/bin/env python3
"""Search the local XSHelp metadata index without copying official page bodies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from xshelp_common import configure_utf8_stdio, default_index_path, load_index


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=default_index_path())
    parser.add_argument("--query", required=True)
    parser.add_argument("--category")
    parser.add_argument("--match", choices=("all", "any"), default="all")
    parser.add_argument("--limit", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.limit < 1 or args.limit > 50:
            return emit("automation_error", "--limit must be between 1 and 50")
        terms = [term.casefold() for term in args.query.split() if term.strip()]
        if not terms:
            return emit("automation_error", "--query must contain at least one term")
        index = load_index(args.index)
        category_filter = args.category.casefold() if args.category else None
        matches: list[dict[str, Any]] = []
        for record in index["documents"]:
            categories = [str(value) for value in record.get("categories", [])]
            if category_filter and not any(category_filter in value.casefold() for value in categories):
                continue
            name = str(record.get("name", ""))
            aliases = [str(value) for value in record.get("aliases", [])]
            haystack = " ".join(
                [name, *aliases, *categories, *record.get("category_codes", []), unquote(str(record["url"]))]
            ).casefold()
            presence = [term in haystack for term in terms]
            if args.match == "all" and not all(presence):
                continue
            if args.match == "any" and not any(presence):
                continue
            name_folded = name.casefold()
            score = sum((12 if term == name_folded else 8 if term in name_folded else 2) for term in terms)
            matches.append({**record, "score": score})
        matches.sort(key=lambda item: (-int(item["score"]), str(item["name"]).casefold(), str(item["url"])))
        selected = matches[: args.limit]
        return emit(
            "success",
            "XSHelp metadata search completed",
            query=args.query,
            terms=terms,
            total_documents=len(index["documents"]),
            total_matches=len(matches),
            returned_matches=len(selected),
            matches=selected,
        )
    except Exception as exc:
        return emit("automation_error", f"XSHelp index search failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main())
