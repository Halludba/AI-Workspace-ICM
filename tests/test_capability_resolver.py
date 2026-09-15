import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capability_resolver", ROOT / "tools" / "capability_resolver.py"
)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


class CapabilityResolverTests(unittest.TestCase):
    def request(self, operation="CREATE", artifact="PDF", extension=".pdf", explicit=None):
        return {
            "schema_version": "1.0",
            "intents": [{
                "operation": operation,
                "artifact_type": artifact,
                "extension": extension,
            }],
            "explicit_skills": explicit or [],
        }

    def test_registry_is_valid_and_lazy(self):
        registry = resolver.load_registry()
        self.assertEqual(registry["routing"], "EXACT_ARTIFACT_INTENT")
        self.assertEqual(registry["default_context_loading"], "EXCLUDE")

    def test_create_pdf_selects_only_pdf_styler(self):
        result = resolver.resolve(self.request())
        self.assertEqual([s["id"] for s in result["selected_skills"]], ["pdf-styler"])
        self.assertEqual(result["load_contexts"], ["skills/pdf-styler/SKILL.md"])
        self.assertFalse(result["skill_contents_loaded_by_resolver"])

    def test_read_pdf_does_not_select_styler(self):
        result = resolver.resolve(self.request(operation="READ"))
        self.assertEqual(result["selected_skills"], [])
        self.assertEqual(len(result["unmatched_intents"]), 1)

    def test_unknown_artifact_can_use_extension_fallback(self):
        result = resolver.resolve(self.request(artifact="UNKNOWN"))
        self.assertEqual(result["selected_skills"][0]["id"], "pdf-styler")
        self.assertIn("EXTENSION_FALLBACK", result["selected_skills"][0]["reasons"])

    def test_wrong_extension_does_not_override_artifact_intent(self):
        result = resolver.resolve(self.request(extension=".txt"))
        self.assertEqual(result["selected_skills"][0]["id"], "pdf-styler")

    def test_unknown_explicit_skill_fails_closed(self):
        with self.assertRaises(resolver.CapabilityError):
            resolver.resolve(self.request(explicit=["does-not-exist"]))

    def test_explicit_skill_composes_with_artifact_routing(self):
        result = resolver.resolve(self.request(explicit=["context-optimizer"]))
        self.assertEqual(
            [s["id"] for s in result["selected_skills"]],
            ["context-optimizer", "pdf-styler"],
        )

    def test_multiple_intents_compose_without_duplicate_skill(self):
        value = self.request()
        value["intents"].append({
            "operation": "STYLE", "artifact_type": "PDF", "extension": ".pdf"
        })
        result = resolver.resolve(value)
        self.assertEqual([s["id"] for s in result["selected_skills"]], ["pdf-styler"])

    def test_lowercase_operation_is_rejected(self):
        with self.assertRaises(resolver.CapabilityError):
            resolver.resolve(self.request(operation="create"))

    def test_path_escape_fails_closed(self):
        with self.assertRaises(resolver.CapabilityError):
            resolver.confined("../outside")

    def test_pdf_manifest_and_registry_agree(self):
        registry = resolver.load_registry()
        entry = next(x for x in registry["skills"] if x["id"] == "pdf-styler")
        manifest = json.loads((ROOT / entry["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["operations"], entry["operations"])
        self.assertEqual(manifest["artifact_types"], entry["artifact_types"])


if __name__ == "__main__":
    unittest.main()
