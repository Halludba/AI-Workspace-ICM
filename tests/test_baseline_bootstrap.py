import importlib.util,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('baseline_bootstrap',ROOT/'tools/baseline_bootstrap.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class BootstrapTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/'config').mkdir(); shutil.copy(ROOT/'config/bootstrap_policy.json',self.root/'config/bootstrap_policy.json')
  for rel in ['WORKSPACE.md','CONTEXT.md','WORKSPACE.json','config/routes.json','config/role_policy.json']:
   p=self.root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(rel+'\n',encoding='utf-8')
  subprocess.run(['git','init','-q'],cwd=self.root,check=True); subprocess.run(['git','config','user.email','t@example.invalid'],cwd=self.root,check=True); subprocess.run(['git','config','user.name','T'],cwd=self.root,check=True); subprocess.run(['git','add','.'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','base'],cwd=self.root,check=True)
 def tearDown(self): self.t.cleanup()
 def test_unchanged_baseline_reuses_without_repo_rediscovery(self):
  m.capture('b',self.root); d=m.delta('b',self.root); self.assertTrue(d['baseline_reusable']); self.assertEqual(d['bootstrap_mode'],'REUSE_BASELINE'); self.assertEqual(d['changed_paths'],[])
 def test_dirty_change_produces_delta_not_false_reuse(self):
  m.capture('b',self.root); (self.root/'x.py').write_text('x\n'); d=m.delta('b',self.root); self.assertFalse(d['baseline_reusable']); self.assertIn('x.py',d['changed_paths']); self.assertEqual(d['bootstrap_mode'],'BASELINE_PLUS_DELTA')
 def test_governing_change_forces_exact_source_escalation(self):
  m.capture('b',self.root); (self.root/'WORKSPACE.md').write_text('changed\n'); d=m.delta('b',self.root); self.assertTrue(d['exact_source_escalation_required']); self.assertIn('WORKSPACE.md',d['governing_paths_changed'])
 def test_commit_move_reports_committed_delta(self):
  m.capture('b',self.root); (self.root/'new.py').write_text('new\n'); subprocess.run(['git','add','new.py'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','move'],cwd=self.root,check=True); d=m.delta('b',self.root); self.assertIn('new.py',d['changed_paths']); self.assertFalse(d['baseline_reusable'])
 def test_session_cache_is_not_reported_as_change(self):
  m.capture('b',self.root); (self.root/'.session/foo').mkdir(parents=True); (self.root/'.session/foo/a').write_text('x'); self.assertEqual(m.delta('b',self.root)['changed_paths'],[])
if __name__=='__main__': unittest.main()
