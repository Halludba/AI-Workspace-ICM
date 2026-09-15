import json
import tempfile
import unittest
from pathlib import Path

from tools import create_workflow, run_manager, run_validator, workflow_validator
from tools.init import initialize_run
from tools.kernel import convergence, journal
from tools.kernel.events import CycleDetectedError, KernelError


class ConvergenceGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.workflows = self.tmp / "workflows"
        self.work = self.tmp / "work"
        self.workflows.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self.tmp_obj.cleanup()

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def make_loop_run(self, *, self_loop: bool = False):
        names = ["alpha", "done"] if self_loop else ["alpha", "beta", "done"]
        workflow = create_workflow.scaffold("loop-flow", names, destination_root=self.workflows)
        manifest_path = workflow / "WORKFLOW.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "ACTIVE"
        manifest["executable"] = True
        if self_loop:
            manifest["transitions"]["01-alpha"] = ["01-alpha", "02-done"]
            alpha = json.loads((workflow / "01-alpha/STAGE.json").read_text(encoding="utf-8"))
            alpha["allowed_next"] = ["01-alpha", "02-done"]
            self._write_json(workflow / "01-alpha/STAGE.json", alpha)
        else:
            manifest["transitions"]["02-beta"] = ["01-alpha", "03-done"]
            beta = json.loads((workflow / "02-beta/STAGE.json").read_text(encoding="utf-8"))
            beta["allowed_next"] = ["01-alpha", "03-done"]
            self._write_json(workflow / "02-beta/STAGE.json", beta)
        self._write_json(manifest_path, manifest)
        self.assertEqual(workflow_validator.validate_workflow(workflow), [])
        return initialize_run(
            "loop-flow", "2026-09-15_loop-run",
            workflow_root=self.workflows,
            destination_root=self.work,
            operation_id="CREATE-RUN",
        )

    @staticmethod
    def _start_first(run: Path) -> None:
        run_manager.start_run(run, "START-RUN")
        run_manager.create_attempt(run, "CREATE-01")
        run_manager.start_attempt(run, "START-01")

    @staticmethod
    def _complete_current(run: Path, label: str, next_stage: str | None, *, extra_check: str | None = None) -> None:
        run_manager.record_validation(run, f"VAL-{label}", "PASS")
        if extra_check:
            run_manager.record_validation(run, f"VAL-{label}-EXTRA", "PASS", check_id=extra_check)
        run_manager.complete_attempt(run, f"COMPLETE-{label}", next_stage=next_stage)

    @staticmethod
    def _create_and_start(run: Path, label: str) -> None:
        run_manager.create_attempt(run, f"CREATE-{label}")
        run_manager.start_attempt(run, f"START-{label}")

    def test_adjacent_equal_self_loop_is_stable_not_cycle(self):
        run = self.make_loop_run(self_loop=True)
        self._start_first(run)
        self._complete_current(run, "A1", "01-alpha")
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "01-alpha")
        state, events = journal.current_state(run)
        self.assertEqual(state["status"], "RUNNING")
        history = convergence.completion_signature_history(
            events, *journal.load_definition(run)
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["sha256"], history[1]["sha256"])

    def test_non_adjacent_revisit_terminalizes_run(self):
        run = self.make_loop_run()
        self._start_first(run)
        self._complete_current(run, "A1", "02-beta")
        self._create_and_start(run, "B1")
        self._complete_current(run, "B1", "01-alpha")
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "02-beta")
        self._create_and_start(run, "B2")
        run_manager.record_validation(run, "VAL-B2", "PASS")
        with self.assertRaises(CycleDetectedError):
            run_manager.complete_attempt(run, "COMPLETE-B2", next_stage="01-alpha")

        state, events = journal.current_state(run)
        self.assertEqual(state["status"], "FAILED")
        self.assertEqual(state["status_reason"], "CYCLE_DETECTED")
        last = events[-1]
        self.assertEqual(last["event_type"], "RUN_FAILED")
        self.assertEqual(last["payload"]["reason"], "CYCLE_DETECTED")
        self.assertEqual(last["payload"]["trigger_operation_id"], "COMPLETE-B2")
        self.assertTrue(last["operation_id"].startswith("__KERNEL_CYCLE_"))
        self.assertFalse(any(e["operation_id"] == "COMPLETE-B2" for e in events))
        beta2 = state["stages"]["02-beta"]["attempts"]["2"]
        self.assertEqual(beta2["status"], "FAILED")

    def test_cycle_retry_is_deterministic_and_adds_no_event(self):
        run = self.make_loop_run()
        self._start_first(run)
        self._complete_current(run, "A1", "02-beta")
        self._create_and_start(run, "B1")
        self._complete_current(run, "B1", "01-alpha")
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "02-beta")
        self._create_and_start(run, "B2")
        run_manager.record_validation(run, "VAL-B2", "PASS")
        with self.assertRaises(CycleDetectedError):
            run_manager.complete_attempt(run, "COMPLETE-B2", next_stage="01-alpha")
        count = len(journal.read_events(run))
        with self.assertRaises(CycleDetectedError):
            run_manager.complete_attempt(run, "COMPLETE-B2", next_stage="01-alpha")
        self.assertEqual(len(journal.read_events(run)), count)

    def test_material_persisted_change_avoids_false_cycle(self):
        run = self.make_loop_run()
        self._start_first(run)
        self._complete_current(run, "A1", "02-beta")
        self._create_and_start(run, "B1")
        self._complete_current(run, "B1", "01-alpha")
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "02-beta", extra_check="new-evidence")
        self._create_and_start(run, "B2")
        self._complete_current(run, "B2", "01-alpha")
        state, _ = journal.current_state(run)
        self.assertEqual(state["status"], "RUNNING")

    def test_reserved_kernel_operation_prefix_is_rejected(self):
        run = self.make_loop_run(self_loop=True)
        with self.assertRaises(KernelError):
            run_manager.start_run(run, "__KERNEL_FAKE")

    def test_malformed_convergence_policy_fails_closed(self):
        run = self.make_loop_run(self_loop=True)
        self._start_first(run)
        run_manager.record_validation(run, "VAL-A1", "PASS")
        original = journal.POLICY["convergence_guard"]
        journal.POLICY["convergence_guard"] = {
            **original,
            "strategy": "MAGIC_TRACKER",
        }
        try:
            with self.assertRaises(KernelError):
                run_manager.complete_attempt(run, "COMPLETE-A1", next_stage="01-alpha")
        finally:
            journal.POLICY["convergence_guard"] = original
        self.assertFalse(any(
            event["operation_id"] == "COMPLETE-A1" for event in journal.read_events(run)
        ))

    def test_working_state_ignores_attempt_identity_and_timestamps(self):
        run = self.make_loop_run(self_loop=True)
        self._start_first(run)
        self._complete_current(run, "A1", "01-alpha")
        first, _ = journal.current_state(run)
        first_digest = convergence.working_state_digest(first)
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "01-alpha")
        second, _ = journal.current_state(run)
        self.assertEqual(first_digest, convergence.working_state_digest(second))

    def test_full_validator_reproduces_cycle_provenance(self):
        run = self.make_loop_run()
        self._start_first(run)
        self._complete_current(run, "A1", "02-beta")
        self._create_and_start(run, "B1")
        self._complete_current(run, "B1", "01-alpha")
        self._create_and_start(run, "A2")
        self._complete_current(run, "A2", "02-beta")
        self._create_and_start(run, "B2")
        run_manager.record_validation(run, "VAL-B2", "PASS")
        with self.assertRaises(CycleDetectedError):
            run_manager.complete_attempt(run, "COMPLETE-B2", next_stage="01-alpha")
        self.assertEqual(run_validator.validate_run(run), [])
        last_path = sorted((run / "journal").glob("[0-9]*_OP-*.json"))[-1]
        data = json.loads(last_path.read_text(encoding="utf-8"))
        data["payload"]["first_seen_sequence"] = 999
        self._write_json(last_path, data)
        errors = run_validator.validate_run(run)
        self.assertTrue(any("first_seen_sequence mismatch" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
