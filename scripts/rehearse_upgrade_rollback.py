#!/usr/bin/env python3
"""Rehearse a Skill upgrade and byte-identical rollback in an isolated temp tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


SKILL_RELATIVE = Path(".agents/skills/xq-xscript-compiler")
CORE_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/xq_compile.py",
)
REQUIRED_SKILL_FILES = CORE_SKILL_FILES + (
    "scripts/xq_backtest.py",
    "references/function-guide.md",
    "references/autotrade-window-guide.md",
)


def _validate_tree(root: Path, required_files: tuple[str, ...] = CORE_SKILL_FILES) -> None:
    if not root.is_dir():
        raise ValueError(f"skill_tree_missing:{root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink_not_allowed:{path.relative_to(root).as_posix()}")
    missing = [relative for relative in required_files if not (root / relative).is_file()]
    if missing:
        raise ValueError(f"required_skill_files_missing:{','.join(missing)}")
    first_line = (root / "SKILL.md").read_text(encoding="utf-8").splitlines()[:1]
    if first_line != ["---"]:
        raise ValueError("skill_frontmatter_missing")


def _tree_digest(root: Path) -> str:
    _validate_tree(root)
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _safe_extract_tar(data: bytes, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or ".." in pure.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe_archive_member:{member.name}")
            target = (destination / Path(*pure.parts)).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError(f"archive_member_outside_destination:{member.name}")
        archive.extractall(destination, members=members)


def _archive_previous_skill(root: Path, tag: str, destination: Path) -> Path:
    command = ["git", "-C", str(root), "archive", "--format=tar", tag, SKILL_RELATIVE.as_posix()]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"upgrade_source_unavailable:{tag}:{detail}")
    _safe_extract_tar(completed.stdout, destination)
    previous = destination / SKILL_RELATIVE
    _validate_tree(previous)
    return previous


def rehearse_from_directories(previous: Path, current: Path, workspace: Path) -> dict[str, Any]:
    _validate_tree(previous, CORE_SKILL_FILES)
    _validate_tree(current, REQUIRED_SKILL_FILES)
    workspace.mkdir(parents=True, exist_ok=False)
    previous_digest = _tree_digest(previous)
    current_digest = _tree_digest(current)
    installed = workspace / "installed-skill"
    backup = workspace / "rollback-backup"

    shutil.copytree(previous, installed)
    shutil.copytree(installed, backup)
    if _tree_digest(installed) != previous_digest or _tree_digest(backup) != previous_digest:
        raise ValueError("initial_backup_digest_mismatch")

    shutil.rmtree(installed)
    shutil.copytree(current, installed)
    _validate_tree(installed, REQUIRED_SKILL_FILES)
    installed_upgrade_digest = _tree_digest(installed)
    if installed_upgrade_digest != current_digest:
        raise ValueError("upgrade_digest_mismatch")

    shutil.rmtree(installed)
    shutil.copytree(backup, installed)
    restored_digest = _tree_digest(installed)
    if restored_digest != previous_digest:
        raise ValueError("rollback_digest_mismatch")

    return {
        "upgrade_verified": True,
        "rollback_verified": True,
        "previous_tree_sha256": previous_digest,
        "current_tree_sha256": current_digest,
        "restored_tree_sha256": restored_digest,
    }


def rehearse(root: Path, source_tag: str) -> dict[str, Any]:
    root = root.resolve()
    current = root / SKILL_RELATIVE
    with tempfile.TemporaryDirectory(prefix="xq-rc-rehearsal-") as temporary:
        workspace = Path(temporary)
        archive_root = workspace / "archive"
        archive_root.mkdir()
        previous = _archive_previous_skill(root, source_tag, archive_root)
        details = rehearse_from_directories(previous, current, workspace / "rehearsal")
    return {
        "status": "success",
        "ready": True,
        "root": str(root),
        "source_tag": source_tag,
        "skill_path": SKILL_RELATIVE.as_posix(),
        **details,
        "temporary_workspace_removed": True,
        "repository_modified": False,
        "xq_touched": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-tag", default="v1.0.0")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = rehearse(args.root, args.source_tag)
    except (OSError, ValueError, tarfile.TarError) as exc:
        result = {
            "status": "automation_error",
            "ready": False,
            "root": str(args.root.resolve()),
            "source_tag": args.source_tag,
            "error": str(exc),
            "repository_modified": False,
            "xq_touched": False,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
