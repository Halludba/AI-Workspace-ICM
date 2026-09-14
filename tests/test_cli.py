import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_python_trampoline_dispatches_run_help(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "icm"), "run", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ICM filesystem-native execution kernel", result.stdout)
        self.assertIn("create-attempt", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows wrapper test")
    def test_windows_cmd_trampoline_dispatches_run_help(self):
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "icm.cmd", "run", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ICM filesystem-native execution kernel", result.stdout)


if __name__ == "__main__":
    unittest.main()
