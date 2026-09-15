#!/usr/bin/env python3
"""Adversarial tests for privacy-safe append-only decision records."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import record_decision


class DecisionRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_obj.name)
        (self.root / "config").mkdir()
        shutil.copy(ROOT / "config" / "decision_policy.json", self.root / "config" / "decision_policy.json")
        self.policy = record_decision.load_decision_policy(self.root)

    def tearDown(self):
        self.tmp_obj.cleanup()

    def record(self, record_id: str = "D-STEP4-0001") -> dict:
        return {
            "record_version": "1.0",
            "record_id": record_id,
            "recorded_utc": "2026-09-15T10:30:00+10:00",
            "directive_id": "DIR-TEST",
            "actor_id": "systems-kernel-architect",
            "objective": "Choose a durable decision-record mechanism.",
            "constraints": [{"id": "C1", "text": "Standard library only.", "provenance": "current contract"}],
            "claims": [{"id": "CL1", "text": "Records are historical evidence.", "provenance": "ICM authority model"}],
            "evidence": [],
            "assumptions": [],
            "alternatives": [{"id": "A1", "option": "Append-only JSON files", "disposition": "SELECTED", "reason": "Inspectable and portable."}],
            "decision": "Store append-only privacy-safe decision summaries under archive/decisions.",
            "unknowns": [],
            "verification": [{"check": "schema", "status": "PASS"}],
            "links": [],
            "privacy_attestation": "NO_PRIVATE_CHAIN_OF_THOUGHT_OR_HIDDEN_SCRATCHPAD_STORED"
        }

    def test_valid_record_passes_without_semantic_privacy_overclaim(self):
        result = record_decision.validate_record(self.record(), self.policy)
        self.assertTrue(result["valid"])
        self.assertEqual(result["privacy_key_guard"], "PASSED")
        self.assertEqual(result["privacy_semantic_proof"], "NOT_CLAIMED")

    def test_nested_private_reasoning_key_fails_before_schema_noise(self):
        data = self.record()
        data["evidence"] = [{
            "id": "E1", "source": "audit", "availability": "AVAILABLE",
            "supports": ["CL1"], "scratchpad": "private"
        }]
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.validate_record(data, self.policy)
        self.assertIn("forbidden private-reasoning", str(ctx.exception))

    def test_wrong_privacy_attestation_fails(self):
        data = self.record()
        data["privacy_attestation"] = "TRUST_ME"
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_unknown_top_level_field_fails_closed(self):
        data = self.record()
        data["notes"] = "extra"
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.validate_record(data, self.policy)
        self.assertIn("unknown field", str(ctx.exception))

    def test_timestamp_requires_timezone(self):
        data = self.record()
        data["recorded_utc"] = "2026-09-15T10:30:00"
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.validate_record(data, self.policy)
        self.assertIn("UTC offset or Z", str(ctx.exception))

    def test_invalid_sha256_fails(self):
        data = self.record()
        data["evidence"] = [{
            "id": "E1", "source": "artifact", "availability": "AVAILABLE",
            "supports": ["CL1"], "sha256": "bad"
        }]
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_duplicate_item_ids_fail(self):
        data = self.record()
        data["claims"].append({"id": "CL1", "text": "duplicate", "provenance": "test"})
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.validate_record(data, self.policy)
        self.assertIn("duplicate id", str(ctx.exception))

    def test_invalid_alternative_disposition_fails(self):
        data = self.record()
        data["alternatives"][0]["disposition"] = "MAYBE"
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_invalid_verification_status_fails(self):
        data = self.record()
        data["verification"][0]["status"] = "GOOD"
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_invalid_link_kind_fails(self):
        data = self.record()
        data["links"] = [{"kind": "secret", "target": "x"}]
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_actor_path_traversal_is_rejected(self):
        data = self.record()
        data["actor_id"] = "../escape"
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_append_only_write_creates_expected_path(self):
        data = self.record()
        out = record_decision.write_record(data, self.root, self.policy)
        self.assertTrue(out.is_file())
        rel = out.relative_to(self.root).as_posix()
        self.assertEqual(rel, "archive/decisions/systems-kernel-architect/2026-09-15/D-STEP4-0001.json")

    def test_existing_record_cannot_be_overwritten(self):
        data = self.record()
        record_decision.write_record(data, self.root, self.policy)
        data["decision"] = "mutated"
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.write_record(data, self.root, self.policy)
        self.assertIn("append-only decision record already exists", str(ctx.exception))

    def test_missing_superseded_record_fails(self):
        data = self.record("D-STEP4-0002")
        data["supersedes_record_id"] = "D-MISSING-0001"
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.write_record(data, self.root, self.policy)
        self.assertIn("does not exist", str(ctx.exception))

    def test_supersession_requires_new_record_and_existing_predecessor(self):
        first = self.record("D-STEP4-0001")
        record_decision.write_record(first, self.root, self.policy)
        second = self.record("D-STEP4-0002")
        second["supersedes_record_id"] = "D-STEP4-0001"
        second["decision"] = "Superseding decision summary."
        out = record_decision.write_record(second, self.root, self.policy)
        self.assertTrue(out.is_file())
        self.assertTrue(record_decision.find_record("D-STEP4-0001", self.root, self.policy).is_file())

    def test_record_cannot_supersede_itself(self):
        data = self.record()
        data["supersedes_record_id"] = data["record_id"]
        with self.assertRaises(record_decision.DecisionError):
            record_decision.validate_record(data, self.policy)

    def test_duplicate_record_id_across_tree_is_corruption(self):
        first = self.record("D-STEP4-0001")
        record_decision.write_record(first, self.root, self.policy)
        duplicate = self.root / "archive/decisions/other/2026-09-15/D-STEP4-0001.json"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(json.dumps(first), encoding="utf-8")
        with self.assertRaises(record_decision.DecisionError) as ctx:
            record_decision.find_record("D-STEP4-0001", self.root, self.policy)
        self.assertIn("duplicate decision record id", str(ctx.exception))

    def test_malformed_policy_fails_cleanly(self):
        (self.root / "config/decision_policy.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(record_decision.PolicyError):
            record_decision.load_decision_policy(self.root)

    def test_cli_validate_returns_structured_result(self):
        source = self.root / "candidate.json"
        source.write_text(json.dumps(self.record(), indent=2), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/record_decision.py"), "--validate", str(source), "--root", str(self.root)],
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["privacy_semantic_proof"], "NOT_CLAIMED")

    def test_cli_write_is_append_only(self):
        source = self.root / "candidate.json"
        source.write_text(json.dumps(self.record(), indent=2), encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "tools/record_decision.py"), "--write", str(source), "--root", str(self.root)]
        first = subprocess.run(cmd, text=True, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = subprocess.run(cmd, text=True, capture_output=True)
        self.assertEqual(second.returncode, 2)
        self.assertIn("append-only decision record already exists", second.stderr)


if __name__ == "__main__":
    unittest.main()
