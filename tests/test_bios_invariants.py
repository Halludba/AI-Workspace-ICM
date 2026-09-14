#!/usr/bin/env python3
"""Adversarial tests for Universal BIOS response invariants."""
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_invariants


class UniversalBIOSInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = check_invariants.load_policy(ROOT)
        seal = cls.policy["terminal_seal"]
        cls.bar = seal["boundary_char"] * seal["boundary_length"]

    def response(self, body="ok", *, marker="Systems Architect", target="[TARGET: NONE]", seal=None):
        seal = seal or f"{self.bar}\n[STATUS: RESPONSE_COMPLETE]\n{self.bar}\n"
        return (
            f"╰── ֎ [{marker}] ◄\n\n"
            f"{target}\n[LOCKED: .icm/*, _core/*]\n\n{body}\n\n{seal}"
        )

    def test_valid_non_execution_response(self):
        result = check_invariants.check_turn_invariants(self.response(), self.policy)
        self.assertTrue(result["valid"])
        self.assertEqual(result["persona"], "Systems Architect")
        self.assertTrue(result["is_none_target"])
        self.assertEqual(result["terminal_status"], "RESPONSE_COMPLETE")
        self.assertIsNone(result["terminal_exit"])

    def test_marker_must_be_at_character_zero(self):
        with self.assertRaisesRegex(check_invariants.InvariantError, "character position 0"):
            check_invariants.check_turn_invariants(" " + self.response(), self.policy)

    def test_marker_requires_blank_line(self):
        text = self.response().replace(" ◄\n\n", " ◄\n", 1)
        with self.assertRaisesRegex(check_invariants.InvariantError, "malformed persona marker"):
            check_invariants.check_turn_invariants(text, self.policy)

    def test_unicode_persona_is_preserved(self):
        result = check_invariants.check_turn_invariants(
            self.response(marker="Specialist 🚀"), self.policy
        )
        self.assertEqual(result["persona"], "Specialist 🚀")

    def test_missing_firmware_lock_fails(self):
        text = self.response().replace("[LOCKED: .icm/*, _core/*]\n", "")
        with self.assertRaisesRegex(check_invariants.InvariantError, "firmware lock"):
            check_invariants.check_turn_invariants(text, self.policy)

    def test_single_target(self):
        result = check_invariants.check_turn_invariants(
            self.response(target="[TARGET: work/run/output.json]"), self.policy
        )
        self.assertEqual(result["targets"], ["work/run/output.json"])
        self.assertFalse(result["is_none_target"])

    def test_multiple_targets(self):
        target = "[TARGETS:\n- work/a.json\n- work/b.json\n]"
        result = check_invariants.check_turn_invariants(self.response(target=target), self.policy)
        self.assertEqual(result["targets"], ["work/a.json", "work/b.json"])

    def test_conflicting_target_forms_fail(self):
        text = self.response(target="[TARGET: work/a.json]\n[TARGETS:\n- work/b.json\n]")
        with self.assertRaisesRegex(check_invariants.InvariantError, "conflicting TARGET"):
            check_invariants.check_turn_invariants(text, self.policy)

    def test_malformed_targets_block_fails(self):
        text = self.response(target="[TARGETS:\nwork/a.json\n]")
        with self.assertRaisesRegex(check_invariants.InvariantError, "malformed TARGETS"):
            check_invariants.check_turn_invariants(text, self.policy)

    def test_no_op_recognition(self):
        result = check_invariants.check_turn_invariants(
            self.response(body="ACTION: NO_OP"), self.policy
        )
        self.assertTrue(result["is_no_op"])

    def test_execution_complete_with_exit_zero(self):
        seal = f"{self.bar}\n[STATUS: COMPLETE | NEXT: verify | EXIT: 0]\n{self.bar}\n"
        result = check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)
        self.assertEqual(result["terminal_status"], "COMPLETE")
        self.assertEqual(result["terminal_next"], "verify")
        self.assertEqual(result["terminal_exit"], 0)

    def test_execution_complete_without_exit_keeps_none(self):
        seal = f"{self.bar}\n[STATUS: COMPLETE | NEXT: verify]\n{self.bar}\n"
        result = check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)
        self.assertIsNone(result["terminal_exit"])

    def test_response_complete_rejects_exit(self):
        seal = f"{self.bar}\n[STATUS: RESPONSE_COMPLETE | EXIT: 0]\n{self.bar}\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "RESPONSE_COMPLETE"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_response_complete_rejects_next(self):
        seal = f"{self.bar}\n[STATUS: RESPONSE_COMPLETE | NEXT: something]\n{self.bar}\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "RESPONSE_COMPLETE"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_unsupported_status_fails(self):
        seal = f"{self.bar}\n[STATUS: SUCCESS]\n{self.bar}\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "unsupported terminal status"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_exact_configured_boundary_length_is_required(self):
        short = "═" * (len(self.bar) - 1)
        seal = f"{short}\n[STATUS: COMPLETE]\n{short}\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "terminal seal"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_truncated_terminal_seal_fails(self):
        seal = f"{self.bar}\n[STATUS: COMPLETE]\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "terminal seal"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_terminal_seal_must_be_final_content(self):
        seal = f"{self.bar}\n[STATUS: COMPLETE]\n{self.bar}\ntrailing text\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "terminal seal"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_unknown_terminal_field_fails(self):
        seal = f"{self.bar}\n[STATUS: COMPLETE | MAGIC: yes]\n{self.bar}\n"
        with self.assertRaisesRegex(check_invariants.InvariantError, "unsupported terminal seal field"):
            check_invariants.check_turn_invariants(self.response(seal=seal), self.policy)

    def test_malformed_workspace_policy_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config").mkdir()
            (root / "config" / "workspace.json").write_text(
                json.dumps({"interaction": "invalid"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(check_invariants.PolicyError, "interaction must be an object"):
                check_invariants.load_policy(root)


if __name__ == "__main__":
    unittest.main()
