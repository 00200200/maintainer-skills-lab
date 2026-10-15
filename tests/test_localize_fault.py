"""tests/test_localize_fault.py - Unit tests for tools/localize_fault.py.

Tests stack trace parsing, AST skeleton generation, symbol localization,
scoped context slicing, and YAML fault reporting.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.localize_fault import (
    extract_slice,
    find_symbol_range,
    generate_ast_skeleton,
    generate_yaml_report,
    main,
    parse_traceback,
)

SAMPLE_PYTHON_CODE = """\"\"\"Sample module for testing fault localization.\"\"\"

import os

class WorkerEngine:
    \"\"\"Worker engine for background tasks.\"\"\"

    def __init__(self, name: str) -> None:
        self.name = name

    def process_task(self, task_id: int, payload: dict) -> bool:
        if not payload:
            raise ValueError("Empty payload")
        return True

def standalone_helper(x: int, y: int) -> int:
    \"\"\"Calculates sum.\"\"\"
    return x + y
"""

SAMPLE_TRACEBACK = """Traceback (most recent call last):
  File "/app/main.py", line 42, in run_app
    engine.process_task(1, {})
  File "/app/worker.py", line 14, in process_task
    raise ValueError("Empty payload")
ValueError: Empty payload
"""


class TestLocalizeFault(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.code_path = Path(self.temp_dir.name) / "sample_worker.py"
        self.code_path.write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_traceback(self) -> None:
        frames = parse_traceback(SAMPLE_TRACEBACK)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].filepath, "/app/main.py")
        self.assertEqual(frames[0].line_number, 42)
        self.assertEqual(frames[0].function_name, "run_app")

        self.assertEqual(frames[1].filepath, "/app/worker.py")
        self.assertEqual(frames[1].line_number, 14)
        self.assertEqual(frames[1].function_name, "process_task")
        self.assertEqual(frames[1].code_line, 'raise ValueError("Empty payload")')

    def test_find_symbol_range(self) -> None:
        method_bounds = find_symbol_range(self.code_path, "WorkerEngine.process_task")
        self.assertIsNotNone(method_bounds)
        self.assertEqual(method_bounds, (11, 14))

        func_bounds = find_symbol_range(self.code_path, "standalone_helper")
        self.assertIsNotNone(func_bounds)
        self.assertEqual(func_bounds, (16, 18))

        missing_bounds = find_symbol_range(self.code_path, "NonExistentClass.method")
        self.assertIsNone(missing_bounds)

    def test_extract_slice_with_omission_notes(self) -> None:
        # File has 19 lines, extracting lines 11-14 with padding 2
        sliced = extract_slice(self.code_path, start_line=11, end_line=14, padding=2)
        self.assertIn("omitted for brevity (lines 1-8)", sliced)
        self.assertIn("11 |     def process_task", sliced)
        self.assertIn("13 |             raise ValueError", sliced)
        self.assertIn("omitted for brevity (lines 17-18)", sliced)

    def test_extract_slice_no_line_numbers(self) -> None:
        sliced = extract_slice(
            self.code_path, start_line=11, end_line=14, padding=0, show_line_numbers=False
        )
        self.assertNotIn("|", sliced)
        self.assertIn('raise ValueError("Empty payload")', sliced)

    def test_generate_ast_skeleton(self) -> None:
        skel = generate_ast_skeleton(self.code_path)
        self.assertIn("class WorkerEngine:", skel)
        self.assertIn("def process_task(self, task_id, payload): ...", skel)
        self.assertIn("def standalone_helper(x, y): ...", skel)
        self.assertNotIn('raise ValueError("Empty payload")', skel)

    def test_generate_yaml_report(self) -> None:
        yaml_out = generate_yaml_report(
            filepath="worker.py",
            symbol="WorkerEngine.process_task",
            start_line=11,
            end_line=14,
            confidence="high",
            rationale="Unchecked empty payload.",
        )
        self.assertIn("fault_localization:", yaml_out)
        self.assertIn('file: "worker.py"', yaml_out)
        self.assertIn('symbol: "WorkerEngine.process_task"', yaml_out)
        self.assertIn("line_range: [11, 14]", yaml_out)
        self.assertIn('confidence: "high"', yaml_out)
        self.assertIn('rationale: "Unchecked empty payload."', yaml_out)

    def test_cli_extract_command(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(
                ["extract", "--file", str(self.code_path), "--lines", "11-14", "--padding", "1"]
            )
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("process_task", output)

    def test_cli_locate_command(self) -> None:
        tb_file = Path(self.temp_dir.name) / "traceback.txt"
        tb_file.write_text(SAMPLE_TRACEBACK, encoding="utf-8")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["locate", "--traceback", str(tb_file)])
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("Detected 2 stack frame(s)", output)
            self.assertIn("Primary candidate for localization:", output)
            self.assertIn('symbol: "process_task"', output)

    def test_cli_skeleton_command(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["skeleton", "--file", str(self.code_path)])
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("class WorkerEngine:", output)

    def test_cli_symbol_command(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(
                ["symbol", "--file", str(self.code_path), "--symbol", "standalone_helper"]
            )
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("def standalone_helper", output)


if __name__ == "__main__":
    unittest.main()
