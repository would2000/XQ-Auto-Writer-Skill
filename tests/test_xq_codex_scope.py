import sys
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_codex_scope as scope  # noqa: E402


class XQCodexScopeTests(unittest.TestCase):
    def contract_config(self) -> dict:
        return {
            "codex_scope": {
                "folder_name": "CODEX",
                "action_settle_seconds": 2,
                "state_timeout_seconds": 15,
                "script_types": {
                    "function": {
                        "expected_location": "自訂/CODEX/",
                        "category_selector": {
                            "title": "函數",
                            "control_type": "Button",
                        },
                        "folder_selector": {
                            "title": "CODEX",
                            "control_type": "TreeItem",
                        },
                        "location_readback_selector": {
                            "title": "自訂/CODEX/",
                            "control_type": "Text",
                        },
                    }
                },
            }
        }

    def test_missing_scope_calibration_fails_before_xq(self) -> None:
        with self.assertRaisesRegex(scope.CodexScopeError, "refusing to touch XQ"):
            scope.load_script_scope_contract({}, "function")

    def test_scope_requires_exact_folder_location_and_slow_wait(self) -> None:
        contract = scope.load_script_scope_contract(self.contract_config(), "function")
        self.assertEqual(contract.folder_name, "CODEX")
        self.assertEqual(contract.expected_location, "自訂/CODEX/")
        self.assertGreaterEqual(contract.action_settle_seconds, 1)
        bad = self.contract_config()
        bad["codex_scope"]["script_types"]["function"]["expected_location"] = "自訂/"
        with self.assertRaisesRegex(scope.CodexScopeError, "expected_location"):
            scope.load_script_scope_contract(bad, "function")

    def test_private_root_location_is_never_authorized_for_cleanup(self) -> None:
        record = {
            "created": True,
            "name": "CodexDoc",
            "script_type": "function",
            "type_readback": "function",
            "storage_location": "自訂/CODEX/",
        }
        self.assertTrue(scope.authorize_manifest_document(
            record,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/CODEX/",
        ))
        self.assertFalse(scope.authorize_manifest_document(
            record,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/",
        ))
        changed = dict(record, storage_location="自訂/")
        self.assertFalse(scope.authorize_manifest_document(
            changed,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/CODEX/",
        ))


if __name__ == "__main__":
    unittest.main()
