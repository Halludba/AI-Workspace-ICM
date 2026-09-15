import importlib.util,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
obs=load('developer_observatory_roi',ROOT/'tools/developer_observatory.py')
arena=load('evaluation_arena_ablation',ROOT/'tools/evaluation_arena.py')

class ResourceOptimizationTests(unittest.TestCase):
 def event(self,eid,session,mechanism,duration,**kw):
  x={'schema_version':'1.0','event_id':eid,'session_id':session,'mode':'NORMAL','phase':'IMPLEMENTATION','timestamp':'2026-09-16T00:00:00+10:00','trigger':'test','role':'icm-runtime-architect','mechanism':mechanism,'duration_ms':duration,'context_refs':[],'directive_refs':[],'causal_refs':[],'model_calls':0,'tool_calls':1,'outcome':'SUCCESS','rework_class':None,'context_escalation':None}; x.update(kw); return x
 def measurement(self,quality=.95,wall=100.0,**kw):
  x={'quality_score':quality,'wall_time_ms':wall,'input_tokens_total':100.0,'model_calls':1.0,'tool_calls':2.0,'rework_count':0.0,'evidence_refs':['evidence:1']}; x.update(kw); return x
 def ablation(self,baseline=None,ablated=None):
  return {'schema_version':'1.0','experiment_id':'ABL-1','mechanism':'session_planner','quality_floor':.9,'baseline':baseline or self.measurement(),'ablated':ablated or self.measurement(wall=80.0,input_tokens_total=80.0)}
 def test_mechanism_cost_profile_ranks_observed_cost_without_worth_claim(self):
  ev=[self.event('1','S1','planner',80),self.event('2','S1','other',10),self.event('3','S2','planner',90),self.event('4','S2','other',10),self.event('5','S3','planner',100)]
  r=obs.mechanism_costs(ev,ROOT); self.assertEqual(r['mechanisms'][0]['mechanism'],'planner'); self.assertFalse(r['worth_claimed']); self.assertTrue(r['ablation_required_for_worth_claim'])
 def test_candidate_requires_repeated_cross_session_cost_evidence(self):
  ev=[self.event('1','S1','planner',80),self.event('2','S1','planner',80),self.event('3','S2','planner',90),self.event('4','S2','other',10)]
  r=obs.optimization_candidates(ev,ROOT); self.assertEqual(r['candidate_count'],1); self.assertEqual(r['candidates'][0]['mechanism'],'planner'); self.assertFalse(r['candidates'][0]['worth_claimed'])
 def test_capture_records_cli_measurement_locally(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'config').mkdir(); shutil.copy(ROOT/'config/developer_observatory_policy.json',root/'config/developer_observatory_policy.json')
   obs.capture_start('CAP-1','NORMAL',root); obs.record_cli_measurement('plan','window-show',12.5,'SUCCESS',root); status=obs.capture_status(root); self.assertTrue(status['active'])
   files=[p for p in (root/'.session/observatory').rglob('*.json') if p.name!='CAPTURE.json']; self.assertEqual(len(files),1); self.assertEqual(json.loads(files[0].read_text())['mechanism'],'icm:plan:window-show'); obs.capture_stop(root); self.assertFalse(obs.capture_status(root)['active'])
 def test_persisted_observatory_event_round_trips_into_cost_analysis(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'config').mkdir(); shutil.copy(ROOT/'config/developer_observatory_policy.json',root/'config/developer_observatory_policy.json')
   obs.capture_start('CAP-2','NORMAL',root); rec=obs.record_cli_measurement('plan','window-show',9.0,'SUCCESS',root); stored=json.loads((root/rec['path']).read_text()); result=obs.mechanism_costs([stored],root); self.assertEqual(result['event_count'],1); self.assertEqual(result['mechanisms'][0]['mechanism'],'icm:plan:window-show')
 def test_favorable_ablation_is_review_candidate_never_auto_removal(self):
  r=arena.compare_ablation(self.ablation(),ROOT); self.assertEqual(r['verdict'],'ABLATION_FAVORABLE'); self.assertTrue(r['candidate_for_removal_review']); self.assertFalse(r['automatic_removal']); self.assertFalse(r['automatic_promotion'])
 def test_quality_regression_blocks_cost_win(self):
  r=arena.compare_ablation(self.ablation(ablated=self.measurement(quality=.80,wall=30.0)),ROOT); self.assertEqual(r['verdict'],'QUALITY_REGRESSION'); self.assertFalse(r['candidate_for_removal_review'])
 def test_missing_optional_ablation_metrics_remain_unknown_not_zero(self):
  b=self.measurement(input_tokens_total=None,model_calls=None); a=self.measurement(wall=80.0,input_tokens_total=None,model_calls=None)
  r=arena.compare_ablation(self.ablation(b,a),ROOT); self.assertIsNone(r['cost_deltas']['input_tokens_total']['delta']); self.assertIsNone(r['cost_deltas']['model_calls']['delta']); self.assertFalse(r['missing_metrics_treated_as_zero'])
 def test_cli_surfaces_expose_roi_and_ablation(self):
  a=subprocess.run([sys.executable,str(ROOT/'icm'),'observe','costs','--help'],cwd=ROOT,text=True,capture_output=True); b=subprocess.run([sys.executable,str(ROOT/'icm'),'arena','ablation','--help'],cwd=ROOT,text=True,capture_output=True)
  self.assertEqual(a.returncode,0,a.stderr); self.assertEqual(b.returncode,0,b.stderr); self.assertIn('events',a.stdout); self.assertIn('request_json',b.stdout)

if __name__=='__main__': unittest.main()