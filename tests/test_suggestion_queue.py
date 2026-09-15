import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('suggestion_queue',ROOT/'tools/suggestion_queue.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class SuggestionQueueTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/'config').mkdir(); (self.root/'.session').mkdir(); (self.root/'config/suggestion_policy.json').write_text((ROOT/'config/suggestion_policy.json').read_text(encoding='utf-8'),encoding='utf-8')
 def tearDown(self): self.t.cleanup()
 def item(self,sid='S1',bundle='B1'): return {'suggestion_id':sid,'title':'Interaction idea','reason':'Useful bridge','bundle_id':bundle,'evidence_refs':['chat:1'],'compatibility_state':'VERIFIED','last_reviewed_revision':'abc123'}
 def test_queue_is_non_authoritative_and_topic_change_silence_are_neutral(self):
  p=m.policy(self.root); self.assertEqual(p['topic_change_effect'],'NONE'); self.assertEqual(p['silence_effect'],'NONE'); self.assertFalse(p['automatic_execution']); self.assertFalse(p['automatic_planner_mutation'])
 def test_unopposed_is_not_promotion_eligible(self):
  m.add('agent',self.item(),self.root); m.transition('agent','S1','UNOPPOSED',self.root)
  with self.assertRaises(m.SuggestionError): m.promotion_candidate('agent','S1',self.root)
 def test_only_accepted_can_form_promotion_candidate_without_mutating_planner(self):
  m.add('agent',self.item(),self.root); m.transition('agent','S1','ACCEPTED',self.root); r=m.promotion_candidate('agent','S1',self.root); self.assertFalse(r['planner_mutation_performed']); self.assertEqual(r['execution_authority'],'NONE'); self.assertTrue(r['requires_plan_sufficiency'])
 def test_go_ahead_scopes_primary_only(self):
  r=m.resolve_phrase('go ahead',['S1','S2'],['S1','S2','S3'],'S2',self.root); self.assertEqual(r['scope'],'PRIMARY_CURRENT'); self.assertEqual(r['targets'],['S2'])
 def test_go_ahead_with_all_scopes_current_bundle(self):
  r=m.resolve_phrase('Go   ahead with all',['S1','S2'],['S1','S2','S3'],'S1',self.root); self.assertEqual(r['scope'],'CURRENT_BUNDLE'); self.assertEqual(r['targets'],['S1','S2'])
 def test_all_pending_requires_explicit_phrase(self):
  r=m.resolve_phrase('go ahead with all pending suggestions',['S1'],['S1','S2','S3'],'S1',self.root); self.assertEqual(r['scope'],'ALL_PENDING'); self.assertEqual(r['targets'],['S1','S2','S3'])
 def test_unrecognized_language_gets_no_deterministic_authorization(self):
  r=m.resolve_phrase('sure why not',['S1'],['S1'],'S1',self.root); self.assertFalse(r['recognized']); self.assertEqual(r['authorization'],'NONE')
 def test_compact_summary_omits_full_reason_and_evidence(self):
  m.add('agent',self.item(),self.root); r=m.compact('agent',self.root); self.assertEqual(r['unresolved_count'],1); self.assertNotIn('reason',r['suggestions'][0]); self.assertNotIn('evidence_refs',r['suggestions'][0])
 def test_session_root_is_gitignored(self):
  import subprocess
  p=subprocess.run(['git','check-ignore','.session/suggestions/agent.json'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0)
if __name__=='__main__': unittest.main()