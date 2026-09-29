import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("test_fast", ROOT / "tools/test_fast.py")
test_fast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test_fast)


class TestFastDefaults(unittest.TestCase):
    def test_pytest_flags_are_quiet_short_and_failfast(self):
        self.assertEqual(test_fast.PYTEST_FLAGS, ("-q", "--tb=short", "-x"))
        command = test_fast.pytest_command(["tests/test_example.py"])
        self.assertEqual(command[1:4], ["-q", "--tb=short", "-x"])
        self.assertIn("tests/test_example.py", command)

    def test_unittest_flags_are_quiet_and_failfast(self):
        self.assertEqual(test_fast.UNITTEST_FLAGS, ("-q", "-f"))
        command = test_fast.unittest_command(python=sys.executable)
        self.assertEqual(command[:3], [sys.executable, "-m", "unittest"])
        self.assertEqual(command[-2:], ["-q", "-f"])
        self.assertIn("discover", command)
        self.assertIn("tests", command)

    def test_cross_language_command_constants(self):
        self.assertEqual(test_fast.NODE_TEST_COMMAND, ("npm", "test", "--", "--bail", "--silent"))
        self.assertEqual(test_fast.RUST_TEST_COMMAND, ("cargo", "test", "--", "--nocapture=false"))

    def test_print_command_does_not_run_suite(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/test_fast.py"),
                "--runner",
                "unittest",
                "--print-command",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        printed = result.stdout.strip()
        self.assertIn("-m unittest", printed)
        self.assertIn("-q", printed)
        self.assertIn("-f", printed)

    def test_unittest_runner_keeps_output_compact_on_failure(self):
        with tempfile.TemporaryDirectory(prefix="mkl-test-fast-") as temporary:
            suite = Path(temporary)
            (suite / "tests").mkdir()
            (suite / "tests" / "test_fail.py").write_text(
                "import unittest\n"
                "class Fail(unittest.TestCase):\n"
                "    def test_boom(self):\n"
                "        self.assertEqual(1, 2)\n",
                encoding="utf-8",
            )
            command = test_fast.unittest_command(["discover", "-s", "tests"], python=sys.executable)
            result = subprocess.run(
                command,
                cwd=suite,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            combined = result.stdout + result.stderr
            # Quiet mode suppresses per-test OK chatter; failfast still reports the failure.
            self.assertNotIn(" ... ok", combined)
            self.assertTrue(
                "FAIL:" in combined or "AssertionError" in combined or "FAILED" in combined,
                msg=combined,
            )


if __name__ == "__main__":
    unittest.main()
