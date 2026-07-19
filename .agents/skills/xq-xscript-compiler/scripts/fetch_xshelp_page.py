#!/usr/bin/env python3
"""Fetch one indexed XSHelp page transiently and emit bounded structured text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xshelp_common import (
    DetailSectionParser,
    canonicalize_url,
    configure_utf8_stdio,
    default_index_path,
    fetch_text,
    load_index,
    normalize_multiline,
)


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=default_index_path())
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--id")
    target.add_argument("--url")
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.max_chars < 500 or args.max_chars > 12000:
            return emit("automation_error", "--max-chars must be between 500 and 12000")
        index = load_index(args.index)
        records = index["documents"]
        if args.id:
            matches = [record for record in records if record.get("id") == args.id]
        else:
            target_url = canonicalize_url(args.url, index["source"])
            matches = [record for record in records if record.get("url") == target_url]
        if len(matches) != 1:
            return emit("automation_error", "Requested XSHelp page is not uniquely present in the local index")
        record = matches[0]
        result = fetch_text(
            str(record["url"]), timeout=args.timeout_seconds, retries=args.retries
        )
        parser = DetailSectionParser()
        parser.feed(result.text)
        sections = {
            key: normalize_multiline("".join(value))
            for key, value in parser.sections.items()
        }
        if not sections["title"] or not (sections["syntax"] or sections["description"]):
            raise RuntimeError("XSHelp page content structure was not recognized")
        budget = args.max_chars
        bounded: dict[str, str] = {}
        for key in ("title", "syntax", "description"):
            value = sections[key]
            bounded[key] = value[:budget]
            budget -= len(bounded[key])
            if budget <= 0:
                break
        return emit(
            "success",
            "XSHelp page fetched transiently",
            id=record["id"],
            url=record["url"],
            categories=record.get("categories", []),
            content=bounded,
            truncated=sum(len(value) for value in sections.values()) > args.max_chars,
            cached=False,
            copyright_mode="transient on-demand read; official body text was not saved",
        )
    except Exception as exc:
        return emit("automation_error", f"XSHelp page fetch failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main())
