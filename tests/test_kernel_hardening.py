import json
import os
import random
import shutil
import socket
import tempfile
import unittest
from pathlib import Path

from tools import create_workflow, run_manager, run_validator, workflow_validator
from tools.init import initialize_run
from tools.kernel import journal
from tools.kernel.events import JournalError, KernelError, LockError, LockRecoveryRequired
from tools.kernel import lock as kernel_lock_module
from tools.kernel.lock import kernel_lock, probe_process

ROOT = Path(__file__).resolve().parents[1]


class KernelHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.workflows = self.tmp / "workflows"
        self.work = self.tmp / "work"
        self.workflows.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self.tmp_obj.cleanup()

    def make_workflow(self):
        workflow = create_workflow.scaffold(
            "sample-flow", ["intake", "verify"], destination_root=self.workflows
        )
        path = workflow / "WORKFLOW.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "ACTIVE"
        data["executable"] = True
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return workflow

    def make_run(self, suffix="hardening"):
        if not (self.workflows / "sample-flow").is_dir():
            self.make_workflow()
        return initialize_run(
            "sample-flow",
            f"2026-09-15_{suffix}",
            workflow_root=self.workflows,
            destination_root=self.work,
            operation_id=f"CREATE-{suffix}",
        )

    def test_workflow_wrong_root_types_fail_cleanly(self):
        workflow = self.make_workflow()
        for value in ([], "hello", 42):
            (workflow / "WORKFLOW.json").write_text(json.dumps(value), encoding="utf-8")
            errors = workflow_validator.validate_workflow(workflow)
            self.assertTrue(any("root must be a JSON object" in error for error in errors))
            self.make_workflow_fresh(workflow)

    def make_workflow_fresh(self, target):
        shutil.rmtree(target)
        fresh = create_workflow.scaffold(
            "sample-flow", ["intake", "verify"], destination_root=self.workflows
        )
        path = fresh / "WORKFLOW.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "ACTIVE"
        data["executable"] = True
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_stage_wrong_root_type_fails_cleanly(self):
        workflow = self.make_workflow()
        stage = workflow / "01-intake/STAGE.json"
        stage.write_text('"hello"\n', encoding="utf-8")
        errors = workflow_validator.validate_workflow(workflow)
        self.assertTrue(any("STAGE.json root must be a JSON object" in error for error in errors))

    def test_malformed_transition_type_fails_cleanly(self):
        workflow = self.make_workflow()
        path = workflow / "WORKFLOW.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["transitions"] = "not-an-object"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        errors = workflow_validator.validate_workflow(workflow)
        self.assertIn("transitions must be an object", errors)

    def test_workflow_markdown_heading_inside_fence_does_not_satisfy_contract(self):
        workflow = self.make_workflow()
        path = workflow / "CONTEXT.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("## Completion", "## Removed Completion")
        text += "\n```markdown\n## Completion\n```\n"
        path.write_text(text, encoding="utf-8")
        errors = workflow_validator.validate_workflow(workflow)
        self.assertTrue(any("Completion" in error and "missing" in error for error in errors))

    def test_run_markdown_heading_inside_fence_does_not_satisfy_contract(self):
        run = self.make_run("fence-run")
        path = run / "RUN.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("## Resume", "## Removed Resume")
        text += "\n```markdown\n## Resume\n```\n"
        path.write_text(text, encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("Resume" in error and "missing" in error for error in errors))

    def test_committed_duplicate_operation_id_is_journal_corruption(self):
        run = self.make_run("dup-op")
        first = journal.read_events(run)[0]
        duplicate = dict(first)
        duplicate["sequence"] = 2
        path = run / "journal" / journal.event_filename(2, duplicate["operation_id"])
        path.write_text(json.dumps(duplicate, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(JournalError):
            journal.read_events(run)

    def test_timestamp_regression_is_rejected(self):
        run = self.make_run("time-regress")
        run_manager.start_run(run, "START")
        events = journal.read_events(run)
        path = sorted((run / "journal").glob("[0-9]*_OP-*.json"))[1]
        second = json.loads(path.read_text(encoding="utf-8"))
        second["timestamp"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(second, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(JournalError):
            journal.reduce_journal(run, journal.read_events(run), use_checkpoint=False)

    def test_missing_lock_owner_fails_closed(self):
        run = self.make_run("missing-owner")
        (run / ".kernel.lock").mkdir()
        with self.assertRaises(LockRecoveryRequired):
            run_manager.start_run(run, "START")

    def test_explicit_force_recovery_can_remove_missing_owner_lock_after_journal_check(self):
        run = self.make_run("recover-lock")
        (run / ".kernel.lock").mkdir()
        result = run_manager.recover_lock(run, force=True)
        self.assertEqual(result["status"], "recovered")
        self.assertFalse((run / ".kernel.lock").exists())

    def test_nested_live_lock_fails_busy(self):
        run = self.make_run("busy-lock")
        with kernel_lock(run, "OWNER"):
            with self.assertRaises(LockError):
                run_manager.start_run(run, "START")

    @unittest.skipUnless(os.name == "nt", "Windows-specific process identity")
    def test_windows_process_identity_uses_creation_filetime(self):
        status, identity = probe_process(os.getpid())
        self.assertEqual(status, "alive")
        self.assertEqual(identity["kind"], "windows_creation_filetime")

    def test_randomized_legal_state_sequences_remain_valid(self):
        for seed in range(8):
            rng = random.Random(seed)
            run = self.make_run(f"random-{seed}")
            op = 0
            for _ in range(24):
                state, _ = journal.current_state(run)
                if state["status"] in {"COMPLETED", "FAILED"}:
                    break
                op += 1
                operation = f"R{seed}-{op}"
                current = state["current"]
                active = None
                if current.get("attempt") is not None:
                    active = state["stages"][current["stage_id"]]["attempts"][str(current["attempt"])]
                if state["status"] == "READY":
                    run_manager.start_run(run, operation)
                elif state["status"] == "BLOCKED":
                    if rng.random() < 0.8:
                        run_manager.resume_run(run, operation)
                    else:
                        run_manager.fail_run(run, operation, "random terminal failure")
                elif active is None or active["status"] in {"SUCCEEDED", "FAILED"}:
                    if active and active["status"] == "SUCCEEDED" and current["stage_id"] == "02-verify":
                        run_manager.complete_run(run, operation)
                    elif rng.random() < 0.85:
                        run_manager.create_attempt(run, operation)
                    else:
                        run_manager.fail_run(run, operation, "random terminal failure")
                elif active["status"] == "PENDING":
                    run_manager.start_attempt(run, operation)
                elif active["status"] == "RUNNING":
                    choice = rng.randrange(5)
                    if choice == 0:
                        run_manager.record_validation(run, operation, "PASS", check_id="random")
                    elif choice == 1:
                        run_manager.block_run(run, operation, "random block")
                    elif choice == 2:
                        run_manager.fail_attempt(run, operation, "random retryable failure")
                    elif choice == 3:
                        run_manager.fail_run(run, operation, "random terminal failure")
                    else:
                        if active["validation"]["status"] != "PASS":
                            run_manager.record_validation(run, operation, "PASS", check_id="random")
                        else:
                            next_stage = None if current["stage_id"] == "02-verify" else "02-verify"
                            run_manager.complete_attempt(run, operation, next_stage=next_stage)
                self.assertEqual(run_validator.validate_run(run), [], f"seed={seed}")

    def test_proven_stale_lock_requires_explicit_recovery(self):
        run = self.make_run("stale-lock")
        lock_dir = run / ".kernel.lock"
        lock_dir.mkdir()
        original = kernel_lock_module.inspect_lock
        kernel_lock_module.inspect_lock = lambda run_dir: {"exists": True, "status": "stale_dead_process", "owner": {}}
        try:
            with self.assertRaises(LockRecoveryRequired):
                kernel_lock_module._reclaim_if_proven_stale(run)
            self.assertTrue(lock_dir.exists())
        finally:
            kernel_lock_module.inspect_lock = original


if __name__ == "__main__":
    unittest.main()
