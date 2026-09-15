"""Tests for read-only local compute capability discovery."""
from __future__ import annotations
import importlib.util,json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("local_compute",ROOT/"tools/local_compute.py"); lc=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(lc)
class LocalComputeTests(unittest.TestCase):
    def observation(self,ffmpeg=False,ollama=False,nvidia=True,nvenc=False):
        return {"schema_version":"1.0","executables":{"ffmpeg":{"available":ffmpeg},"ollama":{"available":ollama},"python":{"available":True},"ffprobe":{"available":ffmpeg},"nvidia-smi":{"available":nvidia}},"features":{"NVIDIA_GPU":{"status":"AVAILABLE" if nvidia else "UNAVAILABLE"},"NVENC":{"status":"AVAILABLE" if nvenc else ("BLOCKED_MISSING_EXECUTABLE" if nvidia and not ffmpeg else "UNAVAILABLE_ENCODER")}},"observation_fingerprint":"a"*64}
    def test_policy_contains_no_machine_specific_observation(self):
        raw=(ROOT/"config/local_compute_policy.json").read_text(encoding="utf-8").lower(); self.assertNotIn("4070",raw); self.assertNotIn("616.64",raw); self.assertNotIn("abdullah",raw)
    def test_discovery_is_observational_and_grants_no_authority(self):
        result=lc.discover(ROOT); self.assertEqual(result["authority"],"OBSERVATIONAL_NONCANONICAL"); self.assertEqual(result["execution_authority"],"NONE"); self.assertEqual(result["mutation_authority"],"NONE")
    def test_video_workload_blocks_when_ffmpeg_is_missing(self):
        result=lc.resolve_workload("VIDEO_TRANSCODE_NVENC",self.observation(ffmpeg=False,nvidia=True),ROOT); self.assertEqual(result["status"],"BLOCKED"); self.assertIn({"kind":"EXECUTABLE","name":"ffmpeg"},result["missing"])
    def test_video_workload_can_be_ready_without_local_chatgpt(self):
        result=lc.resolve_workload("VIDEO_TRANSCODE_NVENC",self.observation(ffmpeg=True,nvidia=True,nvenc=True),ROOT); self.assertEqual(result["status"],"READY"); self.assertEqual(result["execution_authority"],"NONE")
    def test_ollama_worker_blocks_explicitly_when_executable_missing(self):
        result=lc.resolve_workload("LOCAL_OLLAMA_WORKER",self.observation(ollama=False),ROOT); self.assertEqual(result["status"],"BLOCKED"); self.assertEqual(result["missing"],[{"kind":"EXECUTABLE","name":"ollama"}])
    def test_unknown_workload_fails_closed(self):
        with self.assertRaises(lc.LocalComputeError): lc.resolve_workload("SHELL_ANYTHING",self.observation(),ROOT)
    def test_cli_discovery_and_resolution_are_read_only_surfaces(self):
        proc=subprocess.run([sys.executable,str(ROOT/"icm"),"inspect","compute","discover"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr); data=json.loads(proc.stdout); self.assertEqual(data["execution_authority"],"NONE")
        proc=subprocess.run([sys.executable,str(ROOT/"icm"),"inspect","compute","resolve","LOCAL_OLLAMA_WORKER"],cwd=ROOT,text=True,capture_output=True); self.assertEqual(proc.returncode,0,proc.stderr); self.assertIn(json.loads(proc.stdout)["status"],["READY","BLOCKED"])
if __name__=="__main__": unittest.main()
