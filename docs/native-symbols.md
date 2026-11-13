# Native AST symbol extraction (M4)

Build the optional `msl_core` extension using the instructions in
[its README](../crates/msl-core/README.md). Python-only tools retain their current
implementations; no existing extractor, index or repository map calls this API.

```python
import msl_core

symbols = msl_core.extract_ast_symbols(
    "example.py", "class Box:\n    def run(self):\n        return 1\n"
)
for symbol in symbols:
    print(symbol.name, symbol.kind, symbol.parent, symbol.lineno, symbol.end_lineno)
```

## Contract

`extract_ast_symbols(file_path: str, code: str) -> list[Symbol]` parses the supplied
UTF-8-compatible Python string. `file_path` selects the grammar and appears in
error diagnostics. The path need not exist; the function performs no file I/O.
It creates a fresh parser per call and releases the Python GIL during extraction.

Each `msl_core.Symbol` is a frozen record with readable attributes:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Local declaration name, retaining Unicode spelling |
| `kind` | `str` | `function`, `method`, `class` or `struct` |
| `signature` | `str` | Source header before the body, with outer whitespace removed |
| `lineno` | `int` | First declaration line, starting at 1 |
| `end_lineno` | `int` | Last declaration line, inclusive, including the body |
| `parent` | `str \| None` | Nearest outlined owner's dot-qualified path |
| `docstring` | `str \| None` | Basic two-line documentation summary |
| `is_public` | `bool \| None` | Local visibility/export marker; `None` means unknown |

Names remain local; for example, `name="inner", parent="Box.run"`. Rust impl
targets and Go receiver types supply owners even if their declarations are not
present in the input. Generic arguments are omitted from those owner names.
C++ qualified functions retain their qualified name unless the owner matches an
outlined class/struct in the input, in which case they are recorded as methods.
Overloads, prototypes and definitions are separate records, not merged by name.

Results sort by the declaration node's source byte offset, including within a
single line; owners precede their nested declarations. The offsets remain internal
and the same source produces the same order. Equal offsets retain source traversal
order. Records have no cross-call identity contract; compare their attributes
for equality.

LF determines line boundaries; CRLF counts as one boundary. Multiline signatures
retain their exact internal whitespace, comments and CRLF. Bodies and braces
are excluded; Python headers retain their colon. Bodyless declarations retain
their complete source spelling, including terminators. Python decorators and
Rust attributes are outside declaration ranges; inline JS exports are included.
For a single JS variable binding, the header includes `const`/`let`/`var`; a Go
single type declaration includes `type`. Grouped/multiple declarations may start
at the individual binding. This is an outline, not a normalized formatter.

## Supported syntax

| Language | Extensions | Main declarations |
| --- | --- | --- |
| Python | `.py`, `.pyi` | Functions/async functions, classes, methods, nested definitions |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | Named functions/generators, classes, methods, identifier-bound arrows/function expressions |
| TypeScript | `.ts`, `.tsx`, `.mts`, `.cts` | JS constructs, typed/generic functions, abstract classes/methods and function signatures |
| Rust | `.rs` | Functions, function signatures, named/tuple/unit structs, impl methods |
| Go | `.go` | Functions, named struct types, receiver methods |
| C++ | `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.hh`, `.hxx` | Class/struct definitions, function definitions/prototypes, inline and recognized out-of-line methods |
| Java | `.java` | Classes, methods, constructors, nested classes |

Extension matching is case-insensitive. `.h` selects C++; `.c` is unsupported.
Anonymous callbacks/classes, destructured JS bindings, string/computed method
names, aliases, variables, fields, enums, interfaces, traits and Java records
are not outlined. Unsupported enum/interface/trait/record containers are skipped
with their members. C++ function-pointer variables are excluded; complex
declarators may be omitted. There is no macro expansion, preprocessor evaluation,
module/namespace qualification or semantic type/name resolution. Anonymous scopes
do not add a parent record; nesting uses the nearest named outlined owner.

Python documentation uses a leading plain/raw string statement, excluding bytes
and f-strings. Its raw literal content is summarized without decoding escapes,
concatenating literals or applying Python `inspect.cleandoc`. Other languages use
adjacent `/** ... */` or `///` comments; Go also accepts ordinary adjacent comments.
Rust outer attributes can appear between documentation and a declaration. Blank
lines break attachment. The first two nonempty trimmed lines form the summary;
additional lines add `...`. This deliberately provides basic documentation, not
full docstring, Javadoc, JSDoc or Rustdoc interpretation.

`is_public` describes the declaration, not effective project accessibility:

- Python returns `None`; underscores and `__all__` are not export declarations.
- JS/TS direct inline exports return `True`; TS accessibility modifiers and JS
  private `#names` are recognized. Other JS visibility is `None`. Export lists,
  CommonJS assignments, inherited visibility and re-exports are not resolved.
- Rust unrestricted `pub` is `True`; absent or restricted `pub(...)` is `False`.
- Go uses the initial Unicode uppercase-letter convention.
- Java uses a direct `public` modifier; other declarations return `False`.
- C++ members use class/struct defaults and preceding access specifiers.
  Free functions, top-level types and out-of-line definitions return `None`.

## Errors and limitations

Unsupported extensions raise `ValueError`. Invalid argument types raise
`TypeError`; lone Python surrogates raise `UnicodeEncodeError`. Empty supported
sources return `[]`. Any Tree-sitter error or missing syntax node raises
`SyntaxError` with filename and one-based line/character-offset diagnostics.
Recovered symbols and valid prefixes are never returned after a parsing error.
Grammar initialization failures and a one-second per-call parsing timeout raise
`RuntimeError`. There is no fallback parser or partial-success mode.

A syntax tree is not a compiler check: some grammars accept snippets or constructs
that the language compiler rejects. Successful extraction means parsing and the
documented outline succeeded, not semantic validity or complete coverage of every
language construct. The pinned grammars can reject newer syntax. Extraction does
not execute source, resolve dependencies or compute graph rankings.

## Verification and benchmark

```sh
python -m unittest discover -s tests -p 'test_native_symbols.py' -v
python tools/benchmark_symbols.py --size 100 --repeat 5
```

Native tests skip when the extension or both M4 exports are absent; a partially
installed M4 API fails. Tests cover all languages, multiline/nested declarations,
documentation, visibility, Unicode, CRLF, parser recovery and deterministic order.

The benchmark generates a fixed corpus for all seven language variants, checks
expected counts, warms extraction, then compares every repetition with the first
result. JSON includes corpus/result SHA-256 hashes, Python/platform/native versions,
byte and symbol counts, samples and median seconds per language. Timing includes
parser creation, parsing, traversal, sorting and creation of Python records; corpus
generation, imports and result serialization are excluded. Keep the dependency
lockfile, release build, corpus parameters and machine fixed when comparing runs.
No performance measurements or speedup claims are supplied with M4.
