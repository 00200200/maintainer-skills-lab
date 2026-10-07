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

minifier_spec = importlib.util.spec_from_file_location(
    "minify_torch_trace", ROOT / "tools/minify_torch_trace.py"
)
minifier = importlib.util.module_from_spec(minifier_spec)
minifier_spec.loader.exec_module(minifier)

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

    def test_minify_torch_trace_compresses_dispatcher_frames(self):
        # Build 150-line PyTorch autograd traceback dominated by dispatcher frames
        lines = ["Traceback (most recent call last):"]
        lines.append('  File "train.py", line 42, in <module>')
        lines.append("    loss = model(inputs)")

        # 50 internal module dispatcher frames
        for step in range(50):
            lines.append(
                f'  File "/site-packages/torch/nn/modules/module.py", line {1000 + step}, in _call_impl'
            )
            lines.append("    return forward_call(*args, **kwargs)")

        lines.append('  File "models/transformer.py", line 88, in forward')
        lines.append("    return self.proj(attn_out)")

        # 25 internal autograd dispatcher frames
        for step in range(25):
            lines.append(
                f'  File "/site-packages/torch/autograd/__init__.py", line {200 + step}, in backward'
            )
            lines.append("    Variable._execution_engine.run_backward(...)")

        lines.append("RuntimeError: mat1 and mat2 shapes cannot be multiplied (32x128 and 256x512)")

        raw_traceback = "\n".join(lines)
        self.assertGreater(len(lines), 150)

        minified = minifier.minify_trace(raw_traceback)
        minified_lines = minified.splitlines()

        # Compressed to < 15 lines of actionable user-code stack frames
        self.assertLess(len(minified_lines), 15)
        self.assertIn('File "train.py", line 42', minified)
        self.assertIn('File "models/transformer.py", line 88', minified)
        self.assertIn("skipped 50 internal PyTorch/dispatcher frames", minified)
        self.assertIn("skipped 25 internal PyTorch/dispatcher frames", minified)
        self.assertIn(
            "RuntimeError: mat1 and mat2 shapes cannot be multiplied (32x128 and 256x512)",
            minified,
        )

    def test_minify_trace_empty_and_clean(self):
        self.assertEqual(minifier.minify_trace(""), "")
        clean_trace = (
            "Traceback (most recent call last):\n"
            '  File "test.py", line 10, in run\n'
            "    raise ValueError('invalid input')\n"
            "ValueError: invalid input"
        )
        self.assertEqual(minifier.minify_trace(clean_trace), clean_trace)


if __name__ == "__main__":
    unittest.main()
