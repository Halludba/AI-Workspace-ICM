import importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('developer_observatory',ROOT/'tools/developer_observatory.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class ObservatoryTests(unittest.TestCase):
 def event(self,**kw):
  e={'schema_version':'1.0','event_id':'E-1','session_id':'S-1','mode':'NORMAL','phase':'VERIFICATION','timestamp':'2026-09-15T10:00:00Z','trigger':'planner-task','role':'icm-runtime-architect','mechanism':'source_navigator','duration_ms':12.5,'context_refs':['tools/x.py'],'directive_refs':['D-1'],'causal_refs':['consumer:implementation'],'model_calls':0,'tool_calls':1,'outcome':'SUCCESS','rework_class':None,'context_escalation':None}; e.update(kw); return e
 def test_normal_event_is_model_free_and_noncanonical(self):
  r=m.validate_event(self.event(),ROOT); self.assertEqual(r['authority'],'DERIVED_NONCANONICAL'); self.assertEqual(r['execution_authority'],'NONE')
 def test_normal_mode_adds_no_model_calls_but_can_record_observed_calls(self):
  self.assertFalse(m.load_policy(ROOT)['normal_mode_model_calls']); self.assertEqual(m.validate_event(self.event(model_calls=1),ROOT)['model_calls'],1); self.assertIsNone(m.validate_event(self.event(model_calls=None),ROOT)['model_calls'])
 def test_private_reasoning_and_transcripts_rejected_nested(self):
  e=self.event(); e['context_escalation']={'from_level':'C1','to_level':'C2','added_estimated_tokens':4,'reasoning':'secret'}
  with self.assertRaises(m.ObservatoryError): m.validate_event(e,ROOT)
 def test_summary_reports_rework_and_context_escalation_mechanically(self):
  a=self.event(); b=self.event(event_id='E-2',mode='DEVELOPER',outcome='REWORK',rework_class='AVOIDABLE_IMPLEMENTATION_REWORK',context_escalation={'from_level':'C1','to_level':'C2','added_estimated_tokens':200})
  r=m.summarize([a,b],ROOT); self.assertEqual(r['event_count'],2); self.assertEqual(r['mechanism_counts']['source_navigator'],2); self.assertEqual(r['rework_ratio'],0.5); self.assertEqual(r['context_added_estimated_tokens'],200); self.assertEqual(r['average_added_tokens_per_escalation'],200); self.assertEqual(r['value_claim'],'OBSERVED_USAGE_ONLY_NOT_CAUSAL_VALUE')
 def test_rework_class_only_valid_for_rework(self):
  with self.assertRaises(m.ObservatoryError): m.validate_event(self.event(rework_class='EXPLORATORY_REWORK'),ROOT)
  with self.assertRaises(m.ObservatoryError): m.validate_event(self.event(outcome='REWORK'),ROOT)
 def test_timestamp_requires_timezone_and_escalation_positive_delta(self):
  with self.assertRaises(m.ObservatoryError): m.validate_event(self.event(timestamp='2026-09-15T10:00:00'),ROOT)
  with self.assertRaises(m.ObservatoryError): m.validate_event(self.event(context_escalation={'from_level':'C1','to_level':'C2','added_estimated_tokens':0}),ROOT)
 def test_unavailable_call_counts_do_not_erase_phase_or_mechanism_counts(self):
  r=m.summarize([self.event(model_calls=None,tool_calls=None)],ROOT); self.assertIsNone(r['observed_model_calls']); self.assertIsNone(r['observed_tool_calls']); self.assertEqual(r['phase_counts']['VERIFICATION'],1); self.assertEqual(r['mechanism_counts']['source_navigator'],1)
 def test_audit_reports_only_observed_deltas_no_causal_percentage(self):
  r=m.compare_audit({'wall_time_ms':100,'correctness_score':0.8},{'wall_time_ms':80,'correctness_score':0.9}); self.assertEqual(r['observed_deltas']['wall_time_ms']['delta'],-20); self.assertFalse(r['causal_percentage_claimed'])
 def test_record_is_idempotent_and_local(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'config').mkdir(); (root/'config/developer_observatory_policy.json').write_text((ROOT/'config/developer_observatory_policy.json').read_text(),encoding='utf-8'); one=m.record_event(self.event(),root); two=m.record_event(self.event(),root); self.assertFalse(one['idempotent']); self.assertTrue(two['idempotent']); self.assertTrue((root/one['path']).is_file())
 def test_session_observatory_root_is_gitignored(self):
  text=(ROOT/'.gitignore').read_text(encoding='utf-8'); self.assertIn('.session/',text)
 def test_workspace_cli_exposes_observe_surface(self):
  import subprocess,sys
  proc=subprocess.run([sys.executable,str(ROOT/'icm'),'observe','--help'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0); self.assertIn('record',proc.stdout)
if __name__=='__main__': unittest.main()
