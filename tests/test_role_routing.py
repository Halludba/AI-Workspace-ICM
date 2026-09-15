#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import role_resolver


class RoleRoutingTests(unittest.TestCase):
    def request(self, task_class="GENERAL_ICM", *, mutation=False, authorized=False, paths=None, role=None):
        return {
            "schema_version": "1.0",
            "task_class": task_class,
            "mutation_requested": mutation,
            "mutation_authorized": authorized,
            "requested_paths": list(paths or []),
            "explicit_role": role,
        }

    def test_policy_defaults_to_system_architect(self):
        policy = role_resolver.load_policy()
        self.assertEqual(policy["default_role"], "icm-system-architect")
        self.assertEqual(policy["roles"]["icm-system-architect"]["mutation_mode"], "READ_ONLY")

    def test_general_icm_selects_read_only_system_architect(self):
        result = role_resolver.resolve(self.request())
        self.assertEqual(result["selected_role"], "icm-system-architect")
        self.assertEqual(result["mutation_mode"], "READ_ONLY")
        self.assertFalse(result["mutation_permitted"])

    def test_repository_inspection_does_not_require_runtime_role(self):
        result = role_resolver.resolve(self.request("ARCHITECTURE"))
        self.assertEqual(result["selected_role"], "icm-system-architect")

    def test_runtime_mutation_requires_user_authorization(self):
        blocked = role_resolver.resolve(self.request("RUNTIME_IMPLEMENTATION", mutation=True, paths=["tools/example.py"]))
        self.assertEqual(blocked["selected_role"], "icm-runtime-architect")
        self.assertFalse(blocked["mutation_permitted"])
        self.assertEqual(blocked["mutation_reason"], "USER_AUTHORIZATION_REQUIRED")
        allowed = role_resolver.resolve(self.request("RUNTIME_IMPLEMENTATION", mutation=True, authorized=True, paths=["tools/example.py"]))
        self.assertTrue(allowed["mutation_permitted"])

    def test_role_activation_never_grants_mutation_authority(self):
        result = role_resolver.resolve(self.request("RUNTIME_IMPLEMENTATION"))
        self.assertFalse(result["role_activation_grants_authority"])
        self.assertFalse(result["mutation_permitted"])

    def test_workflow_author_can_mutate_owned_and_supporting_paths(self):
        result = role_resolver.resolve(self.request(
            "WORKFLOW_AUTHORING", mutation=True, authorized=True,
            paths=["workflows/sample/WORKFLOW.json", "tests/test_workflow_contracts.py", "mutation_trace.json"],
        ))
        self.assertEqual(result["selected_role"], "workflow-architect")
        self.assertTrue(result["mutation_permitted"])

    def test_scoped_author_cannot_widen_to_runtime_tools(self):
        with self.assertRaises(role_resolver.RolePolicyError):
            role_resolver.resolve(self.request(
                "WORKFLOW_AUTHORING", mutation=True, authorized=True,
                paths=["tools/run_manager.py"],
            ))

    def test_system_architect_cannot_receive_mutation_scope(self):
        with self.assertRaises(role_resolver.RolePolicyError):
            role_resolver.resolve(self.request("ARCHITECTURE", mutation=True, authorized=True, paths=["README.md"]))

    def test_explicit_role_must_match_task_class(self):
        with self.assertRaises(role_resolver.RolePolicyError):
            role_resolver.resolve(self.request("WORKFLOW_AUTHORING", role="icm-runtime-architect"))

    def handoff(self, target="icm-runtime-architect", revision=None, mutation_scope=None):
        revision = revision or subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
        return {
            "schema_version": "1.0",
            "authority_disclaimer": "NON_AUTHORITATIVE_EXECUTION_HANDOFF",
            "source_role": "icm-system-architect",
            "target_role": target,
            "source_revision": revision,
            "objective": "Implement the accepted role contract.",
            "decisions": ["System Architect is read-only."],
            "invariants": ["Role activation does not authorize mutation."],
            "relevant_paths": ["_core/ROLE_PROTOCOL.md"],
            "mutation_scope": list(mutation_scope or ["tools/role_resolver.py"]),
            "forbidden_scope": ["archive/"],
            "verification": ["Run role-routing tests."],
            "open_questions": ["None material."],
        }

    def test_valid_handoff_is_non_authoritative_and_revision_aware(self):
        result = role_resolver.validate_handoff(self.handoff())
        self.assertTrue(result["valid"])
        self.assertTrue(result["revision_matches_current"])
        self.assertFalse(result["handoff_grants_mutation_authority"])

    def test_stale_handoff_requires_live_revalidation(self):
        result = role_resolver.validate_handoff(self.handoff(revision="0" * 40))
        self.assertFalse(result["revision_matches_current"])
        self.assertTrue(result["requires_live_revalidation"])

    def test_read_only_handoff_cannot_carry_mutation_scope(self):
        with self.assertRaises(role_resolver.RolePolicyError):
            role_resolver.validate_handoff(self.handoff(target="icm-system-architect", mutation_scope=["README.md"]))

    def test_scoped_handoff_rejects_outside_path(self):
        with self.assertRaises(role_resolver.RolePolicyError):
            role_resolver.validate_handoff(self.handoff(target="workflow-architect", mutation_scope=["tools/run_manager.py"]))

    def test_cli_validate_and_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp) / "request.json"
            req.write_text(json.dumps(self.request("WORKFLOW_AUTHORING")), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / "tools/role_resolver.py"), "resolve", str(req)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["selected_role"], "workflow-architect")

    def test_workspace_cli_role_surface(self):
        proc = subprocess.run([sys.executable, str(ROOT / "icm"), "role", "validate"], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["default_role"], "icm-system-architect")


if __name__ == "__main__":
    unittest.main()
