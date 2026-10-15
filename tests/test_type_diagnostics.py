"""tests/test_type_diagnostics.py - Unit tests for tools/extract_type_diagnostics.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.extract_type_diagnostics import (
    TypeDiagnostic,
    deduplicate_diagnostics,
    determine_recommended_fix,
    extract_symbol_and_scope,
    format_json,
    format_xml,
    main,
    parse_mypy_output,
    parse_pyright_output,
)


class TestTypeDiagnostics(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_parse_mypy_output_single_error_with_code(self) -> None:
        raw_log = 'src/parser.py:42: error: Item "None" of "Optional[Header]" has no attribute "content" [union-attr]\nFound 1 error in 1 file'
        diags = parse_mypy_output(raw_log, with_scope=False)
        self.assertEqual(len(diags), 1)
        d = diags[0]
        self.assertEqual(d.file, "src/parser.py")
        self.assertEqual(d.line, 42)
        self.assertIsNone(d.column)
        self.assertEqual(d.code, "union-attr")
        self.assertIn("Optional[Header]", d.message)
        self.assertIn("guard", d.recommended_fix.lower())

    def test_parse_mypy_output_with_column_and_notes(self) -> None:
        raw_log = (
            'src/model.py:15:8: error: Argument 1 to "save" has incompatible type "dict[str, Any]"; expected "Config" [arg-type]\n'
            'src/model.py:15:8: note: "Config" has incompatible initializer\n'
        )
        diags = parse_mypy_output(raw_log, with_scope=False)
        self.assertEqual(len(diags), 1)
        d = diags[0]
        self.assertEqual(d.line, 15)
        self.assertEqual(d.column, 8)
        self.assertEqual(d.code, "arg-type")
        self.assertEqual(len(d.notes), 1)
        self.assertIn("incompatible initializer", d.notes[0])

    def test_parse_pyright_output_valid_json(self) -> None:
        pyright_data = {
            "version": "1.1.300",
            "time": "0.123s",
            "generalDiagnostics": [
                {
                    "file": "/repo/src/core.py",
                    "severity": "error",
                    "message": "Optional member cannot be accessed without None check",
                    "range": {
                        "start": {"line": 24, "character": 4},
                        "end": {"line": 24, "character": 12},
                    },
                    "rule": "reportOptionalMemberAccess",
                }
            ],
            "summary": {"errorCount": 1, "warningCount": 0},
        }
        json_str = json.dumps(pyright_data)
        diags = parse_pyright_output(json_str, with_scope=False)
        self.assertEqual(len(diags), 1)
        d = diags[0]
        self.assertEqual(d.line, 25)  # 0-indexed line 24 -> 1-indexed 25
        self.assertEqual(d.column, 5)  # 0-indexed char 4 -> 1-indexed 5
        self.assertEqual(d.code, "reportOptionalMemberAccess")
        self.assertEqual(d.source_tool, "pyright")

    def test_parse_pyright_output_invalid_json(self) -> None:
        diags = parse_pyright_output("invalid json string", with_scope=False)
        self.assertEqual(diags, [])

    def test_extract_symbol_and_scope_function(self) -> None:
        code_file = self.temp_path / "sample.py"
        code_file.write_text(
            "import os\n\n"
            "def compute_metrics(x: int) -> int:\n"
            "    val = x * 2\n"
            "    return val + 1\n",
            encoding="utf-8",
        )
        sym_name, sym_type, context = extract_symbol_and_scope(code_file, 4)
        self.assertEqual(sym_name, "compute_metrics")
        self.assertEqual(sym_type, "function")
        self.assertIsNotNone(context)
        self.assertIn("4:     val = x * 2", context or "")

    def test_extract_symbol_and_scope_class_method(self) -> None:
        code_file = self.temp_path / "sample_class.py"
        code_file.write_text(
            "class Engine:\n"
            "    async def run_step(self, step_id: int) -> None:\n"
            "        result = await self.fetch(step_id)\n"
            "        return result\n",
            encoding="utf-8",
        )
        sym_name, sym_type, context = extract_symbol_and_scope(code_file, 3)
        self.assertEqual(sym_name, "Engine.run_step")
        self.assertEqual(sym_type, "async_function")
        self.assertIsNotNone(context)
        self.assertIn("run_step", context or "")

    def test_extract_symbol_and_scope_non_existent_file(self) -> None:
        non_file = self.temp_path / "non_existent.py"
        sym_name, sym_type, context = extract_symbol_and_scope(non_file, 10)
        self.assertIsNone(sym_name)
        self.assertIsNone(sym_type)
        self.assertIsNone(context)

    def test_determine_recommended_fix(self) -> None:
        fix1 = determine_recommended_fix("union-attr", "Item None has no attribute", "parse_data")
        self.assertIn("parse_data", fix1)
        self.assertIn("guard", fix1.lower())

        fix2 = determine_recommended_fix("return-value", "Incompatible return value type")
        self.assertIn("return type", fix2.lower())

        fix3 = determine_recommended_fix(None, "Incompatible type for argument 1; expected str")
        self.assertIn("parameter", fix3.lower())

    def test_deduplicate_diagnostics(self) -> None:
        d1 = TypeDiagnostic(file="a.py", line=10, symbol="func1", message="err 1")
        d2 = TypeDiagnostic(file="a.py", line=11, symbol="func1", message="err 2")
        d3 = TypeDiagnostic(file="a.py", line=12, symbol="func1", message="err 3")
        d4 = TypeDiagnostic(file="a.py", line=13, symbol="func1", message="err 4")
        d5 = TypeDiagnostic(file="b.py", line=5, symbol="func2", message="err 5")

        deduped = deduplicate_diagnostics([d1, d2, d3, d4, d5], max_per_symbol=2)
        # func1 should be capped at 2
        self.assertEqual(len(deduped), 3)
        self.assertEqual([d.symbol for d in deduped], ["func1", "func1", "func2"])

    def test_format_xml_clean(self) -> None:
        xml = format_xml([])
        self.assertIn('status="CLEAN"', xml)

    def test_format_xml_with_diagnostics(self) -> None:
        d = TypeDiagnostic(
            file="src/utils.py",
            line=20,
            column=4,
            severity="error",
            message="Item None has no attribute length",
            code="union-attr",
            symbol="get_len",
            symbol_type="function",
            context_code="20: return obj.length",
            recommended_fix="Add None guard",
        )
        xml = format_xml([d])
        self.assertIn('<type_errors count="1">', xml)
        self.assertIn('file="src/utils.py"', xml)
        self.assertIn('<symbol type="function">get_len</symbol>', xml)
        self.assertIn("<context>", xml)
        self.assertIn("<recommended_fix>Add None guard</recommended_fix>", xml)

    def test_format_json(self) -> None:
        d = TypeDiagnostic(
            file="src/foo.py",
            line=12,
            message="type error",
            code="arg-type",
        )
        json_output = format_json([d])
        parsed = json.loads(json_output)
        self.assertEqual(parsed["status"], "ERROR")
        self.assertEqual(parsed["error_count"], 1)
        self.assertEqual(parsed["diagnostics"][0]["file"], "src/foo.py")

    def test_cli_mypy_log_file(self) -> None:
        log_file = self.temp_path / "mypy.log"
        log_file.write_text(
            "pkg/core.py:10: error: Incompatible return value [return-value]\n", encoding="utf-8"
        )

        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["--mypy-log", str(log_file), "--no-scope"])
        self.assertEqual(code, 1)  # returns 1 on errors found
        self.assertIn('<type_errors count="1">', f.getvalue())

    def test_cli_json_and_summary(self) -> None:
        log_file = self.temp_path / "clean.log"
        log_file.write_text("Success: no issues found in 1 source file\n", encoding="utf-8")

        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["--mypy-log", str(log_file), "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertEqual(parsed["status"], "CLEAN")
        self.assertEqual(parsed["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
