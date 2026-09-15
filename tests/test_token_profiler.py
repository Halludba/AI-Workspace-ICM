import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "token_profiler", ROOT / "tools" / "token_profiler.py"
)
profiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiler)


class TokenProfilerTests(unittest.TestCase):
    def git(self, root, *args):
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def make_repo(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "tests@example.invalid")
        self.git(root, "config", "user.name", "ICM Tests")
        (root / "config").mkdir()
        return temp, root

    def write_policy(self, root, tracked=25.0, orientation=15.0):
        policy = {
            "release": {
                "context_metrics": {
                    "tracked_text_growth_warning_percent": tracked,
                    "orientation_growth_warning_percent": orientation,
                    "growth_review_skill": "skills/context-optimizer/SKILL.md",
                }
            }
        }
        (root / "config" / "release_policy.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )

    def seed_baseline(self, root):
        self.write_policy(root)
        (root / "WORKSPACE.md").write_text("workspace\n", encoding="utf-8")
        (root / "CONTEXT.md").write_text("context\n", encoding="utf-8")
        (root / "WORKSPACE.json").write_text('{"v":"1"}\n', encoding="utf-8")
        (root / "module.py").write_text("VALUE = 'small'\n", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "baseline")
        self.git(root, "tag", "base")

    def test_profile_release_snapshot(self):
        result = profiler.profile("v0.7.0")
        self.assertGreater(result["total"]["estimated_tokens"], 100000)
        self.assertGreater(result["orientation"]["estimated_tokens"], 1000)
        self.assertEqual(result["source"], "v0.7.0")

    def test_release_growth_over_25_percent_requires_review(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            (root / "module.py").write_text("x = '" + ("a" * 1000) + "'\n", encoding="utf-8")
            result = profiler.compare("base", None, root)
            self.assertTrue(result["growth_review_required"])
            self.assertIn("TRACKED_TEXT_GROWTH", result["growth_review_causes"])
            self.assertEqual(result["growth_review_skill"], "skills/context-optimizer/SKILL.md")
            self.assertGreaterEqual(result["delta_percent"]["tracked_text"], 25.0)

    def test_orientation_growth_has_separate_warning(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            (root / "WORKSPACE.md").write_text("workspace " * 100, encoding="utf-8")
            result = profiler.compare("base", None, root)
            self.assertTrue(result["growth_review_required"])
            self.assertIn("ORIENTATION_GROWTH", result["growth_review_causes"])

    def test_binary_file_is_not_counted_as_text(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            (root / "blob.bin").write_bytes(b"\x00\x01\x02")
            result = profiler.profile(None, root, include_files=True)
            self.assertNotIn("blob.bin", result["by_file"])

    def test_python_symbol_profile_orders_largest_first(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            source = "def small():\n    return 1\n\n" + "def large():\n" + "    x = 1\n" * 40 + "    return x\n"
            (root / "sample.py").write_text(source, encoding="utf-8")
            symbols = profiler.profile_python_symbols("sample.py", None, root)
            self.assertEqual(symbols[0]["name"], "large")
            self.assertGreater(symbols[0]["estimated_tokens"], symbols[-1]["estimated_tokens"])

    def test_invalid_growth_policy_fails_closed(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            self.write_policy(root, tracked=-1)
            with self.assertRaises(profiler.TokenProfileError):
                profiler.compare("base", None, root)

    def test_v070_growth_from_v061_is_below_global_warning(self):
        result = profiler.compare("v0.6.1", "v0.7.0")
        self.assertFalse(result["growth_review_required"])
        self.assertLess(result["delta_percent"]["tracked_text"], 25.0)

    def test_working_tree_profiles_context_optimizer_skill_separately(self):
        result = profiler.profile(None)
        self.assertIn("context-optimizer", result["by_skill"])
        self.assertGreater(result["by_skill"]["context-optimizer"]["estimated_tokens"], 0)

    def test_working_tree_profiles_pdf_styler_separately(self):
        result = profiler.profile(None)
        self.assertIn("pdf-styler", result["by_skill"])
        self.assertGreater(result["by_skill"]["pdf-styler"]["estimated_tokens"], 0)
        self.assertLess(result["orientation"]["estimated_tokens"], result["by_skill"]["pdf-styler"]["estimated_tokens"] + 3000)

    def test_skills_root_metadata_is_not_reported_as_skill(self):
        result = profiler.profile(None)
        self.assertNotIn("registry.json", result["by_skill"])
        self.assertNotIn("CONTEXT.md", result["by_skill"])

    def test_crlf_and_lf_are_equivalent_for_release_comparison(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            original = (root / "module.py").read_text(encoding="utf-8")
            (root / "module.py").write_bytes(original.replace("\n", "\r\n").encode("utf-8"))
            result = profiler.compare("base", None, root)
            self.assertEqual(result["delta_percent"]["tracked_text"], 0.0)
            self.assertEqual(result["current"]["scope"], "TRACKED_WORKTREE")

    def test_release_comparison_excludes_untracked_files(self):
        temp, root = self.make_repo()
        with temp:
            self.seed_baseline(root)
            (root / "untracked.txt").write_text("x" * 5000, encoding="utf-8")
            compared = profiler.compare("base", None, root)
            diagnostic = profiler.profile(None, root)
            self.assertEqual(compared["delta_percent"]["tracked_text"], 0.0)
            self.assertEqual(compared["current"]["scope"], "TRACKED_WORKTREE")
            self.assertEqual(diagnostic["scope"], "WORKTREE_WITH_UNTRACKED")
            self.assertGreater(diagnostic["total"]["estimated_tokens"], compared["current"]["total"]["estimated_tokens"])

    def test_orientation_definition_matches_startup_files(self):
        result = profiler.profile("v0.8.0")
        self.assertEqual(result["orientation_definition"], ["WORKSPACE.md", "CONTEXT.md"])

    def test_git_ref_profile_uses_batch_blob_reader(self):
        original = profiler._ref_bytes
        profiler._ref_bytes = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("per-file git show used"))
        try:
            result = profiler.profile("v0.8.0")
            self.assertEqual(result["scope"], "GIT_REF")
        finally:
            profiler._ref_bytes = original


    def test_git_ref_batch_reader_preserves_legal_unusual_paths(self):
        temp, root = self.make_repo()
        with temp:
            names = ["ordinary.py", "line\nbreak.py", "space name.py", "unicode-?.py"]
            records = []
            for index, name in enumerate(names):
                content = f"VALUE = {index}\n".encode("utf-8")
                blob = subprocess.run(
                    ["git", "hash-object", "-w", "--stdin"], cwd=root,
                    input=content, capture_output=True, check=True,
                ).stdout.strip().decode("ascii")
                records.append(f"100644 blob {blob}\t".encode("ascii") + name.encode("utf-8") + b"\x00")
            tree = subprocess.run(
                ["git", "mktree", "-z"], cwd=root, input=b"".join(records),
                capture_output=True, check=True,
            ).stdout.strip().decode("ascii")
            commit = subprocess.run(
                ["git", "commit-tree", tree, "-m", "pathological paths"], cwd=root,
                capture_output=True, check=True,
            ).stdout.strip().decode("ascii")
            result = profiler.profile(commit, root, include_files=True)
            self.assertEqual(set(result["by_file"]), set(names))
            self.assertEqual(result["text_files"], len(names))


if __name__ == "__main__":
    unittest.main()
