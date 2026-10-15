"""
Unit tests for tools/patch_applier.py
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.patch_applier import (
    PatchBlock,
    apply_patch_file,
    apply_patch_string,
    main,
    parse_patch_blocks,
)


class TestPatchParser(unittest.TestCase):
    def test_parse_single_block(self):
        text = """
<<<<<<< SEARCH
def hello():
    return "world"
=======
def hello():
    return "universe"
>>>>>>> REPLACE
"""
        blocks = parse_patch_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn("def hello():", blocks[0].search)
        self.assertIn('return "universe"', blocks[0].replace)

    def test_parse_with_file_header(self):
        text = """
File: src/calculator.py
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a: int, b: int) -> int:
    return a + b
>>>>>>> REPLACE
"""
        blocks = parse_patch_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].file_path, "src/calculator.py")

    def test_parse_malformed_missing_divider(self):
        text = """
<<<<<<< SEARCH
def foo():
    pass
>>>>>>> REPLACE
"""
        with self.assertRaises(ValueError):
            parse_patch_blocks(text)

    def test_parse_malformed_missing_terminator(self):
        text = """
<<<<<<< SEARCH
def foo():
    pass
=======
def foo():
    return 42
"""
        with self.assertRaises(ValueError):
            parse_patch_blocks(text)


class TestMatchingCascade(unittest.TestCase):
    def test_tier1_exact_match(self):
        content = "line 1\nline 2\nline 3\n"
        search = "line 2\n"
        replace = "line 2 modified\n"

        ok, res, tier, sim, rng, err = apply_patch_string(content, search, replace)
        self.assertTrue(ok)
        self.assertEqual(tier, 1)
        self.assertEqual(sim, 1.0)
        self.assertEqual(res, "line 1\nline 2 modified\nline 3\n")
        self.assertEqual(rng, (2, 2))

    def test_tier1_ambiguous_rejection(self):
        content = "dup\nline 2\ndup\n"
        search = "dup\n"
        replace = "unique\n"

        ok, res, tier, sim, rng, err = apply_patch_string(content, search, replace)
        self.assertFalse(ok)
        self.assertIn("Ambiguous exact match", err or "")

    def test_tier2_crlf_and_trailing_whitespace(self):
        # Target has CRLF and trailing spaces
        content = "def test():  \r\n    return True  \r\n"
        # Search has standard LF and clean lines
        search = "def test():\n    return True\n"
        replace = "def test():\n    return False\n"

        ok, res, tier, sim, rng, err = apply_patch_string(content, search, replace)
        self.assertTrue(ok)
        self.assertEqual(tier, 2)
        self.assertIn("return False", res)

    def test_tier3_relative_indentation(self):
        # Target is inside an indented class/method (8 spaces)
        target = (
            "class Engine:\n"
            "    def run(self):\n"
            "        x = 1\n"
            "        y = 2\n"
            "        return x + y\n"
        )
        # Search block has 0 or 4 spaces
        search = "x = 1\ny = 2\n"
        replace = "x = 10\ny = 20\n"

        ok, res, tier, sim, rng, err = apply_patch_string(target, search, replace)
        self.assertTrue(ok)
        self.assertEqual(tier, 3)
        self.assertIn("        x = 10\n        y = 20\n", res)

    def test_tier4_fuzzy_match(self):
        # Target has slightly different formatting or 1 modified comment line
        target = (
            "def compute(value: int) -> int:\n"
            "    # internal note: fast path\n"
            "    step1 = value * 2\n"
            "    step2 = step1 + 5\n"
            "    return step2\n"
        )
        # Search block omitted the comment but matched 4 out of 5 lines
        search = (
            "def compute(value: int) -> int:\n"
            "    step1 = value * 2\n"
            "    step2 = step1 + 5\n"
            "    return step2\n"
        )
        replace = "def compute(value: int) -> int:\n    step1 = value * 10\n    return step1\n"

        ok, res, tier, sim, rng, err = apply_patch_string(target, search, replace, threshold=0.80)
        self.assertTrue(ok)
        self.assertEqual(tier, 4)
        self.assertGreaterEqual(sim, 0.80)
        self.assertIn("step1 = value * 10", res)

    def test_tier4_below_threshold_rejection(self):
        target = "def apple(): return 1\n"
        search = "def completely_different(): return 999\n"
        replace = "def replacement(): pass\n"

        ok, res, tier, sim, rng, err = apply_patch_string(target, search, replace, threshold=0.85)
        self.assertFalse(ok)
        self.assertIn("No matching block found", err or "")


class TestFileOperations(unittest.TestCase):
    def test_apply_patch_file_with_backup(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "example.py"
            p.write_text("x = 10\ny = 20\n", encoding="utf-8")

            blocks = [PatchBlock(search="y = 20\n", replace="y = 30\n")]
            results = apply_patch_file(p, blocks, backup=True)

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].success)
            self.assertEqual(p.read_text(encoding="utf-8"), "x = 10\ny = 30\n")

            # Verify .orig backup exists
            backup = Path(td) / "example.py.orig"
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "x = 10\ny = 20\n")

    def test_dry_run_does_not_modify(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "test.txt"
            p.write_text("before\n", encoding="utf-8")

            blocks = [PatchBlock(search="before\n", replace="after\n")]
            results = apply_patch_file(p, blocks, dry_run=True)

            self.assertTrue(results[0].success)
            self.assertIn("after", results[0].diff)
            self.assertEqual(p.read_text(encoding="utf-8"), "before\n")


class TestCLI(unittest.TestCase):
    def test_cli_apply(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "code.py"
            p.write_text("val = 1\n", encoding="utf-8")
            patch_text = "<<<<<<< SEARCH\nval = 1\n=======\nval = 2\n>>>>>>> REPLACE\n"

            code = main(["apply", "--file", str(p), "--patch", patch_text])
            self.assertEqual(code, 0)
            self.assertEqual(p.read_text(encoding="utf-8"), "val = 2\n")

    def test_cli_apply_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "code.py"
            p.write_text("val = 1\n", encoding="utf-8")
            patch_text = "<<<<<<< SEARCH\nval = 1\n=======\nval = 2\n>>>>>>> REPLACE\n"

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                code = main(["apply", "--file", str(p), "--patch", patch_text, "--json"])
            self.assertEqual(code, 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["success"])
            self.assertEqual(data[0]["tier"], 1)

    def test_cli_stream_mode(self):
        with tempfile.TemporaryDirectory() as td:
            f1 = Path(td) / "mod1.py"
            f2 = Path(td) / "mod2.py"
            f1.write_text("a = 1\n", encoding="utf-8")
            f2.write_text("b = 2\n", encoding="utf-8")

            stream_input = f"""
File: {f1}
<<<<<<< SEARCH
a = 1
=======
a = 100
>>>>>>> REPLACE

File: {f2}
<<<<<<< SEARCH
b = 2
=======
b = 200
>>>>>>> REPLACE
"""
            with patch("sys.stdin", io.StringIO(stream_input)):
                code = main(["stream"])
            self.assertEqual(code, 0)
            self.assertEqual(f1.read_text(encoding="utf-8"), "a = 100\n")
            self.assertEqual(f2.read_text(encoding="utf-8"), "b = 200\n")

    def test_markdown_fences_ignored(self):
        text = """
Here is the proposed fix:
```python
<<<<<<< SEARCH
def foo():
    return 1
=======
def foo():
    return 2
>>>>>>> REPLACE
```
"""
        blocks = parse_patch_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].search.strip(), "def foo():\n    return 1")
        self.assertEqual(blocks[0].replace.strip(), "def foo():\n    return 2")

    def test_sequential_blocks_in_one_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "multi.py"
            p.write_text("part1 = 1\npart2 = 2\npart3 = 3\n", encoding="utf-8")
            blocks = [
                PatchBlock(search="part1 = 1\n", replace="part1 = 10\n"),
                PatchBlock(search="part3 = 3\n", replace="part3 = 30\n"),
            ]
            results = apply_patch_file(p, blocks)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.success for r in results))
            self.assertEqual(p.read_text(encoding="utf-8"), "part1 = 10\npart2 = 2\npart3 = 30\n")

    def test_file_not_found_handling(self):
        p = Path("/nonexistent/path/to/missing_file.py")
        blocks = [PatchBlock(search="a\n", replace="b\n")]
        results = apply_patch_file(p, blocks)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIn("File not found", results[0].error or "")


if __name__ == "__main__":
    unittest.main()
