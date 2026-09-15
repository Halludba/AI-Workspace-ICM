import importlib.util,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('resume_supervisor',ROOT/'tools/resume_supervisor.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class ResumeSupervisorTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/'config').mkdir();
  for f in ('resume_supervisor_policy.json','session_policy.json','routes.json','role_policy.json'): shutil.copy(ROOT/'config'/f,self.root/'config'/f)
  subprocess.run(['git','init','-q'],cwd=self.root,check=True); subprocess.run(['git','config','user.email','t@example.invalid'],cwd=self.root,check=True); subprocess.run(['git','config','user.name','T'],cwd=self.root,check=True); (self.root/'x').write_text('x'); subprocess.run(['git','add','.'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','base'],cwd=self.root,check=True)
  head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip(); plan={'schema_version':'1.0','session_id':'s','agent_id':'a','agent_role':'ICM Runtime Architect','created_utc':'2026-01-01T00:00:00Z','updated_utc':'2026-01-01T00:00:00Z','authority_disclaimer':'NON_AUTHORITATIVE_INTENT_QUEUE','active_run_id':None,'auto_delete_on_empty':True,'tasks':[{'task_id':'T-01','route_id':'tool-development','stage_id':'s','title':'One','status':'PENDING','depends_on':[],'user_order':1,'user_directive_ref':'U','priority_class':'NORMAL','declared_scope':'SCOPED','target_role':'icm-runtime-architect'},{'task_id':'T-02','route_id':'tool-development','stage_id':'s','title':'Two','status':'PENDING','depends_on':['T-01'],'user_order':2,'user_directive_ref':'U','priority_class':'NORMAL','declared_scope':'SCOPED','target_role':'icm-runtime-architect'}]}; (self.root/'plan.json').write_text(json.dumps(plan)); m.session_planner.install_plan(plan,self.root); m.session_planner.open_execution_window('a',2,self.root); m.session_planner.checkpoint_execution_window('a','T-01','VERIFIED',[],self.root)
 def tearDown(self): self.t.cleanup()
 def test_capsule_uses_verified_prefix_and_next_task(self):
  c=m.capture('a',self.root); self.assertEqual(c['verified_prefix'],['T-01']); self.assertEqual(c['current_task']['task_id'],'T-02'); self.assertFalse(c['canonical_mutation_authority'])
 def test_repo_move_makes_capsule_stale(self):
  c=m.capture('a',self.root); (self.root/'y').write_text('y'); subprocess.run(['git','add','y'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','move'],cwd=self.root,check=True); out=m.validate_currency(c,self.root); self.assertEqual(out['status'],'STALE'); self.assertIn('BASE_REVISION_CHANGED',out['reasons']); self.assertFalse(out['dispatch_allowed'])
 def test_dispatch_is_allowlisted_and_bounded(self):
  one=m.prepare_dispatch('a','LOCAL_CODE_WORKER',self.root); self.assertEqual(one['status'],'READY'); two=m.prepare_dispatch('a','LOCAL_CODE_WORKER',self.root); self.assertEqual(two['attempts'],2)
  with self.assertRaises(m.ResumeError): m.prepare_dispatch('a','LOCAL_CODE_WORKER',self.root)
 def test_unknown_target_fails_closed(self):
  with self.assertRaises(m.ResumeError): m.prepare_dispatch('a','ARBITRARY_SHELL',self.root)
if __name__=='__main__': unittest.main()
