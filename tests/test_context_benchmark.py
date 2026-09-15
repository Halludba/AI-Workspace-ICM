"""Tests for deterministic context benchmark fixtures and metrics."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("context_benchmark", ROOT / "tools" / "context_benchmark.py")
context_benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context_benchmark)


class ContextBenchmarkTests(unittest.TestCase):
    def test_policy_covers_research_benchmark_matrix(self):
        ids = {case["id"] for case in context_benchmark.catalog(ROOT)}
        required = {
            "tiny-direct", "ordinary-scoped", "genuine-global", "single-file-10k", "single-file-50k",
            "single-file-100k", "single-file-150k", "distributed-150k", "evidence-spread",
            "one-symbol-change", "cross-file-dependency",
        }
        self.assertEqual(ids, required)

    def test_fixed_git_ref_baseline_is_reproducible_and_explicitly_unavailable(self):
        first = context_benchmark.baseline("v0.9.0", ROOT)
        second = context_benchmark.baseline("v0.9.0", ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first["source_revision"], subprocess.check_output(["git", "rev-parse", "v0.9.0^{}"], cwd=ROOT, text=True).strip())
        self.assertTrue(all(value is None for value in first["observed_metrics"].values()))
        self.assertTrue(all(value == "UNAVAILABLE" for value in first["metric_availability"].values()))
        self.assertEqual(first["routed_context"]["status"], "UNAVAILABLE")

    def test_150k_fixture_is_generated_on_demand_near_target(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = context_benchmark.materialize("single-file-150k", Path(td), ROOT)
            self.assertEqual(len(manifest["files"]), 1)
            self.assertLess(abs(manifest["estimated_tokens"] - 150000) / 150000, 0.01)

    def test_evidence_spread_places_markers_at_distinct_regions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_benchmark.materialize("evidence-spread", root, ROOT)
            ratios = {}
            for pos in ("start", "middle", "end"):
                text = (root / f"evidence_{pos}.py").read_text(encoding="utf-8")
                ratios[pos] = text.index(f"ICM_EVIDENCE_{pos.upper()}") / len(text)
            self.assertLess(ratios["start"], 0.2)
            self.assertTrue(0.35 < ratios["middle"] < 0.65)
            self.assertGreater(ratios["end"], 0.8)

    def test_change_and_dependency_fixtures_preserve_intended_structure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context_benchmark.materialize("one-symbol-change", root / "change", ROOT)
            base = (root / "change/base.py").read_text(encoding="utf-8")
            changed = (root / "change/changed.py").read_text(encoding="utf-8")
            self.assertIn("return 1", base)
            self.assertIn("return 2", changed)
            context_benchmark.materialize("cross-file-dependency", root / "dep", ROOT)
            self.assertIn("from beta import dependency", (root / "dep/alpha.py").read_text(encoding="utf-8"))
            self.assertIn("def dependency", (root / "dep/beta.py").read_text(encoding="utf-8"))

    def test_summary_reports_p50_p95_and_preserves_unavailable_metrics(self):
        samples = [
            {"observed_metrics": {"wall_time_ms": 10, "tool_calls": 1}},
            {"observed_metrics": {"wall_time_ms": 20, "tool_calls": 2}},
            {"observed_metrics": {"wall_time_ms": 100, "tool_calls": 3}},
        ]
        result = context_benchmark.summarize_samples(samples, ROOT)
        self.assertEqual(result["metrics"]["wall_time_ms"]["p50"], 20.0)
        self.assertEqual(result["metrics"]["wall_time_ms"]["p95"], 100.0)
        self.assertEqual(result["metrics"]["ttft_ms"]["status"], "UNAVAILABLE")

    def test_workspace_cli_exposes_benchmark_catalog(self):
        proc = subprocess.run([sys.executable, str(ROOT / "icm"), "inspect", "benchmark", "catalog"], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["valid"])
        self.assertGreaterEqual(len(payload["cases"]), 11)


if __name__ == "__main__":
    unittest.main()
