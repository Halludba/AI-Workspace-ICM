import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('plan_intelligence',ROOT/'tools/plan_intelligence.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class PlanIntelligenceTests(unittest.TestCase):
 def task(self,**kw):
  x={'task_id':'T-a','title':'Do bounded work','route_id':'tool-development','declared_scope':'SCOPED','target_role':'icm-runtime-architect','context_refs':['runtime'],'acceptance_criteria':['Done condition'],'verification':['Run targeted tests'],'status':'PENDING','depends_on':[]}; x.update(kw); return x
 def test_execution_task_sufficient(self): self.assertEqual(m.assess_task(self.task(),ROOT)['status'],'SUFFICIENT')
 def test_missing_verification_is_insufficient(self):
  x=self.task(); x.pop('verification'); r=m.assess_task(x,ROOT); self.assertEqual(r['status'],'INSUFFICIENT'); self.assertIn('verification',r['missing_fields'])
 def test_read_only_task_does_not_require_execution_fields(self): self.assertEqual(m.assess_task({'task_id':'T-r','target_role':'icm-system-architect'},ROOT)['status'],'SUFFICIENT')
 def test_reconcile_walks_only_downstream_and_shared_context(self):
  p={'tasks':[self.task(task_id='T-a',status='COMPLETED'),self.task(task_id='T-b',depends_on=['T-a']),self.task(task_id='T-c',depends_on=['T-b']),self.task(task_id='T-d',context_refs=['other'])]}
  r=m.reconcile(p,{'changed_task_ids':['T-a'],'changed_context_refs':[]},ROOT); self.assertEqual(r['affected_task_ids'],['T-b','T-c']); self.assertFalse(r['plan_mutated'])
 def test_context_ref_reconciliation_is_targeted(self):
  p={'tasks':[self.task(task_id='T-a',context_refs=['alpha']),self.task(task_id='T-b',context_refs=['beta'])]}; r=m.reconcile(p,{'changed_task_ids':[],'changed_context_refs':['beta']},ROOT); self.assertEqual(r['affected_task_ids'],['T-b'])
if __name__=='__main__': unittest.main()
