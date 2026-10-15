import ast
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("strip_comments", ROOT / "tools/strip_comments.py")
strip_comments = importlib.util.module_from_spec(spec)
spec.loader.exec_module(strip_comments)


SAMPLE_CODE = """#!/usr/bin/env python3
# Copyright (c) 2026 Maintainer Skills Lab Authors
# Licensed under Apache 2.0
\"\"\"Module level docstring for testing.\"\"\"

import os
import sys

# Regular module-level comment
class Worker:
    \"\"\"Worker class documentation.\"\"\"

    def __init__(self, name: str) -> None:
        \"\"\"Initialize worker.\"\"\"
        self.name = name  # Set worker name
        self.url = "https://example.com/api#anchor"  # Valid hash in string
        self.color = "#FF00AA"
        self.legacy = True  # type: ignore[attr-defined]
        self.skip_check = 1  # noqa: E501
        self.uncovered = 0  # pragma: no cover

    def empty_worker(self) -> None:
        \"\"\"Worker with only a docstring.\"\"\"

    def compute(self, x: int) -> int:
        # Step 1
        res = x * 2
        # Step 2
        return res
"""


class StripCommentsUnitTests(unittest.TestCase):
    def test_strip_comments_only(self):
        cleaned, stats = strip_comments.strip_comments_and_docstrings(
            SAMPLE_CODE,
            strip_docstrings=False,
        )

        # Shebang kept
        self.assertIn("#!/usr/bin/env python3", cleaned)

        # License and regular comments stripped
        self.assertNotIn("Copyright (c) 2026", cleaned)
        self.assertNotIn("Regular module-level comment", cleaned)
        self.assertNotIn("Set worker name", cleaned)
        self.assertNotIn("Step 1", cleaned)

        # Directives kept
        self.assertIn("# type: ignore", cleaned)
        self.assertIn("# noqa:", cleaned)
        self.assertIn("# pragma: no cover", cleaned)

        # String literals with # kept
        self.assertIn('"https://example.com/api#anchor"', cleaned)
        self.assertIn('"#FF00AA"', cleaned)

        # Docstrings kept (when strip_docstrings=False)
        self.assertIn("Module level docstring for testing.", cleaned)
        self.assertIn("Worker class documentation.", cleaned)

        # Syntax check
        ast.parse(cleaned)
        self.assertGreater(stats["comments_removed"], 5)

    def test_strip_comments_and_docstrings(self):
        cleaned, stats = strip_comments.strip_comments_and_docstrings(
            SAMPLE_CODE,
            strip_docstrings=True,
        )

        # Docstrings removed
        self.assertNotIn("Module level docstring for testing.", cleaned)
        self.assertNotIn("Worker class documentation.", cleaned)
        self.assertNotIn("Initialize worker.", cleaned)
        self.assertNotIn("Worker with only a docstring.", cleaned)

        # empty_worker has 'pass'
        self.assertIn("def empty_worker(self) -> None:\n        pass", cleaned)

        # Syntax check
        ast.parse(cleaned)
        self.assertGreater(stats["docstrings_removed"], 3)
        self.assertGreater(stats["reduction_pct"], 25.0)

    def test_empty_input(self):
        cleaned, stats = strip_comments.strip_comments_and_docstrings("")
        self.assertEqual(cleaned, "")
        self.assertEqual(stats["original_lines"], 0)

    def test_cli_execution_file_and_json(self):
        with tempfile.NamedTemporaryFile("w+", suffix=".py", encoding="utf-8") as tmp:
            tmp.write(SAMPLE_CODE)
            tmp.flush()

            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                code = strip_comments.main([tmp.name, "--strip-docstrings", "--json"])
                self.assertEqual(code, 0)
                parsed = json.loads(mock_out.getvalue())
                self.assertIn("code", parsed)
                self.assertIn("stats", parsed)
                self.assertNotIn("Worker class documentation.", parsed["code"])
                ast.parse(parsed["code"])


if __name__ == "__main__":
    unittest.main()
