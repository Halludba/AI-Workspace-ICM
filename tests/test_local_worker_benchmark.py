import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location("evaluation_arena",ROOT/"tools/evaluation_arena.py"); a=importlib.util.module_from_spec(S); S.loader.exec_module(a)
class WorkerBenchmarkTests(unittest.TestCase):
 def trial(self,**kw):
  d={"tool_calls":5,"valid_tool_calls":5,"unnecessary_tool_calls":0,"scope_violations":0,"verified_success":True,"patch_correct":True,"wall_time_ms":100.0,"input_tokens_total":1000.0,"repair_count":0.0,"vram_peak_mib":9000.0,"coding_quality_score":0.75}; d.update(kw); return d
 def provider(self,pid,trials): return {"provider_id":pid,"capability_id":"LOCAL_CODE_WORKER","trials":trials}
 def test_tool_and_scope_reliability_gate_out_high_coding_score(self):
  good=self.provider("reliable",[self.trial(coding_quality_score=.72) for _ in range(5)]); risky=self.provider("risky",[self.trial(coding_quality_score=.99),self.trial(scope_violations=1,coding_quality_score=.99),self.trial(coding_quality_score=.99),self.trial(coding_quality_score=.99),self.trial(coding_quality_score=.99)]); out=a.compare_local_workers({"schema_version":"1.0","benchmark_id":"b","providers":[good,risky]}); self.assertIn("reliable",out["eligible_provider_ids"]); self.assertNotIn("risky",out["eligible_provider_ids"]); self.assertTrue(out["generic_coding_score_cannot_override_failed_tool_or_scope_gate"]); self.assertFalse(out["automatic_promotion"])
 def test_invalid_tool_rate_fails_quality_gate(self):
  bad=self.provider("bad",[self.trial(valid_tool_calls=3)]); out=a.compare_local_workers({"schema_version":"1.0","benchmark_id":"b2","providers":[bad]}); self.assertEqual(out["eligible_provider_ids"],[]); self.assertFalse(out["scorecards"][0]["quality_gates"]["valid_tool_call_rate"])
 def test_missing_optional_metrics_remain_unknown(self):
  p=self.provider("p",[self.trial(vram_peak_mib=None,input_tokens_total=None)]); out=a.compare_local_workers({"schema_version":"1.0","benchmark_id":"b3","providers":[p]}); m=out["scorecards"][0]["metrics"]; self.assertIsNone(m["vram_peak_mib_median"]); self.assertIsNone(m["input_tokens_total_median"]); self.assertFalse(out["missing_metrics_treated_as_zero"])
 def test_pareto_frontier_keeps_tradeoff(self):
  fast=self.provider("fast",[self.trial(wall_time_ms=50,coding_quality_score=.75) for _ in range(5)]); quality=self.provider("quality",[self.trial(wall_time_ms=100,coding_quality_score=.90) for _ in range(5)]); out=a.compare_local_workers({"schema_version":"1.0","benchmark_id":"b4","providers":[fast,quality]}); self.assertEqual(set(out["pareto_frontier_provider_ids"]),{"fast","quality"})
 def test_wrong_capability_rejected(self):
  p=self.provider("x",[self.trial()]); p["capability_id"]="MODEL_X"
  with self.assertRaises(a.EvaluationArenaError): a.compare_local_workers({"schema_version":"1.0","benchmark_id":"b5","providers":[p]})
 def test_cli_surface(self):
  p=subprocess.run([__import__("sys").executable,str(ROOT/"icm"),"arena","worker-benchmark","--help"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr)
if __name__=="__main__": unittest.main()
