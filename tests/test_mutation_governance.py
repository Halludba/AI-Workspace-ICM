#!/usr/bin/env python3
"""Adversarial tests for two-axis mutation governance."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_mutation


class MutationGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = check_mutation.load_mutation_policy(ROOT)

    def sample(self):
        return {
            "schema_version": "1.0",
            "directive_id": "DIR-2026-09-15:step2",
            "summary": "Introduce two-axis mutation governance.",
            "candidates": [
                {
                    "candidate_id": "C-001",
                    "target_paths": ["_core/CONVENTIONS.md", "config/mutation_policy.json"],
                    "change_kind": "REWRITE",
                    "disposition": "ACCEPT",
                    "rationale": "Separate classification from disposition.",
                },
                {
                    "candidate_id": "C-002",
                    "target_paths": ["tools/future_experiment.py"],
                    "change_kind": "NEW",
                    "disposition": "DEFER",
                    "rationale": "Valid idea, not part of this milestone.",
                },
                {
                    "candidate_id": "C-003",
                    "target_paths": ["config/deprecated.json"],
                    "change_kind": "DELETE",
                    "disposition": "REJECT",
                    "rationale": "Still required.",
                },
            ],
            "applied_changes": [],
        }

    def noop(self, disposition="ACCEPT"):
        return {
            "schema_version": "1.0",
            "directive_id": "DIR-002",
            "summary": "No material change proposed.",
            "candidates": [
                {
                    "candidate_id": "C-001",
                    "target_paths": [],
                    "change_kind": "NO_OP",
                    "disposition": disposition,
                    "rationale": "No mutation is justified.",
                }
            ],
            "applied_changes": [],
        }

    def test_all_15_change_kind_disposition_pairs_are_valid(self):
        for kind in self.policy["change_kinds"]:
            for disposition in self.policy["dispositions"]:
                trace = self.noop(disposition) if kind == "NO_OP" else self.sample()
                if kind != "NO_OP":
                    trace["candidates"] = [{
                        "candidate_id": "C-001",
                        "target_paths": ["tools/example.py"],
                        "change_kind": kind,
                        "disposition": disposition,
                        "rationale": "Matrix coverage.",
                    }]
                    trace["applied_changes"] = []
                result = check_mutation.validate_mutation_trace(trace, self.policy)
                self.assertTrue(result["valid"], (kind, disposition))

    def test_noop_accept_is_commit_ready_without_fake_application(self):
        result = check_mutation.validate_mutation_trace(self.noop("ACCEPT"), self.policy, is_none_turn=True, commit_ready=True)
        self.assertEqual(result["accepted_no_op_count"], 1)
        self.assertEqual(result["applied_count"], 0)

    def test_noop_reject_and_defer_are_governance_valid(self):
        for disposition in ("REJECT", "DEFER"):
            result = check_mutation.validate_mutation_trace(self.noop(disposition), self.policy, is_none_turn=True)
            self.assertTrue(result["valid"])
            self.assertEqual(result["accepted_no_op_count"], 0)

    def test_accepted_mutation_can_exist_before_application(self):
        result = check_mutation.validate_mutation_trace(self.sample(), self.policy)
        self.assertEqual(result["accepted_mutating_count"], 1)
        self.assertEqual(result["applied_count"], 0)

    def test_commit_ready_requires_accepted_mutation_application(self):
        with self.assertRaises(check_mutation.MutationError) as ctx:
            check_mutation.validate_mutation_trace(self.sample(), self.policy, commit_ready=True)
        self.assertIn("accepted but unapplied", str(ctx.exception))

    def test_commit_ready_passes_after_application_record(self):
        trace = self.sample()
        trace["applied_changes"] = [{
            "candidate_id": "C-001",
            "description": "Updated governance contract and policy.",
            "evidence_refs": ["git-diff"],
        }]
        result = check_mutation.validate_mutation_trace(trace, self.policy, commit_ready=True)
        self.assertTrue(result["valid"])
        self.assertEqual(result["applied_count"], 1)

    def test_nonaccepted_candidate_cannot_be_applied(self):
        trace = self.sample()
        trace["applied_changes"] = [{"candidate_id": "C-002"}]
        with self.assertRaises(check_mutation.MutationError) as ctx:
            check_mutation.validate_mutation_trace(trace, self.policy)
        self.assertIn("only ACCEPT", str(ctx.exception))

    def test_noop_cannot_be_applied(self):
        trace = self.noop("ACCEPT")
        trace["applied_changes"] = [{"candidate_id": "C-001"}]
        with self.assertRaises(check_mutation.MutationError) as ctx:
            check_mutation.validate_mutation_trace(trace, self.policy)
        self.assertIn("NO_OP cannot appear", str(ctx.exception))

    def test_multi_target_candidate_links_to_turn_scope(self):
        trace = self.sample()
        declared = ["_core/CONVENTIONS.md", "config/mutation_policy.json", "tests/test_mutation_governance.py"]
        result = check_mutation.validate_mutation_trace(trace, self.policy, declared_targets=declared)
        self.assertTrue(result["valid"])

    def test_accepted_target_outside_turn_scope_fails(self):
        with self.assertRaises(check_mutation.MutationError) as ctx:
            check_mutation.validate_mutation_trace(
                self.sample(), self.policy, declared_targets=["_core/CONVENTIONS.md"]
            )
        self.assertIn("exceed declared turn scope", str(ctx.exception))

    def test_target_none_rejects_accepted_mutation(self):
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(self.sample(), self.policy, is_none_turn=True)

    def test_rejected_or_deferred_targets_need_not_be_turn_targets(self):
        trace = self.sample()
        trace["candidates"][0]["disposition"] = "REJECT"
        result = check_mutation.validate_mutation_trace(trace, self.policy, declared_targets=[])
        self.assertTrue(result["valid"])

    def test_noop_requires_empty_target_paths(self):
        trace = self.noop()
        trace["candidates"][0]["target_paths"] = ["README.md"]
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)

    def test_mutating_candidate_requires_target_paths(self):
        trace = self.sample()
        trace["candidates"][0]["target_paths"] = []
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)

    def test_duplicate_candidate_id_fails(self):
        trace = self.sample()
        trace["candidates"][1]["candidate_id"] = "C-001"
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)

    def test_unknown_candidate_field_fails_closed(self):
        trace = self.sample()
        trace["candidates"][0]["surprise"] = True
        with self.assertRaises(check_mutation.MutationError) as ctx:
            check_mutation.validate_mutation_trace(trace, self.policy)
        self.assertIn("unknown field", str(ctx.exception))

    def test_renderer_escapes_markdown_table_delimiters(self):
        trace = self.noop("REJECT")
        trace["candidates"][0]["rationale"] = "A | B\nsecond line"
        rendered = check_mutation.render_mutation_markdown(trace, self.policy)
        self.assertIn(r"A \| B<br>second line", rendered)

    def test_malformed_policy_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            (root / "config/mutation_policy.json").write_text(
                json.dumps({"change_kinds": []}), encoding="utf-8"
            )
            with self.assertRaises(check_mutation.PolicyError):
                check_mutation.load_mutation_policy(root)

    def test_cli_commit_ready_mode(self):
        trace = self.sample()
        trace["applied_changes"] = [{"candidate_id": "C-001"}]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trace.json"
            path.write_text(json.dumps(trace), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools/check_mutation.py"), str(path), "--commit-ready"],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_absolute_target_path_fails(self):
        trace = self.sample()
        trace["candidates"][0]["target_paths"] = ["/outside.py"]
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)

    def test_duplicate_applied_candidate_fails(self):
        trace = self.sample()
        trace["applied_changes"] = [{"candidate_id": "C-001"}, {"candidate_id": "C-001"}]
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)

    def test_unknown_top_level_field_fails_closed(self):
        trace = self.sample()
        trace["extra"] = "not allowed"
        with self.assertRaises(check_mutation.MutationError):
            check_mutation.validate_mutation_trace(trace, self.policy)


if __name__ == "__main__":
    unittest.main()
