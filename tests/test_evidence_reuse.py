import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=importlib.util.spec_from_file_location('evidence_reuse',ROOT/'tools/evidence_reuse.py'); m=importlib.util.module_from_spec(S); S.loader.exec_module(m)
class EvidenceReuseTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/'config').mkdir(); (self.root/'config/evidence_reuse_policy.json').write_text((ROOT/'config/evidence_reuse_policy.json').read_text(),encoding='utf-8'); subprocess.run(['git','init','-q'],cwd=self.root,check=True); subprocess.run(['git','config','user.email','t@example.invalid'],cwd=self.root,check=True); subprocess.run(['git','config','user.name','T'],cwd=self.root,check=True); (self.root/'a.txt').write_text('a\n'); subprocess.run(['git','add','.'],cwd=self.root,check=True); subprocess.run(['git','commit','-qm','base'],cwd=self.root,check=True)
 def tearDown(self): self.t.cleanup()
 def req(self,fp='aaa',vol='CONTENT_ADDRESSED',env=None): return {'producer':'validator','producer_version':'1','volatility':vol,'inputs':[{'ref':'a','kind':'FILE','fingerprint':fp}],'environment_fingerprint':env}
 def test_key_is_order_independent_and_changes_with_dependency(self):
  a=self.req(); a['inputs'].append({'ref':'b','kind':'CONFIG','fingerprint':'bbb'}); b=dict(a); b['inputs']=list(reversed(a['inputs'])); self.assertEqual(m.evidence_key(a,self.root)['key'],m.evidence_key(b,self.root)['key']); self.assertNotEqual(m.evidence_key(self.req('ccc'),self.root)['key'],m.evidence_key(self.req('aaa'),self.root)['key'])
 def test_store_hit_and_changed_input_miss(self):
  r={**self.req(),'result_summary':'validated unchanged','evidence_refs':['test:x']}; self.assertTrue(m.store(r,self.root)['stored']); self.assertEqual(m.lookup(self.req(),self.root)['status'],'HIT'); self.assertEqual(m.lookup(self.req('changed'),self.root)['status'],'MISS')
 def test_volatile_is_never_reused(self):
  q=self.req(vol='VOLATILE'); self.assertFalse(m.store({**q,'result_summary':'now','evidence_refs':[]},self.root)['stored']); self.assertEqual(m.lookup(q,self.root)['status'],'BYPASS_VOLATILE')
 def test_environment_dependent_requires_environment(self):
  with self.assertRaises(m.EvidenceReuseError): m.evidence_key(self.req(vol='ENVIRONMENT_DEPENDENT'),self.root)
 def test_repository_fingerprint_detects_worktree_staged_and_untracked(self):
  base=m.repository_fingerprint(root=self.root)['fingerprint']; (self.root/'a.txt').write_text('b\n'); work=m.repository_fingerprint(root=self.root)['fingerprint']; self.assertNotEqual(base,work); subprocess.run(['git','add','a.txt'],cwd=self.root,check=True); staged=m.repository_fingerprint(root=self.root)['fingerprint']; self.assertNotEqual(work,staged); (self.root/'u.txt').write_text('u'); untracked=m.repository_fingerprint(root=self.root)['fingerprint']; self.assertNotEqual(staged,untracked)
 def test_path_scoped_repository_fingerprint_declares_partial_scope(self):
  r=m.repository_fingerprint(['a.txt'],self.root); self.assertEqual(r['scope'],'PATHS'); self.assertEqual(r['paths'],['a.txt'])
 def test_reproducible_host_fact_reuses_only_same_environment(self):
  f={'fact_id':'powershell:utf8-writer','classification':'ENVIRONMENT_DEPENDENT','value':'DOTNET_UTF8_NO_BOM','cause':'legacy writer behavior','reproducible':True,'evidence_refs':['run:1'],'environment_fingerprint':'env1'}; self.assertTrue(m.record_host_fact(f,self.root)['stored']); self.assertEqual(m.lookup_host_fact(f['fact_id'],'env1',self.root)['status'],'HIT'); self.assertEqual(m.lookup_host_fact(f['fact_id'],'env2',self.root)['status'],'INVALIDATED_ENVIRONMENT')
 def test_transient_failure_is_not_durable(self):
  f={'fact_id':'network:timeout','classification':'TRANSIENT','value':'timeout','cause':'one request','reproducible':False,'evidence_refs':['run:1'],'environment_fingerprint':'env1'}; self.assertFalse(m.record_host_fact(f,self.root)['stored'])
 def test_workspace_cli_exposes_evidence_surface(self):
  p=subprocess.run([__import__('sys').executable,str(ROOT/'icm'),'evidence','repo-fingerprint'],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr); self.assertIn('fingerprint',p.stdout)
if __name__=='__main__': unittest.main()
