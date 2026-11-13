"""Optional native minifier dispatch and differential tests against Python."""

from __future__ import annotations

import builtins
import importlib.util
import itertools
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import kit

CASES = (
    "",
    "plain text",
    "A  \n\n\n\nB\t \n",
    " \t\n\n\n \t",
    "\n" * 200,
    "A  \r\n\r\n\r\nB\t\r\n",
    "A\rB  \r",
    "A\u0085B\u2028C\u2029  ",
    "|  a   |  b  |\n| :--- | ---: |\n| x | y |\n",
    "\t  |  a  | b  |  \t\n",
    "| a | no trailing pipe   \nnot | a table  \n|\n||\n|||\n",
    "| `a|b` | escaped \\| pipe |\n",
    "|  a  | b |\r\n| c | d |\r\n",
    "\u00a0\u2003|\u2009a\u202f|\x1cb\x1f|\u3000\n",
    "a <!-- hidden --> b\n<!--\nmultiline\n-->\nend\n",
    "<!-- first --><!-- second -->tail",
    "<!-- outer <!-- inner --> visible -->",
    "<!-- unclosed\n| a  | b |\n",
    "<!---> and <!-- -->\n",
    "abc--><!-- comment -->def",
    "## Steps\n\n\n1. One\n2. Two\n",
    "```python\ndef f():\n    return 1  \n\n\n<!-- keep -->\n```\n\n\nend   \n",
    "~~~md\n|  keep   |  padding |\n<!-- keep -->\n~~~\n<!-- remove -->",
    "````\n```\n<!-- keep -->\n````` \t\nend   ",
    "~~~\n```\n~~~ tail\n<!-- keep -->\n~~~\nend  ",
    "```\nno closing fence\n<!-- keep -->\n\n\n",
    "```\r\n<!-- keep -->\r\n```\r\n<!-- also protected: CR prevents closure -->",
    "   ``` text\ncode  \n   ```\t\nend  ",
    "    ```\n<!-- not protected -->\n    ```\n",
    "\t```\n<!-- not protected -->\n\t```\n",
    "Zażółć 漢字 🙂\n```\nΣ code  \n```\n|  a  | b |\n",
    "\x00\n<!-- \x00 -->\n| \x00  | b |\n```\n\x00  \n```",
    "\ud800\n| \udfff  | text |\n```\n\ud800 \n```\n",
    "@@FENCE0@@\n```\n<!-- keep -->\n```\n",
    "```\n@@FENCE1@@\n```\n~~~\nbody\n~~~",
    "<!--\n```\nbody\n```\n-->after\n",
)


def fresh_kit():
    spec = importlib.util.spec_from_file_location("kit_native_dispatch_test", kit.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeDispatchTests(unittest.TestCase):
    def test_missing_module_uses_unchanged_python_reference(self):
        original_import = builtins.__import__

        def absent(name, *args, **kwargs):
            if name == "msl_core":
                raise ModuleNotFoundError("No module named msl_core", name="msl_core")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=absent):
            module = fresh_kit()
        self.assertIsNone(module._native_minify_markdown)
        for text in CASES:
            with self.subTest(text=repr(text)):
                self.assertEqual(module.minify_markdown(text), kit._minify_markdown_python(text))

    def test_installed_module_is_used_without_python_fallback(self):
        native = types.ModuleType("msl_core")
        native.minify_markdown = Mock(return_value="native result")
        with patch.dict(sys.modules, {"msl_core": native}):
            module = fresh_kit()
        with patch.object(
            module, "_minify_markdown_python", side_effect=AssertionError("No fallback")
        ):
            self.assertEqual(module.minify_markdown("input"), "native result")
        native.minify_markdown.assert_called_once_with("input")

    def test_native_execution_errors_are_not_treated_as_missing_module(self):
        for error in (
            ValueError("native failure"),
            ImportError("native dependency failure"),
            ModuleNotFoundError("native call failed", name="msl_core"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "native output invalid"),
        ):
            with (
                self.subTest(error=error),
                patch.object(kit, "_native_minify_markdown", side_effect=error),
                patch.object(kit, "_minify_markdown_python") as fallback,
            ):
                with self.assertRaises(type(error)) as caught:
                    kit.minify_markdown("input")
                self.assertIs(caught.exception, error)
                fallback.assert_not_called()

    def test_broken_import_is_not_silently_ignored(self):
        original_import = builtins.__import__
        for error in (
            ImportError("ABI mismatch"),
            RuntimeError("initialization failed"),
            ModuleNotFoundError("missing dependency", name="native_dependency"),
        ):

            def broken(name, *args, _error=error, **kwargs):
                if name == "msl_core":
                    raise _error
                return original_import(name, *args, **kwargs)

            with self.subTest(error=error), patch("builtins.__import__", side_effect=broken):
                with self.assertRaises(type(error)) as caught:
                    fresh_kit()
                self.assertIs(caught.exception, error)

    def test_installed_module_without_required_function_is_broken(self):
        with patch.dict(sys.modules, {"msl_core": types.ModuleType("msl_core")}):
            with self.assertRaises(ImportError):
                fresh_kit()

    def test_export_does_not_confuse_native_output_errors_with_non_utf8_input(self):
        error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "native output invalid")
        with patch.object(kit, "_native_minify_markdown", side_effect=error) as native:
            with self.assertRaises(UnicodeDecodeError) as caught:
                kit._maybe_minify_markdown_bytes(b"valid input", "SKILL.md", True)
            self.assertIs(caught.exception, error)
            native.assert_called_once_with("valid input")
        with patch.object(kit, "_native_minify_markdown") as native:
            self.assertEqual(kit._maybe_minify_markdown_bytes(b"\xff", "SKILL.md", True), b"\xff")
            native.assert_not_called()

    def test_reference_expected_results_and_line_ending_quirks(self):
        self.assertEqual(kit._minify_markdown_python("A  \n\n\nB\t\n"), "A\n\nB\n")
        self.assertEqual(kit._minify_markdown_python("| a   | b |\r\n"), "| a | b |\n")
        self.assertEqual(kit._minify_markdown_python("A  \r\n"), "A  \r\n")
        self.assertEqual(kit._minify_markdown_python("a<!-- hidden -->b"), "ab")
        self.assertEqual(kit._minify_markdown_python("a<!-- open"), "a<!-- open")


@unittest.skipIf(
    kit._native_minify_markdown is None, "Optional msl_core extension is not installed"
)
class NativeParityTests(unittest.TestCase):
    def assert_parity(self, text):
        expected = kit._minify_markdown_python(text)
        self.assertEqual(kit._native_minify_markdown(text), expected)
        self.assertEqual(kit.minify_markdown(text), expected)

    def test_comments_tables_fences_unicode_and_literal_placeholder_collisions(self):
        for text in CASES:
            with self.subTest(text=repr(text)):
                self.assert_parity(text)

    def test_fence_indentation_lengths_and_line_ending_combinations(self):
        for newline, indent, marker, suffix in itertools.product(
            ("\n", "\r\n", "\r"),
            ("", " ", "  ", "   ", "    ", "\t"),
            ("```", "~~~~"),
            ("", "\t", "  ", "\r", " tail"),
        ):
            text = newline.join(
                [
                    "Intro 🙂   ",
                    indent + marker + "python",
                    "<!-- keep if fenced -->",
                    "|  x  | y  |",
                    indent + marker + suffix,
                    "<!-- remove if outside -->",
                    "",
                    "",
                    "Tail   ",
                ]
            )
            with self.subTest(
                newline=repr(newline), indent=repr(indent), marker=marker, suffix=repr(suffix)
            ):
                self.assert_parity(text)

    def test_python_whitespace_in_table_cells_and_ordinary_lines(self):
        whitespace = (
            "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680"
            "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
            "\u2028\u2029\u202f\u205f\u3000"
        )
        for character in whitespace:
            with self.subTest(character=repr(character)):
                self.assert_parity(f"{character}|{character}x{character}| y |{character}\n")
                self.assert_parity(f"plain{character}\n")

    def test_real_repository_markdown(self):
        for relative in (
            "README.md",
            "skills/mkl-humanize/SKILL.md",
            "skills/mkl-review-pr/SKILL.md",
            "assets/canonical_preamble.md",
        ):
            with self.subTest(path=relative):
                text = (Path(kit.ROOT) / relative).read_bytes().decode("utf-8")
                self.assert_parity(text)

    def test_native_requires_a_python_string(self):
        for value in (b"text", None, 42):
            with self.subTest(value=value), self.assertRaises(TypeError):
                kit._native_minify_markdown(value)


if __name__ == "__main__":
    unittest.main()
