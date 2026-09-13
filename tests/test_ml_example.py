import contextlib
import copy
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ml_example", ROOT / "examples/ml-training/run.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)

BASELINE = {
    "residual_shape": [2, 2],
    "loss": 2.0,
    "gradient": 2.0,
    "weight_after_step": 0.8,
}
CANDIDATE = {
    "residual_shape": [2, 1],
    "loss": 0.0,
    "gradient": 0.0,
    "weight_after_step": 1.0,
}


class MLExampleTests(unittest.TestCase):
    def test_known_broadcast_failure_and_fix_satisfy_oracle(self):
        result = example.assess({"baseline": BASELINE, "candidate": CANDIDATE})
        self.assertTrue(result["verified"])
        self.assertEqual(result["baseline"]["outcome"], "assertion-failure")
        self.assertEqual(result["candidate"]["outcome"], "pass")

    def test_two_passing_runs_do_not_reproduce_bug(self):
        result = example.assess({"baseline": CANDIDATE, "candidate": CANDIDATE})
        self.assertFalse(result["verified"])

    def test_wrong_update_or_shape_cannot_hide_behind_zero_loss(self):
        for field, value in (("weight_after_step", 0.8), ("residual_shape", [2, 2])):
            with self.subTest(field=field):
                candidate = {**CANDIDATE, field: value}
                result = example.assess({"baseline": BASELINE, "candidate": candidate})
                self.assertFalse(result["verified"])

    def test_nonfinite_numbers_never_verify(self):
        for side in ("baseline", "candidate"):
            for field in ("loss", "gradient", "weight_after_step"):
                for value in (float("nan"), float("inf")):
                    with self.subTest(side=side, field=field, value=value):
                        cases = copy.deepcopy({"baseline": BASELINE, "candidate": CANDIDATE})
                        cases[side][field] = value
                        self.assertFalse(example.assess(cases)["verified"])

    def test_unrelated_baseline_failure_is_not_reproduction(self):
        baseline = {**BASELINE, "loss": 100.0}
        self.assertFalse(example.assess({"baseline": baseline, "candidate": CANDIDATE})["verified"])

    def test_setup_failure_has_distinct_exit_code_and_no_success_claim(self):
        def unavailable():
            raise ImportError("fixture dependency unavailable")

        output = io.StringIO()
        with patch.dict(example.RUNNERS, pytorch=unavailable), contextlib.redirect_stdout(output):
            exit_code = example.main(["--framework", "pytorch"])
        report = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["outcome"], "execution-error")
        self.assertFalse(report["verified"])


if __name__ == "__main__":
    unittest.main()
