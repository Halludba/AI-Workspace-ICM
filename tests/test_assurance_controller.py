import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "assurance_controller", ROOT / "tools" / "assurance_controller.py"
)
assurance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assurance)


class AssuranceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = assurance.load_policy()

    def base(self, risk="LOW", current="PLAUSIBLE"):
        return {
            "schema_version": "1.0",
            "assessment_id": "A-test",
            "subject_id": "subject:test",
            "risk_level": risk,
            "current_assurance": current,
            "user_mode": "AUTO",
            "impact_scope": "SCOPED_VALIDATION",
            "signals": {
                "ambiguity": False,
                "contradiction": False,
                "critical_unknowns": [],
                "live_state_unknown": False,
                "missing_evidence": False,
                "high_novelty": False,
                "irreversible": False,
            },
            "verification": {"availability": "NONE", "status": "NOT_RUN"},
            "history": [],
        }

    def step(self, before="PLAUSIBLE", after="SUPPORTED", action="SEARCH_PRIMARY_SOURCE",
             level="L3_CORROBORATE", deltas=None, refs=None):
        return {
            "before_assurance": before,
            "action": action,
            "level": level,
            "after_assurance": after,
            "delta_types": deltas if deltas is not None else ["NEW_PRIMARY_EVIDENCE"],
            "evidence_refs": refs if refs is not None else ["source:primary"],
        }

    def test_low_risk_plausible_direct_is_assured(self):
        result = assurance.evaluate_assessment(self.base(), use_cache=False)
        self.assertEqual(result["outcome"], "ASSURED")
        self.assertEqual(result["minimum_level"], "L0_DIRECT")

    def test_medium_insufficient_routes_to_deliberation(self):
        result = assurance.evaluate_assessment(self.base("MEDIUM", "PLAUSIBLE"), use_cache=False)
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")
        self.assertEqual(result["action"], "DELIBERATE")
        self.assertEqual(result["level"], "L1_DELIBERATE")

    def test_deterministic_verification_is_preferred(self):
        value = self.base("MEDIUM", "PLAUSIBLE")
        value["verification"] = {"availability": "CHEAP_DETERMINISTIC", "status": "NOT_RUN"}
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["action"], "RUN_DETERMINISTIC_CHECK")
        self.assertEqual(result["level"], "L2_VERIFY")

    def test_ambiguity_routes_to_user(self):
        value = self.base("MEDIUM", "PLAUSIBLE")
        value["signals"]["ambiguity"] = True
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["action"], "ASK_USER")

    def test_contradiction_routes_to_resolution(self):
        value = self.base("LOW", "PLAUSIBLE")
        value["signals"]["contradiction"] = True
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["action"], "RESOLVE_CONTRADICTION")
        self.assertEqual(result["level"], "L3_CORROBORATE")

    def test_self_confidence_never_gates(self):
        value = self.base("MEDIUM", "PLAUSIBLE")
        value["self_confidence"] = 1.0
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertFalse(result["self_confidence_used_for_gate"])
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")

    def test_internal_deliberation_cannot_increase_assurance(self):
        value = self.base("MEDIUM", "SUPPORTED")
        value["history"] = [self.step(action="DELIBERATE", level="L1_DELIBERATE")]
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_assurance_increase_requires_delta_and_evidence(self):
        value = self.base("MEDIUM", "SUPPORTED")
        value["history"] = [self.step(deltas=[], refs=[])]
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_valid_external_delta_passes(self):
        value = self.base("MEDIUM", "SUPPORTED")
        value["history"] = [self.step()]
        assurance.validate_assessment(value)

    def test_supported_without_evidence_history_is_rejected(self):
        value = self.base("MEDIUM", "SUPPORTED")
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_verified_requires_verification_delta(self):
        value = self.base("HIGH", "VERIFIED")
        value["history"] = [self.step(after="VERIFIED")]
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_verified_with_deterministic_delta_passes(self):
        value = self.base("HIGH", "VERIFIED")
        value["history"] = [self.step(
            after="VERIFIED", action="RUN_DETERMINISTIC_CHECK", level="L2_VERIFY",
            deltas=["DETERMINISTIC_VERIFICATION"], refs=["test:passed"],
        )]
        assurance.validate_assessment(value)

    def test_full_regression_signal_requires_at_least_verify(self):
        value = self.base("LOW", "PLAUSIBLE")
        value["impact_scope"] = "FULL_REGRESSION"
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")
        self.assertEqual(result["level"], "L3_CORROBORATE")

    def test_fast_mode_cannot_bypass_full_regression_floor(self):
        value = self.base("LOW", "UNKNOWN")
        value["user_mode"] = "FAST"
        value["impact_scope"] = "FULL_REGRESSION"
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")
        self.assertGreaterEqual(
            self.policy["deliberation_levels"].index(result["level"]),
            self.policy["deliberation_levels"].index("L2_VERIFY"),
        )

    def test_fast_low_risk_can_proceed_with_uncertainty(self):
        value = self.base("LOW", "UNKNOWN")
        value["user_mode"] = "FAST"
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["outcome"], "PROCEED_WITH_UNCERTAINTY")

    def test_deep_mode_forces_corroboration(self):
        value = self.base("LOW", "PLAUSIBLE")
        value["user_mode"] = "DEEP"
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")
        self.assertEqual(result["level"], "L3_CORROBORATE")
        self.assertEqual(result["action"], "INDEPENDENT_REVIEW")

    def test_one_no_delta_action_stops_further_escalation(self):
        value = self.base("HIGH", "PLAUSIBLE")
        value["history"] = [self.step(before="PLAUSIBLE", after="PLAUSIBLE", action="RUN_DETERMINISTIC_CHECK", level="L2_VERIFY", deltas=[], refs=[])]
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["decision"], "TERMINAL")
        self.assertEqual(result["outcome"], "REQUEST_HUMAN")
        self.assertIn("consecutive_no_delta", result["reason"])

    def test_critical_second_cycle_escalates_to_l4(self):
        value = self.base("CRITICAL", "SUPPORTED")
        value["history"] = [self.step(before="PLAUSIBLE", after="SUPPORTED")]
        value["signals"]["missing_evidence"] = True
        result = assurance.evaluate_assessment(value, use_cache=False)
        self.assertEqual(result["decision"], "ASSURANCE_ACTION")
        self.assertEqual(result["level"], "L4_DEEP_ASSURANCE")

    def test_private_reasoning_keys_are_rejected(self):
        value = self.base()
        value["signals"]["scratchpad"] = "hidden"
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_bad_self_confidence_type_is_rejected(self):
        value = self.base()
        value["self_confidence"] = True
        with self.assertRaises(assurance.AssuranceError):
            assurance.validate_assessment(value)

    def test_read_object_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_bytes(b"\xef\xbb\xbf{\"value\": 1}\n")
            self.assertEqual(assurance.read_object(path, "input"), {"value": 1})

    def _temp_root(self, temp_dir):
        root = Path(temp_dir)
        (root / "config").mkdir(parents=True)
        (root / "config" / "assurance_policy.json").write_text(
            (ROOT / "config" / "assurance_policy.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return root

    def evidence_backed(self):
        value = self.base("LOW", "SUPPORTED")
        value["history"] = [self.step()]
        value["basis_fingerprint"] = "a" * 64
        return value

    def test_cache_hit_reuses_matching_evidence_backed_assurance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._temp_root(tmp)
            assurance.write_cache(self.evidence_backed(), root)
            value = self.base("LOW", "UNKNOWN")
            value["basis_fingerprint"] = "a" * 64
            result = assurance.evaluate_assessment(value, root)
            self.assertEqual(result["outcome"], "ASSURED")
            self.assertEqual(result["cache_status"], "HIT")
            self.assertEqual(result["effective_assurance"], "SUPPORTED")

    def test_cache_miss_on_fingerprint_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._temp_root(tmp)
            assurance.write_cache(self.evidence_backed(), root)
            value = self.base("LOW", "UNKNOWN")
            value["basis_fingerprint"] = "b" * 64
            result = assurance.evaluate_assessment(value, root)
            self.assertNotEqual(result.get("cache_status"), "HIT")
            self.assertEqual(result["decision"], "ASSURANCE_ACTION")

    def test_cache_is_invalidated_by_contradiction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._temp_root(tmp)
            assurance.write_cache(self.evidence_backed(), root)
            value = self.base("LOW", "UNKNOWN")
            value["basis_fingerprint"] = "a" * 64
            value["signals"]["contradiction"] = True
            result = assurance.evaluate_assessment(value, root)
            self.assertEqual(result["decision"], "ASSURANCE_ACTION")
            self.assertEqual(result["action"], "RESOLVE_CONTRADICTION")
            self.assertNotEqual(result.get("cache_status"), "HIT")

    def test_cache_write_requires_supported_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._temp_root(tmp)
            value = self.base("LOW", "PLAUSIBLE")
            value["basis_fingerprint"] = "a" * 64
            with self.assertRaises(assurance.AssuranceError):
                assurance.write_cache(value, root)

    def test_session_cache_root_is_gitignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".session/", gitignore)

    def test_cache_policy_cannot_escape_session_root(self):
        policy = assurance.load_policy()
        policy["cache"]["root"] = "../outside"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "assurance_policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            with self.assertRaises(assurance.AssuranceError):
                assurance.load_policy(root)


    def quick(self, risk="LOW", impact="SCOPED_VALIDATION", mode="AUTO"):
        return {
            "schema_version": "1.0",
            "risk_level": risk,
            "impact_scope": impact,
            "user_mode": mode,
            "known_flags": {
                "ambiguity": False,
                "contradiction": False,
                "critical_unknown": False,
                "failed_verification": False,
                "live_state_unknown": False,
                "missing_evidence": False,
                "high_novelty": False,
                "irreversible": False,
            },
        }

    def test_quick_bypasses_clean_low_risk(self):
        result = assurance.evaluate_quick_trigger(self.quick())
        self.assertFalse(result["invoke_assurance_controller"])

    def test_quick_invokes_high_risk(self):
        result = assurance.evaluate_quick_trigger(self.quick(risk="HIGH"))
        self.assertTrue(result["invoke_assurance_controller"])
        self.assertIn("RISK_FLOOR", result["causes"])

    def test_quick_invokes_full_regression(self):
        result = assurance.evaluate_quick_trigger(self.quick(impact="FULL_REGRESSION"))
        self.assertTrue(result["invoke_assurance_controller"])
        self.assertIn("IMPACT_FLOOR", result["causes"])

    def test_quick_invokes_known_uncertainty(self):
        value = self.quick()
        value["known_flags"]["contradiction"] = True
        result = assurance.evaluate_quick_trigger(value)
        self.assertTrue(result["invoke_assurance_controller"])
        self.assertIn("CONTRADICTION", result["causes"])

    def test_quick_deep_mode_always_invokes(self):
        result = assurance.evaluate_quick_trigger(self.quick(mode="DEEP"))
        self.assertTrue(result["invoke_assurance_controller"])
        self.assertIn("USER_DEEP", result["causes"])


if __name__ == "__main__":
    unittest.main()
