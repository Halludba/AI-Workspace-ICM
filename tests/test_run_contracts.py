import json
import tempfile
import unittest
from pathlib import Path

from tools import create_workflow, run_validator, workflow_validator
from tools.init import initialize_run
from tools.kernel.events import KernelError

ROOT = Path(__file__).resolve().parents[1]


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
            "sample-flow", ["intake", "verify"], destination_root=self.workflows
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
            inputs = [str(source)]
        return initialize_run(
            "sample-flow",
            "2026-09-15_sample-run",
            input_paths=inputs,
            workflow_root=self.workflows,
            destination_root=self.work,
            operation_id="CREATE-RUN",
        )

    def test_run_template_is_valid(self):
        self.assertEqual(run_validator.validate_run(ROOT / "work/_template"), [])

    def test_draft_workflow_cannot_initialize_run(self):
        self.make_workflow(active=False)
        with self.assertRaises(KernelError):
            initialize_run(
                "sample-flow",
                "2026-09-15_draft-run",
                workflow_root=self.workflows,
                destination_root=self.work,
            )

    def test_active_workflow_creates_ready_run_without_attempt(self):
        path = self.make_run()
        self.assertEqual(run_validator.validate_run(path), [])
        state = json.loads((path / "RUN.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "READY")
        self.assertEqual(state["current"], {
            "stage_id": "01-intake", "attempt": None, "execution_sequence": 0
        })
        events = sorted((path / "journal").glob("[0-9]*_OP-*.json"))
        self.assertEqual(len(events), 1)
        first = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual(first["event_type"], "RUN_CREATED")
        self.assertIn("snapshot_sha256", first["payload"])

    def test_run_snapshots_workflow_contract(self):
        source = self.make_workflow(active=True)
        run = initialize_run(
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
        with self.assertRaises(KernelError):
            initialize_run(
                "sample-flow", "bad-run-id",
                workflow_root=self.workflows, destination_root=self.work,
            )

    def test_run_projection_wrong_root_fails_cleanly(self):
        run = self.make_run()
        (run / "RUN.json").write_text("[]\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("RUN.json root must be a JSON object" in error for error in errors))

    def test_workflow_snapshot_tampering_is_detected(self):
        run = self.make_run()
        path = run / "definition/WORKFLOW.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("workflow_sha256 mismatch" in error for error in errors))

    def test_snapshot_manifest_tampering_breaks_root_seal(self):
        run = self.make_run()
        path = run / "definition/snapshot.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["authority"] = "tampered"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        errors = run_validator.validate_run(run)
        self.assertTrue(any("snapshot_sha256 mismatch" in error for error in errors))

    def test_base_work_root_contains_only_template(self):
        actual = sorted(path.name for path in (ROOT / "work").iterdir() if path.is_dir())
        self.assertEqual(actual, ["_template"])


if __name__ == "__main__":
    unittest.main()
