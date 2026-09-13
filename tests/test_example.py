import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("example", ROOT / "examples/bugfix/run.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class ExampleTests(unittest.TestCase):
    def test_reference_fix_satisfies_same_regression(self):
        report = example.evaluate(example.HERE / "before/slug.py", example.HERE / "after/slug.py")
        self.assertTrue(report["verified"])
        self.assertEqual(report["baseline"]["outcome"], "assertion-failure")
        self.assertEqual(report["baseline"]["errors"], 0)
        self.assertEqual(report["candidate"]["outcome"], "pass")
        self.assertEqual(report["baseline"]["tests_run"], report["candidate"]["tests_run"])

    def test_passing_both_versions_does_not_prove_regression(self):
        fixed = example.HERE / "after/slug.py"
        self.assertFalse(example.evaluate(fixed, fixed)["verified"])

    def test_broken_candidate_is_not_verified(self):
        broken = example.HERE / "before/slug.py"
        self.assertFalse(example.evaluate(broken, broken)["verified"])

    def test_import_failure_is_not_bug_reproduction(self):
        with tempfile.TemporaryDirectory() as temporary:
            broken = Path(temporary) / "slug.py"
            broken.write_text("import deliberately_missing_dependency_for_mkl\n")
            report = example.evaluate(broken, example.HERE / "after/slug.py")
            self.assertFalse(report["verified"])
            self.assertEqual(report["baseline"]["outcome"], "execution-error")

    def test_timeout_is_not_bug_reproduction(self):
        with tempfile.TemporaryDirectory() as temporary:
            broken = Path(temporary) / "slug.py"
            broken.write_text("import time\ntime.sleep(5)\n")
            report = example.run_case(broken, timeout=0.05)
            self.assertEqual(report["outcome"], "execution-error")
            self.assertEqual(report["details"], "timeout")


if __name__ == "__main__":
    unittest.main()
