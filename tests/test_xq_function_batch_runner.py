import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "xq-xscript-compiler" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import xq_function_batch_runner as batch  # noqa: E402


class XQFunctionBatchRunnerTests(unittest.TestCase):
    def pair_payload(self, pair_id: str, digest: str = "d" * 64) -> dict:
        rows = []
        for role in ("control", "shortage"):
            case_id = f"{pair_id}-{role}"
            rows.append({
                "case_id": case_id,
                "status": "completed",
                "stage": "result_captured",
                "attempts": 1,
                "case": {"pair_id": pair_id, "role": role},
                "compile": {},
                "result": {},
                "late_recovery": None,
            })
        cleanup = {}
        for index in range(4):
            cleanup[f"{pair_id}-{index}"] = {
                "status": "completed",
                "stage": "completed",
                "last_evidence": {"absence_verified": True},
            }
        return {
            "schema_version": 1,
            "suite_id": "suite",
            "case_digest": digest,
            "runner_contract_version": batch.RUNNER_CONTRACT_VERSION,
            "selected_pair_ids": [pair_id],
            "counts": {"total": 2, "completed": 2, "failed": 0, "pending": 0},
            "active_case_id": None,
            "active_cleanup_document_id": None,
            "cleanup_states": cleanup,
            "windows_wait_incidents": [],
            "cases": rows,
            "last_error": None,
        }

    def test_aggregate_accepts_one_complete_result_per_pair(self) -> None:
        digest = "d" * 64
        payload = batch.aggregate_pair_results(
            suite_id="suite",
            case_digest=digest,
            pair_ids=["pair-a", "pair-b"],
            pair_payloads={
                "pair-a": self.pair_payload("pair-a", digest),
                "pair-b": self.pair_payload("pair-b", digest),
            },
        )
        self.assertEqual(payload["counts"]["completed"], 4)
        self.assertEqual(payload["selected_pair_ids"], ["pair-a", "pair-b"])
        self.assertEqual(len({row["case_id"] for row in payload["cases"]}), 4)

    def test_aggregate_rejects_missing_pair_and_mixed_digest(self) -> None:
        digest = "d" * 64
        with self.assertRaisesRegex(batch.BatchError, "pair set mismatch"):
            batch.aggregate_pair_results(
                suite_id="suite",
                case_digest=digest,
                pair_ids=["pair-a", "pair-b"],
                pair_payloads={"pair-a": self.pair_payload("pair-a", digest)},
            )
        changed = self.pair_payload("pair-a", "e" * 64)
        with self.assertRaisesRegex(batch.BatchError, "case digest mismatch"):
            batch.validate_pair_result(
                changed, suite_id="suite", case_digest=digest, pair_id="pair-a",
            )

    def test_duplicate_case_and_incomplete_cleanup_are_rejected(self) -> None:
        payload = self.pair_payload("pair-a")
        payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]
        with self.assertRaisesRegex(batch.BatchError, "duplicate"):
            batch.validate_pair_result(
                payload, suite_id="suite", case_digest="d" * 64, pair_id="pair-a",
            )
        payload = self.pair_payload("pair-a")
        next(iter(payload["cleanup_states"].values()))["stage"] = "delete_confirmation_verified"
        with self.assertRaisesRegex(batch.BatchError, "cleanup evidence"):
            batch.validate_pair_result(
                payload, suite_id="suite", case_digest="d" * 64, pair_id="pair-a",
            )

    def test_windows_wait_incident_stops_pair_certification(self) -> None:
        payload = self.pair_payload("pair-a")
        payload["windows_wait_incidents"] = [{"incident_kind": "dialog_timeout"}]
        with self.assertRaisesRegex(batch.BatchError, "Windows wait incident"):
            batch.validate_pair_result(
                payload, suite_id="suite", case_digest="d" * 64, pair_id="pair-a",
            )

    def test_resume_skips_completed_prefix_and_rejects_changed_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "pair-a.json"
            result.write_text(json.dumps(self.pair_payload("pair-a")), encoding="utf-8")
            states = batch.initialize_pair_states(["pair-a", "pair-b"])
            states["pair-a"].update({
                "status": "completed",
                "result_json": str(result),
                "result_sha256": batch.file_sha256(result),
            })
            manifest = {
                "schema_version": batch.BATCH_SCHEMA_VERSION,
                "batch_contract_version": batch.BATCH_CONTRACT_VERSION,
                "batch_id": "batch",
                "suite_id": "suite",
                "case_digest": "d" * 64,
                "case_schema_version": 2,
                "runner_contract_version": batch.RUNNER_CONTRACT_VERSION,
                "xq_version": "3.19.03",
                "required_pair_ids": ["pair-a", "pair-b"],
                "cooldown_seconds": 15.0,
                "pacing": {},
                "pair_states": states,
                "output_json": str(root / "aggregate.json"),
                "output_junit": str(root / "aggregate.xml"),
                "created_at_utc": "2026-07-24T00:00:00+00:00",
                "last_completed_at_utc": "2026-07-24T00:00:00+00:00",
                "last_error": None,
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = batch.validate_resume_manifest(
                path,
                suite_id="suite",
                case_digest="d" * 64,
                xq_version="3.19.03",
                pair_ids=["pair-a", "pair-b"],
            )
            self.assertEqual(batch.next_pair_id(loaded), "pair-b")
            result.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(batch.BatchError, "digest changed"):
                batch.validate_resume_manifest(
                    path,
                    suite_id="suite",
                    case_digest="d" * 64,
                    xq_version="3.19.03",
                    pair_ids=["pair-a", "pair-b"],
                )

    def test_pair_contract_version_must_not_be_mixed(self) -> None:
        payload = self.pair_payload("pair-a")
        payload["runner_contract_version"] = "6"
        with self.assertRaisesRegex(batch.BatchError, "runner contract mismatch"):
            batch.validate_pair_result(
                payload, suite_id="suite", case_digest="d" * 64, pair_id="pair-a",
            )

    def test_interrupted_child_result_is_discoverable_without_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory)
            config = private_root / "xq-ui.json"
            config.write_text("{}", encoding="utf-8")
            results = private_root / "function-boundary-results"
            results.mkdir()
            run_id = "12345678-1234-4234-9234-123456789abc"
            expected = results / f"suite-{run_id}.json"
            expected.write_text("{}", encoding="utf-8")
            self.assertEqual(
                batch.discover_completed_child_result(config, "suite", run_id),
                expected.resolve(),
            )


if __name__ == "__main__":
    unittest.main()
