"""
Unit tests for tools/repomap.py (PageRank AST-Based Symbol Map Generator)
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.repomap import (
    DEFAULT_MAX_TOKENS,
    compute_pagerank,
    count_tokens,
    extract_file_symbols,
    generate_repomap,
    main,
    rank_repository_symbols,
)


class TestPageRankAlgorithm(unittest.TestCase):
    def test_empty_graph(self):
        scores = compute_pagerank({})
        self.assertEqual(scores, {})

    def test_single_node(self):
        scores = compute_pagerank({"A": set()})
        self.assertAlmostEqual(scores["A"], 1.0)

    def test_linear_graph_centrality(self):
        # A -> B -> C: C should accumulate the highest rank
        graph = {
            "A": {"B"},
            "B": {"C"},
            "C": set(),
        }
        scores = compute_pagerank(graph)
        self.assertGreater(scores["C"], scores["B"])
        self.assertGreater(scores["B"], scores["A"])
        self.assertAlmostEqual(sum(scores.values()), 1.0, places=4)

    def test_cyclic_graph(self):
        graph = {
            "A": {"B"},
            "B": {"C"},
            "C": {"A"},
        }
        scores = compute_pagerank(graph)
        self.assertAlmostEqual(scores["A"], 1.0 / 3.0, places=3)
        self.assertAlmostEqual(scores["B"], 1.0 / 3.0, places=3)
        self.assertAlmostEqual(scores["C"], 1.0 / 3.0, places=3)


class TestAstSymbolExtraction(unittest.TestCase):
    def test_extract_classes_and_functions(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            code_file = base / "engine.py"
            code_file.write_text(
                '"""Core engine module."""\n\n'
                "class BaseEngine:\n"
                '    """Abstract engine."""\n'
                "    pass\n\n"
                "class TokenEngine(BaseEngine):\n"
                '    """Token management engine."""\n'
                "    def allocate(self, budget: int) -> bool:\n"
                '        """Allocate tokens."""\n'
                "        return budget > 0\n\n"
                "def compute_hash(data: str) -> str:\n"
                '    """Compute hash string."""\n'
                "    return str(hash(data))\n",
                encoding="utf-8",
            )

            fs = extract_file_symbols(code_file, base)
            self.assertIsNotNone(fs)
            self.assertEqual(len(fs.classes), 2)
            self.assertEqual(len(fs.functions), 1)

            token_engine = next(c for c in fs.classes if c.name == "TokenEngine")
            self.assertIn("BaseEngine", token_engine.signature)
            self.assertEqual(token_engine.docstring, "Token management engine.")
            self.assertEqual(len(token_engine.methods), 1)
            self.assertEqual(token_engine.methods[0].name, "TokenEngine.allocate")

            fn = fs.functions[0]
            self.assertEqual(fn.name, "compute_hash")
            self.assertIn("def compute_hash(data)", fn.signature)

    def test_broken_syntax_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            broken_file = base / "broken.py"
            broken_file.write_text("def broken_syntax(:\n", encoding="utf-8")

            fs = extract_file_symbols(broken_file, base)
            self.assertIsNone(fs)


class TestRepositoryRanking(unittest.TestCase):
    def test_referential_ranking(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            # Core library file defining models
            (base / "core.py").write_text(
                "class Database:\n"
                "    def query(self, q):\n"
                "        return []\n\n"
                "def connect(dsn):\n"
                "    return Database()\n",
                encoding="utf-8",
            )

            # High-traffic caller importing and using core
            (base / "service.py").write_text(
                "from core import Database, connect\n\n"
                "def handle_request(req):\n"
                "    db = connect('postgres://...')\n"
                "    return db.query(req)\n",
                encoding="utf-8",
            )

            # Isolated script
            (base / "utils.py").write_text(
                "def local_helper():\n    return 42\n",
                encoding="utf-8",
            )

            ranked_files = rank_repository_symbols(base)
            file_names = [f.rel_path for f in ranked_files]

            self.assertIn("core.py", file_names)
            self.assertIn("service.py", file_names)
            self.assertIn("utils.py", file_names)

            # core.py should rank higher than isolated utils.py due to incoming references
            core_rank = next(f.rank for f in ranked_files if f.rel_path == "core.py")
            utils_rank = next(f.rank for f in ranked_files if f.rel_path == "utils.py")
            self.assertGreater(core_rank, utils_rank)


class TestRepomapFormattingAndBudget(unittest.TestCase):
    def test_budget_enforcement(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            # Create several files with multiple symbols
            for i in range(5):
                (base / f"module_{i}.py").write_text(
                    f"class Processor{i}:\n"
                    f"    def step_a(self): pass\n"
                    f"    def step_b(self): pass\n\n"
                    f"def run_proc_{i}(): pass\n",
                    encoding="utf-8",
                )

            # Generate repomap with small token budgets
            for budget in (30, 60, 150, 400):
                output = generate_repomap(base, max_tokens=budget)
                toks = count_tokens(output)
                self.assertLessEqual(
                    toks,
                    budget,
                    f"Output tokens {toks} exceeded budget {budget}",
                )

    def test_empty_repository(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = generate_repomap(base, max_tokens=800)
            self.assertIn("Empty repository map", output)


class TestRepomapCLI(unittest.TestCase):
    def test_cli_default_text_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "sample.py").write_text(
                "class App:\n    def start(self): pass\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--project", str(base), "--max-tokens", "500"])
            self.assertEqual(code, 0)
            text = stdout.getvalue()
            self.assertIn("sample.py:", text)
            self.assertIn("class App:", text)
            self.assertIn("def start(self)", text)

    def test_cli_json_output(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "service.py").write_text(
                "def serve(): pass\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["--project", str(base), "--json"])
            self.assertEqual(code, 0)

            data = json.loads(stdout.getvalue())
            self.assertEqual(data["budget_tokens"], DEFAULT_MAX_TOKENS)
            self.assertEqual(data["total_files"], 1)
            self.assertEqual(data["total_symbols"], 1)
            self.assertIn("repomap", data)

    def test_cli_invalid_directory(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            code = main(["--project", "/nonexistent/path/never/exists"])
        self.assertEqual(code, 1)
        self.assertIn("Error: Project directory does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
