import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pdf-styler"
SPEC = importlib.util.spec_from_file_location(
    "pdf_styler_skill", SKILL / "tools" / "pdf_styler.py"
)
pdf_styler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pdf_styler)


class PdfStylerSkillTests(unittest.TestCase):
    def test_default_style_resolves_from_local_manifest(self):
        style = pdf_styler.resolve_style()
        self.assertEqual(style["id"], "style.pdf.formats")
        self.assertEqual(pdf_styler.default_style_id(), "style.pdf.formats")

    def test_style_preserves_semantic_content_boundary(self):
        style = pdf_styler.resolve_style()
        self.assertTrue(
            style["adaptation"]["semantic_content_may_not_be_rewritten_for_style_fit"]
        )

    def test_fidelity_audit_does_not_overclaim_unsupported_controls(self):
        result = pdf_styler.fidelity_audit(pdf_styler.resolve_style())
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["dependency_status"], "AVAILABLE")
        self.assertEqual(result["missing_fonts"], [])
        self.assertIn("components.footer", result["unsupported_renderer_controls"])
        self.assertIn("pagination.keep_section_together", result["unsupported_renderer_controls"])

    def test_schema_rejects_typography_missing_renderer_fields(self):
        style = pdf_styler.resolve_style()
        style["typography"]["body"] = {}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-style.json"
            path.write_text(json.dumps(style), encoding="utf-8")
            with self.assertRaises(pdf_styler.jsonschema.ValidationError):
                pdf_styler.load_style(str(path))

    def test_specimen_render_creates_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "specimen.pdf"
            pdf_styler.render_specimen(out, pdf_styler.resolve_style())
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"%PDF"))
            self.assertGreater(len(data), 1000)

    def test_bundled_style_is_listed(self):
        self.assertIn("style.pdf.formats", pdf_styler.list_styles())


if __name__ == "__main__":
    unittest.main()
