import importlib.util,json,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SL=importlib.util.spec_from_file_location("local_execution",ROOT/"tools/local_execution.py"); le=importlib.util.module_from_spec(SL); SL.loader.exec_module(le)
SB=importlib.util.spec_from_file_location("local_capability_broker",ROOT/"tools/local_capability_broker.py"); b=importlib.util.module_from_spec(SB); SB.loader.exec_module(b)
class BrokerTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/"config").mkdir(); (self.root/"tests").mkdir(); shutil.copy(ROOT/"config/local_execution_policy.json",self.root/"config/local_execution_policy.json"); shutil.copy(ROOT/"config/local_capability_broker_policy.json",self.root/"config/local_capability_broker_policy.json"); (self.root/"tests/test_t.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n"); (self.root/"a.py").write_text("VALUE=1\n"); subprocess.run(["git","init","-q"],cwd=self.root,check=True); subprocess.run(["git","config","user.email","t@example.invalid"],cwd=self.root,check=True); subprocess.run(["git","config","user.name","T"],cwd=self.root,check=True); subprocess.run(["git","add","."],cwd=self.root,check=True); subprocess.run(["git","commit","-qm","base"],cwd=self.root,check=True); self.head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=self.root,text=True).strip(); self.jobs=[]
 def tearDown(self):
  for j in self.jobs:
   try: le.cleanup(j,self.root)
   except Exception: pass
  shutil.rmtree(self.root.parent/(self.root.name+".icm-worktrees"),ignore_errors=True); self.t.cleanup()
 def req(self,kind,target,cap,args): return {"schema_version":"1.0","target_kind":kind,"target_id":target,"capability":cap,"args":args}
 def test_snapshot_search_and_read_use_dirty_live_state(self):
  (self.root/"a.py").write_text("VALUE=9\nneedle_here=True\n"); le.create_live_snapshot("S",[],self.root); out=b.execute(self.req("LIVE_SNAPSHOT","S","SOURCE_SEARCH",{"query":"needle_here","paths":["."]}),self.root); self.assertEqual(out["result"]["hits"][0]["path"],"a.py"); read=b.execute(self.req("LIVE_SNAPSHOT","S","SOURCE_READ",{"path":"a.py","start_line":1,"end_line":2}),self.root); self.assertIn("VALUE=9",read["result"]["text"])
 def test_snapshot_named_test_suite_runs_without_shell_surface(self):
  le.create_live_snapshot("S2",[],self.root); out=b.execute(self.req("LIVE_SNAPSHOT","S2","TEST_SUITE",{"suite":"FULL_REGRESSION"}),self.root); self.assertEqual(out["result"]["outcome"],"PASS"); self.assertFalse(out["arbitrary_shell_used"])
 def test_patch_validation_is_confined_to_isolated_scope(self):
  st=le.create_job({"job_id":"J","mode":"ISOLATED_MUTATION","base_revision":self.head,"suite":None,"mutation_scope":["a.py"],"owner":"test"},self.root); self.jobs.append("J"); patch="diff --git a/a.py b/a.py\nindex 5ef3f36..0ca4d70 100644\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-VALUE=1\n+VALUE=2\n"; out=b.execute(self.req("ISOLATED_JOB","J","PATCH_VALIDATE",{"patch":patch}),self.root); self.assertTrue(out["result"]["valid"]); bad=patch.replace("a.py","tests/test_t.py");
  with self.assertRaises(b.BrokerError): b.execute(self.req("ISOLATED_JOB","J","PATCH_VALIDATE",{"patch":bad}),self.root)
 def test_unknown_or_arbitrary_capability_rejected(self):
  le.create_live_snapshot("S3",[],self.root)
  with self.assertRaises(b.BrokerError): b.execute(self.req("LIVE_SNAPSHOT","S3","RUN_COMMAND",{"command":"whoami"}),self.root)
 def test_cli_exposes_broker_surface(self):
  p=subprocess.run([__import__("sys").executable,str(ROOT/"icm"),"broker","--help"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr)
if __name__=="__main__": unittest.main()
