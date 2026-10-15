"""tests/test_structural_refactor.py - Unit tests for tools/structural_refactor.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.structural_refactor import (
    get_native_binary_path,
    has_native_ast_grep,
    main,
    refactor_file,
    refactor_paths,
    refactor_source,
    run_native_ast_grep,
)


class TestStructuralRefactor(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_refactor_call_with_multi_args(self) -> None:
        source = (
            "def handle():\n"
            "    # Log event\n"
            '    app.logger.warn("User logged in", user_id=123, ip="127.0.0.1")\n'
            "    return True\n"
        )
        pattern = "$LOGGER.warn($$$ARGS)"
        rewrite = "$LOGGER.warning($$$ARGS)"

        transformed, count, err = refactor_source(source, pattern, rewrite)
        self.assertIsNone(err)
        self.assertEqual(count, 1)
        self.assertIn(
            "app.logger.warning('User logged in', user_id=123, ip='127.0.0.1')", transformed
        )
        self.assertIn("# Log event", transformed)

    def test_refactor_assert_statement(self) -> None:
        source = (
            "def test_endpoint(self):\n"
            "    resp = client.get('/api')\n"
            "    assert resp.status_code == 200\n"
        )
        pattern = "assert $A == $B"
        rewrite = "self.assertEqual($A, $B)"

        transformed, count, err = refactor_source(source, pattern, rewrite)
        self.assertIsNone(err)
        self.assertEqual(count, 1)
        self.assertIn("self.assertEqual(resp.status_code, 200)", transformed)

    def test_refactor_remove_none_default(self) -> None:
        source = "val = metadata.get('env', None)\n"
        pattern = "$DICT.get($KEY, None)"
        rewrite = "$DICT.get($KEY)"

        transformed, count, err = refactor_source(source, pattern, rewrite)
        self.assertIsNone(err)
        self.assertEqual(count, 1)
        self.assertIn("val = metadata.get('env')", transformed)

    def test_refactor_multiple_matches_in_file(self) -> None:
        source = "logger.warn('first')\n# intervening comment\nlogger.warn('second')\n"
        pattern = "logger.warn($MSG)"
        rewrite = "logger.warning($MSG)"

        transformed, count, err = refactor_source(source, pattern, rewrite)
        self.assertIsNone(err)
        self.assertEqual(count, 2)
        self.assertIn("logger.warning('first')", transformed)
        self.assertIn("logger.warning('second')", transformed)
        self.assertIn("# intervening comment", transformed)

    def test_refactor_file_dry_run(self) -> None:
        test_file = self.temp_path / "service.py"
        content = "logger.warn('service alert')\n"
        test_file.write_text(content, encoding="utf-8")

        res = refactor_file(
            test_file,
            pattern_str="logger.warn($MSG)",
            rewrite_str="logger.warning($MSG)",
            dry_run=True,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.matches_count, 1)
        self.assertIn("-logger.warn('service alert')", res.diff)
        self.assertIn("+logger.warning('service alert')", res.diff)

        # File on disk must remain unchanged during dry run
        disk_content = test_file.read_text(encoding="utf-8")
        self.assertEqual(disk_content, content)

    def test_refactor_file_live_write(self) -> None:
        test_file = self.temp_path / "live.py"
        test_file.write_text("logger.warn('persist')\n", encoding="utf-8")

        res = refactor_file(
            test_file,
            pattern_str="logger.warn($MSG)",
            rewrite_str="logger.warning($MSG)",
            dry_run=False,
        )
        self.assertTrue(res.success)
        self.assertEqual(res.matches_count, 1)

        # File on disk must be updated
        disk_content = test_file.read_text(encoding="utf-8")
        self.assertIn("logger.warning('persist')", disk_content)

    def test_refactor_paths_directory(self) -> None:
        f1 = self.temp_path / "a.py"
        f2 = self.temp_path / "b.py"
        f1.write_text("logger.warn('a')\n", encoding="utf-8")
        f2.write_text("logger.info('b')\n", encoding="utf-8")

        results = refactor_paths(
            self.temp_path,
            pattern_str="logger.warn($MSG)",
            rewrite_str="logger.warning($MSG)",
            dry_run=True,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].file, str(f1))
        self.assertEqual(results[0].matches_count, 1)

    def test_safety_check_prevents_syntax_corruption(self) -> None:
        # If a rewrite template was somehow invalid, it shouldn't produce corrupt files
        source = "x = 42\n"
        pattern = "x = 42"
        rewrite = "x = def"  # invalid syntax

        transformed, count, err = refactor_source(source, pattern, rewrite)
        self.assertIsNotNone(err)
        self.assertEqual(count, 0)
        self.assertEqual(transformed, source)

    def test_native_helpers(self) -> None:
        has_sg = has_native_ast_grep()
        self.assertIsInstance(has_sg, bool)
        bin_path = get_native_binary_path()
        self.assertTrue(bin_path is None or isinstance(bin_path, str))

        # When native is not installed, run_native_ast_grep returns None
        with patch("tools.structural_refactor.get_native_binary_path", return_value=None):
            self.assertIsNone(run_native_ast_grep("a", "b", self.temp_path))

    def test_cli_json_output(self) -> None:
        test_file = self.temp_path / "app.py"
        test_file.write_text("logger.warn('cli test')\n", encoding="utf-8")

        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(
                [
                    "--pattern",
                    "logger.warn($MSG)",
                    "--rewrite",
                    "logger.warning($MSG)",
                    "--path",
                    str(test_file),
                    "--dry-run",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(f.getvalue())
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["total_matches"], 1)
        self.assertEqual(payload["files_modified_count"], 1)


if __name__ == "__main__":
    unittest.main()
