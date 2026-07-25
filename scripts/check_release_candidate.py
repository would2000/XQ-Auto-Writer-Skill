#!/usr/bin/env python3
"""Validate the frozen release-candidate interface without changing the repository."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_CONTRACT = Path("release/rc-interface-v2.json")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("contract_root_must_be_object")
    return value


def _literal_constants(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value_node = node.value
        if value_node is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    pass
    return result


def _cli_options(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    options: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        for argument in node.args:
            if (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and argument.value.startswith("--")
            ):
                options.add(argument.value)
    return sorted(options)


def _semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid_semver:{value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def validate_release_candidate(root: Path, contract_path: Path) -> dict[str, Any]:
    root = root.resolve()
    resolved_contract = (
        contract_path.resolve()
        if contract_path.is_absolute()
        else (root / contract_path).resolve()
    )
    errors: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    try:
        contract = _load_json(resolved_contract)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "automation_error",
            "ready": False,
            "root": str(root),
            "contract": str(resolved_contract),
            "errors": [{"code": "contract_invalid", "detail": str(exc)}],
        }

    contract_version = str(contract.get("contract_version", ""))
    if contract.get("schema_version") != 1 or contract_version not in {"1", "2"}:
        errors.append({"code": "unsupported_contract_version"})

    version_path = root / "VERSION"
    try:
        repository_version = version_path.read_text(encoding="utf-8").strip()
        stable_version = str(contract["current_stable_version"])
        target_version = str(contract["target_release_version"])
        stable_semver = _semver(stable_version)
        target_semver = _semver(target_version)
        if contract_version == "1":
            transition_ok = (
                target_semver > stable_semver
                and target_semver[:2] == (stable_semver[0], stable_semver[1] + 1)
                and target_semver[2] == 0
            )
        else:
            transition_ok = (
                target_semver == (stable_semver[0] + 1, 0, 0)
                and contract.get("release_transition") == "major"
            )
        if repository_version == stable_version:
            candidate_phase = "development"
            phase_ok = True
        elif repository_version == target_version:
            candidate_phase = "release_preparation"
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            phase_ok = re.search(
                rf"(?m)^## \[{re.escape(target_version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                changelog,
            ) is not None
        else:
            candidate_phase = "invalid"
            phase_ok = False
        version_ok = transition_ok and phase_ok
    except (OSError, KeyError, ValueError) as exc:
        version_ok = False
        repository_version = None
        candidate_phase = "invalid"
        errors.append({"code": "version_contract_invalid", "detail": str(exc)})
    if not version_ok and not any(item["code"] == "version_contract_invalid" for item in errors):
        errors.append(
            {
                "code": "version_contract_mismatch",
                "repository_version": repository_version,
                "stable_version": contract.get("current_stable_version"),
                "target_version": contract.get("target_release_version"),
            }
        )
    checks["version_transition"] = version_ok

    missing_documents = [
        relative
        for relative in contract.get("required_documents", [])
        if not (root / relative).is_file()
    ]
    checks["required_documents"] = not missing_documents
    if missing_documents:
        errors.append({"code": "required_documents_missing", "paths": missing_documents})

    script_dir = root / ".agents/skills/xq-xscript-compiler/scripts"
    missing_entries = [
        name
        for name in contract.get("required_entry_points", [])
        if not (script_dir / name).is_file()
    ]
    checks["required_entry_points"] = not missing_entries
    if missing_entries:
        errors.append({"code": "required_entry_points_missing", "names": missing_entries})

    constant_mismatches: list[dict[str, Any]] = []
    for relative, expected_constants in contract.get("schema_constants", {}).items():
        path = root / relative
        if not path.is_file():
            constant_mismatches.append({"path": relative, "reason": "missing"})
            continue
        actual_constants = _literal_constants(path)
        for name, expected in expected_constants.items():
            actual = actual_constants.get(name, {"missing": True})
            if actual != expected:
                constant_mismatches.append(
                    {"path": relative, "name": name, "expected": expected, "actual": actual}
                )
    checks["schema_constants"] = not constant_mismatches
    if constant_mismatches:
        errors.append({"code": "schema_constant_mismatch", "items": constant_mismatches})

    cli_mismatches: list[dict[str, Any]] = []
    for relative, expected_options in contract.get("public_cli_options", {}).items():
        path = root / relative
        if not path.is_file():
            cli_mismatches.append({"path": relative, "reason": "missing"})
            continue
        actual_options = _cli_options(path)
        expected_sorted = sorted(expected_options)
        if actual_options != expected_sorted:
            cli_mismatches.append(
                {
                    "path": relative,
                    "added": sorted(set(actual_options) - set(expected_sorted)),
                    "removed": sorted(set(expected_sorted) - set(actual_options)),
                }
            )
    checks["public_cli_options"] = not cli_mismatches
    if cli_mismatches:
        errors.append({"code": "public_cli_mismatch", "items": cli_mismatches})

    workflow_path = root / ".github/workflows/ci.yml"
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
        ci_tokens = [
            "python scripts/check_release_candidate.py",
            "python scripts/rehearse_upgrade_rollback.py",
            "fetch-depth: 0",
        ]
        missing_ci_tokens = [token for token in ci_tokens if token not in workflow]
    except OSError as exc:
        missing_ci_tokens = ["ci.yml"]
        errors.append({"code": "ci_workflow_unreadable", "detail": str(exc)})
    checks["ci_release_candidate_gates"] = not missing_ci_tokens
    if missing_ci_tokens:
        errors.append({"code": "ci_release_candidate_gates_missing", "tokens": missing_ci_tokens})

    return {
        "status": "success" if not errors else "automation_error",
        "ready": not errors,
        "root": str(root),
        "contract": str(resolved_contract),
        "current_stable_version": contract.get("current_stable_version"),
        "target_release_version": contract.get("target_release_version"),
        "candidate_phase": candidate_phase,
        "upgrade_source_tag": contract.get("upgrade_source_tag"),
        "checks": checks,
        "errors": errors,
        "xq_ui_verified": False,
        "xq_ui_note": "offline contract validation does not prove XQ UI behavior",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = validate_release_candidate(args.root, args.contract)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
