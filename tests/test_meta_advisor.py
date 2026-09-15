import importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('meta_advisor',ROOT/'tools/meta_advisor.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class MetaAdvisorTests(unittest.TestCase):
 def suggestion(self,**kw):
  x={'suggestion_id':'S-1','title':'Lazy planner loading','novelty':'EXTENDS_EXISTING','benefit':'SUBSTANTIAL','frequency':'COMMON','universality':'CORE','repository_tokens_added':500,'default_context_tokens_added':0,'routed_context_tokens_added':40,'runtime_calls_added':0,'complexity':'LOW','compatibility':'VERIFIED','interaction_risk':'LOW','verification':'DETERMINISTIC','reversibility':'EASY','existing_mechanism':'session_planner','evidence_refs':['planner telemetry']}; x.update(kw); return x
 def test_good_suggestion_is_recommended_without_model_confidence(self):
  r=m.evaluate_suggestion(self.suggestion(),ROOT); self.assertEqual(r['verdict'],'RECOMMEND'); self.assertEqual(r['value_density'],'HIGH'); self.assertEqual(r['evidence_confidence'],'HIGH'); self.assertEqual(r['confidence_basis'],'EVIDENCE_CLASSIFICATIONS_NOT_MODEL_CONFIDENCE')
 def test_evidence_confidence_is_ordinal_and_evidence_derived(self):
  self.assertEqual(m.evaluate_suggestion(self.suggestion(),ROOT)['evidence_confidence'],'HIGH'); self.assertEqual(m.evaluate_suggestion(self.suggestion(evidence_refs=[],verification='NONE'),ROOT)['evidence_confidence'],'LOW')
 def test_duplicate_or_conflict_is_rejected(self):
  self.assertEqual(m.evaluate_suggestion(self.suggestion(novelty='DUPLICATE'),ROOT)['verdict'],'REJECT'); self.assertEqual(m.evaluate_suggestion(self.suggestion(compatibility='CONFLICT'),ROOT)['verdict'],'REJECT')
 def test_high_tax_or_unknown_risk_routes_to_review(self):
  r=m.evaluate_suggestion(self.suggestion(default_context_tokens_added=500,interaction_risk='UNKNOWN'),ROOT); self.assertEqual(r['verdict'],'HUMAN_REVIEW'); self.assertIn('HIGH_DEFAULT_CONTEXT_TAX',r['reasons'])
 def test_any_added_runtime_call_routes_to_review(self):
  r=m.evaluate_suggestion(self.suggestion(runtime_calls_added=1),ROOT); self.assertEqual(r['verdict'],'HUMAN_REVIEW'); self.assertIn('ADDED_RUNTIME_CALL_TAX',r['reasons'])
 def test_simple_presentation_does_not_change_evaluation(self):
  c=self.suggestion(); e=m.evaluate_suggestion(c,ROOT); r=m.present_suggestion(c,e,'SIMPLE',ROOT); self.assertIn('Why it helps:',r['text']); self.assertIn('Confidence: HIGH (evidence-derived).',r['text']); self.assertTrue(r['evaluation_unchanged'])
 def test_research_requires_explicit_evidence_reason(self):
  base={'decision_id':'D-1','impact':'LOW','evidence_state':'SUFFICIENT','current_empirical_dependency':False,'current_external_dependency':False,'research_can_resolve':True,'internal_attempts':0,'unresolved_questions':[]}; self.assertFalse(m.advise_research(base,ROOT)['recommend_research']); high={**base,'impact':'HIGH','evidence_state':'MISSING','unresolved_questions':['Need benchmark']}; self.assertTrue(m.advise_research(high,ROOT)['recommend_research'])
 def test_research_not_recommended_when_it_cannot_resolve_decision(self):
  d={'decision_id':'D-1','impact':'HIGH','evidence_state':'MISSING','current_empirical_dependency':False,'current_external_dependency':False,'research_can_resolve':False,'internal_attempts':3,'unresolved_questions':['Unresolvable internally?']}; r=m.advise_research(d,ROOT); self.assertFalse(r['recommend_research']); self.assertIn('RESEARCH_NOT_EXPECTED_TO_RESOLVE',r['reasons'])
 def test_current_external_dependency_recommends_research(self):
  d={'decision_id':'D-1','impact':'MEDIUM','evidence_state':'WEAK','current_empirical_dependency':True,'current_external_dependency':False,'research_can_resolve':True,'internal_attempts':0,'unresolved_questions':['Current provider behavior?']}; self.assertTrue(m.advise_research(d,ROOT)['recommend_research'])
 def test_prompt_compiler_keeps_established_and_unresolved_distinct(self):
  q={'title':'Research caching','decision':'Choose cache strategy','source_refs':['config/context_runtime_policy.json'],'established_facts':['ICM forbids padding'],'unresolved_questions':['Current provider semantics?'],'claims_to_verify':['Cache behavior'],'out_of_scope':['Redesign routing'],'comparison_dimensions':['latency','cost'],'required_output':'Evidence then recommendation.'}; r=m.compile_research_prompt(q,ROOT); self.assertIn('Established facts',r['prompt']); self.assertIn('Unresolved questions',r['prompt']); self.assertEqual(r['authority'],'NONCANONICAL_RESEARCH_TRANSPORT')
 def test_prompt_compiler_requires_open_question_or_claim(self):
  q={'title':'Research','decision':'Decide','source_refs':[],'established_facts':[],'unresolved_questions':[],'claims_to_verify':[],'out_of_scope':[],'comparison_dimensions':[],'required_output':'Evidence.'};
  with self.assertRaises(m.MetaAdvisorError): m.compile_research_prompt(q,ROOT)
 def test_presentation_only_changes_density(self):
  for mode in ('SIMPLE','STANDARD','TECHNICAL'):
   r=m.presentation_mode(mode,ROOT); self.assertFalse(r['changes_rigor']); self.assertFalse(r['changes_authority'])
 def test_workspace_cli_exposes_advise_surface(self):
  import subprocess,sys
  proc=subprocess.run([sys.executable,str(ROOT/'icm'),'advise','--help'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0); self.assertIn('compile-research',proc.stdout)
if __name__=='__main__': unittest.main()
