#!/usr/bin/env python3
"""Validate repository files that must remain safe in a public checkout."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote


TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".xs"}
TEXT_NAMES = {
    ".gitattributes",
    ".gitignore",
    ".gitmodules",
    "LICENSE",
    "VERSION",
}
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
LOCAL_PATH_PATTERN = re.compile(
    r"\b[A-Za-z]:[\\/](?:Users|Projects)[\\/]", re.IGNORECASE
)
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*]\((?P<target>[^)\n]+)\)")
FRONTMATTER_PATTERN = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_SKILL_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


class RepositoryHygieneError(RuntimeError):
    """Raised when the checker itself cannot inspect the repository."""


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    message: str


@dataclass(frozen=True)
class HygieneReport:
    status: str
    message: str
    tracked_files: int
    text_files: int
    markdown_files: int
    skill_files: int
    finding_count: int
    findings: list[Finding]


def _git_tracked_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryHygieneError(f"Cannot list tracked files: {exc}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RepositoryHygieneError(
            f"git ls-files failed with exit code {completed.returncode}: {stderr}"
        )
    try:
        output = completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RepositoryHygieneError("Tracked file names are not valid UTF-8") from exc
    return sorted(path for path in output.split("\0") if path)


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def _read_utf8(path: Path, relative_path: str, findings: list[Finding]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        findings.append(Finding("utf8", relative_path, f"Cannot read as UTF-8: {exc}"))
        return None


def _forbidden_path_reason(relative_path: str) -> str | None:
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    name = parts[-1]
    if "__pycache__" in parts or name.endswith((".pyc", ".pyo", ".pyd")):
        return "Python cache or compiled artifact must not be tracked"
    if normalized == ".xq-auto-writer" or normalized.startswith(".xq-auto-writer/"):
        return "Machine-specific XQ state must not be tracked"
    if normalized.startswith("generated/") and normalized != "generated/.gitkeep":
        return "Generated user XScript must not be tracked"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "Environment or secret override must not be tracked"
    return None


def _markdown_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def _check_markdown(
    root: Path, path: Path, relative_path: str, text: str, findings: list[Finding]
) -> None:
    fence_count = len(re.findall(r"(?m)^```", text))
    if fence_count % 2:
        findings.append(
            Finding("markdown_fence", relative_path, "Unbalanced triple-backtick fence")
        )

    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        target = _markdown_target(match.group("target"))
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_text = unquote(target.split("#", 1)[0])
        if not path_text:
            continue
        resolved = (path.parent / path_text).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            findings.append(
                Finding("markdown_link", relative_path, f"Link escapes repository: {target}")
            )
            continue
        if not resolved.exists():
            findings.append(
                Finding("markdown_link", relative_path, f"Missing local target: {target}")
            )


def _unquote_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
        return parsed if isinstance(parsed, str) else value
    return value


def _check_skill(relative_path: str, text: str, findings: list[Finding]) -> None:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        findings.append(
            Finding("skill_frontmatter", relative_path, "Missing or invalid YAML frontmatter")
        )
        return

    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        if not line or line.isspace() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            continue
        key_match = re.match(r"^(?P<key>[A-Za-z0-9_-]+):(?P<value>.*)$", line)
        if not key_match:
            findings.append(
                Finding("skill_frontmatter", relative_path, f"Invalid top-level line: {line}")
            )
            continue
        key = key_match.group("key")
        if key in values:
            findings.append(
                Finding("skill_frontmatter", relative_path, f"Duplicate key: {key}")
            )
        values[key] = _unquote_scalar(key_match.group("value"))

    unexpected = sorted(set(values) - ALLOWED_SKILL_KEYS)
    if unexpected:
        findings.append(
            Finding(
                "skill_frontmatter",
                relative_path,
                f"Unexpected top-level keys: {', '.join(unexpected)}",
            )
        )
    name = values.get("name", "").strip()
    description = values.get("description", "").strip()
    if not name:
        findings.append(Finding("skill_frontmatter", relative_path, "Missing name"))
    elif len(name) > 64 or not SKILL_NAME_PATTERN.fullmatch(name):
        findings.append(
            Finding("skill_frontmatter", relative_path, f"Invalid skill name: {name}")
        )
    if not description:
        findings.append(Finding("skill_frontmatter", relative_path, "Missing description"))
    elif len(description) > 1024 or "<" in description or ">" in description:
        findings.append(
            Finding("skill_frontmatter", relative_path, "Invalid skill description")
        )


def inspect_repository(root: Path | str) -> HygieneReport:
    root_path = Path(root).resolve()
    tracked_files = _git_tracked_files(root_path)
    findings: list[Finding] = []
    text_count = 0
    markdown_count = 0
    skill_count = 0

    for relative_path in tracked_files:
        forbidden_reason = _forbidden_path_reason(relative_path)
        if forbidden_reason:
            findings.append(Finding("forbidden_path", relative_path, forbidden_reason))

        path = root_path / relative_path
        if not path.is_file() or not _is_text_file(path):
            continue
        text_count += 1
        text = _read_utf8(path, relative_path, findings)
        if text is None:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.endswith((" ", "\t")):
                findings.append(
                    Finding(
                        "trailing_whitespace",
                        relative_path,
                        f"Trailing whitespace on line {line_number}",
                    )
                )
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(
                    Finding("secret", relative_path, "Potential credential or private key")
                )
                break
        if LOCAL_PATH_PATTERN.search(text):
            findings.append(
                Finding("local_path", relative_path, "Machine-specific absolute path")
            )

        if path.suffix.lower() == ".md":
            markdown_count += 1
            _check_markdown(root_path, path, relative_path, text, findings)
        if relative_path.replace("\\", "/").endswith("/SKILL.md"):
            skill_count += 1
            _check_skill(relative_path, text, findings)

    status = "success" if not findings else "automation_error"
    message = (
        "Repository hygiene checks passed"
        if not findings
        else f"Repository hygiene checks found {len(findings)} issue(s)"
    )
    return HygieneReport(
        status=status,
        message=message,
        tracked_files=len(tracked_files),
        text_files=text_count,
        markdown_files=markdown_count,
        skill_files=skill_count,
        finding_count=len(findings),
        findings=findings,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate public repository hygiene.")
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
        report = inspect_repository(args.root)
        payload = asdict(report)
        exit_code = 0 if report.status == "success" else 3
    except Exception as exc:  # CLI boundary preserves one JSON object and exit code 3.
        payload = {
            "status": "automation_error",
            "message": f"Repository hygiene validation failed: {type(exc).__name__}: {exc}",
            "finding_count": 0,
            "findings": [],
        }
        exit_code = 3
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
