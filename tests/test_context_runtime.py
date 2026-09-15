"""Tests for stable/dynamic prompt planning and observed runtime telemetry."""
from __future__ import annotations
import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("context_runtime",ROOT/"tools/context_runtime.py")
rt=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(rt)

class ContextRuntimeTests(unittest.TestCase):
    def block(self,id,cls,sha="a"*64,tokens=10): return {"id":id,"class":cls,"source_ref":id,"sha256":sha,"estimated_tokens":tokens}
    def observed(self,subject,cache,wall):
        r=rt.telemetry_template(subject,root=ROOT); r["cache_state"]=cache; r["provider"]="test"; r["model"]="fixture"
        for name,value in {"input_tokens_total":100,"input_tokens_cached":40 if cache=="WARM" else 0,"input_tokens_uncached":60 if cache=="WARM" else 100,"model_calls":1,"tool_calls":2,"wall_time_ms":wall}.items(): r["observed_metrics"][name]=value; r["metric_availability"][name]="OBSERVED"
        return r
    def test_policy_has_no_provider_pricing_ttl_or_cache_minimum_and_forbids_padding(self):
        p=rt.load_policy(ROOT); raw=json.dumps(p).lower(); self.assertNotIn("pricing",raw); self.assertNotIn("ttl",raw); self.assertNotIn("minimum_tokens",raw); self.assertTrue(p["prompt"]["forbid_padding_for_cache"])
    def test_prompt_plan_orders_stable_before_dynamic_and_never_pads(self):
        req={"schema_version":"1.0","blocks":[self.block("task","DYNAMIC_TASK","d"*64),self.block("auth","STABLE_AUTHORITY","a"*64),self.block("route","STABLE_ROUTED_CONTEXT","b"*64)]}
        result=rt.build_prompt_plan(req,ROOT); self.assertEqual([b["id"] for b in result["blocks"]],["auth","route","task"]); self.assertFalse(result["padding_applied"]); self.assertEqual(result["cache_hint"]["authority"],"PERFORMANCE_HINT_ONLY")
    def test_dynamic_change_does_not_change_stable_prefix_fingerprint(self):
        base={"schema_version":"1.0","blocks":[self.block("auth","STABLE_AUTHORITY","a"*64),self.block("task","DYNAMIC_TASK","b"*64)]}
        changed=json.loads(json.dumps(base)); changed["blocks"][1]["sha256"]="c"*64
        a=rt.build_prompt_plan(base,ROOT); b=rt.build_prompt_plan(changed,ROOT); self.assertEqual(a["stable_prefix"]["fingerprint"],b["stable_prefix"]["fingerprint"]); self.assertNotEqual(a["plan_fingerprint"],b["plan_fingerprint"])
    def test_template_marks_every_host_metric_explicitly_unavailable(self):
        r=rt.telemetry_template("T",root=ROOT); self.assertTrue(all(v is None for v in r["observed_metrics"].values())); self.assertTrue(all(v=="UNAVAILABLE" for v in r["metric_availability"].values()))
    def test_observed_telemetry_validates_and_input_tokens_reconcile(self):
        r=self.observed("T","WARM",20); self.assertTrue(rt.validate_telemetry(r,ROOT)["valid"]); r["observed_metrics"]["input_tokens_total"]=101
        with self.assertRaises(rt.ContextRuntimeError): rt.validate_telemetry(r,ROOT)
    def test_unavailable_metric_cannot_carry_invented_value(self):
        r=rt.telemetry_template("T",root=ROOT); r["observed_metrics"]["ttft_ms"]=5
        with self.assertRaises(rt.ContextRuntimeError): rt.validate_telemetry(r,ROOT)
    def test_context_sources_and_prompt_fingerprint_are_integrity_metadata_not_authority(self):
        r=rt.telemetry_template("T",[{"source_ref":"WORKSPACE.md","sha256":"a"*64,"estimated_tokens":10,"block_class":"STABLE_AUTHORITY"}],ROOT); r["prompt_plan_fingerprint"]="b"*64
        out=rt.validate_telemetry(r,ROOT); self.assertEqual(out["authority"],"NONCANONICAL_RUNTIME_EVIDENCE")
    def test_cold_warm_comparison_uses_only_observed_values_and_never_padding(self):
        result=rt.compare_cache_records([self.observed("C","COLD",100),self.observed("W","WARM",60)],ROOT); self.assertEqual(result["groups"]["COLD"]["metrics"]["wall_time_ms"]["p50"],100.0); self.assertEqual(result["warm_minus_cold_p50"]["wall_time_ms"],-40.0); self.assertIsNone(result["warm_minus_cold_p50"]["ttft_ms"]); self.assertFalse(result["padding_used"])
    def test_cli_plan_and_template(self):
        with tempfile.TemporaryDirectory() as td:
            req=Path(td)/"p.json"; req.write_text(json.dumps({"schema_version":"1.0","blocks":[self.block("auth","STABLE_AUTHORITY")]}),encoding="utf-8")
            proc=subprocess.run([sys.executable,str(ROOT/"icm"),"inspect","runtime","plan",str(req)],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr); self.assertTrue(json.loads(proc.stdout)["padding_applied"] is False)
            proc=subprocess.run([sys.executable,str(ROOT/"icm"),"inspect","runtime","template","S"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr); self.assertTrue(json.loads(proc.stdout)["valid"])

if __name__=="__main__": unittest.main()
