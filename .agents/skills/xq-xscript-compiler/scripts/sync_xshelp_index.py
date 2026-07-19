#!/usr/bin/env python3
"""Build a metadata-only index of all XSHelp syntax entries reachable from category lists."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

from xshelp_common import (
    DEFAULT_BASE_URL,
    FetchError,
    LinkHeadingParser,
    atomic_write_json,
    canonicalize_url,
    configure_utf8_stdio,
    default_index_path,
    fetch_text,
)


def emit(status: str, message: str, **extra: Any) -> int:
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "success" else 3


def parse_page(html: str) -> LinkHeadingParser:
    parser = LinkHeadingParser()
    parser.feed(html)
    return parser


def detail_url(url: str, base_url: str) -> bool:
    parsed = urlparse(url)
    base = urlparse(base_url)
    query = parse_qs(parsed.query)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() == base.netloc.lower()
        and parsed.path.rstrip("/") == base.path.rstrip("/")
        and bool(query.get("HelpName"))
        and bool(query.get("group"))
    )


def build_index(
    *,
    base_url: str,
    index_path: Path,
    delay_seconds: float,
    timeout_seconds: float,
    retries: int,
) -> dict[str, Any]:
    started_wall = datetime.now(ZoneInfo("Asia/Taipei"))
    started = time.monotonic()
    metrics: dict[str, Any] = {"request_attempts": 0, "retries": 0, "latencies": []}

    robots_url = urljoin(base_url, "/robots.txt")
    robots_status: int | str = "unavailable"
    try:
        robots_status = fetch_text(
            robots_url, timeout=timeout_seconds, retries=retries, metrics=metrics
        ).status
    except FetchError as exc:
        robots_status = exc.status or "unavailable"

    home = fetch_text(base_url, timeout=timeout_seconds, retries=retries, metrics=metrics)
    home_parser = parse_page(home.text)
    base = urlparse(base_url)
    list_path = urlparse(urljoin(base_url, "lists")).path.rstrip("/")
    category_links: dict[str, str] = {}
    for href, _text in home_parser.links:
        url = canonicalize_url(href, base_url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if (
            parsed.netloc == base.netloc
            and parsed.path.rstrip("/") == list_path
            and query.get("a")
        ):
            category_links[query["a"][0]] = url

    if not category_links:
        raise RuntimeError("No XSHelp category links were discovered")

    categories: list[dict[str, Any]] = []
    documents_by_url: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    discovered_links = 0
    for category_code, category_url in sorted(category_links.items()):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            result = fetch_text(
                category_url, timeout=timeout_seconds, retries=retries, metrics=metrics
            )
        except FetchError as exc:
            failures.append({"category_code": category_code, "url": category_url, "error": str(exc)})
            continue
        parser = parse_page(result.text)
        category_title = parser.headings[0] if parser.headings else category_code
        category_document_urls: set[str] = set()
        for href, anchor_text in parser.links:
            url = canonicalize_url(href, category_url)
            if not detail_url(url, base_url):
                continue
            discovered_links += 1
            category_document_urls.add(url)
            record = documents_by_url.setdefault(
                url,
                {
                    "id": hashlib.sha256(url.encode("utf-8")).hexdigest()[:20],
                    "name": anchor_text or parse_qs(urlparse(url).query)["HelpName"][0],
                    "aliases": set(),
                    "category_codes": set(),
                    "categories": set(),
                    "url": url,
                },
            )
            if anchor_text:
                record["aliases"].add(anchor_text)
            record["category_codes"].add(category_code)
            record["categories"].add(category_title)
        categories.append(
            {
                "code": category_code,
                "title": category_title,
                "url": category_url,
                "document_count": len(category_document_urls),
            }
        )

    if failures:
        raise RuntimeError(
            f"XSHelp category sync failed for {len(failures)} categories; previous index was preserved: {failures}"
        )
    if not documents_by_url:
        raise RuntimeError("No XSHelp syntax documents were discovered")

    documents: list[dict[str, Any]] = []
    for record in documents_by_url.values():
        documents.append(
            {
                **record,
                "aliases": sorted(record["aliases"], key=str.casefold),
                "category_codes": sorted(record["category_codes"]),
                "categories": sorted(record["categories"], key=str.casefold),
            }
        )
    documents.sort(key=lambda item: (str(item["name"]).casefold(), str(item["url"])))
    categories.sort(key=lambda item: str(item["code"]))
    elapsed = time.monotonic() - started
    latencies = [float(value) for value in metrics.pop("latencies", [])]
    index = {
        "schema_version": 1,
        "source": base_url,
        "generated_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "copyright_mode": "metadata-only; official body text is not stored",
        "body_text_stored": False,
        "categories": categories,
        "documents": documents,
        "stats": {
            "started_at": started_wall.isoformat(),
            "elapsed_seconds": round(elapsed, 3),
            "request_attempts": metrics["request_attempts"],
            "retries": metrics["retries"],
            "robots_status": robots_status,
            "category_count": len(categories),
            "discovered_document_links": discovered_links,
            "unique_document_count": len(documents),
            "duplicates_merged": discovered_links - len(documents),
            "failed_categories": 0,
            "average_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else 0,
            "maximum_latency_seconds": round(max(latencies), 3) if latencies else 0,
        },
    }
    atomic_write_json(index_path, index)
    return index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--index", type=Path, default=default_index_path())
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--retries", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.delay_seconds < 0 or args.delay_seconds > 10:
            return emit("automation_error", "--delay-seconds must be between 0 and 10")
        if args.timeout_seconds <= 0 or args.timeout_seconds > 120:
            return emit("automation_error", "--timeout-seconds must be between 0 and 120")
        if args.retries < 0 or args.retries > 8:
            return emit("automation_error", "--retries must be between 0 and 8")
        index = build_index(
            base_url=canonicalize_url(args.base_url),
            index_path=args.index,
            delay_seconds=args.delay_seconds,
            timeout_seconds=args.timeout_seconds,
            retries=args.retries,
        )
        return emit(
            "success",
            "XSHelp metadata index synchronized",
            index=str(args.index.resolve()),
            stats=index["stats"],
        )
    except Exception as exc:
        return emit("automation_error", f"XSHelp index sync failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    configure_utf8_stdio()
    sys.exit(main())
