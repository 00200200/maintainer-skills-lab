"""Native BPE parity and regression tests for optional backend dispatch."""

from __future__ import annotations

import builtins
import random
import sys
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from tools import kit

try:
    import msl_core
except ModuleNotFoundError as error:
    if error.name != "msl_core":
        raise
    msl_core = None

try:
    import tiktoken
except ModuleNotFoundError as error:
    if error.name != "tiktoken":
        raise
    tiktoken = None

NATIVE_BPE_PRESENT = msl_core is not None and any(
    name in vars(msl_core) for name in ("count_tokens", "DisallowedSpecialTokenError")
)


class DisallowedSpecial(ValueError):
    """Stand-in for the native exception, independent of the optional wheel."""


class TokenDispatchTests(unittest.TestCase):
    def test_only_absent_native_module_returns_no_backend(self):
        original_import = builtins.__import__

        def absent(name, *args, **kwargs):
            if name == "msl_core":
                raise ModuleNotFoundError("Not installed", name="msl_core")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=absent):
            self.assertIsNone(kit._native_token_backend())

    def test_broken_native_imports_propagate(self):
        original_import = builtins.__import__
        for error in [
            ImportError("ABI mismatch"),
            RuntimeError("Initialization failed"),
            ModuleNotFoundError("Missing dependency", name="native_dependency"),
        ]:

            def broken(name, *args, _error=error, **kwargs):
                if name == "msl_core":
                    raise _error
                return original_import(name, *args, **kwargs)

            with (
                self.subTest(error=error),
                patch("builtins.__import__", side_effect=broken),
                patch.dict(sys.modules, {"tiktoken": None}),
            ):
                with self.assertRaises(type(error)) as caught:
                    kit.count_tokens("hello")
                self.assertIs(caught.exception, error)

    def test_incomplete_installed_extension_is_not_absent(self):
        for missing in ["count_tokens", "DisallowedSpecialTokenError"]:
            native = types.ModuleType("msl_core")
            native.count_tokens = Mock(return_value=2)
            native.DisallowedSpecialTokenError = DisallowedSpecial
            delattr(native, missing)
            with (
                self.subTest(missing=missing),
                patch.dict(sys.modules, {"msl_core": native, "tiktoken": None}),
                patch.object(kit, "load_library", return_value=({}, {})),
            ):
                with self.assertRaises(ImportError):
                    kit.count_tokens("hello")
                with self.assertRaises(ImportError):
                    kit.profile_tokens()

    def test_native_is_used_when_python_is_absent_for_both_exact_encodings(self):
        native = types.ModuleType("msl_core")
        native.count_tokens = Mock(return_value=7)
        native.DisallowedSpecialTokenError = DisallowedSpecial
        with (
            patch.dict(sys.modules, {"msl_core": native, "tiktoken": None}),
            patch.object(kit, "approximate_tokens", side_effect=AssertionError("No fallback")),
        ):
            for encoding in ["cl100k_base", "o200k_base"]:
                self.assertEqual(kit.count_tokens("hello", encoding), 7)
                native.count_tokens.assert_called_with("hello", encoding)

    def test_unexpected_native_execution_errors_never_fall_back(self):
        for error in [
            RuntimeError("BPE failed"),
            ValueError("Unexpected failure"),
            ImportError("Broken dependency"),
            ModuleNotFoundError("Call failed", name="msl_core"),
            UnicodeEncodeError("utf-8", "\ud800", 0, 1, "Unexpected codec failure"),
        ]:
            native = Mock(side_effect=error)
            with (
                self.subTest(error=error),
                patch.object(
                    kit, "_native_token_backend", return_value=(native, DisallowedSpecial)
                ),
                patch.object(kit, "approximate_tokens") as heuristic,
                patch.dict(sys.modules, {"tiktoken": None}),
            ):
                with self.assertRaises(type(error)) as caught:
                    kit.count_tokens("hello")
                self.assertIs(caught.exception, error)
                heuristic.assert_not_called()

    def test_native_disallowed_special_preserves_existing_heuristic(self):
        text = "before <|endoftext|> after"
        with (
            patch.object(
                kit,
                "_native_token_backend",
                return_value=(Mock(side_effect=DisallowedSpecial("Rejected")), DisallowedSpecial),
            ),
            patch.dict(sys.modules, {"tiktoken": None}),
        ):
            self.assertEqual(kit.count_tokens(text), kit.approximate_tokens(text))

    def test_absent_extension_uses_python_tiktoken(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        python.get_encoding.return_value.encode.return_value = [1, 2, 3]
        with (
            patch.object(kit, "_native_token_backend", return_value=None),
            patch.dict(sys.modules, {"tiktoken": python}),
        ):
            self.assertEqual(kit.count_tokens("hello", "o200k_base"), 3)
        python.get_encoding.assert_called_once_with("o200k_base")
        python.get_encoding.return_value.encode.assert_called_once_with("hello")

    def test_absent_both_backends_uses_unchanged_heuristic(self):
        with (
            patch.object(kit, "_native_token_backend", return_value=None),
            patch.dict(sys.modules, {"tiktoken": None}),
        ):
            for text in ["hello world", "漢字🙂", "<|endoftext|>"]:
                self.assertEqual(kit.count_tokens(text), kit.approximate_tokens(text))

    def test_other_encodings_still_use_python_and_invalid_ones_use_heuristic(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        python.get_encoding.return_value.encode.return_value = [1, 2]
        with (
            patch.object(kit, "_native_token_backend", side_effect=AssertionError("No dispatch")),
            patch.dict(sys.modules, {"tiktoken": python}),
        ):
            self.assertEqual(kit.count_tokens("hello", "p50k_base"), 2)
            python.get_encoding.assert_called_once_with("p50k_base")
            python.get_encoding.side_effect = ValueError("Unknown encoding unknown")
            self.assertEqual(kit.count_tokens("hello", "unknown"), kit.approximate_tokens("hello"))

    def test_unexpected_python_failures_propagate_without_trying_native(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        with (
            patch.object(kit, "_native_token_backend") as native,
            patch.dict(sys.modules, {"tiktoken": python}),
            patch.object(kit, "approximate_tokens") as heuristic,
        ):
            for error in [RuntimeError("Failed"), ValueError("Invalid vocabulary")]:
                for phase in ["initialize", "encode"]:
                    with self.subTest(error=error, phase=phase):
                        python.get_encoding.side_effect = error if phase == "initialize" else None
                        python.get_encoding.return_value.encode.side_effect = error
                        with self.assertRaises(type(error)) as caught:
                            kit.count_tokens("hello")
                        self.assertIs(caught.exception, error)
            native.assert_not_called()
            heuristic.assert_not_called()

    def test_python_special_rejection_uses_heuristic_without_trying_native(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        python.get_encoding.return_value.encode.side_effect = ValueError(
            "Encountered text corresponding to disallowed special token '<|endoftext|>'"
        )
        with (
            patch.dict(sys.modules, {"tiktoken": python}),
            patch.object(kit, "_native_token_backend", side_effect=AssertionError("No dispatch")),
        ):
            self.assertEqual(
                kit.count_tokens("<|endoftext|>"),
                kit.approximate_tokens("<|endoftext|>"),
            )

    def test_broken_python_imports_propagate(self):
        original_import = builtins.__import__
        for error in [
            ImportError("ABI mismatch"),
            RuntimeError("Initialization failed"),
            ModuleNotFoundError("Missing dependency", name="tiktoken_dependency"),
        ]:

            def broken(name, *args, _error=error, **kwargs):
                if name == "tiktoken":
                    raise _error
                return original_import(name, *args, **kwargs)

            with (
                self.subTest(error=error),
                patch("builtins.__import__", side_effect=broken),
                patch.object(kit, "_native_token_backend") as native,
            ):
                with self.assertRaises(type(error)) as caught:
                    kit.count_tokens("hello")
                self.assertIs(caught.exception, error)
                native.assert_not_called()

    def test_both_backends_installed_python_wins_for_counts_and_profile(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        python.get_encoding.return_value.encode.return_value = [1, 2, 3]
        native = types.ModuleType("msl_core")
        native.count_tokens = Mock(side_effect=AssertionError("Native must not run"))
        native.DisallowedSpecialTokenError = DisallowedSpecial
        with (
            patch.dict(sys.modules, {"tiktoken": python, "msl_core": native}),
            patch.object(kit, "_native_token_backend", side_effect=AssertionError("No dispatch")),
            patch.object(kit, "load_library", return_value=({}, {})),
            patch.object(kit, "export_files", return_value={}),
        ):
            for encoding in ["cl100k_base", "o200k_base"]:
                self.assertEqual(kit.count_tokens("hello", encoding), 3)
                self.assertEqual(kit.profile_tokens(encoding=encoding)["encoding"], encoding)
        native.count_tokens.assert_not_called()

    def test_older_extensions_without_both_exports_fall_back(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        python.get_encoding.return_value.encode.return_value = [1, 2]
        for milestone in ["M1", "M2"]:
            native = types.ModuleType("msl_core")
            native.minify_markdown = Mock()
            if milestone == "M2":
                native.walk_project = Mock()
            with (
                self.subTest(milestone=milestone),
                patch.dict(sys.modules, {"msl_core": native, "tiktoken": None}),
                patch.object(kit, "load_library", return_value=({}, {})),
                patch.object(kit, "export_files", return_value={}),
            ):
                self.assertIsNone(kit._native_token_backend())
                self.assertEqual(kit.count_tokens("hello"), kit.approximate_tokens("hello"))
                self.assertIn("heuristic", kit.profile_tokens()["encoding"])
                with patch.dict(sys.modules, {"tiktoken": python}):
                    self.assertEqual(kit.count_tokens("hello"), 2)
                    self.assertEqual(kit.profile_tokens()["encoding"], "cl100k_base")

    def test_python_unknown_encoding_allows_native_supported_encoding(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock(side_effect=ValueError("Unknown encoding o200k_base"))
        native = Mock(return_value=7)
        with (
            patch.dict(sys.modules, {"tiktoken": python}),
            patch.object(kit, "_native_token_backend", return_value=(native, DisallowedSpecial)),
            patch.object(kit, "load_library", return_value=({}, {})),
            patch.object(kit, "export_files", return_value={}),
        ):
            self.assertEqual(kit.count_tokens("hello", "o200k_base"), 7)
            native.assert_called_once_with("hello", "o200k_base")
            self.assertEqual(kit.profile_tokens(encoding="o200k_base")["encoding"], "o200k_base")

    def test_empty_text_preserves_short_circuit_even_for_unknown_encoding(self):
        with patch.object(kit, "_native_token_backend", side_effect=AssertionError("No backend")):
            self.assertEqual(kit.count_tokens(""), 0)
            self.assertEqual(kit.count_tokens("", "unknown"), 0)

    def test_profile_labels_native_exact_and_missing_backends_heuristic(self):
        with (
            patch.object(kit, "load_library", return_value=({}, {})),
            patch.object(kit, "export_files", return_value={}),
            patch.dict(sys.modules, {"tiktoken": None}),
        ):
            for encoding in ["cl100k_base", "o200k_base"]:
                with patch.object(
                    kit,
                    "_native_token_backend",
                    return_value=(Mock(), DisallowedSpecial),
                ):
                    self.assertEqual(kit.profile_tokens(encoding=encoding)["encoding"], encoding)
            with patch.object(kit, "_native_token_backend", return_value=None):
                self.assertIn("heuristic", kit.profile_tokens()["encoding"])

    def test_profile_preserves_other_encodings_and_propagates_native_import_failures(self):
        python = types.ModuleType("tiktoken")
        python.get_encoding = Mock()
        with (
            patch.object(kit, "load_library", return_value=({}, {})),
            patch.object(kit, "export_files", return_value={}),
            patch.dict(sys.modules, {"tiktoken": python}),
            patch.object(kit, "_native_token_backend", side_effect=RuntimeError("Broken native")),
        ):
            self.assertEqual(kit.profile_tokens(encoding="p50k_base")["encoding"], "p50k_base")
            with (
                patch.dict(sys.modules, {"tiktoken": None}),
                self.assertRaisesRegex(RuntimeError, "Broken native"),
            ):
                kit.profile_tokens()


@unittest.skipUnless(NATIVE_BPE_PRESENT, "Optional native BPE backend is unavailable")
class NativeTokenContractTests(unittest.TestCase):
    def test_empty_default_encoding_and_basic_counts(self):
        self.assertEqual(msl_core.count_tokens(""), 0)
        for encoding in ["cl100k_base", "o200k_base"]:
            self.assertEqual(msl_core.count_tokens("hello world", encoding), 2)
            self.assertEqual(msl_core.count_tokens("", encoding=encoding), 0)

    def test_unknown_encodings_raise_even_for_empty_text(self):
        for encoding in ["unknown", "p50k_base", "CL100K_BASE", ""]:
            for text in ["", "hello"]:
                with self.subTest(encoding=encoding, text=text), self.assertRaises(ValueError):
                    msl_core.count_tokens(text, encoding)

    def test_binding_rejects_non_string_arguments(self):
        for text in [None, b"hello", 123]:
            with self.subTest(text=text), self.assertRaises(TypeError):
                msl_core.count_tokens(text)
        with self.assertRaises(TypeError):
            msl_core.count_tokens("hello", None)

    def test_known_specials_raise_value_error_subclass_without_python_tiktoken(self):
        for encoding in ["cl100k_base", "o200k_base"]:
            with self.subTest(encoding=encoding):
                with self.assertRaises(msl_core.DisallowedSpecialTokenError) as caught:
                    msl_core.count_tokens("before <|endoftext|> after", encoding)
                self.assertIsInstance(caught.exception, ValueError)


@unittest.skipUnless(
    NATIVE_BPE_PRESENT and tiktoken is not None, "Requires native BPE and tiktoken"
)
class NativeTokenParityTests(unittest.TestCase):
    def test_unicode_whitespace_code_and_seeded_corpus(self):
        cases = [
            "",
            "hello world",
            "\0",
            " \t\r\n\n",
            "A\rB\nC\r\nD",
            "Zażółć gęślą jaźń 漢字 日本語 한국어",
            "مرحبا بالعالم हिन्दी",
            "🙂👩🏽‍💻🏳️‍🌈",
            "é e\u0301 İ ı Σ ς",
            "can't I'M we've 0123456789",
            "\ufeff\u200b\u2028\u2029\u00a0",
            "# Heading\n| a | b |\n```py\nprint(1)\n```",
            "text " * 1000,
            "\ud800",
            "\udfff",
            "\ud83d\ude42",
            "a\ud800b\udfff",
            "\ud800\ud800\udc00\udfff",
            "<|not_a_special_token|>",
        ]
        generator = random.Random(132)
        alphabet = "abcXYZ0123 \t\r\n🙂漢é\u0301العربية"
        cases.extend("".join(generator.choices(alphabet, k=257)) for _ in range(32))
        for encoding in ["cl100k_base", "o200k_base"]:
            reference = tiktoken.get_encoding(encoding)
            for text in cases:
                with self.subTest(encoding=encoding, text=repr(text[:60])):
                    self.assertEqual(
                        msl_core.count_tokens(text, encoding),
                        len(reference.encode(text)),
                    )

    def test_special_token_policy_matches_each_encoding(self):
        spellings = [
            "<|endoftext|>",
            "<|endofprompt|>",
            "<|fim_prefix|>",
            "<|fim_middle|>",
            "<|fim_suffix|>",
            "<|im_start|>",
        ]
        for encoding in ["cl100k_base", "o200k_base"]:
            reference = tiktoken.get_encoding(encoding)
            for spelling in spellings:
                text = f"before {spelling} after"
                with self.subTest(encoding=encoding, spelling=spelling):
                    if spelling in reference.special_tokens_set:
                        with self.assertRaises(ValueError):
                            reference.encode(text)
                        with self.assertRaises(msl_core.DisallowedSpecialTokenError):
                            msl_core.count_tokens(text, encoding)
                        self.assertEqual(
                            kit.count_tokens(text, encoding),
                            kit.approximate_tokens(text),
                        )
                    else:
                        self.assertEqual(
                            msl_core.count_tokens(text, encoding),
                            len(reference.encode(text)),
                        )

    def test_cached_encodings_support_concurrent_calls(self):
        jobs = [
            (encoding, "Unicode 🙂 漢字 " * 20) for encoding in ["cl100k_base", "o200k_base"] * 8
        ]
        expected = [len(tiktoken.get_encoding(encoding).encode(text)) for encoding, text in jobs]
        with ThreadPoolExecutor(max_workers=4) as executor:
            actual = list(executor.map(lambda job: msl_core.count_tokens(job[1], job[0]), jobs))
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
