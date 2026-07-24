from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "check_release_candidate.py"
CONTRACT_PATH = PROJECT_ROOT / "release" / "rc-interface-v1.json"
SPEC = importlib.util.spec_from_file_location("check_release_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
rc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rc)


class ReleaseCandidateTests(unittest.TestCase):
    def test_repository_matches_frozen_contract(self) -> None:
        result = rc.validate_release_candidate(PROJECT_ROOT, CONTRACT_PATH)
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["xq_ui_verified"])

    def _write_contract(self, mutate) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        mutate(contract)
        path = Path(temporary.name) / "contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        return path

    def test_schema_constant_change_is_rejected(self) -> None:
        def mutate(contract) -> None:
            constants = contract["schema_constants"][
                ".agents/skills/xq-xscript-compiler/scripts/xq_backtest.py"
            ]
            constants["RECOVERY_SCHEMA_VERSION"] = 999

        result = rc.validate_release_candidate(PROJECT_ROOT, self._write_contract(mutate))
        self.assertFalse(result["ready"])
        self.assertIn("schema_constant_mismatch", [item["code"] for item in result["errors"]])

    def test_public_cli_change_is_rejected(self) -> None:
        def mutate(contract) -> None:
            contract["public_cli_options"][
                ".agents/skills/xq-xscript-compiler/scripts/xq_function_regression.py"
            ].append("--unreviewed-option")

        result = rc.validate_release_candidate(PROJECT_ROOT, self._write_contract(mutate))
        self.assertFalse(result["ready"])
        self.assertIn("public_cli_mismatch", [item["code"] for item in result["errors"]])

    def test_target_must_be_next_minor_without_changing_version(self) -> None:
        def mutate(contract) -> None:
            contract["target_release_version"] = "0.2.1"

        result = rc.validate_release_candidate(PROJECT_ROOT, self._write_contract(mutate))
        self.assertFalse(result["ready"])
        self.assertIn("version_contract_mismatch", [item["code"] for item in result["errors"]])


if __name__ == "__main__":
    unittest.main()
