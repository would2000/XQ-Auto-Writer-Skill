from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "release_maintenance.py"
SPEC = importlib.util.spec_from_file_location("release_maintenance", MODULE_PATH)
assert SPEC and SPEC.loader
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


class ReleaseMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / "maintenance.json"

    def test_enter_requires_confirmation_and_duplicate_is_rejected(self) -> None:
        refused = maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="0.2.0",
            target_version="0.3.0",
            confirmed=False,
        )
        self.assertEqual(refused["status"], "confirmation_required")
        self.assertFalse(self.state.exists())

        entered = maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="0.2.0",
            target_version="0.3.0",
            confirmed=True,
        )
        self.assertEqual(entered["mode"], "active")
        duplicate = maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="0.2.0",
            target_version="0.3.0",
            confirmed=True,
        )
        self.assertEqual(duplicate["error"], "maintenance_already_active")

    def test_leave_requires_matching_ready_evidence(self) -> None:
        maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="0.2.0",
            target_version="0.3.0",
            confirmed=True,
        )
        evidence = Path(self.temporary.name) / "rc.json"
        evidence.write_text(
            json.dumps(
                {
                    "status": "success",
                    "ready": True,
                    "current_stable_version": "0.2.0",
                    "target_release_version": "0.3.0",
                }
            ),
            encoding="utf-8",
        )
        result = maintenance.leave_maintenance(
            self.state, confirmed=True, rc_evidence=evidence
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["mode"], "inactive")
        self.assertFalse(self.state.exists())

    def test_not_ready_evidence_keeps_state(self) -> None:
        maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="0.2.0",
            target_version="0.3.0",
            confirmed=True,
        )
        evidence = Path(self.temporary.name) / "rc.json"
        evidence.write_text(
            json.dumps({"status": "automation_error", "ready": False}), encoding="utf-8"
        )
        result = maintenance.leave_maintenance(
            self.state, confirmed=True, rc_evidence=evidence
        )
        self.assertEqual(result["error"], "release_candidate_evidence_not_ready")
        self.assertTrue(self.state.exists())

    def test_leave_accepts_windows_powershell_utf8_bom_evidence(self) -> None:
        maintenance.enter_maintenance(
            self.state,
            reason="test",
            current_version="1.0.0",
            target_version="1.1.0",
            confirmed=True,
        )
        evidence = Path(self.temporary.name) / "rc-bom.json"
        evidence.write_text(
            json.dumps(
                {
                    "status": "success",
                    "ready": True,
                    "current_stable_version": "1.0.0",
                    "target_release_version": "1.1.0",
                }
            ),
            encoding="utf-8-sig",
        )
        result = maintenance.leave_maintenance(
            self.state, confirmed=True, rc_evidence=evidence
        )
        self.assertEqual(result["status"], "success")
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
