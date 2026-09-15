import importlib.util,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/("tools/"+name+".py")); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
le=load("local_execution"); a=load("local_worker_agent")
class AgentTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); (self.root/"config").mkdir(); (self.root/"tests").mkdir();
  for f in ["local_execution_policy.json","local_capability_broker_policy.json","local_worker_agent_policy.json","local_worker_policy.json","context_runtime_policy.json","source_navigator_policy.json"]:
   shutil.copy(ROOT/"config"/f,self.root/"config"/f)
  (self.root/"tests/test_t.py").write_text("import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n"); (self.root/"a.py").write_text("VALUE=1\nneedle=True\n"); subprocess.run(["git","init","-q"],cwd=self.root,check=True); subprocess.run(["git","config","user.email","t@example.invalid"],cwd=self.root,check=True); subprocess.run(["git","config","user.name","T"],cwd=self.root,check=True); subprocess.run(["git","add","."],cwd=self.root,check=True); subprocess.run(["git","commit","-qm","base"],cwd=self.root,check=True); self.head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=self.root,text=True).strip(); self.jobs=[]
 def tearDown(self):
  for j in self.jobs:
   try: le.cleanup(j,self.root)
   except Exception: pass
  shutil.rmtree(self.root.parent/(self.root.name+".icm-worktrees"),ignore_errors=True); self.t.cleanup()
 def req(self,kind,target): return {"schema_version":"1.0","job_id":"A-1","target_kind":kind,"target_id":target,"objective":"Find needle and report."}
 def test_bounded_snapshot_discovery_returns_snapshot_bound_result(self):
  snap=le.create_live_snapshot("S",[],self.root); actions=iter([{"kind":"TOOL","capability":"SOURCE_SEARCH","args":{"query":"needle","paths":["."]},"status":None,"summary":None,"patch":None},{"kind":"TOOL","capability":"SOURCE_READ","args":{"path":"a.py","start_line":1,"end_line":2},"status":None,"summary":None,"patch":None},{"kind":"FINAL","capability":None,"args":{},"status":"SUCCESS","summary":"Found exact source.","patch":""}]); out=a.run_agent(self.req("LIVE_SNAPSHOT","S"),self.root,transport=lambda m: next(actions)); self.assertEqual(out["tool_calls"],2); self.assertEqual(out["target"]["snapshot_fingerprint"],snap["snapshot_fingerprint"]); self.assertFalse(out["canonical_mutation"])
 def test_tool_budget_fails_closed(self):
  le.create_live_snapshot("S2",[],self.root); action={"kind":"TOOL","capability":"SOURCE_SEARCH","args":{"query":"x","paths":["."]},"status":None,"summary":None,"patch":None};
  with self.assertRaisesRegex(a.LocalAgentError,"tool-call budget"): a.run_agent(self.req("LIVE_SNAPSHOT","S2"),self.root,transport=lambda m: action)
 def test_snapshot_worker_cannot_return_patch(self):
  le.create_live_snapshot("S3",[],self.root); final={"kind":"FINAL","capability":None,"args":{},"status":"SUCCESS","summary":"candidate","patch":"diff --git a/a.py b/a.py\n"};
  with self.assertRaisesRegex(a.LocalAgentError,"snapshot worker"): a.run_agent(self.req("LIVE_SNAPSHOT","S3"),self.root,transport=lambda m: final)
 def test_isolated_worker_patch_is_deterministically_validated(self):
  le.create_job({"job_id":"J","mode":"ISOLATED_MUTATION","base_revision":self.head,"suite":None,"mutation_scope":["a.py"],"owner":"test"},self.root); self.jobs.append("J"); patch="diff --git a/a.py b/a.py\nindex 07f7ec5..252f0d5 100644\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-VALUE=1\n+VALUE=2\n needle=True\n"; final={"kind":"FINAL","capability":None,"args":{},"status":"SUCCESS","summary":"candidate","patch":patch}; out=a.run_agent(self.req("ISOLATED_JOB","J"),self.root,transport=lambda m: final); self.assertTrue(out["patch_validation"]["result"]["valid"]); self.assertFalse(out["automatic_patch_apply"])
 def test_cli_surface(self):
  p=subprocess.run([__import__("sys").executable,str(ROOT/"icm"),"worker","agent","--help"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(p.returncode,0,p.stderr)
if __name__=="__main__": unittest.main()
