import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "context_resolver", ROOT / "tools" / "context_resolver.py"
)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


class ContextRoutingTests(unittest.TestCase):
    def test_registry_is_complete(self):
        resolver.validate_registry()
        routes = json.loads(
            (ROOT / "config/routes.json").read_text(encoding="utf-8")
        )["routes"]
        self.assertEqual(len(routes), 10)
        for route in routes:
            self.assertTrue((ROOT / route["context"]).is_file())

    def test_scoped_profile_plan_does_not_load_siblings(self):
        plan = resolver.build_plan("profile-development")
        self.assertEqual(plan["mode"], "SCOPED")
        self.assertEqual(plan["roots"], ["profiles"])
        self.assertIn("profiles/CONTEXT.md", plan["context_files"])
        self.assertNotIn("skills/CONTEXT.md", plan["context_files"])

    def test_direct_rejects_sibling_route(self):
        with self.assertRaises(resolver.ContextError):
            resolver.build_plan(
                "workspace-config", "DIRECT", ["test-development"]
            )

    def test_path_escape_fails_closed(self):
        with self.assertRaises(resolver.ContextError):
            resolver.confined("../outside")

    def test_unknown_route_fails_closed(self):
        with self.assertRaises(resolver.ContextError):
            resolver.build_plan("does-not-exist")

    def test_global_requires_reason_and_explicit_scope(self):
        with self.assertRaises(resolver.ContextError):
            resolver.build_plan(
                "workspace-architecture", "GLOBAL", ["test-development"]
            )
        with self.assertRaises(resolver.ContextError):
            resolver.build_plan(
                "workspace-architecture", "GLOBAL", [],
                "cross-system verification"
            )
        plan = resolver.build_plan(
            "workspace-architecture", "GLOBAL", ["test-development"],
            "cross-system verification"
        )
        self.assertEqual(plan["roots"], ["_core", "tests"])

    def test_mutation_adds_conventions(self):
        plan = resolver.build_plan("workspace-architecture", mutation=True)
        self.assertIn("_core/CONVENTIONS.md", plan["context_files"])

    def test_reference_and_run_content_are_data_by_default(self):
        policy = json.loads(
            (ROOT / "config/context_policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            policy["content_roles"]["references"], "data_by_default"
        )
        self.assertEqual(
            policy["content_roles"]["work"], "data_and_state_by_default"
        )
        self.assertFalse(
            policy["progressive_disclosure"]["siblings_auto_loaded"]
        )

    def test_visible_prefix_is_utf8_correct(self):
        cfg = json.loads(
            (ROOT / "config/workspace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            cfg["interaction"]["visible_role_prefix"],
            "╰── <ROLE OR AGENT NAME>",
        )

    def test_workspace_version(self):
        ws = json.loads((ROOT / "WORKSPACE.json").read_text(encoding="utf-8"))
        self.assertEqual(ws["workspace_version"], "0.4.0")
        self.assertEqual(ws["status"], "RUN_ARCHITECTURE")

    def test_supporting_routes_are_explicit_and_ordered(self):
        plan = resolver.build_plan(
            "workspace-architecture",
            "SCOPED",
            ["test-development", "tool-development"],
        )
        self.assertEqual(
            plan["supporting_routes"],
            ["test-development", "tool-development"],
        )
        self.assertEqual(plan["roots"], ["_core", "tests", "tools"])

    def test_required_context_path_missing_fails_closed(self):
        original = resolver.confined
        def fake_confined(rel):
            if rel == "profiles/CONTEXT.md":
                return ROOT / "profiles" / "__missing_context__.md"
            return original(rel)
        resolver.confined = fake_confined
        try:
            with self.assertRaises(resolver.ContextError):
                resolver.build_plan("profile-development")
        finally:
            resolver.confined = original


if __name__ == "__main__":
    unittest.main()
