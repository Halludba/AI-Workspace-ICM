import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('evaluation_arena',ROOT/'tools/evaluation_arena.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
REV='a'*40
class StrategyRunnerTests(unittest.TestCase):
 def case(self,cid='C-1',partition='TUNE',sha='b'*64):
  return {'schema_version':'1.0','case_id':cid,'title':'Bounded task','task_kind':'QA','partition':partition,'base_revision':REV,'input_sha256':sha,'source_refs':['ref:a'],'tags':['qa'],'evaluator':{'kind':'DETERMINISTIC','evaluator_ref':'tests/check.py','quality_floor':0.9}}
 def variant(self,vid='V-1',**kw):
  x={'schema_version':'1.0','variant_id':vid,'base_revision':REV,'model_ref':'host:model','context_policy_ref':'route:qa','planner_enabled':True,'verification_mode':'NORMAL','max_model_calls':2,'max_tool_calls':4,'strategy_params':{'context_level':'C2'}}; x.update(kw); return x
 def suite(self,cases=None,variants=None): return {'cases':cases or [self.case()],'variants':variants or [self.variant()],'experiment_config':{'purpose':'bounded-search'},'experiment_id':'EXP-RUN'}
 def metrics(self,**kw):
  x={k:None for k in m._benchmark_policy(ROOT)['required_metrics']}; x.update({'wall_time_ms':100.0,'model_calls':1.0,'tool_calls':1.0,'input_tokens_total':100.0}); x.update(kw); return x
 def observation(self,outcome='SUCCESS',**metrics): return {'schema_version':'1.0','outcome':outcome,'observed_metrics':self.metrics(**metrics),'rework_class':None,'evidence_refs':['exec:1']}
 def quality(self,score=.95): return {'schema_version':'1.0','evaluator_kind':'DETERMINISTIC','evaluator_id':'tests:quality','score':score,'evidence_refs':['quality:1']}
 def request(self,variants=None,token_budget=1000.0,**budget):
  b={'wall_time_ms':5000.0,'model_calls':10.0,'tool_calls':20.0,'input_tokens_total':token_budget}; b.update(budget); return {'schema_version':'1.0','run_id':'RUN-1','partition':'TUNE','variant_ids':variants or ['V-1'],'replicates':1,'budget':b}
 def test_missing_execution_capability_fails_closed(self):
  with self.assertRaises(m.EvaluationArenaError): m.run_strategy_search(self.suite(),self.request(),None,lambda *a:self.quality(),ROOT)
 def test_missing_evaluator_capability_fails_closed(self):
  with self.assertRaises(m.EvaluationArenaError): m.run_strategy_search(self.suite(),self.request(),lambda *a:self.observation(),None,ROOT)
 def test_non_allowlisted_strategy_parameter_fails_closed(self):
  bad=self.variant(strategy_params={'temperature':0.1})
  with self.assertRaises(m.EvaluationArenaError): m.run_strategy_search(self.suite(variants=[bad]),self.request(),lambda *a:self.observation(),lambda *a:self.quality(),ROOT)
 def test_executor_packet_hides_partition_and_evaluator(self):
  seen=[]
  def executor(packet): seen.append(packet); return self.observation()
  r=m.run_strategy_search(self.suite(),self.request(),executor,lambda *a:self.quality(),ROOT)
  self.assertEqual(r['trial_count'],1); self.assertFalse(r['executor_partition_visible']); self.assertFalse(r['executor_evaluator_visible'])
  self.assertNotIn('partition',seen[0]['case']); self.assertNotIn('evaluator',seen[0]['case']); self.assertNotIn('quality_floor',seen[0]['case'])
 def test_two_complete_variants_flow_into_arena_analysis(self):
  variants=[self.variant('V-1'),self.variant('V-2',strategy_params={'context_level':'C3'})]
  def executor(packet): return self.observation(wall_time_ms=100 if packet['variant']['variant_id']=='V-1' else 150,input_tokens_total=100 if packet['variant']['variant_id']=='V-1' else 120)
  def evaluator(case,obs,packet): return self.quality(.95 if packet['variant']['variant_id']=='V-1' else .96)
  r=m.run_strategy_search(self.suite(variants=variants),self.request(variants=['V-1','V-2']),executor,evaluator,ROOT)
  self.assertEqual(len(r['completed_variants']),2); self.assertTrue(r['comparison_ready']); self.assertIsNotNone(r['analysis']); self.assertFalse(r['automatic_promotion'])
 def test_quality_floor_failure_stops_variant_without_padding_trials(self):
  cases=[self.case('C-1'),self.case('C-2',sha='c'*64)]
  calls=[]
  def executor(packet): calls.append(packet['case']['case_id']); return self.observation()
  r=m.run_strategy_search(self.suite(cases=cases),self.request(),executor,lambda *a:self.quality(.5),ROOT)
  self.assertEqual(calls,['C-1']); self.assertEqual(r['trial_count'],1); self.assertEqual(r['completed_variants'],[]); self.assertIsNone(r['analysis'])
  self.assertEqual(r['discarded_variants'][0]['reason'],'QUALITY_FLOOR_FAILURE')
 def test_failed_execution_stops_before_evaluator(self):
  evaluated=[]
  def evaluator(*args): evaluated.append(True); return self.quality()
  r=m.run_strategy_search(self.suite(),self.request(),lambda *a:self.observation(outcome='FAILED'),evaluator,ROOT)
  self.assertEqual(evaluated,[]); self.assertEqual(r['trial_count'],0); self.assertEqual(r['attempt_count'],1); self.assertEqual(r['discarded_variants'][0]['reason'],'EXECUTION_FAILED')
 def test_executor_exceeding_hard_budget_fails_closed(self):
  req=self.request(model_calls=1.0)
  with self.assertRaisesRegex(m.EvaluationArenaError,'hard budget: model_calls'):
   m.run_strategy_search(self.suite(),req,lambda *a:self.observation(model_calls=2.0),lambda *a:self.quality(),ROOT)
 def test_configured_token_budget_requires_observed_tokens(self):
  with self.assertRaisesRegex(m.EvaluationArenaError,'token budget configured'):
   m.run_strategy_search(self.suite(),self.request(token_budget=1000.0),lambda *a:self.observation(input_tokens_total=None),lambda *a:self.quality(),ROOT)
 def test_unconfigured_token_budget_allows_unavailable_tokens(self):
  r=m.run_strategy_search(self.suite(),self.request(token_budget=None),lambda *a:self.observation(input_tokens_total=None),lambda *a:self.quality(),ROOT)
  self.assertIsNone(r['budget_consumed']['input_tokens_total']); self.assertEqual(r['trial_count'],1)
 def test_fixture_callbacks_are_deterministic_and_bounded(self):
  packet={'case':{'case_id':'C-1'},'variant':{'variant_id':'V-1'},'replicate':0}
  fixture={'schema_version':'1.0','executions':{'C-1|V-1|0':self.observation()},'evaluations':{'C-1|V-1|0':self.quality()}}
  executor,evaluator=m.fixture_callbacks(fixture); self.assertEqual(executor(packet)['outcome'],'SUCCESS'); self.assertEqual(evaluator(None,None,packet)['score'],.95)
 def test_fixture_missing_entry_fails_closed(self):
  packet={'case':{'case_id':'C-1'},'variant':{'variant_id':'V-1'},'replicate':0}; executor,_=m.fixture_callbacks({'schema_version':'1.0','executions':{},'evaluations':{}})
  with self.assertRaisesRegex(m.EvaluationArenaError,'fixture execution missing'): executor(packet)
 def test_strategy_run_request_rejects_excessive_variant_count(self):
  ids=[f'V-{i}' for i in range(m.load_policy(ROOT)['strategy_runner']['max_variants']+1)]
  with self.assertRaises(m.EvaluationArenaError): m.validate_strategy_run_request(self.request(variants=ids),ROOT)
