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
 def metrics(self,**kw):
  keys=m._benchmark_policy(ROOT)['required_metrics']; x={k:None for k in keys}; x.update({'wall_time_ms':100.0,'input_tokens_total':1000.0,'model_calls':1.0,'tool_calls':1.0}); x.update(kw); return x
 def trial(self,variant='1',case='1',replicate=0,score=0.95,wall=100,tokens=1000,outcome='SUCCESS',rework_class=None,partition='TUNE',**kw):
  x={'schema_version':'1.0','trial_id':f'T-{variant}-{case}-{replicate}','experiment_id':'EXP-1','manifest_fingerprint':('1'*63+variant[-1]),'case_fingerprint':('2'*63+case[-1]),'variant_fingerprint':('3'*63+variant[-1]),'partition':partition,'replicate':replicate,'quality_floor':0.9,'quality_evidence':{'schema_version':'1.0','evaluator_kind':'DETERMINISTIC','evaluator_id':'tests:check','score':score,'evidence_refs':['test:pass']},'observed_metrics':self.metrics(wall_time_ms=wall,input_tokens_total=tokens),'outcome':outcome,'rework_class':rework_class}; x.update(kw); return x
 def test_pareto_keeps_quality_time_tradeoff_and_excludes_dominated(self):
  trials=[self.trial('1',score=.95,wall=100,tokens=1000),self.trial('2',score=.96,wall=200,tokens=1200),self.trial('3',score=.94,wall=150,tokens=1200)]
  r=m.analyze_trials(trials,ROOT); self.assertEqual(r['pareto_frontier'],['3'*63+'1','3'*63+'2']); self.assertIn('3'*63+'1',r['dominated_by']['3'*63+'3']); self.assertIsNone(r['canonical_total_rank'])
 def test_below_quality_floor_is_not_frontier_eligible(self):
  r=m.analyze_trials([self.trial('1',score=.85),self.trial('2',score=.95,wall=200)],ROOT); self.assertFalse(r['variants']['3'*63+'1']['quality_eligible']); self.assertNotIn('3'*63+'1',r['pareto_frontier'])
 def test_missing_optional_metric_is_reported_not_zero(self):
  a=self.trial('1'); a['observed_metrics']['input_tokens_total']=None; b=self.trial('2',wall=120)
  r=m.analyze_trials([a,b],ROOT); self.assertIn('input_tokens_total',r['optional_metrics_omitted']); self.assertNotIn('input_tokens_total',r['metrics_used_for_pareto'])
 def test_missing_wall_time_makes_variant_incomparable(self):
  a=self.trial('1'); a['observed_metrics']['wall_time_ms']=None; b=self.trial('2')
  r=m.analyze_trials([a,b],ROOT); self.assertFalse(r['variants']['3'*63+'1']['frontier_eligible'])
 def test_repeated_trials_preserve_values_and_median(self):
  r=m.analyze_trials([self.trial('1',replicate=0,wall=100),self.trial('1',replicate=1,wall=140)],ROOT); d=r['variants']['3'*63+'1']['distributions']['wall_time_ms']; self.assertEqual(d['values'],[100.0,140.0]); self.assertEqual(d['median'],120.0)
 def test_variant_case_coverage_must_match(self):
  with self.assertRaises(m.EvaluationArenaError): m.analyze_trials([self.trial('1',case='1'),self.trial('2',case='2')],ROOT)

 def test_suite_manifest_is_replay_identified_and_blinded(self):
  suite=m.build_suite_manifest([self.case(partition='TUNE'),self.case(case_id='C-2',partition='HOLDOUT',input_sha256='c'*64)],[self.variant()],{'repetitions':2},'EXP-1',ROOT); again=m.build_suite_manifest([self.case(partition='TUNE'),self.case(case_id='C-2',partition='HOLDOUT',input_sha256='c'*64)],[self.variant()],{'repetitions':2},'EXP-1',ROOT); self.assertEqual(suite['suite_fingerprint'],again['suite_fingerprint']); text=str(suite['execution_view']); self.assertNotIn("'partition':",text); self.assertNotIn("'evaluator':",text); self.assertFalse(suite['execution_view']['partition_metadata_exposed'])
 def test_suite_fingerprint_changes_with_config(self):
  a=m.build_suite_manifest([self.case()],[self.variant()],{'repetitions':1},'EXP-1',ROOT); b=m.build_suite_manifest([self.case()],[self.variant()],{'repetitions':2},'EXP-1',ROOT); self.assertNotEqual(a['suite_fingerprint'],b['suite_fingerprint'])
 def test_holdout_comparison_keeps_partitions_separate_and_never_promotes(self):
  tune=m.analyze_trials([self.trial('1',score=.95,wall=100,partition='TUNE'),self.trial('2',score=.94,wall=130,partition='TUNE')],ROOT); hold=m.analyze_trials([self.trial('1',score=.85,wall=110,partition='HOLDOUT'),self.trial('2',score=.95,wall=140,partition='HOLDOUT')],ROOT); r=m.compare_partitions(tune,hold); self.assertIn('TUNE_FRONTIER_NOT_REPRODUCED_ON_HOLDOUT',r['variants']['3'*63+'1']['signals']); self.assertIn('QUALITY_FLOOR_NOT_REPRODUCED_ON_HOLDOUT',r['variants']['3'*63+'1']['signals']); self.assertFalse(r['automatic_promotion']); self.assertEqual(r['generalization_claim'],'HOLDOUT_EVIDENCE_ONLY_NOT_PROOF_OF_GENERALIZATION')
 def test_partition_comparison_requires_same_variants(self):
  tune=m.analyze_trials([self.trial('1',partition='TUNE')],ROOT); hold=m.analyze_trials([self.trial('2',partition='HOLDOUT')],ROOT)
  with self.assertRaises(m.EvaluationArenaError): m.compare_partitions(tune,hold)

if __name__=='__main__': unittest.main()
