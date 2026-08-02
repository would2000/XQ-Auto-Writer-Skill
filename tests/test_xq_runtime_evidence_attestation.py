from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import xq_runtime_evidence_attestation as attestation  # noqa: E402
import xq_runtime_evidence_suite as suite  # noqa: E402


CASE_FILE = (
    PROJECT_ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "references"
    / "runtime-evidence-cases-v1.json"
)
PUBLIC_ATTESTATION = PROJECT_ROOT / "release" / "xq-runtime-evidence-v1.json"


class RuntimeEvidenceAttestationTests(unittest.TestCase):
    def completed_manifest(self):
        _raw, cases, digest = suite.load_cases(CASE_FILE)
        manifest = suite._new_manifest(Path("private"), digest, cases)
        for case in cases:
            runtime = {
                "status": "success", "progress_seen": True, "new_report_count": 1,
                "marker_matched": True, "report_decision": "completed",
                "report_cleanup_complete": True, "recovery_checkpoint_retained": False,
                "settings_evidence": {
                    "active_script": {
                        "script_name": case.caller_name, "script_type": case.caller_type,
                        "location": "自訂/CODEX/",
                    }
                },
                "private_product": "2330", "report_window_handle": 123,
                "rows": [{"private": "value"}],
            }
            if case.caller_type == "indicator":
                runtime = {
                    "status": "success", "script_name": case.caller_name,
                    "row_count": 5, "recovery": {"complete": True},
                    "rows": [{"private": "value"}],
                }
            manifest["cases"][case.case_id] = {
                "status": "completed",
                "result": {
                    "normalized": {
                        "function_compile_status": "success", "caller_compile_status": "success",
                        "function_source_sha256": attestation.source_sha256(case.function_source),
                        "caller_source_sha256": attestation.source_sha256(case.caller_source),
                        "runtime_status": "success", "success_count": 1,
                        "failure_count": 0, "total_trades": 1, "row_count": 5,
                        "report_cleanup_complete": True,
                        "recovery_checkpoint_retained": False,
                    },
                    "runtime": runtime,
                    "post_recovery": {"decision": "safe_to_start", "checkpoint_present": False},
                },
            }
        return manifest, cases, digest

    def test_public_attestation_excludes_private_runtime_fields(self):
        manifest, cases, digest = self.completed_manifest()
        payload = attestation.build_attestation(manifest, cases, digest, "3.19.03")
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertFalse(payload["contains_private_data"])
        self.assertNotIn("private_product", serialized)
        self.assertNotIn("report_window_handle", serialized)
        self.assertNotIn('"rows"', serialized)
        self.assertNotIn("2330", serialized)
        self.assertEqual(len(payload["cases"]), 4)

    def test_tracked_attestation_matches_current_cases_and_fixture_hashes(self):
        _raw, cases, digest = suite.load_cases(CASE_FILE)
        payload = json.loads(PUBLIC_ATTESTATION.read_text(encoding="utf-8"))
        self.assertEqual(payload["suite_digest"], digest)
        public_cases = {item["case_id"]: item for item in payload["cases"]}
        self.assertEqual(set(public_cases), {case.case_id for case in cases})
        for case in cases:
            compile_evidence = public_cases[case.case_id]["compile"]
            self.assertEqual(
                compile_evidence["function_source_sha256"],
                attestation.source_sha256(case.function_source),
            )
            self.assertEqual(
                compile_evidence["caller_source_sha256"],
                attestation.source_sha256(case.caller_source),
            )

    def test_incomplete_or_changed_source_evidence_is_rejected(self):
        manifest, cases, digest = self.completed_manifest()
        manifest["cases"][cases[0].case_id]["status"] = "failed"
        with self.assertRaisesRegex(attestation.AttestationError, "not completed"):
            attestation.build_attestation(manifest, cases, digest, "3.19.03")
        manifest, cases, digest = self.completed_manifest()
        manifest["cases"][cases[0].case_id]["result"]["normalized"]["function_source_sha256"] = "0" * 64
        with self.assertRaisesRegex(attestation.AttestationError, "source changed"):
            attestation.build_attestation(manifest, cases, digest, "3.19.03")

    def test_write_requires_confirmation_and_refuses_overwrite(self):
        manifest, _cases, _digest = self.completed_manifest()
        with tempfile.TemporaryDirectory(dir=attestation.PRIVATE_ROOT) as raw_private:
            manifest_path = Path(raw_private) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with tempfile.TemporaryDirectory(dir=attestation.RELEASE_ROOT) as raw_release:
                output = Path(raw_release) / "attestation.json"
                args = argparse.Namespace(
                    manifest=manifest_path, cases=CASE_FILE, xq_version="3.19.03",
                    output=output, confirm_public_attestation=False, dry_run=False,
                )
                with self.assertRaisesRegex(attestation.AttestationError, "confirm"):
                    attestation.execute(args)
                args.confirm_public_attestation = True
                attestation.execute(args)
                with self.assertRaisesRegex(attestation.AttestationError, "overwrite"):
                    attestation.execute(args)


if __name__ == "__main__":
    unittest.main()
