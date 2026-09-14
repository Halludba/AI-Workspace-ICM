import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_workflow = load_module("create_workflow_run_tests", "tools/create_workflow.py")
workflow_validator = load_module("workflow_validator_run_tests", "tools/workflow_validator.py")
create_run = load_module("create_run_tests", "tools/create_run.py")
run_validator = load_module("run_validator_tests", "tools/run_validator.py")


class RunContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.workflows = self.tmp / "workflows"
        self.work = self.tmp / "work"
        self.workflows.mkdir()
        self.work.mkdir()

    def tearDown(self):
        self.tmp_obj.cleanup()

    def make_workflow(self, active=True):
        path = create_workflow.scaffold(
            "sample-flow",
            ["intake", "verify"],
            destination_root=self.workflows,
        )
        if active:
            manifest_path = path / "WORKFLOW.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["status"] = "ACTIVE"
            data["executable"] = True
            manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(workflow_validator.validate_workflow(path), [])
        return path

    def make_run(self, with_input=False):
        self.make_workflow(active=True)
        inputs = []
        if with_input:
            source = self.tmp / "source.txt"
            source.write_text("source material\n", encoding="utf-8")
            inputs = [source]
        return create_run.create_run(
            "sample-flow",
            "2026-09-15_sample-run",
            input_paths=inputs,
            workflow_root=self.workflows,
            destination_root=self.work,
        )

    def test_run_template_is_valid(self):
        self.assertEqual(run_validator.validate_run(ROOT / "work/_template"), [])

    def test_draft_workflow_cannot_start_run(self):
        self.make_workflow(active=False)
        with self.assertRaises(create_run.RunCreateError):
            create_run.create_run(
                "sample-flow", "2026-09-15_draft-run",
                workflow_root=self.workflows, destination_root=self.work,
            )

    def test_active_workflow_creates_valid_ready_run(self):
        path = self.make_run()
        self.assertEqual(run_validator.validate_run(path), [])
        state = json.loads((path / "RUN.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "READY")
        self.assertEqual(state["current"]["stage_id"], "01-intake")
        attempt = json.loads(
            (path / "stages/01-intake/attempts/0001/ATTEMPT.json").read_text(encoding="utf-8")
        )
        self.assertEqual(attempt["status"], "PENDING")
        self.assertEqual(attempt["execution_sequence"], 1)

    def test_run_snapshots_workflow_contract(self):
        source = self.make_workflow(active=True)
        run = create_run.create_run(
            "sample-flow", "2026-09-15_snapshot-run",
            workflow_root=self.workflows, destination_root=self.work,
        )
        snap_before = (run / "definition/WORKFLOW.json").read_text(encoding="utf-8")
        manifest_path = source / "WORKFLOW.json"
        changed = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed["description"] = "changed after run creation"
        manifest_path.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")
        self.assertEqual((run / "definition/WORKFLOW.json").read_text(encoding="utf-8"), snap_before)
        self.assertEqual(run_validator.validate_run(run), [])

    def test_input_hash_tampering_is_detected(self):
        run = self.make_run(with_input=True)
        (run / "inputs/source.txt").write_text("tampered\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("sha256 mismatch" in error for error in errors))

    def test_invalid_run_id_rejected(self):
        self.make_workflow(active=True)
        with self.assertRaises(create_run.RunCreateError):
            create_run.create_run(
                "sample-flow", "bad-run-id",
                workflow_root=self.workflows, destination_root=self.work,
            )

    def test_artifact_path_escape_fails_closed(self):
        run = self.make_run()
        state_path = run / "RUN.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["inputs"] = [{"path": "../outside.txt", "sha256": "0" * 64}]
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("escapes run" in error for error in errors))

    def test_completed_run_requires_successful_terminal_attempt(self):
        run = self.make_run()
        state_path = run / "RUN.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["status"] = "COMPLETED"
        state["completion"] = {
            "terminal_stage": "02-verify",
            "completed_at": "2026-09-15T00:00:00Z",
        }
        state["current"] = {"stage_id": "02-verify", "attempt": 1, "execution_sequence": 2}
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("current attempt record is missing" in error for error in errors))

    def test_duplicate_execution_sequence_is_detected(self):
        run = self.make_run()
        source = run / "stages/01-intake/attempts/0001"
        target = run / "stages/01-intake/attempts/0002"
        shutil.copytree(source, target)
        attempt_path = target / "ATTEMPT.json"
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt["attempt"] = 2
        attempt_path.write_text(json.dumps(attempt, indent=2) + "\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("execution_sequence values must be unique" in error for error in errors))

    def test_base_work_root_contains_only_template(self):
        actual = sorted(path.name for path in (ROOT / "work").iterdir() if path.is_dir())
        self.assertEqual(actual, ["_template"])

    def test_definition_snapshot_hash_tampering_is_detected(self):
        run = self.make_run()
        context = run / "definition/CONTEXT.md"
        context.write_text(context.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("snapshot hash mismatch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
