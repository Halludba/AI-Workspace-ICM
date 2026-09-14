import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import create_workflow
import workflow_validator


class WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def scaffold(self, workflow_id="example-flow", stages=None):
        stages = stages or ["intake", "transform", "verify"]
        return create_workflow.scaffold(
            workflow_id,
            stages,
            destination_root=self.tmp,
        )

    def load_manifest(self, path):
        return json.loads((path / "WORKFLOW.json").read_text(encoding="utf-8"))

    def save_manifest(self, path, data):
        (path / "WORKFLOW.json").write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def test_template_is_valid_and_non_executable(self):
        template = ROOT / "workflows" / "_template"
        self.assertEqual(workflow_validator.validate_workflow(template), [])
        data = self.load_manifest(template)
        self.assertEqual(data["status"], "TEMPLATE")
        self.assertFalse(data["executable"])

    def test_scaffolder_creates_valid_linear_draft(self):
        path = self.scaffold()
        self.assertEqual(workflow_validator.validate_workflow(path), [])
        data = self.load_manifest(path)
        self.assertEqual(data["status"], "DRAFT")
        self.assertFalse(data["executable"])
        self.assertEqual(data["entry_stage"], "01-intake")
        self.assertEqual(data["terminal_stages"], ["03-verify"])
        self.assertEqual(data["transitions"]["01-intake"], ["02-transform"])
        self.assertEqual(data["transitions"]["03-verify"], [])

    def test_scaffolder_rejects_bad_ids_and_duplicate_stages(self):
        with self.assertRaises(create_workflow.ScaffoldError):
            create_workflow.scaffold("Bad Name", ["intake"], destination_root=self.tmp)
        with self.assertRaises(create_workflow.ScaffoldError):
            create_workflow.scaffold(
                "valid-name", ["intake", "intake"], destination_root=self.tmp
            )

    def test_draft_cannot_claim_executable(self):
        path = self.scaffold()
        data = self.load_manifest(path)
        data["executable"] = True
        self.save_manifest(path, data)
        errors = workflow_validator.validate_workflow(path)
        self.assertIn("executable flag does not match workflow status", errors)

    def test_missing_workflow_section_fails(self):
        path = self.scaffold()
        context = (path / "CONTEXT.md").read_text(encoding="utf-8")
        context = context.replace("## Completion", "## Done")
        (path / "CONTEXT.md").write_text(context, encoding="utf-8")
        errors = workflow_validator.validate_workflow(path)
        self.assertTrue(any("workflow missing section" in error for error in errors))

    def test_unreachable_stage_fails(self):
        path = self.scaffold()
        data = self.load_manifest(path)
        data["transitions"]["01-intake"] = ["03-verify"]
        self.save_manifest(path, data)
        stage = json.loads((path / "01-intake" / "STAGE.json").read_text(encoding="utf-8"))
        stage["allowed_next"] = ["03-verify"]
        (path / "01-intake" / "STAGE.json").write_text(
            json.dumps(stage, indent=2) + "\n", encoding="utf-8"
        )
        errors = workflow_validator.validate_workflow(path)
        self.assertTrue(any("unreachable stage(s): 02-transform" in error for error in errors))

    def test_stage_output_contract_requires_confined_object_path(self):
        path = self.scaffold()
        stage_path = path / "01-intake" / "STAGE.json"
        stage = json.loads(stage_path.read_text(encoding="utf-8"))
        stage["outputs"] = ["result.txt", {"path": "../escape.txt"}]
        stage_path.write_text(json.dumps(stage, indent=2) + "\n", encoding="utf-8")
        errors = workflow_validator.validate_workflow(path)
        self.assertTrue(any("outputs[0] must be an object" in error for error in errors))
        self.assertTrue(any("outputs[1].path must stay inside" in error for error in errors))

    def test_live_output_directory_is_forbidden_in_definition(self):
        path = self.scaffold()
        (path / "01-intake" / "output").mkdir()
        errors = workflow_validator.validate_workflow(path)
        self.assertIn("workflow definitions may not contain live output directories", errors)

    def test_base_workflows_are_domain_neutral(self):
        children = sorted(
            path.name for path in (ROOT / "workflows").iterdir() if path.is_dir()
        )
        self.assertEqual(children, ["_template"])


if __name__ == "__main__":
    unittest.main()
