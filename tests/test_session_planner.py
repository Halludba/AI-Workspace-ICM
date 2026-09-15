#!/usr/bin/env python3
"""Adversarial tests for the ephemeral ICM session planner."""
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

import session_planner


class SessionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_obj.name)
        (self.root / "config").mkdir()
        shutil.copy(ROOT / "config/session_policy.json", self.root / "config/session_policy.json")
        shutil.copy(ROOT / "config/routes.json", self.root / "config/routes.json")
        self.policy = session_planner.load_session_policy(self.root)

    def tearDown(self):
        self.tmp_obj.cleanup()

    def task(self, task_id, *, depends=None, status="PENDING", user_order=None,
             user_ref=None, priority="NORMAL", scope="SCOPED", route="tool-development"):
        return {
            "task_id": task_id,
            "route_id": route,
            "stage_id": None,
            "title": f"Task {task_id}",
            "status": status,
            "depends_on": list(depends or []),
            "user_order": user_order,
            "user_directive_ref": user_ref,
            "priority_class": priority,
            "declared_scope": scope,
        }

    def plan(self, tasks=None, *, agent_id="chatgpt56"):
        return {
            "schema_version": "1.0",
            "session_id": "session-2026-09-15",
            "agent_id": agent_id,
            "agent_role": "Systems Kernel Architect",
            "created_utc": "2026-09-15T10:00:00+10:00",
            "updated_utc": "2026-09-15T10:00:00+10:00",
            "authority_disclaimer": "NON_AUTHORITATIVE_INTENT_QUEUE",
            "active_run_id": None,
            "tasks": tasks or [self.task("T-01")],
            "auto_delete_on_empty": True,
        }

    def test_valid_plan_passes(self):
        result = session_planner.validate_plan(self.plan(), self.policy, root=self.root)
        self.assertTrue(result["valid"])

    def test_unknown_route_fails(self):
        plan = self.plan([self.task("T-01", route="does-not-exist")])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_dependency_cycle_fails(self):
        plan = self.plan([
            self.task("T-01", depends=["T-02"]),
            self.task("T-02", depends=["T-01"]),
        ])
        with self.assertRaises(session_planner.SessionPlanError) as ctx:
            session_planner.validate_plan(plan, self.policy, root=self.root)
        self.assertIn("dependency cycle", str(ctx.exception))

    def test_unknown_dependency_fails(self):
        plan = self.plan([self.task("T-01", depends=["T-99"])])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_two_in_progress_tasks_fail(self):
        plan = self.plan([
            self.task("T-01", status="IN_PROGRESS"),
            self.task("T-02", status="IN_PROGRESS"),
        ])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_in_progress_requires_completed_dependencies(self):
        plan = self.plan([
            self.task("T-01"),
            self.task("T-02", depends=["T-01"], status="IN_PROGRESS"),
        ])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_blocked_requires_reason(self):
        plan = self.plan([self.task("T-01", status="BLOCKED")])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_user_order_requires_directive_reference(self):
        plan = self.plan([self.task("T-01", user_order=1)])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_duplicate_user_order_fails(self):
        plan = self.plan([
            self.task("T-01", user_order=1, user_ref="user:1"),
            self.task("T-02", user_order=1, user_ref="user:1"),
        ])
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_agent_namespace_rejects_traversal(self):
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.plan_path("../escape", self.root, self.policy)

    def test_explicit_user_order_overrides_correctness_class(self):
        plan = self.plan([
            self.task("T-01", user_order=1, user_ref="user:priority", priority="NORMAL"),
            self.task("T-02", priority="CORRECTNESS_REPAIR"),
        ])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-01")

    def test_correctness_repair_beats_normal_without_user_override(self):
        plan = self.plan([
            self.task("T-01", priority="NORMAL"),
            self.task("T-02", priority="CORRECTNESS_REPAIR"),
        ])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-02")

    def test_unlock_count_breaks_priority_tie(self):
        plan = self.plan([
            self.task("T-01"),
            self.task("T-02"),
            self.task("T-03", depends=["T-01"]),
        ])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-01")
        self.assertEqual(selected["derived_unlock_count"], 1)

    def test_scoped_beats_global_as_late_tie_break(self):
        plan = self.plan([
            self.task("T-01", scope="GLOBAL"),
            self.task("T-02", scope="SCOPED"),
        ])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-02")

    def test_creation_order_is_final_tie_break(self):
        plan = self.plan([self.task("T-02"), self.task("T-01")])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-02")

    def test_in_progress_task_is_resumed_before_new_selection(self):
        plan = self.plan([self.task("T-01", status="IN_PROGRESS"), self.task("T-02")])
        selected = session_planner.select_next_task(plan, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-01")
        self.assertEqual(selected["selection_reason"], "resume_in_progress")

    def test_install_uses_agent_namespaced_path(self):
        plan = self.plan(agent_id="agent-one")
        path = session_planner.install_plan(plan, self.root, self.policy)
        self.assertEqual(path.relative_to(self.root).as_posix(), ".session/plans/agent-one.json")
        self.assertTrue(path.is_file())

    def test_start_rejects_nonselected_task(self):
        plan = self.plan([
            self.task("T-01", priority="CORRECTNESS_REPAIR"),
            self.task("T-02")
        ])
        session_planner.install_plan(plan, self.root, self.policy)
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.start_task("chatgpt56", "T-02", self.root, self.policy)

    def test_start_block_resume_lifecycle(self):
        plan = self.plan()
        session_planner.install_plan(plan, self.root, self.policy)
        session_planner.start_task("chatgpt56", "T-01", self.root, self.policy)
        blocked = session_planner.block_task("chatgpt56", "T-01", "waiting", self.root, self.policy)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertTrue(session_planner.plan_path("chatgpt56", self.root, self.policy).exists())
        resumed = session_planner.resume_task("chatgpt56", "T-01", self.root, self.policy)
        self.assertEqual(resumed["status"], "PENDING")

    def test_final_completion_self_deletes_plan(self):
        plan = self.plan()
        path = session_planner.install_plan(plan, self.root, self.policy)
        session_planner.start_task("chatgpt56", "T-01", self.root, self.policy)
        result = session_planner.complete_task("chatgpt56", "T-01", self.root, self.policy)
        self.assertTrue(result["deleted"])
        self.assertFalse(path.exists())

    def test_blocked_task_prevents_auto_delete(self):
        task = self.task("T-01", status="BLOCKED")
        task["status_reason"] = "external dependency"
        plan = self.plan([task])
        path = session_planner.install_plan(plan, self.root, self.policy)
        self.assertTrue(path.exists())
        self.assertIsNone(session_planner.select_next_task(plan, self.policy, root=self.root))

    def test_installing_already_completed_plan_leaves_no_file(self):
        plan = self.plan([self.task("T-01", status="COMPLETED")])
        path = session_planner.install_plan(plan, self.root, self.policy)
        self.assertIsNone(path)
        self.assertFalse(session_planner.plan_path("chatgpt56", self.root, self.policy).exists())

    def test_completion_unlocks_dependent_task(self):
        plan = self.plan([
            self.task("T-01"),
            self.task("T-02", depends=["T-01"]),
        ])
        session_planner.install_plan(plan, self.root, self.policy)
        session_planner.start_task("chatgpt56", "T-01", self.root, self.policy)
        session_planner.complete_task("chatgpt56", "T-01", self.root, self.policy)
        loaded = session_planner.load_plan("chatgpt56", self.root, self.policy)
        selected = session_planner.select_next_task(loaded, self.policy, root=self.root)
        self.assertEqual(selected["task_id"], "T-02")

    def test_authority_disclaimer_is_exact(self):
        plan = self.plan()
        plan["authority_disclaimer"] = "AUTHORITATIVE"
        with self.assertRaises(session_planner.SessionPlanError):
            session_planner.validate_plan(plan, self.policy, root=self.root)

    def test_gitignore_excludes_session_root(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".session/", text.splitlines())

    def test_cli_validate_reports_next_task(self):
        source = self.root / "plan.json"
        source.write_text(json.dumps(self.plan(), indent=2), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/session_planner.py"), "--root", str(self.root), "validate", str(source)],
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["next_task"]["task_id"], "T-01")
        self.assertIn("derived_unlock_count", payload["next_task"])

    def test_malformed_priority_policy_fails_cleanly(self):
        policy_path = self.root / "config/session_policy.json"
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        data["priority_class_rank"] = {"NORMAL": 0}
        policy_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(session_planner.PolicyError):
            session_planner.load_session_policy(self.root)
