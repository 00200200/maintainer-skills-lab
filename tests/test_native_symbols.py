"""Contract tests for the optional, syntax-only Tree-sitter symbol extractor."""

from __future__ import annotations

import unittest

try:
    import msl_core
except ModuleNotFoundError as error:
    if error.name != "msl_core":
        raise
    msl_core = None

# Older optional wheels have no M4 API; partial APIs must fail rather than skip.
HAS_AST = msl_core is not None and any(
    name in vars(msl_core) for name in ("Symbol", "extract_ast_symbols")
)

FIELDS = (
    "name",
    "kind",
    "signature",
    "lineno",
    "end_lineno",
    "parent",
    "docstring",
    "is_public",
)

CASES = {
    "py": (
        'class Container:\n    """Container docs."""\n'
        '    def work(self):\n        """Work docs."""\n        pass\n'
        "async def helper():\n    pass\n",
        [
            ("Container", "class", None, None),
            ("work", "method", "Container", None),
            ("helper", "function", None, None),
        ],
    ),
    "js": (
        "/** Container docs. */\nexport class Container {\n"
        "  /** Work docs. */\n  work(x) { return x; }\n}\n"
        "export const helper = (x) => x + 1;\n",
        [
            ("Container", "class", None, True),
            ("work", "method", "Container", None),
            ("helper", "function", None, True),
        ],
    ),
    "ts": (
        "/** Container docs. */\nexport class Container<T> {\n"
        "  /** Work docs. */\n  public work(x: T): T { return x; }\n}\n"
        "export function helper<T>(x: T): T { return x; }\n",
        [
            ("Container", "class", None, True),
            ("work", "method", "Container", True),
            ("helper", "function", None, True),
        ],
    ),
    "rs": (
        "/// Container docs.\npub struct Container {}\nimpl Container {\n"
        "    /// Work docs.\n    pub fn work(&self) { fn nested() {} }\n}\n"
        "fn helper() {}\n",
        [
            ("Container", "struct", None, True),
            ("work", "method", "Container", True),
            ("nested", "function", "Container.work", False),
            ("helper", "function", None, False),
        ],
    ),
    "go": (
        "package main\n// Container docs.\ntype Container struct {}\n"
        "// Work docs.\nfunc (c *Container) Work(x int) int { return x }\n"
        "func helper() {}\n",
        [
            ("Container", "struct", None, True),
            ("Work", "method", "Container", True),
            ("helper", "function", None, False),
        ],
    ),
    "cpp": (
        "/** Container docs. */\nclass Container {\npublic:\n"
        "  /// Work docs.\n  int work(int x) { return x; }\n"
        "private:\n  void secret() {}\n};\nint helper() { return 1; }\n",
        [
            ("Container", "class", None, None),
            ("work", "method", "Container", True),
            ("secret", "method", "Container", False),
            ("helper", "function", None, None),
        ],
    ),
    "java": (
        "/** Container docs. */\npublic class Container {\n"
        "  /** Work docs. */\n  public int work(int x) { return x; }\n"
        "  private void helper() {}\n}\n",
        [
            ("Container", "class", None, True),
            ("work", "method", "Container", True),
            ("helper", "method", "Container", False),
        ],
    ),
}


def records(symbols):
    return [tuple(getattr(symbol, field) for field in FIELDS) for symbol in symbols]


@unittest.skipUnless(HAS_AST, "Optional native AST API is unavailable")
class NativeSymbolTests(unittest.TestCase):
    def extract(self, extension, code):
        return msl_core.extract_ast_symbols(f"/nonexistent/source.{extension}", code)

    def test_each_language_kinds_parents_docs_and_visibility(self):
        for extension, (code, expected) in CASES.items():
            with self.subTest(extension=extension):
                symbols = self.extract(extension, code)
                self.assertEqual(
                    [(s.name, s.kind, s.parent, s.is_public) for s in symbols],
                    expected,
                )
                self.assertEqual(symbols[0].docstring, "Container docs.")
                method = next(s for s in symbols if s.name in ("work", "Work"))
                self.assertEqual(method.docstring, "Work docs.")
                for symbol in symbols:
                    self.assertIsInstance(symbol, msl_core.Symbol)
                    self.assertGreaterEqual(symbol.lineno, 1)
                    self.assertGreaterEqual(symbol.end_lineno, symbol.lineno)
                    self.assertTrue(symbol.signature)
                    self.assertNotIn("return x", symbol.signature)

    def test_python_multiline_signature_nesting_unicode_and_decorators(self):
        code = (
            "@decorator\nclass Café:\n"
            '    async def méthode(\n        self,\n        x: str = "🙂",\n'
            '    ) -> str:\n        """First line.\n        Second line.\n'
            '        Third line.\n        """\n'
            "        def inner():\n            return x\n        return inner()\n"
        )
        symbols = self.extract("py", code)
        self.assertEqual(
            [(s.name, s.kind, s.parent) for s in symbols],
            [
                ("Café", "class", None),
                ("méthode", "method", "Café"),
                ("inner", "function", "Café.méthode"),
            ],
        )
        self.assertEqual((symbols[0].lineno, symbols[0].end_lineno), (2, 13))
        self.assertEqual((symbols[1].lineno, symbols[1].end_lineno), (3, 13))
        self.assertEqual(
            symbols[1].signature,
            'async def méthode(\n        self,\n        x: str = "🙂",\n    ) -> str:',
        )
        self.assertEqual(symbols[1].docstring, "First line. Second line....")

    def test_multiline_signatures_across_braced_languages(self):
        cases = {
            "js": "function work(\n x,\n y\n) { return x; }",
            "ts": "function work(\n x: number,\n y: number\n): number { return x; }",
            "rs": "fn work(\n x: i32,\n y: i32\n) -> i32 { x }",
            "go": "package main\nfunc work(\n x int,\n y int,\n) int { return x }",
            "cpp": "int work(\n int x,\n int y\n) { return x; }",
            "java": "class C { int work(\n int x,\n int y\n) { return x; } }",
        }
        for extension, code in cases.items():
            with self.subTest(extension=extension):
                symbol = next(s for s in self.extract(extension, code) if s.name == "work")
                self.assertIn("\n", symbol.signature)
                self.assertNotIn("return", symbol.signature)
                self.assertTrue(symbol.signature.rstrip().endswith((")", "number", "i32", "int")))

    def test_jsx_tsx_and_extension_aliases(self):
        for extension in ["js", "jsx", "mjs", "cjs", "tsx"]:
            with self.subTest(extension=extension):
                symbols = self.extract(extension, "export const View = () => <div>Hello</div>;")
                self.assertEqual([s.name for s in symbols], ["View"])
                self.assertTrue(symbols[0].is_public)
        for extension, base in [
            ("pyi", "py"),
            ("mts", "ts"),
            ("cts", "ts"),
            ("h", "cpp"),
            ("hpp", "cpp"),
            ("hh", "cpp"),
            ("cxx", "cpp"),
            ("cc", "cpp"),
            ("hxx", "cpp"),
            ("CPP", "cpp"),
        ]:
            with self.subTest(extension=extension):
                self.assertEqual(
                    records(self.extract(extension, CASES[base][0])),
                    records(self.extract(base, CASES[base][0])),
                )

    def test_nested_classes_and_method_scopes(self):
        symbols = self.extract("java", "class Outer { class Inner { void work() {} } }")
        self.assertEqual(
            [(s.name, s.parent) for s in symbols],
            [
                ("Outer", None),
                ("Inner", "Outer"),
                ("work", "Outer.Inner"),
            ],
        )
        symbols = self.extract("js", "class C { work() { function inner() {} } }")
        self.assertEqual(next(s for s in symbols if s.name == "inner").kind, "function")
        self.assertEqual(next(s for s in symbols if s.name == "inner").parent, "C.work")

    def test_same_line_symbols_follow_source_positions_not_names(self):
        code = "struct Box {} impl Box { fn work() { fn nested() {} } fn alpha() {} }"
        expected = [
            ("Box", "struct", None),
            ("work", "method", "Box"),
            ("nested", "function", "Box.work"),
            ("alpha", "method", "Box"),
        ]
        for _ in range(4):
            symbols = self.extract("rs", code)
            self.assertEqual([(s.name, s.kind, s.parent) for s in symbols], expected)
            self.assertTrue(all(s.lineno == 1 and s.end_lineno == 1 for s in symbols))

    def test_rust_unit_tuple_structs_attributes_and_scoped_visibility(self):
        code = "/// Docs.\n#[derive(Debug)]\npub struct Unit;\npub(crate) struct Pair(i32);\n"
        symbols = self.extract("rs", code)
        self.assertEqual([s.name for s in symbols], ["Unit", "Pair"])
        self.assertEqual(symbols[0].docstring, "Docs.")
        self.assertTrue(symbols[0].is_public)
        self.assertFalse(symbols[1].is_public)

    def test_generic_receivers_impls_and_explicit_member_visibility(self):
        cases = {
            "rs": "pub struct Box<T> { value: T }\nimpl<T> Box<T> { pub fn run(&self) {} }",
            "go": "package main\ntype Box[T any] struct {}\nfunc (b *Box[T]) Run() {}",
        }
        for extension, code in cases.items():
            with self.subTest(extension=extension):
                method = next(s for s in self.extract(extension, code) if s.kind == "method")
                self.assertEqual(method.parent, "Box")
                self.assertTrue(method.is_public)
        symbols = self.extract("ts", "export class Box { private hidden() {} public run() {} }")
        self.assertFalse(next(s for s in symbols if s.name == "hidden").is_public)
        self.assertTrue(next(s for s in symbols if s.name == "run").is_public)
        symbols = self.extract("js", "export const a = () => 1, b = () => 2;")
        self.assertEqual([s.name for s in symbols], ["a", "b"])
        self.assertTrue(all(s.is_public for s in symbols))

    def test_java_constructor_and_bodyless_method(self):
        code = "public abstract class Box { public Box() {} public abstract void run(); }"
        symbols = self.extract("java", code)
        self.assertEqual(
            [(s.name, s.kind) for s in symbols],
            [
                ("Box", "class"),
                ("Box", "method"),
                ("run", "method"),
            ],
        )
        self.assertEqual(symbols[1].parent, "Box")
        self.assertEqual(symbols[2].signature, "public abstract void run();")

    def test_blank_lines_break_comment_documentation(self):
        for extension, code in [
            ("js", "/** Unattached. */\n\nfunction f() {}"),
            ("rs", "/// Unattached.\n\nfn f() {}"),
            ("go", "package main\n// Unattached.\n\nfunc f() {}"),
        ]:
            with self.subTest(extension=extension):
                self.assertIsNone(self.extract(extension, code)[0].docstring)

    def test_cpp_prototypes_overloads_and_out_of_line_methods(self):
        code = (
            "struct Box { void run(); int run(int x); };\n"
            "void Box::run() {}\nint Box::run(int x) { return x; }\n"
            "void (*callback)(int);\nint free_function();\n"
        )
        symbols = self.extract("cpp", code)
        methods = [s for s in symbols if s.name == "run"]
        self.assertEqual(len(methods), 4)
        self.assertTrue(all(s.kind == "method" and s.parent == "Box" for s in methods))
        self.assertFalse(any(s.name == "callback" for s in symbols))
        self.assertEqual(next(s for s in symbols if s.name == "free_function").kind, "function")

    def test_no_false_symbols_from_strings_comments_or_anonymous_callbacks(self):
        code = 'const text = "function fake() {}"; /* class Fake {} */\nitems.map(x => x);'
        self.assertEqual(self.extract("js", code), [])
        code = 'def f():\n    b"not docs"\n    return "def fake(): pass"\n'
        self.assertIsNone(self.extract("py", code)[0].docstring)
        code = 'def f():\n    f"not docs"\n    pass\n'
        self.assertIsNone(self.extract("py", code)[0].docstring)

    def test_empty_sources_crlf_and_no_final_newline(self):
        for extension in CASES:
            with self.subTest(extension=extension):
                self.assertEqual(self.extract(extension, ""), [])
        code = "def café(\r\n    x,\r\n):\r\n    return x"
        symbol = self.extract("py", code)[0]
        self.assertEqual((symbol.lineno, symbol.end_lineno), (1, 4))
        self.assertIn("\r\n", symbol.signature)
        self.assertEqual(self.extract("py", code + "\r\n")[0].end_lineno, 4)

    def test_parse_errors_never_return_valid_prefix_or_recovered_symbols(self):
        malformed = {
            "py": "def ok(): pass\ndef bad(:\n",
            "js": "function ok() {}\nfunction bad( {",
            "ts": "class Good {}\nfunction bad( {",
            "rs": "fn ok() {}\nfn broken( {",
            "go": "package main\nfunc ok() {}\nfunc broken( {",
            "cpp": "int ok() { return 0; }\nclass Missing {",
            "java": "class Good {}\nclass Missing {",
        }
        for extension, code in malformed.items():
            with self.subTest(extension=extension), self.assertRaises(SyntaxError) as caught:
                self.extract(extension, code)
            self.assertTrue(caught.exception.filename.endswith(f".{extension}"))
            self.assertGreaterEqual(caught.exception.lineno, 1)

    def test_unsupported_extensions_and_types_are_errors(self):
        for path in ["source", "source.txt", "source.c", "source.py.backup"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                msl_core.extract_ast_symbols(path, "")
        for path, code in [(None, ""), ("a.py", None), ("a.py", b"pass")]:
            with self.subTest(path=path, code=code), self.assertRaises(TypeError):
                msl_core.extract_ast_symbols(path, code)
        with self.assertRaises(UnicodeEncodeError):
            self.extract("py", "\ud800")

    def test_records_are_read_only_and_results_deterministic(self):
        for extension, (code, _) in CASES.items():
            with self.subTest(extension=extension):
                expected = records(self.extract(extension, code))
                for _ in range(4):
                    self.assertEqual(records(self.extract(extension, code)), expected)
        symbol = self.extract("py", "def f(): pass")[0]
        with self.assertRaises(AttributeError):
            symbol.name = "changed"


if __name__ == "__main__":
    unittest.main()
