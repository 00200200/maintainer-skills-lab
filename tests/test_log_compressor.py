import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("log_compressor", ROOT / "tools/log_compressor.py")
log_compressor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(log_compressor)


class LogCompressorUnitTests(unittest.TestCase):
    def test_approximate_tokens(self):
        self.assertEqual(log_compressor.approximate_tokens(""), 0)
        self.assertGreater(log_compressor.approximate_tokens("test log output line"), 0)

    def test_merge_spans(self):
        spans = [(0, 5), (3, 8), (10, 15), (14, 20)]
        merged = log_compressor.merge_spans(spans)
        self.assertEqual(merged, [(0, 8), (10, 20)])

    def test_find_error_anchors(self):
        sample = [
            "running 10 tests",
            "test_one ... ok",
            "Traceback (most recent call last):",
            '  File "test_fail.py", line 42, in test_broken',
            "    assert x == y",
            "AssertionError: 5 != 10",
            "FAILED tests/test_broken.py::test_broken",
            "error[E0308]: mismatched types",
            "npm ERR! code ELIFECYCLE",
        ]
        anchors = log_compressor.find_error_anchor_indices(sample)
        self.assertIn(2, anchors)  # Traceback
        self.assertIn(5, anchors)  # AssertionError
        self.assertIn(6, anchors)  # FAILED
        self.assertIn(7, anchors)  # error[E0308]
        self.assertIn(8, anchors)  # npm ERR!

    def test_empty_input(self):
        compressed, stats = log_compressor.compress_log("")
        self.assertEqual(compressed, "")
        self.assertEqual(stats["original_lines"], 0)

    def test_small_input_stays_uncompressed(self):
        small = "line 1\nline 2\nline 3\n"
        compressed, stats = log_compressor.compress_log(small, max_lines=10)
        self.assertEqual(compressed, small)
        self.assertEqual(stats["original_lines"], 3)
        self.assertEqual(stats["reduction_pct"], 0.0)

    def test_noisy_pytest_compression(self):
        # Generate 1,500 lines of passing tests, with 1 failure in the middle
        lines = []
        lines.append("pytest-8.1.0 platform darwin -- Python 3.11.8")
        lines.append("rootdir: /tmp/project, configfile: pyproject.toml")
        lines.append("collected 500 items")
        lines.append("")

        for i in range(1, 200):
            lines.append(f"tests/test_feature_{i}.py . [ {i // 5}%]")

        # Error block
        lines.append(
            "=================================== FAILURES ==================================="
        )
        lines.append(
            "_________________________________ test_critical ________________________________"
        )
        lines.append("Traceback (most recent call last):")
        lines.append('  File "/tmp/project/tests/test_critical.py", line 88, in test_critical')
        lines.append("    assert actual == expected")
        lines.append("E   AssertionError: assert False is True")
        lines.append(
            "FAILED tests/test_critical.py::test_critical - AssertionError: assert False is True"
        )

        for i in range(201, 500):
            lines.append(f"tests/test_feature_{i}.py . [ {i // 5}%]")

        lines.append(
            "=========================== short test summary info ============================"
        )
        lines.append(
            "FAILED tests/test_critical.py::test_critical - AssertionError: assert False is True"
        )
        lines.append(
            "======================== 1 failed, 499 passed in 4.52s ========================="
        )

        raw_log = "\n".join(lines)
        self.assertGreater(len(lines), 500)

        compressed, stats = log_compressor.compress_log(raw_log, max_lines=60, max_tokens=800)

        # Must preserve critical diagnostics
        self.assertIn("AssertionError: assert False is True", compressed)
        self.assertIn("Traceback (most recent call last):", compressed)
        self.assertIn("1 failed, 499 passed in 4.52s", compressed)
        self.assertIn("lines of passing/standard output omitted", compressed)

        # Must be drastically compressed
        self.assertLess(stats["compressed_lines"], 70)
        self.assertGreater(stats["reduction_pct"], 75.0)

    def test_cli_file_and_json(self):
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8") as tmp:
            tmp.write(
                "header 1\nheader 2\n"
                + ("test ok\n" * 200)
                + "AssertionError: boom\n"
                + ("tail\n" * 10)
            )
            tmp.flush()

            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                exit_code = log_compressor.main([tmp.name, "--json"])
                self.assertEqual(exit_code, 0)
                parsed = json.loads(mock_out.getvalue())
                self.assertIn("compressed", parsed)
                self.assertIn("stats", parsed)
                self.assertIn("AssertionError: boom", parsed["compressed"])

    def test_extract_error_signature_python_traceback(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "/path/to/slug.py", line 24, in make_slug\n'
            '    raise ValueError("bad slug")\n'
            "ValueError: bad slug\n"
        )
        sig = log_compressor.extract_error_signature(tb)
        self.assertEqual(sig, 'ValueError("bad slug") at slug.py:24')

    def test_extract_error_signature_pytest_failed(self):
        pytest_log = "FAILED tests/test_api.py::test_login - AssertionError: assert 401 == 200\n"
        sig = log_compressor.extract_error_signature(pytest_log)
        self.assertEqual(sig, "AssertionError: assert 401 == 200 at test_api.py::test_login")

    def test_extract_error_signature_rust(self):
        rust_log = "error[E0308]: mismatched types\n  --> src/main.rs:42:5\n   |\n42 |     x + y\n"
        sig = log_compressor.extract_error_signature(rust_log)
        self.assertEqual(sig, "error[E0308]: mismatched types at main.rs:42")

    def test_extract_error_signature_empty_or_passing(self):
        self.assertIsNone(log_compressor.extract_error_signature(""))
        self.assertIsNone(log_compressor.extract_error_signature("all 50 tests passed in 0.2s\n"))

    def test_mask_repeated_observation_identical(self):
        tb_turn_1 = (
            "Running suite...\n"
            "Traceback (most recent call last):\n"
            '  File "slug.py", line 24, in make_slug\n'
            '    raise ValueError("bad slug")\n'
            "ValueError: bad slug\n" + ("extra trace info\n" * 50)
        )
        tb_turn_2 = (
            "Running suite turn 2...\n"
            "Traceback (most recent call last):\n"
            '  File "slug.py", line 24, in make_slug\n'
            '    raise ValueError("bad slug")\n'
            "ValueError: bad slug\n" + ("extra trace info\n" * 50)
        )

        masked, is_masked = log_compressor.mask_repeated_observation(tb_turn_2, tb_turn_1, turn=3)
        self.assertTrue(is_masked)
        self.assertIn("[Test failed with IDENTICAL signature as Turn 3:", masked)
        self.assertIn('ValueError("bad slug") at slug.py:24', masked)
        self.assertIn("Traceback omitted", masked)
        self.assertLess(len(masked), len(tb_turn_2) // 2)

    def test_mask_repeated_observation_changed_error(self):
        tb_turn_1 = (
            "Traceback (most recent call last):\n"
            '  File "slug.py", line 24, in make_slug\n'
            "ValueError: bad slug\n"
        )
        tb_turn_2 = (
            "Traceback (most recent call last):\n"
            '  File "slug.py", line 48, in make_slug\n'
            "IndexError: list index out of range\n"
        )

        result, is_masked = log_compressor.mask_repeated_observation(tb_turn_2, tb_turn_1)
        self.assertFalse(is_masked)
        self.assertEqual(result, tb_turn_2)

    def test_cli_mask_previous(self):
        with (
            tempfile.NamedTemporaryFile("w+", encoding="utf-8") as f_prev,
            tempfile.NamedTemporaryFile("w+", encoding="utf-8") as f_curr,
        ):
            tb = (
                "Traceback (most recent call last):\n"
                '  File "worker.py", line 12, in do_work\n'
                'KeyError: "task_id"\n' + ("noisy debug lines\n" * 30)
            )
            f_prev.write(tb)
            f_prev.flush()
            f_curr.write(tb)
            f_curr.flush()

            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                code = log_compressor.main(
                    [f_curr.name, "--mask-previous", f_prev.name, "--turn", "2"]
                )
                self.assertEqual(code, 0)
                out = mock_out.getvalue()
                self.assertIn("IDENTICAL signature as Turn 2", out)
                self.assertIn('KeyError("task_id") at worker.py:12', out)


if __name__ == "__main__":
    unittest.main()
