import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Before Python 3.11, importing tomllib fails; simulate that on the current interpreter.
WITHOUT_TOMLLIB = (
    "import runpy, sys\n"
    "sys.modules['tomllib'] = None\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


class OldPythonTests(unittest.TestCase):
    def test_tools_explain_the_python_requirement_without_a_traceback(self):
        for name in ("kit.py", "skill_watch.py"):
            with self.subTest(tool=name):
                script = str(ROOT / "tools" / name)
                result = subprocess.run(
                    [sys.executable, "-c", WITHOUT_TOMLLIB, script],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("needs Python 3.11 or newer", result.stderr)
                self.assertIn(script, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
