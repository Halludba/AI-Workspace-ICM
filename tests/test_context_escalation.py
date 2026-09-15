"""Tests for bounded provenance-preserving context escalation."""
from __future__ import annotations
import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("context_escalation",ROOT/"tools/context_escalation.py")
esc=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(esc)
NAV_SPEC=importlib.util.spec_from_file_location("source_navigator",ROOT/"tools/source_navigator.py")
nav=importlib.util.module_from_spec(NAV_SPEC); NAV_SPEC.loader.exec_module(nav)

class ContextEscalationTests(unittest.TestCase):
    def ref(self,kind="EXACT_SYMBOL",path="a.py"):
        return {"path":path,"source_kind":"WORKTREE","git_revision":"a"*40,"sha256":"b"*64,"retrieval_kind":kind,"estimated_tokens":10,"exact_source_recoverable":True}
    def record(self,from_level="C0_MAP",to_level="C1_EXACT_SYMBOL",reason="TARGET_DEFINITION_REQUIRED",refs=None,before=10,after=20):
        return {"schema_version":"1.0","subject_id":"S-1","from_level":from_level,"to_level":to_level,"reason_code":reason,"provenance":refs or [self.ref()],"context_delta":{"before_estimated_tokens":before,"after_estimated_tokens":after,"delta_estimated_tokens":after-before,"added_items":1}}
    def test_policy_defines_exact_bounded_ladder(self):
        p=esc.load_policy(ROOT); self.assertEqual(p["levels"],["C0_MAP","C1_EXACT_SYMBOL","C2_LOCAL_DEPENDENCIES","C3_CROSS_FILE_SLICE","C4_WHOLE_SOURCE","C5_SUBSYSTEM_GLOBAL"]); self.assertTrue(p["adjacent_only"])
    def test_valid_adjacent_transition_has_no_automatic_assurance_effect(self):
        result=esc.validate_transition(self.record(),ROOT); self.assertEqual(result["assurance_effect"],"NONE_AUTOMATIC"); self.assertTrue(result["exact_source_recoverable"])
    def test_skipping_levels_fails_closed(self):
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(self.record(to_level="C2_LOCAL_DEPENDENCIES",reason="LOCAL_DEPENDENCY_UNRESOLVED"),ROOT)
    def test_self_confidence_or_more_tokens_is_not_an_escalation_reason(self):
        for reason in ("SELF_CONFIDENCE_LOW","MORE_TOKENS_AVAILABLE","THINK_HARDER_ONLY"):
            with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(self.record(reason=reason),ROOT)
    def test_self_confidence_field_cannot_enter_transition_contract(self):
        rec=self.record(); rec["self_confidence"]=0.2
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(rec,ROOT)
    def test_positive_context_delta_is_required_and_must_reconcile(self):
        bad=self.record(before=20,after=20)
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(bad,ROOT)
        bad=self.record(); bad["context_delta"]["delta_estimated_tokens"]=999
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(bad,ROOT)
    def test_exact_provenance_is_mandatory(self):
        bad=self.record(); bad["provenance"][0]["exact_source_recoverable"]=False
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(bad,ROOT)
        bad=self.record(); bad["provenance"][0]["sha256"]="short"
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(bad,ROOT)
    def test_cross_file_level_requires_multiple_exact_sources(self):
        rec=self.record("C2_LOCAL_DEPENDENCIES","C3_CROSS_FILE_SLICE","CROSS_FILE_DEPENDENCY_UNRESOLVED",[self.ref("EXACT_SYMBOL","a.py")],20,40)
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(rec,ROOT)
        rec["provenance"].append(self.ref("EXACT_SYMBOL","b.py")); self.assertTrue(esc.validate_transition(rec,ROOT)["valid"])
    def test_whole_source_level_requires_exact_file_evidence(self):
        rec=self.record("C3_CROSS_FILE_SLICE","C4_WHOLE_SOURCE","SLICE_INSUFFICIENT",[self.ref("EXACT_REGION")],40,80)
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(rec,ROOT)
        rec["provenance"]=[self.ref("EXACT_FILE")]; self.assertTrue(esc.validate_transition(rec,ROOT)["valid"])
    def test_source_navigator_provenance_can_be_promoted_without_losing_hash(self):
        retrieval=nav.retrieve_symbol("tools/context_resolver.py","build_plan",root=ROOT,use_cache=False)
        ref=esc.provenance_from_retrieval(retrieval); self.assertEqual(ref["sha256"],retrieval["source"]["sha256"]); self.assertGreater(ref["estimated_tokens"],0); self.assertTrue(ref["exact_source_recoverable"])
    def test_c5_requires_explicit_routed_multi_source_provenance(self):
        refs=[self.ref("ROUTED_CONTEXT","_core/CONTEXT_PROTOCOL.md"),self.ref("ROUTED_CONTEXT","_core/ASSURANCE_PROTOCOL.md")]
        rec=self.record("C4_WHOLE_SOURCE","C5_SUBSYSTEM_GLOBAL","CROSS_SYSTEM_CONTRACT_REQUIRED",refs,100,140)
        self.assertTrue(esc.validate_transition(rec,ROOT)["valid"])
        rec["provenance"]=refs[:1]
        with self.assertRaises(esc.ContextEscalationError): esc.validate_transition(rec,ROOT)
    def test_c4_can_use_real_exact_file_retrieval(self):
        retrieval=nav.retrieve_file("tools/context_resolver.py",root=ROOT)
        ref=esc.provenance_from_retrieval(retrieval)
        rec=self.record("C3_CROSS_FILE_SLICE","C4_WHOLE_SOURCE","SLICE_INSUFFICIENT",[ref],100,100+ref["estimated_tokens"])
        self.assertTrue(esc.validate_transition(rec,ROOT)["valid"])
    def test_cli_validates_record(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"record.json"; p.write_text(json.dumps(self.record()),encoding="utf-8")
            proc=subprocess.run([sys.executable,str(ROOT/"icm"),"inspect","escalation","validate",str(p)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(proc.returncode,0,proc.stderr); self.assertTrue(json.loads(proc.stdout)["valid"])

if __name__ == "__main__": unittest.main()
