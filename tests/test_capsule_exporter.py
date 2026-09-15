import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capsule_exporter", ROOT / "tools" / "capsule_exporter.py"
)
capsule = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capsule)


class CapsuleExporterTests(unittest.TestCase):
    def make_workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        for rel, text in {
            "WORKSPACE.md": "workspace\n",
            "CONTEXT.md": "router\n",
            "_core/AUTHORITY.md": "authority\n",
            "skills/CONTEXT.md": "skills context\n",
        }.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        policy = {
            "schema_version": "1.0",
            "default_mode": "MINIMAL",
            "supported_modes": ["MINIMAL", "PORTABLE"],
            "supported_targets": ["qwen", "gemini", "generic-upload"],
            "base_context": ["WORKSPACE.md", "CONTEXT.md", "_core/AUTHORITY.md", "skills/CONTEXT.md"],
            "generated_files": ["BOOTSTRAP.md", "CAPSULE_MANIFEST.json"],
            "minimal_rule": "BASE_CONTEXT_PLUS_SELECTED_SKILL_CONTEXT",
            "portable_rule": "MINIMAL_PLUS_SELECTED_SKILL_PACKAGE",
            "input_rule": "EXPLICIT_PATHS_ONLY",
            "archive_rule": "SORTED_FIXED_TIMESTAMP",
            "token_estimator": {
                "kind": "HEURISTIC_CHARS_PER_TOKEN",
                "chars_per_token_mid": 4.0,
                "chars_per_token_low": 4.7,
                "chars_per_token_high": 3.2,
            },
        }
        (root / "config").mkdir()
        (root / "config/capsule_policy.json").write_text(json.dumps(policy), encoding="utf-8")
        self.add_skill(root, "pdf-styler", ["CREATE", "EDIT", "STYLE"], ["PDF"], [".pdf"])
        self.add_skill(root, "context-optimizer", ["OPTIMIZE"], ["CONTEXT"], [])
        registry = {
            "schema_version": "1.0", "routing": "EXACT_ARTIFACT_INTENT",
            "default_context_loading": "EXCLUDE",
            "skills": [self.registry_entry(root, "context-optimizer"), self.registry_entry(root, "pdf-styler")],
        }
        (root / "skills/registry.json").write_text(json.dumps(registry), encoding="utf-8")
        return temp, root
    def add_skill(self, root, skill_id, operations, artifact_types, extensions):
        skill = root / "skills" / skill_id
        (skill / "tools").mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
        (skill / "extra.json").write_text('{"extra":true}\n', encoding="utf-8")
        (skill / "tools/worker.py").write_text("VALUE = 1\n", encoding="utf-8")
        manifest = {
            "schema_version": "1.0", "id": skill_id,
            "context": f"skills/{skill_id}/SKILL.md",
            "operations": operations, "artifact_types": artifact_types,
            "extensions": extensions,
            "capsule_context": [f"skills/{skill_id}/extra.json"],
            "capsule_portable": [f"skills/{skill_id}/tools/worker.py"],
        }
        (skill / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (skill / "registry-entry.json").write_text(json.dumps({
            "id": skill_id, "context": f"skills/{skill_id}/SKILL.md",
            "manifest": f"skills/{skill_id}/manifest.json",
            "operations": operations, "artifact_types": artifact_types,
            "extensions": extensions,
        }), encoding="utf-8")

    def registry_entry(self, root, skill_id):
        return json.loads((root / f"skills/{skill_id}/registry-entry.json").read_text(encoding="utf-8"))

    def request(self):
        return capsule._request("CREATE", "PDF", ".pdf", [])
    def test_minimal_capsule_contains_only_selected_skill_context(self):
        temp, root = self.make_workspace()
        with temp:
            plan = capsule.build_plan(target="qwen", mode="MINIMAL", request=self.request(), input_paths=[], root=root)
            paths = {m["path"] for m in plan["members"]}
            self.assertIn("skills/pdf-styler/SKILL.md", paths)
            self.assertIn("skills/pdf-styler/manifest.json", paths)
            self.assertIn("skills/pdf-styler/extra.json", paths)
            self.assertNotIn("skills/pdf-styler/tools/worker.py", paths)
            self.assertFalse(any("context-optimizer" in path for path in paths))

    def test_portable_capsule_uses_declared_inventory_not_directory_walk(self):
        temp, root = self.make_workspace()
        with temp:
            junk = root / "skills/pdf-styler/__pycache__/junk.pyc"
            junk.parent.mkdir(parents=True)
            junk.write_bytes(b"\x00junk")
            plan = capsule.build_plan(target="qwen", mode="PORTABLE", request=self.request(), input_paths=[], root=root)
            paths = {m["path"] for m in plan["members"]}
            self.assertIn("skills/pdf-styler/tools/worker.py", paths)
            self.assertNotIn("skills/pdf-styler/__pycache__/junk.pyc", paths)
            self.assertNotIn("skills/pdf-styler/registry-entry.json", paths)

    def test_explicit_input_is_included_and_escape_is_rejected(self):
        temp, root = self.make_workspace()
        with temp:
            (root / "input.txt").write_text("task input\n", encoding="utf-8")
            plan = capsule.build_plan(target="gemini", mode="MINIMAL", request=self.request(), input_paths=["input.txt"], root=root)
            self.assertIn("input.txt", {m["path"] for m in plan["members"]})
            with self.assertRaises(capsule.CapsuleError):
                capsule.build_plan(target="gemini", mode="MINIMAL", request=self.request(), input_paths=["../escape.txt"], root=root)
    def test_export_is_reproducible_and_archive_order_is_sorted(self):
        temp, root = self.make_workspace()
        with temp:
            plan = capsule.build_plan(target="generic-upload", mode="MINIMAL", request=self.request(), input_paths=[], root=root)
            first = capsule.export_capsule(plan, root / "a.zip", root)
            second = capsule.export_capsule(plan, root / "b.zip", root)
            self.assertEqual(first["archive_sha256"], second["archive_sha256"])
            with zipfile.ZipFile(root / "a.zip") as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIsNone(archive.testzip())
                for info in archive.infolist():
                    self.assertEqual(info.date_time, capsule.FIXED_ZIP_TIME)

    def test_manifest_reports_scope_and_token_estimate(self):
        temp, root = self.make_workspace()
        with temp:
            plan = capsule.build_plan(target="qwen", mode="MINIMAL", request=self.request(), input_paths=[], root=root)
            capsule.export_capsule(plan, root / "capsule.zip", root)
            with zipfile.ZipFile(root / "capsule.zip") as archive:
                manifest = json.loads(archive.read("CAPSULE_MANIFEST.json"))
                bootstrap = archive.read("BOOTSTRAP.md").decode("utf-8")
            self.assertEqual(manifest["selected_skills"], ["pdf-styler"])
            self.assertTrue(manifest["token_estimate"]["includes_manifest"])
            self.assertGreater(manifest["token_estimate"]["estimated_text_tokens"], 0)
            self.assertIn("not a complete clone", bootstrap)
            self.assertIn("omitted repository content", manifest["scope_note"])


if __name__ == "__main__":
    unittest.main()
