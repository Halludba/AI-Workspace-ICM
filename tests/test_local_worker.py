"""Tests for bounded local-worker delegation and fail-closed candidate patches."""
from __future__ import annotations
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("local_worker",ROOT/"tools/local_worker.py"); lw=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(lw)
NAV=importlib.util.spec_from_file_location("source_navigator",ROOT/"tools/source_navigator.py"); nav=importlib.util.module_from_spec(NAV); NAV.loader.exec_module(nav)

class LocalWorkerTests(unittest.TestCase):
    def item(self): return lw.context_item_from_retrieval(nav.retrieve_symbol("tools/context_resolver.py","build_plan",root=ROOT,use_cache=False))
    def job(self,content_item=None):
        return {"schema_version":"1.0","job_id":"JOB-test","architect_role":"icm-runtime-architect","objective":"Propose a bounded test patch.","base_revision":lw._head(ROOT),"context_level":"C1_EXACT_SYMBOL","context_items":[content_item or self.item()],"mutation_scope":["tools/**"],"forbidden_scope":["tools/kernel/**"],"acceptance_criteria":["Patch only the declared tool scope","Propose deterministic tests"]}
    def packet(self): return lw.build_packet(self.job(),ROOT)
    def result(self,status="SUCCESS",path="tools/context_resolver.py"):
        if status=="BLOCKED": patch=""
        elif path=="tools/context_resolver.py": patch='diff --git a/tools/context_resolver.py b/tools/context_resolver.py\n--- a/tools/context_resolver.py\n+++ b/tools/context_resolver.py\n@@ -1,5 +1,5 @@\n #!/usr/bin/env python3\n-"""Build and validate a deterministic context-loading plan."""\n+"""Build and validate a deterministic context-loading plan candidate."""\n from __future__ import annotations\n \n import argparse\n'
        else: patch=f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
        source=self.packet()["context_items"][0]["source_ref"]
        return {"status":status,"changed_files":[] if status=="BLOCKED" else [path],"patch":patch,"tests":[{"command":"python -m unittest tests.test_example","status":"PROPOSED"}],"evidence":[{"source_ref":source,"claim":"Bounded source evidence used."}],"assumptions":[],"unresolved":[]}
    def ready_observation(self):
        return {"schema_version":"1.0","executables":{"ollama":{"available":True}},"features":{},"observation_fingerprint":"a"*64}
    def fake_response(self,result=None):
        return {"model":"ornith-1.5:35b","message":{"role":"assistant","content":json.dumps(result or self.result())},"done":True,"total_duration":1000000,"prompt_eval_count":100,"eval_count":50}

    def test_packet_uses_exact_bounded_context_and_no_whole_repo_kind(self):
        packet=self.packet(); self.assertEqual(packet["context_level"],"C1_EXACT_SYMBOL"); self.assertEqual(len(packet["context_items"]),1); self.assertLess(packet["estimated_tokens"],lw.load_policy(ROOT)["max_packet_estimated_tokens"]); self.assertEqual(packet["execution_authority"],"NONE"); self.assertFalse(packet["canonical_mutation"])
    def test_whole_repository_context_and_oversized_packets_fail_closed(self):
        item=self.item(); item["retrieval_kind"]="WHOLE_REPOSITORY"
        with self.assertRaises(lw.LocalWorkerError): lw.build_packet(self.job(item),ROOT)
        item=self.item(); item["content"]="x"*(lw.load_policy(ROOT)["max_packet_estimated_tokens"]*5)
        with self.assertRaises(lw.LocalWorkerError): lw.build_packet(self.job(item),ROOT)
    def test_stale_base_revision_and_non_runtime_architect_fail_closed(self):
        job=self.job(); job["base_revision"]="0"*40
        with self.assertRaises(lw.LocalWorkerError): lw.build_packet(job,ROOT)
        job=self.job(); job["architect_role"]="icm-system-architect"
        with self.assertRaises(lw.LocalWorkerError): lw.build_packet(job,ROOT)
    def test_result_rejects_unauthorized_or_forbidden_patch_paths(self):
        packet=self.packet()
        with self.assertRaises(lw.LocalWorkerError): lw.validate_result(packet,self.result(path="README.md"),ROOT)
        with self.assertRaises(lw.LocalWorkerError): lw.validate_result(packet,self.result(path="tools/kernel/journal.py"),ROOT)
    def test_private_reasoning_fields_and_false_test_execution_claims_are_rejected(self):
        packet=self.packet(); result=self.result(); result["reasoning"]="hidden"
        with self.assertRaises(lw.LocalWorkerError): lw.validate_result(packet,result,ROOT)
        result=self.result(); result["tests"][0]["status"]="PASS"
        with self.assertRaises(lw.LocalWorkerError): lw.validate_result(packet,result,ROOT)
    def test_candidate_patch_is_validated_but_never_applied(self):
        packet=self.packet(); target=ROOT/"tools/context_resolver.py"; before=target.exists(); out=lw.validate_result(packet,self.result(),ROOT); self.assertEqual(out["authority"],"CANDIDATE_ONLY"); self.assertEqual(target.exists(),before)
    def test_execution_requires_explicit_authorization_assertion(self):
        with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(self.packet(),user_authorized=False,root=ROOT,observation=self.ready_observation(),transport=lambda *a: self.fake_response(),state_root=Path(tempfile.mkdtemp()))
    def test_missing_ollama_preflight_blocks_without_model_call(self):
        obs={"schema_version":"1.0","executables":{"ollama":{"available":False}},"features":{},"observation_fingerprint":"b"*64}
        called=[]
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(self.packet(),user_authorized=True,root=ROOT,observation=obs,transport=lambda *a: called.append(True),state_root=Path(td))
        self.assertEqual(called,[])
    def test_fake_ollama_execution_returns_candidate_and_observed_telemetry_without_raw_reasoning(self):
        packet=self.packet()
        with tempfile.TemporaryDirectory() as td:
            out=lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(),state_root=Path(td))
        self.assertEqual(out["result"]["status"],"SUCCESS"); self.assertEqual(out["result"]["authority"],"CANDIDATE_ONLY"); self.assertFalse(out["raw_provider_response_persisted"]); self.assertFalse(out["private_reasoning_persisted"]); self.assertEqual(out["telemetry"]["metric_availability"]["input_tokens_cached"],"UNAVAILABLE"); self.assertEqual(out["telemetry"]["observed_metrics"]["input_tokens_total"],100)
    def test_malformed_response_and_timeout_fail_closed_and_consume_bounded_attempts(self):
        packet=self.packet()
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:{"model":"ornith-1.5:35b","message":{"content":"not json"}},state_root=state)
            def timeout(*a): raise TimeoutError("timeout")
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=timeout,state_root=state)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(),state_root=state)
    def test_needs_repair_allows_only_one_repair_cycle(self):
        packet=self.packet(); repair=self.result(status="NEEDS_REPAIR")
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            one=lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(repair),state_root=state); self.assertEqual(one["attempt"],1)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(repair),state_root=state)
            two=lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(repair),state_root=state,repair_feedback="Fix the bounded candidate according to architect review."); self.assertEqual(two["attempt"],2)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(),state_root=state)
    def test_success_is_terminal_for_same_packet(self):
        packet=self.packet()
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(),state_root=state)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a:self.fake_response(),state_root=state)

    def test_packet_rejects_context_that_does_not_match_base_revision(self):
        item=self.item(); item["content"] += "\n# drift"
        with self.assertRaises(lw.LocalWorkerError): lw.build_packet(self.job(item),ROOT)

    def test_nonapplicable_patch_fails_closed_before_architect_review(self):
        packet=self.packet(); result=self.result(); result["patch"]=result["patch"].replace("Build and validate a deterministic context-loading plan.","THIS LINE DOES NOT EXIST")
        with self.assertRaises(lw.LocalWorkerError): lw.validate_result(packet,result,ROOT)

    def test_existing_inflight_job_lock_blocks_second_model_call(self):
        packet=self.packet(); policy=lw.load_policy(ROOT); called=[]
        with tempfile.TemporaryDirectory() as td:
            state=Path(td); lock=lw._job_lock_path(packet,ROOT,policy,state); lock.mkdir(parents=True)
            with self.assertRaises(lw.LocalWorkerError): lw.execute_packet(packet,user_authorized=True,root=ROOT,observation=self.ready_observation(),transport=lambda *a: called.append(True),state_root=state)
        self.assertEqual(called,[])

    def test_repair_feedback_changes_dynamic_prompt_plan_not_stable_prefix(self):
        packet=self.packet(); base=lw._attempt_prompt_plan(packet,None,ROOT); repair=lw._attempt_prompt_plan(packet,"correct the patch",ROOT)
        self.assertEqual(base["stable_prefix"]["fingerprint"],repair["stable_prefix"]["fingerprint"]); self.assertNotEqual(base["plan_fingerprint"],repair["plan_fingerprint"])

    def test_workspace_cli_preflight_blocks_cleanly_without_ollama(self):
        import subprocess,sys
        proc=subprocess.run([sys.executable,str(ROOT/"icm"),"worker","preflight"],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        payload=json.loads(proc.stdout); self.assertTrue(payload["valid"]); self.assertEqual(payload["preflight"]["status"],"BLOCKED")

if __name__=="__main__": unittest.main()
