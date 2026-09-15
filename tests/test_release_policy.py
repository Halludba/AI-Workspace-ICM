import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_validator", ROOT / "tools" / "release_validator.py"
)
release_validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_validator)


class ReleasePolicyTests(unittest.TestCase):
    def test_current_workspace_release_is_valid(self):
        result = release_validator.validate_workspace()
        self.assertTrue(result["valid"])
        self.assertEqual(result["workspace_version"], "0.8.1")
        self.assertEqual(result["expected_tag"], "v0.8.1")

    def test_standard_semver_versions_pass(self):
        for version in ["0.6.1", "0.7.0", "1.0.0", "0.7.0-dev.1", "1.2.3+build.7"]:
            self.assertEqual(release_validator.validate_version(version), version)

    def test_non_semver_release_numbers_fail(self):
        for version in ["0.61", "0.65", "0.6.0.5", "v0.6.1", "01.2.3"]:
            with self.assertRaises(release_validator.ReleasePolicyError):
                release_validator.validate_version(version)

    def test_development_uses_git_commits_not_public_tags(self):
        policy = release_validator.load_policy()
        self.assertEqual(policy["versioning"]["development_identity"], "git_commit")
        self.assertFalse(policy["development"]["public_tag_each_commit"])
        self.assertEqual(policy["development"]["push_policy"], "VERIFIED_RELEASE_MILESTONES")

    def test_published_tags_are_retained_and_immutable(self):
        policy = release_validator.load_policy()
        self.assertTrue(policy["release"]["published_tags_immutable"])
        self.assertTrue(policy["history"]["retain_published_tags"])
        self.assertFalse(policy["history"]["duplicate_release_trees"])
        self.assertEqual(policy["history"]["default_context"], "EXCLUDE")

    def test_structured_tag_note_passes(self):
        note = """ICM v0.6.1 - Release and version governance

Previous: v0.6.0

Added
- Release policy.

Fixed
- Corrected version naming.

Verification
- Full regression PASS.
"""
        result = release_validator.validate_tag_message(note, "0.6.1")
        self.assertEqual(result["sections"], ["Added", "Fixed", "Verification"])

    def test_tag_note_requires_verification(self):
        note = """ICM v0.6.1 - Release and version governance

Previous: v0.6.0

Changed
- Version policy.
"""
        with self.assertRaises(release_validator.ReleasePolicyError):
            release_validator.validate_tag_message(note, "0.6.1")

    def test_policy_rejects_duplicate_release_trees(self):
        policy = release_validator.load_policy()
        policy["history"]["duplicate_release_trees"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "release_policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            with self.assertRaises(release_validator.ReleasePolicyError):
                release_validator.load_policy(root)


    def test_context_metric_thresholds_must_be_positive(self):
        policy = release_validator.load_policy()
        policy["release"]["context_metrics"]["tracked_text_growth_warning_percent"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "release_policy.json").write_text(
                json.dumps(policy), encoding="utf-8"
            )
            with self.assertRaises(release_validator.ReleasePolicyError):
                release_validator.load_policy(root)

    def test_tag_note_rejects_empty_sections(self):
        note = """ICM v0.8.1 - Hardening

Previous: v0.8.0

Fixed
- Correctness fixes.

Verification
"""
        with self.assertRaises(release_validator.ReleasePolicyError):
            release_validator.validate_tag_message(note, "0.8.1")

    def test_tag_note_rejects_invalid_previous_version(self):
        note = """ICM v0.8.1 - Hardening

Previous: vbanana

Fixed
- Correctness fixes.

Verification
- Tests PASS.
"""
        with self.assertRaises(release_validator.ReleasePolicyError):
            release_validator.validate_tag_message(note, "0.8.1")

    def test_context_metric_thresholds_must_be_finite(self):
        policy = release_validator.load_policy()
        policy["release"]["context_metrics"]["tracked_text_growth_warning_percent"] = float("nan")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "release_policy.json").write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaises(release_validator.ReleasePolicyError):
                release_validator.load_policy(root)


if __name__ == "__main__":
    unittest.main()
