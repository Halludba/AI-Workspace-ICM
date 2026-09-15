import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('continuity_presenter',ROOT/'tools/continuity_presenter.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class ContinuityPresenterTests(unittest.TestCase):
 def test_high_established_mapping_surfaces_as_rediscovery(self):
  v={'term':'Design by Contract','term_status':'ESTABLISHED_TERM','mapping_strength':'HIGH','user_path':['noticed duplicated rules','proposed relationship-owned rules'],'basis':['user observation','user proposal']}; r=m.validate_concept_callout(v,ROOT); self.assertTrue(r['surface_as_rediscovery']); self.assertFalse(r['private_reasoning_used'])
 def test_related_or_medium_mapping_does_not_claim_rediscovery(self):
  v={'term':'Middleware','term_status':'RELATED_CONCEPT','mapping_strength':'MEDIUM','user_path':['proposed a bridge'],'basis':['user proposal']}; self.assertFalse(m.validate_concept_callout(v,ROOT)['surface_as_rediscovery'])
 def test_footer_prefers_active_planner_over_suggestion(self):
  r=m.compile_footer('chatgpt56-sol',ROOT); self.assertEqual(r['next_step']['kind'],'EXECUTABLE'); self.assertEqual(r['next_step']['task_id'],'T-1330-human-presentation'); self.assertFalse(r['changes_authority'])
 def test_candidate_is_never_executable_when_no_planner(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'config').mkdir(); (root/'.session/suggestions').mkdir(parents=True); (root/'.session/plans').mkdir(parents=True)
   for f in ('human_presentation_policy.json','suggestion_policy.json','session_policy.json','role_policy.json','routes.json'):
    src=ROOT/'config'/f
    if src.exists(): (root/'config'/f).write_text(src.read_text(encoding='utf-8'),encoding='utf-8')
   q={'schema_version':'1.0','agent_id':'a','updated_utc':'2026-01-01T00:00:00Z','suggestions':[{'suggestion_id':'S1','title':'Idea','reason':'r','status':'UNOPPOSED','bundle_id':'B','evidence_refs':[],'compatibility_state':'VERIFIED','last_reviewed_revision':'x','created_utc':'2026-01-01T00:00:00Z','updated_utc':'2026-01-01T00:00:00Z'}]}; (root/'.session/suggestions/a.json').write_text(json.dumps(q),encoding='utf-8')
   r=m.compile_footer('a',root); self.assertEqual(r['next_step']['kind'],'CANDIDATE'); self.assertEqual(r['next_step']['execution_authority'],'NONE')
if __name__=='__main__': unittest.main()