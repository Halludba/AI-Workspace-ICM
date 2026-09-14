import json
import os
import tempfile
import unittest
from pathlib import Path

from tools import create_workflow, run_manager, run_validator, workflow_validator
from tools.init import initialize_run
from tools.kernel import journal
from tools.kernel.events import (
    EventLimitExceededError,
    IdempotencyConflictError,
    JournalError,
    TransitionError,
)


class RunManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.workflows = self.tmp / "workflows"
        self.work = self.tmp / "work"
        self.workflows.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self.tmp_obj.cleanup()

    def make_run(self, required_output=None):
        workflow = create_workflow.scaffold(
            "sample-flow", ["intake", "verify"], destination_root=self.workflows
        )
        if required_output is not None:
            stage_path = workflow / "01-intake" / "STAGE.json"
            stage = json.loads(stage_path.read_text(encoding="utf-8"))
            stage["outputs"] = [required_output]
            stage_path.write_text(json.dumps(stage, indent=2) + "\n", encoding="utf-8")
        manifest_path = workflow / "WORKFLOW.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "ACTIVE"
        manifest["executable"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(workflow_validator.validate_workflow(workflow), [])
        return initialize_run(
            "sample-flow",
            "2026-09-15_manager-run",
            workflow_root=self.workflows,
            destination_root=self.work,
            operation_id="CREATE-RUN",
        )

    @staticmethod
    def state(run):
        return json.loads((run / "RUN.json").read_text(encoding="utf-8"))

    @staticmethod
    def attempt(run, stage, number):
        path = run / "stages" / stage / "attempts" / f"{number:04d}" / "ATTEMPT.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def start_first_attempt(self, run):
        run_manager.start_run(run, "START-RUN")
        run_manager.create_attempt(run, "CREATE-A1")
        run_manager.start_attempt(run, "START-A1")

    def test_run_start_and_attempt_start_are_distinct(self):
        run = self.make_run()
        self.assertIsNone(self.state(run)["current"]["attempt"])
        run_manager.start_run(run, "START-RUN")
        self.assertEqual(self.state(run)["status"], "RUNNING")
        self.assertIsNone(self.state(run)["current"]["attempt"])
        run_manager.create_attempt(run, "CREATE-A1")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "PENDING")
        run_manager.start_attempt(run, "START-A1")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "RUNNING")

    def test_artifact_registration_hashes_and_confines_output(self):
        run = self.make_run()
        self.start_first_attempt(run)
        artifact = run / "stages/01-intake/attempts/0001/artifacts/result.txt"
        artifact.write_text("result\n", encoding="utf-8")
        run_manager.register_artifact(run, "ART-1", str(artifact), "stage_output")
        record = self.attempt(run, "01-intake", 1)["output_artifacts"][0]
        self.assertEqual(record["sha256"], journal.sha256_file(artifact))
        rogue = self.tmp / "outside.txt"
        rogue.write_text("outside\n", encoding="utf-8")
        with self.assertRaises(Exception):
            run_manager.register_artifact(run, "ART-2", str(rogue), "stage_output")

    def test_required_output_blocks_success_until_registered_and_hash_current(self):
        run = self.make_run({"path": "result.txt", "role": "stage_output"})
        self.start_first_attempt(run)
        run_manager.record_validation(run, "VAL-OUT", "PASS")
        with self.assertRaises(Exception):
            run_manager.complete_attempt(run, "MISS-OUT", next_stage="02-verify")
        artifact = run / "stages/01-intake/attempts/0001/artifacts/result.txt"
        artifact.write_text("result\n", encoding="utf-8")
        run_manager.register_artifact(run, "REG-OUT", str(artifact), "stage_output")
        artifact.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(Exception):
            run_manager.complete_attempt(run, "STALE-HASH", next_stage="02-verify")
        artifact.write_text("result\n", encoding="utf-8")
        run_manager.complete_attempt(run, "GOOD-OUT", next_stage="02-verify")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "SUCCEEDED")

    def test_validation_history_is_append_only_with_derived_aggregate(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.record_validation(run, "V1", "FAIL", check_id="review")
        run_manager.record_validation(run, "V2", "PASS", check_id="review")
        run_manager.record_validation(run, "V3", "PASS", check_id="schema")
        attempt = self.attempt(run, "01-intake", 1)
        self.assertEqual(len(attempt["validations"]), 3)
        self.assertEqual(attempt["validation"]["status"], "PASS")
        self.assertEqual(attempt["validation"]["checks"], {"review": "PASS", "schema": "PASS"})

    def test_successful_handoff_requires_explicit_next_attempt_creation(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.record_validation(run, "VAL-1", "PASS")
        run_manager.complete_attempt(run, "COMPLETE-A1", next_stage="02-verify")
        state = self.state(run)
        self.assertEqual(state["current"]["stage_id"], "01-intake")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "SUCCEEDED")
        run_manager.create_attempt(run, "CREATE-A2")
        state = self.state(run)
        self.assertEqual(state["current"], {
            "stage_id": "02-verify", "attempt": 1, "execution_sequence": 2
        })
        self.assertEqual(self.attempt(run, "02-verify", 1)["status"], "PENDING")

    def test_failed_attempt_retries_same_stage_as_new_attempt(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.fail_attempt(run, "FAIL-A1", "transient failure")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "FAILED")
        self.assertEqual(self.state(run)["status"], "RUNNING")
        run_manager.create_attempt(run, "RETRY-A1")
        self.assertEqual(self.state(run)["current"], {
            "stage_id": "01-intake", "attempt": 2, "execution_sequence": 2
        })
        self.assertEqual(self.attempt(run, "01-intake", 2)["status"], "PENDING")

    def test_terminal_attempt_and_run_completion_are_distinct(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.record_validation(run, "V1", "PASS")
        run_manager.complete_attempt(run, "C1", next_stage="02-verify")
        run_manager.create_attempt(run, "CA2")
        run_manager.start_attempt(run, "SA2")
        run_manager.record_validation(run, "V2", "PASS")
        run_manager.complete_attempt(run, "C2")
        self.assertEqual(self.state(run)["status"], "RUNNING")
        self.assertEqual(self.attempt(run, "02-verify", 1)["status"], "SUCCEEDED")
        run_manager.complete_run(run, "DONE")
        self.assertEqual(self.state(run)["status"], "COMPLETED")
        with self.assertRaises(TransitionError):
            run_manager.complete_run(run, "DONE-AGAIN")

    def test_operation_id_retry_is_idempotent(self):
        run = self.make_run()
        first = run_manager.start_run(run, "SAME-OP")
        second = run_manager.start_run(run, "SAME-OP")
        self.assertEqual(first, second)
        self.assertEqual(len(journal.read_events(run)), 2)

    def test_operation_id_conflict_fails_closed(self):
        run = self.make_run()
        run_manager.start_run(run, "CONFLICT")
        with self.assertRaises(IdempotencyConflictError):
            journal.execute_event(run, "RUN_FAILED", {
                "reason": "different command",
                "failed_at_stage": "01-intake",
                "failed_at_attempt": None,
            }, "CONFLICT")
        self.assertEqual(len(journal.read_events(run)), 2)

    def test_block_and_resume_preserve_attempt(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.block_run(run, "BLOCK", "waiting")
        self.assertEqual(self.state(run)["status"], "BLOCKED")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "BLOCKED")
        run_manager.resume_run(run, "RESUME")
        self.assertEqual(self.state(run)["status"], "RUNNING")
        self.assertEqual(self.attempt(run, "01-intake", 1)["status"], "RUNNING")

    def test_run_failure_is_terminal_and_immutable(self):
        run = self.make_run()
        self.start_first_attempt(run)
        run_manager.fail_run(run, "FAIL-RUN", "fatal")
        self.assertEqual(self.state(run)["status"], "FAILED")
        with self.assertRaises(TransitionError):
            run_manager.resume_run(run, "NOPE")

    def test_projection_drift_is_repaired_even_when_sequence_matches(self):
        run = self.make_run()
        state_path = run / "RUN.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        data["status"] = "FAILED"
        state_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        journal.recover(run)
        self.assertEqual(self.state(run)["status"], "READY")

    def test_recovery_scrubs_uncommitted_temp_event(self):
        run = self.make_run()
        temp = run / "journal/.tmp_000002_OP-CRASH.json"
        temp.write_text("partial", encoding="utf-8")
        journal.recover(run)
        self.assertFalse(temp.exists())

    def test_sequence_gap_fails_closed(self):
        run = self.make_run()
        run_manager.start_run(run, "START")
        run_manager.create_attempt(run, "CREATE")
        events = sorted((run / "journal").glob("[0-9]*_OP-*.json"))
        events[1].unlink()
        with self.assertRaises(JournalError):
            journal.read_events(run)

    def test_corrupt_checkpoint_falls_back_to_full_replay(self):
        run = self.make_run()
        run_manager.start_run(run, "START")
        run_manager.create_attempt(run, "CREATE")
        checkpoints = list((run / "journal").glob(".snapshot_seq_*.json"))
        self.assertTrue(checkpoints)
        checkpoints[-1].write_text("{broken", encoding="utf-8")
        state, _ = journal.current_state(run)
        self.assertEqual(state["current"]["attempt"], 1)

    def test_checkpoint_state_must_equal_full_prefix_reduction(self):
        run = self.make_run()
        run_manager.start_run(run, "START")
        run_manager.create_attempt(run, "CREATE")
        checkpoints = sorted((run / "journal").glob(".snapshot_seq_*.json"))
        self.assertTrue(checkpoints)
        checkpoint_path = checkpoints[-1]
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["state"]["status"] = "FAILED"
        checkpoint["state_sha256"] = journal.canonical_sha256(checkpoint["state"])
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2) + "\n", encoding="utf-8")
        cached = journal.reduce_journal(run, use_checkpoint=True)
        full = journal.reduce_journal(run, use_checkpoint=False)
        self.assertEqual(cached, full)
        self.assertEqual(journal.canonical_sha256(cached), journal.canonical_sha256(full))

    def test_event_ceiling_reserves_final_slot_for_emergency_failure(self):
        run = self.make_run()
        original = journal.POLICY.get("max_events_per_run", 500)
        journal.POLICY["max_events_per_run"] = 8
        try:
            self.start_first_attempt(run)  # sequences 2-4
            run_manager.record_validation(run, "V1", "PASS")  # 5
            run_manager.record_validation(run, "V2", "PASS")  # 6
            run_manager.record_validation(run, "V3", "PASS")  # 7
            with self.assertRaises(EventLimitExceededError):
                run_manager.record_validation(run, "V4", "PASS")
            events = journal.read_events(run)
            self.assertEqual(len(events), 8)
            self.assertEqual(events[-1]["event_type"], "RUN_FAILED")
            self.assertEqual(events[-1]["payload"]["reason"], "EXCEEDED_MAX_JOURNAL_EVENTS")
            self.assertEqual(self.state(run)["status"], "FAILED")
        finally:
            journal.POLICY["max_events_per_run"] = original

    def test_symlink_escape_is_rejected_when_supported(self):
        run = self.make_run()
        self.start_first_attempt(run)
        outside = self.tmp / "outside-secret.txt"
        outside.write_text("secret\n", encoding="utf-8")
        link = run / "stages/01-intake/attempts/0001/artifacts/link.txt"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not available")
        with self.assertRaises(Exception):
            run_manager.register_artifact(run, "SYMLINK", str(link), "stage_output")

    def test_full_verify_accepts_consistent_run(self):
        run = self.make_run()
        self.start_first_attempt(run)
        self.assertEqual(run_validator.validate_run(run), [])
        run_manager.verify(run)


if __name__ == "__main__":
    unittest.main()
