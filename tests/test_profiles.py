import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
EXPECTED = {
    "reasoning-auditor": "Reasoning Auditor",
    "prompt-architect": "Prompt Architect",
    "project-scout": "Project Scout",
}
REQUIRED_SECTIONS = [
    "Identity", "Purpose", "Activation", "Operating Priorities",
    "Required Behaviors", "Output Discipline", "Authority Boundary", "Non-Goals",
]


def sections(text: str) -> list[str]:
    return re.findall(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)


class SpecialistProfileTests(unittest.TestCase):
    def test_exact_installed_specialists_exist(self):
        actual = {p.name for p in PROFILES.iterdir() if p.is_dir()}
        self.assertTrue(set(EXPECTED).issubset(actual))
        for profile_id in EXPECTED:
            self.assertTrue((PROFILES / profile_id / "PROFILE.md").is_file())

    def test_profile_section_grammar_is_consistent(self):
        for profile_id, display_name in EXPECTED.items():
            text = (PROFILES / profile_id / "PROFILE.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"# {display_name}\n"), profile_id)
            self.assertEqual(sections(text), REQUIRED_SECTIONS, profile_id)

    def test_visible_marker_matches_profile_identity(self):
        for profile_id, display_name in EXPECTED.items():
            text = (PROFILES / profile_id / "PROFILE.md").read_text(encoding="utf-8")
            self.assertIn(f"`╰── ֎ [{display_name}] ◄`", text, profile_id)

    def test_activation_is_explicit_not_resident(self):
        for profile_id in EXPECTED:
            text = (PROFILES / profile_id / "PROFILE.md").read_text(encoding="utf-8")
            activation = text.split("## Activation\n", 1)[1].split("\n## ", 1)[0].lower()
            self.assertIn("explicit", activation, profile_id)
            self.assertIn("load only", activation, profile_id)

    def test_authority_boundary_remains_below_core(self):
        for profile_id in EXPECTED:
            text = (PROFILES / profile_id / "PROFILE.md").read_text(encoding="utf-8")
            authority = text.split("## Authority Boundary\n", 1)[1].split("\n## ", 1)[0]
            self.assertIn("_core/", authority, profile_id)
            self.assertRegex(authority.lower(), r"cannot|below", profile_id)

    def test_profiles_are_host_neutral(self):
        forbidden = ["OneDrive", "C:\\\\", "DESKTOP-", "Remote Desktop Commander"]
        for profile_id in EXPECTED:
            text = (PROFILES / profile_id / "PROFILE.md").read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, profile_id)

    def test_reasoning_auditor_forbids_private_reasoning_capture(self):
        text = (PROFILES / "reasoning-auditor" / "PROFILE.md").read_text(encoding="utf-8").lower()
        self.assertIn("without requesting or storing private chain-of-thought", text)
        self.assertIn("do not produce private chain-of-thought", text)

    def test_profile_router_forbids_sibling_autoload(self):
        context = (PROFILES / "CONTEXT.md").read_text(encoding="utf-8").lower()
        self.assertIn("do not load sibling profiles automatically", context)


if __name__ == "__main__":
    unittest.main()
