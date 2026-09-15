"""Tests for deterministic sub-file exact-source navigation."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("source_navigator", ROOT / "tools/source_navigator.py")
nav = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nav)


class SourceNavigatorTests(unittest.TestCase):
    def make_workspace(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "ICM Tests"], cwd=root, check=True)
        (root / "config").mkdir()
        policy = json.loads((ROOT / "config/source_navigator_policy.json").read_text(encoding="utf-8"))
        (root / "config/source_navigator_policy.json").write_text(json.dumps(policy), encoding="utf-8")
        return temp, root

    def commit_source(self, root: Path, text: str, name: str = "sample.py") -> None:
        (root / name).write_text(text, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "source"], cwd=root, check=True)

    def test_shared_ast_map_preserves_nested_and_control_flow_definitions(self):
        mapping = nav.python_source_map.build_python_source_map(
            "if True:\n    def conditional():\n        return 1\n\nclass A:\n    def method(self):\n        return 2\n"
        )
        self.assertEqual([s["qualified_name"] for s in mapping["symbols"]], ["conditional", "A", "A.method"])

    def test_map_is_derived_noncanonical_and_exposes_exact_source_identity(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "class A:\n    def method(self):\n        return 1\n\ndef top():\n    return 2\n")
            first = nav.map_source("sample.py", root=root)
            second = nav.map_source("sample.py", root=root)
            self.assertEqual([s["qualified_name"] for s in first["source_map"]["symbols"]], ["A", "A.method", "top"])
            self.assertEqual(first["cache"]["authority"], "NONCANONICAL_DERIVED_HINT")
            self.assertEqual(second["cache"]["status"], "HIT")
            self.assertEqual(len(first["source"]["sha256"]), 64)
            self.assertTrue(first["exact_source_recoverable"])
            self.assertNotIn("text", first)

    def test_exact_symbol_and_region_return_only_selected_source(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "before = 0\n\ndef target():\n    value = 1\n    return value\n\nafter = 2\n")
            selected = nav.retrieve_symbol("sample.py", "target", root=root)
            self.assertEqual(selected["retrieval_kind"], "EXACT_SYMBOL")
            self.assertIn("def target", selected["text"])
            self.assertNotIn("before = 0", selected["text"])
            self.assertNotIn("after = 2", selected["text"])
            region = nav.retrieve_region("sample.py", 1, 1, root=root)
            self.assertEqual(region["retrieval_kind"], "EXACT_REGION")
            self.assertEqual(region["text"], "before = 0")
            self.assertEqual(region["semantic_coverage"], "NOT_CLAIMED")

    def test_ambiguous_short_symbol_fails_and_qualified_succeeds(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "class A:\n    def run(self):\n        return 1\nclass B:\n    def run(self):\n        return 2\n")
            with self.assertRaises(nav.SourceNavigatorError):
                nav.retrieve_symbol("sample.py", "run", root=root)
            selected = nav.retrieve_symbol("sample.py", "A.run", root=root)
            self.assertIn("return 1", selected["text"])

    def test_source_change_and_indexer_change_invalidate_cache_identity(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "def value():\n    return 1\n")
            first = nav.map_source("sample.py", root=root)
            policy = nav.load_policy(root)
            path1 = nav._cache_path(root, policy, first["source"]["sha256"])
            (root / "sample.py").write_text("def value():\n    return 22\n", encoding="utf-8")
            changed = nav.map_source("sample.py", root=root)
            path2 = nav._cache_path(root, policy, changed["source"]["sha256"])
            self.assertNotEqual(first["source"]["sha256"], changed["source"]["sha256"])
            self.assertNotEqual(path1, path2)
            policy_path = root / "config/source_navigator_policy.json"
            policy2 = json.loads(policy_path.read_text(encoding="utf-8"))
            policy2["indexer_version"] = "2"
            policy_path.write_text(json.dumps(policy2), encoding="utf-8")
            path3 = nav._cache_path(root, nav.load_policy(root), changed["source"]["sha256"])
            self.assertNotEqual(path2, path3)

    def test_git_ref_provenance_pins_revision_and_hash(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "def value():\n    return 1\n")
            subprocess.run(["git", "tag", "base"], cwd=root, check=True)
            result = nav.map_source("sample.py", "base", root=root, use_cache=False)
            commit = subprocess.check_output(["git", "rev-parse", "base^{}"], cwd=root, text=True).strip()
            self.assertEqual(result["source"]["git_revision"], commit)
            self.assertEqual(result["source"]["source_kind"], "GIT_REF")
            self.assertEqual(len(result["source"]["sha256"]), 64)

    def test_malformed_or_unsupported_semantics_fail_closed_but_exact_region_remains_available(self):
        temp, root = self.make_workspace()
        with temp:
            (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
            (root / "note.txt").write_text("plain text\nsecond line\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "sources"], cwd=root, check=True)
            for path in ("bad.py", "note.txt"):
                with self.assertRaises(nav.SourceNavigatorError):
                    nav.map_source(path, root=root)
                exact = nav.retrieve_region(path, 1, 1, root=root)
                self.assertEqual(exact["semantic_coverage"], "NOT_CLAIMED")

    def test_region_symbol_limits_and_single_snapshot_fail_closed(self):
        temp, root = self.make_workspace()
        with temp:
            self.commit_source(root, "def target():\n    return 1\n" + "".join(f"x{i} = {i}\n" for i in range(1100)))
            with self.assertRaises(nav.SourceNavigatorError):
                nav.retrieve_region("sample.py", 1, 1001, root=root)
            with self.assertRaises(nav.SourceNavigatorError):
                nav.retrieve_symbol("sample.py", "target", context_lines=201, root=root)
            original = nav._source_bytes
            calls = []
            def counted(*args, **kwargs):
                calls.append(1)
                return original(*args, **kwargs)
            nav._source_bytes = counted
            try:
                nav.retrieve_symbol("sample.py", "target", root=root)
            finally:
                nav._source_bytes = original
            self.assertEqual(len(calls), 1)

    def test_workspace_cli_returns_only_requested_symbol_slice(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "icm"), "inspect", "source", "symbol", "tools/token_profiler.py", "profile_route"],
            cwd=ROOT, text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["retrieval_kind"], "EXACT_SYMBOL")
        self.assertIn("def profile_route", payload["text"])
        self.assertNotIn("def profile_python_symbols", payload["text"])


if __name__ == "__main__":
    unittest.main()
