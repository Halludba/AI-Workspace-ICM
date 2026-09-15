#!/usr/bin/env python3
"""Adversarial tests for verification impact classification."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import impact_classifier


class ImpactClassifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp_obj.name)
        (self.repo / "config").mkdir()
        shutil.copy(ROOT / "config" / "impact_policy.json", self.repo / "config" / "impact_policy.json")
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "ICM Tests")
        self.write("README.md", "# Test\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")

    def tearDown(self):
        self.tmp_obj.cleanup()

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=str(self.repo), text=True, capture_output=True)
        if proc.returncode != 0:
            self.fail(proc.stderr)
        return proc.stdout

    def write(self, rel: str, text: str) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def classify(self, **kwargs):
        return impact_classifier.classify_change(self.repo, **kwargs)

    def test_no_changes_is_scoped_and_commit_gate_remains_full(self):
        result = self.classify()
        self.assertEqual(result["impact"], "SCOPED_VALIDATION")
        self.assertEqual(result["reasons"], ["no_canonical_changes"])
        self.assertEqual(result["canonical_commit_verification"], "FULL_REGRESSION")
        self.assertTrue(result["full_regression_before_canonical_commit"])

    def test_readme_only_change_is_scoped(self):
        self.write("README.md", "# Changed\n")
        result = self.classify()
        self.assertEqual(result["impact"], "SCOPED_VALIDATION")
        self.assertEqual(result["reasons"], ["bounded_noncritical_change"])

    def test_core_convention_change_requires_full_regression(self):
        self.write("_core/CONVENTIONS.md", "authority\n")
        result = self.classify()
        self.assertEqual(result["impact"], "FULL_REGRESSION")
        self.assertTrue(any(reason.startswith("sensitive_path:") for reason in result["reasons"]))

    def test_config_change_requires_full_regression(self):
        self.write("config/example.json", "{}\n")
        result = self.classify()
        self.assertEqual(result["impact"], "FULL_REGRESSION")
        self.assertTrue(any(reason.startswith("sensitive_prefix:") for reason in result["reasons"]))

    def test_kernel_change_requires_full_regression(self):
        self.write("tools/kernel/example.py", "VALUE = 1\n")
        self.assertEqual(self.classify()["impact"], "FULL_REGRESSION")

    def test_profile_change_is_scoped(self):
        self.write("profiles/a/PROFILE.md", "# Profile\n")
        self.assertEqual(self.classify()["impact"], "SCOPED_VALIDATION")

    def test_generic_workflow_change_is_scoped(self):
        self.write("workflows/sample/STAGE.json", "{}\n")
        self.assertEqual(self.classify()["impact"], "SCOPED_VALIDATION")

    def test_workflow_template_change_is_full(self):
        self.write("workflows/_template/STAGE.json", "{}\n")
        self.assertEqual(self.classify()["impact"], "FULL_REGRESSION")

    def test_test_only_change_is_scoped(self):
        self.write("tests/test_example.py", "def test_ok(): pass\n")
        self.assertEqual(self.classify()["impact"], "SCOPED_VALIDATION")

    def test_untracked_sensitive_file_is_seen(self):
        self.write("config/new_policy.json", "{}\n")
        result = self.classify()
        self.assertIn("config/new_policy.json", result["changed_paths"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_staged_mode_excludes_unstaged_changes(self):
        self.write("README.md", "# staged\n")
        self.git("add", "README.md")
        self.write("config/unstaged.json", "{}\n")
        result = self.classify(staged=True)
        self.assertEqual(result["changed_paths"], ["README.md"])
        self.assertEqual(result["impact"], "SCOPED_VALIDATION")

    def test_sensitive_semantic_token_escalates_generic_tool(self):
        self.write("tools/helper.py", "authority = 'changed'\n")
        result = self.classify()
        self.assertEqual(result["impact"], "FULL_REGRESSION")
        self.assertTrue(any(reason.startswith("sensitive_semantics:") for reason in result["reasons"]))

    def test_generic_tool_without_sensitive_semantics_is_scoped(self):
        self.write("tools/helper.py", "VALUE = 'ordinary'\n")
        self.assertEqual(self.classify()["impact"], "SCOPED_VALIDATION")

    def test_ignored_pyc_is_excluded(self):
        self.write("tools/__pycache__/x.pyc", "bytes")
        result = self.classify()
        self.assertEqual(result["canonical_changed_paths"], [])
        self.assertIn("tools/__pycache__/x.pyc", result["ignored_paths"])

    def test_semver_is_explicitly_out_of_scope(self):
        self.write("README.md", "# change\n")
        self.assertEqual(self.classify()["semver_classification"], "OUT_OF_SCOPE")

    def test_explicit_sensitive_path_is_full(self):
        result = self.classify(paths=["tools/run_manager.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_assurance_controller_change_requires_full_regression(self):
        result = self.classify(paths=["tools/assurance_controller.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_token_profiler_change_requires_full_regression(self):
        result = self.classify(paths=["tools/token_profiler.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_capability_resolver_change_requires_full_regression(self):
        result = self.classify(paths=["tools/capability_resolver.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_capsule_exporter_change_requires_full_regression(self):
        result = self.classify(paths=["tools/capsule_exporter.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_capability_registry_change_requires_full_regression(self):
        result = self.classify(paths=["skills/registry.json"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_malformed_policy_fails_cleanly(self):
        (self.repo / "config/impact_policy.json").write_text("{}\n", encoding="utf-8")
        with self.assertRaises(impact_classifier.PolicyError):
            impact_classifier.load_impact_policy(self.repo)

    def test_policy_cannot_weaken_commit_gate(self):
        policy = json.loads((self.repo / "config/impact_policy.json").read_text(encoding="utf-8"))
        policy["canonical_commit_scope"] = "SCOPED_VALIDATION"
        (self.repo / "config/impact_policy.json").write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(impact_classifier.PolicyError):
            impact_classifier.load_impact_policy(self.repo)

    def test_policy_cannot_mix_semver_into_scope(self):
        policy = json.loads((self.repo / "config/impact_policy.json").read_text(encoding="utf-8"))
        policy["semver_classification"] = "MAJOR"
        (self.repo / "config/impact_policy.json").write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(impact_classifier.PolicyError):
            impact_classifier.load_impact_policy(self.repo)

    def test_non_git_directory_fails(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / "config").mkdir()
            shutil.copy(ROOT / "config/impact_policy.json", path / "config/impact_policy.json")
            with self.assertRaises(impact_classifier.ImpactError):
                impact_classifier.classify_change(path)

    def test_cli_returns_structured_result(self):
        self.write("README.md", "# cli\n")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "impact_classifier.py"), "--repo", str(self.repo)],
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["impact"], "SCOPED_VALIDATION")
        self.assertEqual(payload["canonical_commit_verification"], "FULL_REGRESSION")

    def test_role_resolver_change_requires_full_regression(self):
        result = self.classify(paths=["tools/role_resolver.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_context_benchmark_change_requires_full_regression(self):
        result = self.classify(paths=["tools/context_benchmark.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_context_escalation_change_requires_full_regression(self):
        result = self.classify(paths=["tools/context_escalation.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_context_runtime_change_requires_full_regression(self):
        result = self.classify(paths=["tools/context_runtime.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_local_compute_change_requires_full_regression(self):
        result = self.classify(paths=["tools/local_compute.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_meta_advisor_change_requires_full_regression(self):
        result = self.classify(paths=["tools/meta_advisor.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_evaluation_arena_change_requires_full_regression(self):
        result = self.classify(paths=["tools/evaluation_arena.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_developer_observatory_change_requires_full_regression(self):
        result = self.classify(paths=["tools/developer_observatory.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_plan_intelligence_change_requires_full_regression(self):
        result = self.classify(paths=["tools/plan_intelligence.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")

    def test_local_worker_change_requires_full_regression(self):
        result = self.classify(paths=["tools/local_worker.py"])
        self.assertEqual(result["impact"], "FULL_REGRESSION")


if __name__ == "__main__":
    unittest.main()
