#!/usr/bin/env python3
"""Validate VERSION and CHANGELOG.md before creating a release."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>[^]]+)] - (?P<release_date>\d{4}-\d{2}-\d{2})$"
)
MAX_VERSION_LENGTH = 128


class ReleaseMetadataError(ValueError):
    """Raised when release metadata is missing or inconsistent."""


@dataclass(frozen=True)
class ReleaseMetadata:
    status: str
    message: str
    version: str
    release_count: int
    latest_release_date: str
    changelog_versions: list[str]


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ReleaseMetadataError(f"Missing required file: {path.name}") from exc
    except UnicodeError as exc:
        raise ReleaseMetadataError(f"Cannot read {path.name} as UTF-8: {exc}") from exc
    except OSError as exc:
        raise ReleaseMetadataError(f"Cannot read {path.name}: {exc}") from exc


def _load_version(root: Path) -> str:
    raw = _read_utf8(root / "VERSION")
    lines = raw.splitlines()
    if len(lines) != 1 or not lines[0]:
        raise ReleaseMetadataError("VERSION must contain exactly one non-empty line")

    version = lines[0]
    if version != version.strip():
        raise ReleaseMetadataError("VERSION must not contain surrounding whitespace")
    if len(version) > MAX_VERSION_LENGTH:
        raise ReleaseMetadataError(
            f"VERSION exceeds the {MAX_VERSION_LENGTH}-character safety limit"
        )
    if version.startswith("v"):
        raise ReleaseMetadataError("VERSION must not include the tag prefix 'v'")
    if not SEMVER_PATTERN.fullmatch(version):
        raise ReleaseMetadataError(f"VERSION is not valid Semantic Versioning: {version}")
    return version


def _load_changelog(root: Path, current_version: str) -> tuple[list[str], list[date]]:
    text = _read_utf8(root / "CHANGELOG.md")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    if not headings:
        raise ReleaseMetadataError("CHANGELOG.md has no level-two release headings")

    unreleased_count = sum(heading == "## [Unreleased]" for heading in headings)
    if unreleased_count != 1:
        raise ReleaseMetadataError(
            "CHANGELOG.md must contain exactly one '## [Unreleased]' heading"
        )
    if headings[0] != "## [Unreleased]":
        raise ReleaseMetadataError("'## [Unreleased]' must be the first level-two heading")

    versions: list[str] = []
    release_dates: list[date] = []
    for heading in headings[1:]:
        match = RELEASE_HEADING_PATTERN.fullmatch(heading)
        if not match:
            raise ReleaseMetadataError(f"Invalid CHANGELOG.md release heading: {heading}")

        version = match.group("version")
        if not SEMVER_PATTERN.fullmatch(version):
            raise ReleaseMetadataError(
                f"CHANGELOG.md contains invalid Semantic Versioning: {version}"
            )
        if version in versions:
            raise ReleaseMetadataError(
                f"CHANGELOG.md contains duplicate release version: {version}"
            )

        release_date_text = match.group("release_date")
        try:
            release_date = date.fromisoformat(release_date_text)
        except ValueError as exc:
            raise ReleaseMetadataError(
                f"CHANGELOG.md contains invalid release date: {release_date_text}"
            ) from exc

        versions.append(version)
        release_dates.append(release_date)

    if not versions:
        raise ReleaseMetadataError("CHANGELOG.md must contain at least one released version")
    if versions[0] != current_version:
        raise ReleaseMetadataError(
            "VERSION must match the first released CHANGELOG.md entry "
            f"({current_version!r} != {versions[0]!r})"
        )
    if any(older > newer for newer, older in zip(release_dates, release_dates[1:])):
        raise ReleaseMetadataError(
            "CHANGELOG.md release dates must be in descending order"
        )

    return versions, release_dates


def load_release_metadata(root: Path | str) -> ReleaseMetadata:
    """Read and validate release metadata rooted at *root*."""

    root_path = Path(root).resolve()
    version = _load_version(root_path)
    versions, release_dates = _load_changelog(root_path, version)
    return ReleaseMetadata(
        status="success",
        message="Release metadata is consistent",
        version=version,
        release_count=len(versions),
        latest_release_date=release_dates[0].isoformat(),
        changelog_versions=versions,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate VERSION and CHANGELOG.md release metadata."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the parent of this script directory).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = _build_parser().parse_args(argv)
    try:
        result = asdict(load_release_metadata(args.root))
        exit_code = 0
    except Exception as exc:  # CLI boundary: always preserve the single-JSON contract.
        result = {
            "status": "automation_error",
            "message": f"Release metadata validation failed: {type(exc).__name__}: {exc}",
        }
        exit_code = 3

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
