import importlib.util, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('evaluation_arena',ROOT/'tools/evaluation_arena.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
REV='a'*40; SHA='b'*64
class EvaluationArenaTests(unittest.TestCase):
 def case(self,**kw):
  x={'schema_version':'1.0','case_id':'C-1','title':'Answer bounded question','task_kind':'QA','partition':'HOLDOUT','base_revision':REV,'input_sha256':SHA,'source_refs':['ref:a'],'tags':['qa'],'evaluator':{'kind':'DETERMINISTIC','evaluator_ref':'tests/check.py','quality_floor':0.9}}; x.update(kw); return x
 def variant(self,**kw):
  x={'schema_version':'1.0','variant_id':'V-1','base_revision':REV,'model_ref':'host:model','context_policy_ref':'route:qa','planner_enabled':True,'verification_mode':'NORMAL','max_model_calls':2,'max_tool_calls':4,'strategy_params':{'context_level':'C2'}}; x.update(kw); return x
 def test_case_and_variant_have_deterministic_content_ids(self):
  self.assertEqual(m.validate_case(self.case(),ROOT)['case_fingerprint'],m.validate_case(self.case(),ROOT)['case_fingerprint']); self.assertEqual(m.validate_variant(self.variant(),ROOT)['variant_fingerprint'],m.validate_variant(self.variant(),ROOT)['variant_fingerprint'])
 def test_execution_view_hides_holdout_and_evaluator(self):
  r=m.case_execution_view(self.case(),ROOT); self.assertNotIn('partition',r); self.assertNotIn('evaluator',r); self.assertTrue(r['partition_hidden']); self.assertTrue(r['evaluator_hidden'])
 def test_manifest_pins_revision_and_never_promotes(self):
  r=m.prepare_manifest(self.case(),self.variant(),'EXP-1',ROOT); self.assertEqual(r['base_revision'],REV); self.assertFalse(r['partition_exposed_to_execution']); self.assertFalse(r['automatic_promotion'])
 def test_revision_mismatch_fails_closed(self):
  with self.assertRaises(m.EvaluationArenaError): m.prepare_manifest(self.case(),self.variant(base_revision='c'*40),'EXP-1',ROOT)
 def test_quality_evidence_types_are_explicit_and_judge_not_ground_truth(self):
  e={'schema_version':'1.0','evaluator_kind':'JUDGE','evaluator_id':'judge:x','score':0.91,'evidence_refs':['result:1']}; r=m.validate_quality_evidence(e,0.9,ROOT); self.assertTrue(r['meets_quality_floor']); self.assertFalse(r['judge_is_ground_truth'])
 def test_quality_floor_is_required_and_bounded(self):
  c=self.case(); c['evaluator']['quality_floor']=1.2
  with self.assertRaises(m.EvaluationArenaError): m.validate_case(c,ROOT)
 def test_private_reasoning_keys_fail_nested(self):
  v=self.variant(strategy_params={'reasoning':'secret'})
  with self.assertRaises(m.EvaluationArenaError): m.validate_variant(v,ROOT)
 def test_strategy_params_are_data_not_commands(self):
  with self.assertRaises(m.EvaluationArenaError): m.validate_variant(self.variant(strategy_params={'nested':{'cmd':'x'}}),ROOT)
 def test_workspace_cli_exposes_arena_surface(self):
  p=subprocess.run([sys.executable,str(ROOT/'icm'),'arena','--help'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0); self.assertIn('prepare',p.stdout)
if __name__=='__main__': unittest.main()
