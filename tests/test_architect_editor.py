"""tests/test_architect_editor.py - Unit tests for tools/architect_editor.py.

Tests Architect handoff parsing, search/replace execution, fuzzy whitespace matching,
Python syntax validation, cost savings estimations, and CLI commands.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.architect_editor import (
    ArchitectHandoff,
    ChangeInstruction,
    apply_search_replace,
    estimate_token_savings,
    main,
    parse_handoff_json,
    serialize_handoff,
    validate_python_syntax,
)

SAMPLE_TARGET_CODE = """def compute_total(items: list[int]) -> int:
    total = 0
    for item in items:
        total += item
    return total
"""


class TestArchitectEditor(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.code_path = Path(self.temp_dir.name) / "calc.py"
        self.code_path.write_text(SAMPLE_TARGET_CODE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_handoff_serialization_roundtrip(self) -> None:
        handoff = ArchitectHandoff(
            task_id="fix_sum",
            target_files=["calc.py"],
            invariant_summary="Must handle empty list",
            changes=[
                ChangeInstruction(
                    file="calc.py",
                    intent="Use builtin sum()",
                    search_block="    total = 0\n    for item in items:\n        total += item\n    return total",
                    replace_block="    return sum(items)",
                )
            ],
        )
        serialized = serialize_handoff(handoff)
        parsed = parse_handoff_json(serialized)
        self.assertEqual(parsed.task_id, "fix_sum")
        self.assertEqual(len(parsed.changes), 1)
        self.assertEqual(parsed.changes[0].intent, "Use builtin sum()")

    def test_apply_search_replace_exact(self) -> None:
        search = "    total = 0\n    for item in items:\n        total += item\n    return total"
        replace = "    return sum(items)"
        success, msg = apply_search_replace(self.code_path, search, replace)
        self.assertTrue(success)
        self.assertIn("Exact match", msg)
        self.assertIn("return sum(items)", self.code_path.read_text())

    def test_apply_search_replace_fuzzy_whitespace(self) -> None:
        search = (
            "    total = 0   \n    for item in items:  \n        total += item\n    return total"
        )
        replace = "    return sum(items)"
        success, msg = apply_search_replace(self.code_path, search, replace, fuzzy_whitespace=True)
        self.assertTrue(success)
        self.assertIn("Fuzzy match", msg)

    def test_apply_search_replace_not_found(self) -> None:
        search = "non_existent_function_call()"
        replace = "pass"
        success, msg = apply_search_replace(self.code_path, search, replace)
        self.assertFalse(success)
        self.assertIn("could not be located", msg)

    def test_validate_python_syntax_valid(self) -> None:
        valid, msg = validate_python_syntax(self.code_path)
        self.assertTrue(valid)
        self.assertEqual(msg, "Syntax valid.")

    def test_validate_python_syntax_invalid(self) -> None:
        bad_path = Path(self.temp_dir.name) / "bad.py"
        bad_path.write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")
        valid, msg = validate_python_syntax(bad_path)
        self.assertFalse(valid)
        self.assertIn("SyntaxError", msg)

    def test_estimate_token_savings(self) -> None:
        savings = estimate_token_savings(total_file_tokens=4000)
        self.assertGreater(savings["savings_percent"], 65.0)
        self.assertLess(savings["dual_model_cost_usd"], savings["single_model_cost_usd"])

    def test_cli_apply_dry_run(self) -> None:
        handoff_data = {
            "task_id": "dry_run_test",
            "target_files": [str(self.code_path)],
            "invariant_summary": "Test dry run",
            "changes": [
                {
                    "file": str(self.code_path),
                    "intent": "Replace total",
                    "search_block": "total = 0",
                    "replace_block": "total = 1",
                }
            ],
        }
        handoff_file = Path(self.temp_dir.name) / "handoff.json"
        handoff_file.write_text(json.dumps(handoff_data), encoding="utf-8")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["apply", "--handoff", str(handoff_file), "--dry-run"])
            self.assertEqual(exit_code, 0)
            self.assertIn("[DRY-RUN]", mock_stdout.getvalue())
            # File should be unchanged
            self.assertIn("total = 0", self.code_path.read_text())

    def test_cli_apply_real(self) -> None:
        handoff_data = {
            "task_id": "real_run_test",
            "target_files": [str(self.code_path)],
            "invariant_summary": "Test real run",
            "changes": [
                {
                    "file": str(self.code_path),
                    "intent": "Replace total",
                    "search_block": "total = 0",
                    "replace_block": "total = 10",
                }
            ],
        }
        handoff_file = Path(self.temp_dir.name) / "handoff.json"
        handoff_file.write_text(json.dumps(handoff_data), encoding="utf-8")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["apply", "--handoff", str(handoff_file)])
            self.assertEqual(exit_code, 0)
            self.assertIn("[OK]", mock_stdout.getvalue())
            self.assertIn("total = 10", self.code_path.read_text())

    def test_cli_estimate(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["estimate", "--file-tokens", "5000"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Dual-Model Cost & Token Optimization", mock_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
