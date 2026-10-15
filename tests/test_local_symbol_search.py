"""
Unit tests for tools/local_symbol_search.py
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.local_symbol_search import (
    SymbolIndex,
    SymbolItem,
    extract_python_symbols,
    extract_regex_symbols,
    format_markdown,
    main,
)


class TestSymbolExtraction(unittest.TestCase):
    def test_python_ast_extractor(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            py_file = base / "sample.py"
            py_file.write_text(
                '"""Module docstring."""\n\n'
                'class TokenGovernor:\n'
                '    """Manages token budgets."""\n'
                '    def __init__(self, limit: int = 1000):\n'
                '        self.limit = limit\n\n'
                '    def get_remaining(self, used: int) -> int:\n'
                '        """Calculate remaining tokens."""\n'
                '        return max(0, self.limit - used)\n\n'
                'async def fetch_metrics() -> dict:\n'
                '    return {}\n',
                encoding="utf-8",
            )

            symbols = extract_python_symbols(py_file, base)
            names = [s.symbol_name for s in symbols]
            kinds = [s.symbol_kind for s in symbols]

            self.assertIn("TokenGovernor", names)
            self.assertIn("TokenGovernor.get_remaining", names)
            self.assertIn("fetch_metrics", names)
            self.assertIn("class", kinds)
            self.assertIn("method", kinds)
            self.assertIn("function", kinds)

            gov = next(s for s in symbols if s.symbol_name == "TokenGovernor")
            self.assertEqual(gov.docstring, "Manages token budgets.")
            self.assertEqual(gov.lineno, 3)

    def test_regex_extractor_non_python(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # TypeScript
            ts_file = base / "service.ts"
            ts_file.write_text("export interface UserProfile {\n  id: string;\n}\nexport async function fetchUser() {}\n", encoding="utf-8")
            ts_symbols = extract_regex_symbols(ts_file, base)
            self.assertEqual(len(ts_symbols), 2)
            self.assertEqual(ts_symbols[0].symbol_name, "UserProfile")
            self.assertEqual(ts_symbols[1].symbol_name, "fetchUser")

            # Go
            go_file = base / "main.go"
            go_file.write_text("package main\nfunc ExecuteTask() {}\ntype TaskConfig struct {}\n", encoding="utf-8")
            go_symbols = extract_regex_symbols(go_file, base)
            self.assertEqual(len(go_symbols), 2)
            self.assertEqual(go_symbols[0].symbol_name, "ExecuteTask")
            self.assertEqual(go_symbols[1].symbol_name, "TaskConfig")

            # Rust
            rs_file = base / "lib.rs"
            rs_file.write_text("pub struct BudgetPool;\npub fn allocate() {}\n", encoding="utf-8")
            rs_symbols = extract_regex_symbols(rs_file, base)
            self.assertEqual(len(rs_symbols), 2)
            self.assertEqual(rs_symbols[0].symbol_name, "BudgetPool")
            self.assertEqual(rs_symbols[1].symbol_name, "allocate")


class TestSymbolIndexAndSearch(unittest.TestCase):
    def test_in_memory_index_and_bm25_ranking(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f1 = base / "budget.py"
            f1.write_text(
                "def calculate_token_budget(used: int) -> int:\n"
                "    '''Direct calculation of budget.'''\n"
                "    return 1000 - used\n",
                encoding="utf-8",
            )
            f2 = base / "logger.py"
            f2.write_text(
                "def log_message(msg: str) -> None:\n"
                "    '''Mentions calculate_token_budget in passing comment.'''\n"
                "    pass\n",
                encoding="utf-8",
            )

            idx = SymbolIndex(None)
            idx.index_project(base)

            # Query should prioritize f1 because calculate_token_budget is in symbol_name
            results = idx.query("calculate_token_budget", limit=2)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].filepath, "budget.py")
            self.assertEqual(results[0].symbol_name, "calculate_token_budget")
            idx.close()

    def test_kind_filter(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f = base / "types.py"
            f.write_text("class MyService:\n    def run(self): pass\n", encoding="utf-8")

            idx = SymbolIndex(None)
            idx.index_project(base)

            classes = idx.query("MyService", kind="class")
            self.assertEqual(len(classes), 1)
            self.assertEqual(classes[0].symbol_kind, "class")

            funcs = idx.query("MyService", kind="function")
            self.assertEqual(len(funcs), 0)
            idx.close()

    def test_incremental_indexing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            db_file = base / "test.db"
            code_file = base / "counter.py"
            code_file.write_text("def count_items(): pass\n", encoding="utf-8")

            idx1 = SymbolIndex(db_file)
            c1 = idx1.index_project(base)
            self.assertEqual(c1, 1)
            idx1.close()

            # Second indexing with unchanged file should skip
            idx2 = SymbolIndex(db_file)
            c2 = idx2.index_project(base)
            self.assertEqual(c2, 0)
            idx2.close()


class TestCLIAndFormatting(unittest.TestCase):
    def test_cli_search_json(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "mod.py").write_text("def find_me(): pass\n", encoding="utf-8")

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["search", "find_me", "--project", str(base), "--json"])
            self.assertEqual(code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["symbol_name"], "find_me")

    def test_format_markdown_empty_and_filled(self):
        empty_out = format_markdown([])
        self.assertIn("No symbols found", empty_out)

        item = SymbolItem(
            filepath="src/test.py",
            symbol_name="test_fn",
            symbol_kind="function",
            lineno=10,
            end_lineno=12,
            signature="def test_fn() -> None",
            docstring="Does testing.",
            body_snippet="pass",
        )
        filled_out = format_markdown([item])
        self.assertIn("`test_fn`", filled_out)
        self.assertIn("src/test.py:10", filled_out)


if __name__ == "__main__":
    unittest.main()
