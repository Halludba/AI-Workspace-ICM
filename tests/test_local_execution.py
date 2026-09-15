import importlib.util,json,shutil,subprocess,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('local_execution',ROOT/'tools/local_execution.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class LocalExecutionTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/'config').mkdir(); shutil.copy(ROOT/'config/local_execution_policy.json',self.root/'config/local_execution_policy.json'); (self.root/'tests').mkdir(); (self.root/'tests/test_tiny.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n',encoding='utf-8'); subprocess.run(['git','init','-q'],cwd=self.root,check=True); subprocess.run(['git','config','user.email','t@example.invalid'],cwd=self.root,check=True); subprocess.run(['git','config','user.name','T'],cwd=self.root,check=True); (self.root/'a.py').write_text('VALUE=1\n'); subprocess.run(['git','add','.'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','base'],cwd=self.root,check=True); self.head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=self.root,text=True).strip(); self.jobs=[]
 def tearDown(self):
  for j in self.jobs:
   try: m.cleanup(j,self.root)
   except Exception: pass
  shutil.rmtree(self.root.parent/(self.root.name+'.icm-worktrees'),ignore_errors=True); self.t.cleanup()
 def request(self,j='J-1',mode='SNAPSHOT_VERIFY',suite='FULL_REGRESSION',scope=None): return {'job_id':j,'mode':mode,'base_revision':self.head,'suite':suite,'mutation_scope':scope or [],'owner':'test'}
 def create(self,*a,**kw):
  req=self.request(*a,**kw); self.jobs.append(req['job_id']); return m.create_job(req,self.root)
 def test_snapshot_verification_is_revision_bound(self):
  self.create(); r=m.run_snapshot('J-1',self.root); self.assertEqual(r['evidence']['outcome'],'PASS'); cur=m.evidence_currency(r['evidence'],self.root); self.assertEqual(cur['status'],'CURRENT_SUCCESS')
 def test_pass_becomes_stale_success_when_repository_moves(self):
  self.create(); ev=m.run_snapshot('J-1',self.root)['evidence']; (self.root/'a.py').write_text('VALUE=2\n'); subprocess.run(['git','add','a.py'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','move'],cwd=self.root,check=True); cur=m.evidence_currency(ev,self.root); self.assertEqual(cur['status'],'STALE_SUCCESS'); self.assertIn('a.py',cur['changed_paths']); self.assertFalse(cur['reusable_as_current_proof'])
 def test_dirty_current_worktree_makes_snapshot_success_stale(self):
  self.create(); ev=m.run_snapshot('J-1',self.root)['evidence']; (self.root/'a.py').write_text('dirty\n'); self.assertEqual(m.evidence_currency(ev,self.root)['status'],'STALE_SUCCESS')
 def test_mutation_scope_collision_is_deterministic(self):
  self.assertTrue(m.scopes_overlap(['tools/**'],['tools/a.py'])['overlap']); self.assertFalse(m.scopes_overlap(['tools/**'],['tests/a.py'])['overlap']); self.assertTrue(m.scopes_overlap(['a.py'],['a.py'])['overlap'])
 def test_isolated_mutation_gets_separate_worktree_and_scope(self):
  st=self.create('J-M','ISOLATED_MUTATION',None,['tools/**']); self.assertTrue(Path(st['worktree_path']).is_dir()); self.assertNotEqual(Path(st['worktree_path']).resolve(),self.root.resolve()); self.assertEqual(st['mutation_scope'],['tools/**'])
 def test_snapshot_rejects_mutation_scope(self):
  with self.assertRaises(m.LocalExecutionError): m.create_job(self.request('BAD',scope=['a.py']),self.root)
 def test_worker_handoff_is_bound_to_isolated_worktree(self):
  self.create('J-W','ISOLATED_MUTATION',None,['tools/**']); h=m.worker_handoff('J-W',self.root); self.assertTrue(h['invoke_local_worker_inside_worktree']); self.assertFalse(h['shared_mutable_worktree']); self.assertEqual(h['base_revision'],self.head)
 def test_exclusive_leases_reject_overlap(self):
  self.create('L-1','EXCLUSIVE_LEASE',None,['tools/**']);
  with self.assertRaisesRegex(m.LocalExecutionError,'collides'): m.create_job(self.request('L-2','EXCLUSIVE_LEASE',None,['tools/a.py']),self.root)
 def test_released_exclusive_lease_no_longer_blocks_scope(self):
  self.create('L-R1','EXCLUSIVE_LEASE',None,['tools/**']); m.cleanup('L-R1',self.root); self.jobs.remove('L-R1'); st=self.create('L-R2','EXCLUSIVE_LEASE',None,['tools/a.py']); self.assertEqual(st['status'],'READY')
 def test_async_launch_completes_snapshot_job(self):
  self.create('J-A'); out=m.launch_snapshot('J-A',self.root); self.assertEqual(out['status'],'RUNNING');
  end=time.time()+8; state=None
  while time.time()<end:
   state=m.status('J-A',self.root)
   if state['job']['status'] in {'COMPLETE','FAILED'}: break
   time.sleep(.1)
  self.assertEqual(state['job']['status'],'COMPLETE'); self.assertEqual(state['evidence']['outcome'],'PASS')
 def test_cli_exposes_local_execution_surface(self):
  p=subprocess.run([__import__('sys').executable,str(ROOT/'icm'),'local-exec','collision','["tools/**"]','["tools/a.py"]'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr); self.assertIn('"overlap": true',p.stdout.lower())
if __name__=='__main__': unittest.main()
