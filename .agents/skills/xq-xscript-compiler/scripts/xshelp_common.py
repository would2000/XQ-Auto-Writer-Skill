#!/usr/bin/env python3
"""Shared helpers for the metadata-only XSHelp knowledge integration."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://xshelp.xq.com.tw/XSHelp/"
USER_AGENT = "XQ-Auto-Writer-Knowledge-Indexer/1.0"


def configure_utf8_stdio() -> None:
    """Keep JSON automation output deterministic on non-UTF-8 Windows locales."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_index_path() -> Path:
    return project_root() / "third_party" / "xshelp" / "index.json"


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class FetchResult:
    url: str
    text: str
    status: int
    elapsed_seconds: float


def fetch_text(
    url: str,
    *,
    timeout: float = 20,
    retries: int = 3,
    backoff_seconds: float = 0.5,
    metrics: dict[str, Any] | None = None,
) -> FetchResult:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        started = time.monotonic()
        if metrics is not None:
            metrics["request_attempts"] = int(metrics.get("request_attempts", 0)) + 1
            if attempt:
                metrics["retries"] = int(metrics.get("retries", 0)) + 1
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    text = raw.decode("utf-8", errors="replace")
            elapsed = time.monotonic() - started
            if metrics is not None:
                metrics.setdefault("latencies", []).append(elapsed)
            return FetchResult(url=url, text=text, status=status, elapsed_seconds=elapsed)
        except HTTPError as exc:
            last_error = exc
            status = int(exc.code)
            exc.close()
            retryable = status == 429 or status >= 500
            if not retryable or attempt >= retries:
                raise FetchError(f"HTTP {status} for {url}", status=status) from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= retries:
                raise FetchError(f"Network failure for {url}: {exc}") from exc
        time.sleep(backoff_seconds * (2**attempt))
    raise FetchError(f"Unable to fetch {url}: {last_error}")


class LinkHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.headings: list[str] = []
        self._href: str | None = None
        self._anchor_depth = 0
        self._anchor_text: list[str] = []
        self._heading_tag: str | None = None
        self._heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and self._href is None:
            self._href = dict(attrs).get("href")
            self._anchor_depth = 1
            self._anchor_text = []
        elif self._href is not None:
            self._anchor_depth += 1
        if tag in {"h1", "h2", "h3", "h4"} and self._heading_tag is None:
            self._heading_tag = tag
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._anchor_text.append(data)
        if self._heading_tag is not None:
            self._heading_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._href is not None:
            self._anchor_depth -= 1
            if tag == "a" or self._anchor_depth <= 0:
                text = " ".join("".join(self._anchor_text).split())
                if self._href:
                    self.links.append((self._href, text))
                self._href = None
                self._anchor_depth = 0
                self._anchor_text = []
        if tag == self._heading_tag:
            text = " ".join("".join(self._heading_text).split())
            if text:
                self.headings.append(text)
            self._heading_tag = None
            self._heading_text = []


class DetailSectionParser(HTMLParser):
    TARGETS = {"fnc-title": "title", "syntax": "syntax", "desc": "description"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: dict[str, list[str]] = {value: [] for value in self.TARGETS.values()}
        self.fields: dict[str, list[str]] = {}
        self._active: str | None = None
        self._depth = 0
        self._row_depth = 0
        self._cell_depth = 0
        self._cell_role: str | None = None
        self._row_label: list[str] = []
        self._row_value: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "tr" and self._row_depth == 0:
            self._row_depth = 1
            self._row_label = []
            self._row_value = []
        elif self._row_depth and tag not in {"br", "img", "input", "link", "meta", "hr"}:
            self._row_depth += 1
        if self._row_depth and tag == "td":
            if "field-title" in classes:
                self._cell_role = "label"
                self._cell_depth = 1
            elif classes.intersection({"field-value", "field-vlaue"}):
                self._cell_role = "value"
                self._cell_depth = 1
        elif self._cell_role is not None and tag not in {"br", "img", "input", "link", "meta", "hr"}:
            self._cell_depth += 1
        if self._cell_role is not None and tag in {"br", "p", "pre", "li", "code"}:
            self._current_cell().append("\n")

        if self._active is None and tag == "div":
            for class_name, section in self.TARGETS.items():
                if class_name in classes:
                    self._active = section
                    self._depth = 1
                    return
        elif self._active is not None and tag not in {"br", "img", "input", "link", "meta", "hr"}:
            self._depth += 1
        if self._active is not None and tag in {"br", "p", "pre", "li"}:
            self.sections[self._active].append("\n")

    def handle_data(self, data: str) -> None:
        if self._cell_role is not None:
            self._current_cell().append(data)
        if self._active is not None:
            self.sections[self._active].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._cell_role is not None:
            if tag in {"p", "pre", "li", "code"}:
                self._current_cell().append("\n")
            if tag not in {"br", "img", "input", "link", "meta", "hr"}:
                self._cell_depth -= 1
            if self._cell_depth <= 0:
                self._cell_role = None
                self._cell_depth = 0
        if self._row_depth:
            if tag not in {"br", "img", "input", "link", "meta", "hr"}:
                self._row_depth -= 1
            if self._row_depth <= 0:
                label = normalize_multiline("".join(self._row_label))
                if label:
                    self.fields[label] = list(self._row_value)
                self._row_depth = 0

        if self._active is None:
            return
        if tag in {"p", "pre", "li"}:
            self.sections[self._active].append("\n")
        if tag not in {"br", "img", "input", "link", "meta", "hr"}:
            self._depth -= 1
        if self._depth <= 0:
            self._active = None
            self._depth = 0

    def _current_cell(self) -> list[str]:
        return self._row_label if self._cell_role == "label" else self._row_value


def normalize_multiline(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.replace("\r\n", "\n").split("\n")]
    result: list[str] = []
    for line in lines:
        if line or (result and result[-1]):
            result.append(line)
    return "\n".join(result).strip()


def canonicalize_url(url: str, base_url: str = DEFAULT_BASE_URL) -> str:
    parsed = urlparse(urljoin(base_url, url))
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_index(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("documents"), list):
        raise ValueError(f"Unsupported XSHelp index format: {path}")
    return data
