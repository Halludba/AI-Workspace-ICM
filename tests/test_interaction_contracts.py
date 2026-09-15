import importlib.util,json,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('interaction_contracts',ROOT/'tools/interaction_contracts.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class InteractionContractTests(unittest.TestCase):
 def test_policy_is_valid_and_grants_no_authority(self):
  r=m.validate_policy(ROOT); self.assertTrue(r['valid']); self.assertFalse(r['grants_execution_authority']); self.assertFalse(r['grants_mutation_authority']); self.assertFalse(r['automatic_rule_deletion'])
 def test_expected_bridges_exist(self):
  for cid in ('planner-git','context-assurance','role-mutation','worker-governance','observatory-meta-advisor','arena-governance','capability-host'):
   self.assertEqual(m.contract(cid,ROOT)['id'],cid)
 def test_invariant_sources_are_exact_existing_files(self):
  p=json.loads((ROOT/'config/interaction_policy.json').read_text(encoding='utf-8'))
  for inv in p['invariants']:
   self.assertGreaterEqual(len(inv['source_refs']),2)
   for ref in inv['source_refs']: self.assertTrue((ROOT/ref).is_file(),ref)
 def test_unknown_contract_fails_closed(self):
  with self.assertRaises(m.InteractionError): m.contract('missing',ROOT)
 def test_dedup_requires_complete_coverage_and_never_auto_deletes(self):
  c={'contract_id':'role-mutation','duplicate_rule_refs':['README.md','profiles/CONTEXT.md'],'relevant_paths':['route','handoff'],'covered_paths':['route','handoff']}; r=m.assess_dedup(c,ROOT); self.assertTrue(r['eligible_for_semantic_review']); self.assertFalse(r['automatic_delete']); self.assertTrue(r['semantic_equivalence_required'])
 def test_incomplete_dedup_coverage_is_not_eligible(self):
  c={'contract_id':'role-mutation','duplicate_rule_refs':['README.md'],'relevant_paths':['route','handoff'],'covered_paths':['route']}; r=m.assess_dedup(c,ROOT); self.assertFalse(r['eligible_for_semantic_review']); self.assertEqual(r['missing_paths'],['handoff'])
 def test_workspace_cli_exposes_interaction_surface(self):
  p=subprocess.run([sys.executable,str(ROOT/'icm'),'interaction','validate'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr); self.assertIn('contract_count',p.stdout)
if __name__=='__main__': unittest.main()