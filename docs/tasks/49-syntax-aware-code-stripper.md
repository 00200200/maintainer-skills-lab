# [Optimization] Syntax-Aware Comment & Docstring Stripper (tools/strip_comments.py)

**Labels**: `enhancement`, `optimization`, `good first issue`

## Context & Problem
When maintainer skills (such as `mkl-review-dependency`, `mkl-reproduce-bug`, and `mkl-review-source-change`) inspect third-party dependencies, reference libraries, or vendor code, an enormous portion (25% to 40%) of the consumed token budget is wasted on:
1. **Boilerplate License Headers**: 20–50 line copyright notices (Apache 2.0, MIT, GPL, BSD) duplicated at the top of every vendor source file.
2. **Verbose Docstrings**: Multi-paragraph Sphinx or Google-style docstrings restating parameter types and obvious return values.
3. **Inline Narrative & ASCII Art**: Extensive architectural commentary, ASCII architecture diagrams, and obsolete `# TODO` notes that provide no value for local bug reproduction or code review.

Naive stripping with regular expressions (`re.sub(r'#.*', '', text)`) is catastrophic for code analysis:
- It strips valid `#` characters inside string literals (e.g., URLs `"https://example.com#section"`, hex colors `"#FFFFFF"`, or regex character sets).
- It breaks code formatting and multi-line strings.
- It accidentally removes essential static analysis directives like `# type: ignore`, `# noqa`, or `# pragma: no cover`.

We need a syntax-aware, token-preserving code minifier `tools/strip_comments.py` that utilizes Python's built-in tokenizer to safely strip non-essential comments and docstrings while preserving syntax validity and critical linter directives, saving 25–40% of context tokens on reference code.

## Prior Art & Industry Standards
- **Repomix (`--remove-comments`)**: Multi-language code packaging tool that strips comments across codebases before packing them into LLM prompt contexts.
- **Aider (`repomap.py` / minification routines)**: AST-driven code minification to fit massive codebases into narrow LLM context windows.
- **Python `tokenize` and `ast` Standard Libraries**: Exact lexical token stream parsing and unparsing that guarantees syntactic fidelity.

## Proposed Solution
Create a lightweight, zero-dependency Python utility `tools/strip_comments.py`:
- Uses standard library `tokenize` and `io.StringIO` to process Python source code without AST loss or regex corruption.
- Safely strips:
  - Header license blocks.
  - Standard `#` inline and block comments.
  - Module, class, and function docstrings (configurable via `--strip-docstrings`).
  - Consecutive redundant blank lines (collapsing multiple empty lines into at most one).
- Preserves:
  - Compiler, type, and linter directives: `# type: ignore`, `# noqa`, `# pragma: no cover`, `# pylint:`, `# fmt: skip`.
  - String literals containing `#`.
  - Shebang lines (`#!/usr/bin/env python3`).
  - Code indentation and syntax validity (passes `ast.parse()` cleanly).

```bash
# Strip comments from a file and print to stdout
python3 tools/strip_comments.py --file vendor/requests/models.py

# Strip both comments and verbose docstrings
python3 tools/strip_comments.py --file vendor/urllib3/poolmanager.py --strip-docstrings

# Pipe mode: ideal for git show or shell pipelines
git show v2.31.0:src/core.py | python3 tools/strip_comments.py --pipe

# Report token savings breakdown in JSON format
python3 tools/strip_comments.py --file src/large_module.py --stats
```

### Architecture & Token Reduction Flow

```
[ Raw Python Source Code ] (1,000 lines / ~4,200 tokens)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│             tools/strip_comments.py                    │
├────────────────────────────────────────────────────────┤
│ 1. Lexical Tokenizer (`tokenize.generate_tokens`)      │
│    - Distinguishes COMMENT vs STRING tokens            │
│ 2. Directive Whitelist Filter:                         │
│    - Retains `# type: ignore`, `# noqa`, `# pragma:`   │
│ 3. AST / Token Docstring Recognizer:                   │
│    - Strips standalone docstrings (Expr -> Constant)   │
│ 4. Whitespace Normalizer:                              │
│    - Collapses consecutive blank lines                 │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
[ Minified Python Code ] (620 lines / ~2,600 tokens)
  -> 38% Token Reduction with 100% Syntactic Integrity!
```

### CLI Interface & Options
- `--file <path>`: Source Python file to minify.
- `--output <path>`: Write minified output to destination file (defaults to stdout).
- `--in-place`: Safely overwrite the target file in-place.
- `--pipe`: Read source code from `sys.stdin` and stream minified output to `sys.stdout`.
- `--strip-docstrings`: Strip class, function, and module docstrings in addition to comments.
- `--keep-directives`: Keep `# type: ignore`, `# noqa`, and `# pragma:` (default: enabled).
- `--stats`: Output a structured JSON or ASCII summary comparing original vs stripped lines, characters, and estimated tokens.

## Implementation Tasks
- [ ] Implement `tools/strip_comments.py` using Python's standard `tokenize` and `io` modules.
- [ ] Implement directive retention regex to preserve `# type: ignore`, `# noqa`, and `# pragma: no cover`.
- [ ] Implement docstring detection and removal while ensuring valid statement bodies (e.g. inserting `pass` if a function/class body only contained a docstring).
- [ ] Add blank line condensation to eliminate whitespace bloating.
- [ ] Implement `--stats` token reporting using `tiktoken` (if available) or standard character/word heuristic fallback.
- [ ] Add unit tests in `tests/test_strip_comments.py` testing:
  - Strings containing `#` characters.
  - Multi-line strings assigned to variables.
  - Functions containing only a docstring (ensuring replacement with `pass` so syntax remains valid).
  - Directive preservation.
  - Syntax verification via `ast.parse()` on minified code.
- [ ] Update `skills/mkl-review-dependency/SKILL.md` to recommend `strip_comments.py` before loading vendor libraries into agent context.

## Acceptance Criteria
- 100% standard library Python 3.11+ (no external dependencies required).
- All stripped code compiles cleanly with `ast.parse(minified_code)`.
- Reduces token footprint of heavily commented and documented reference files by at least 25–40%.
- Preserves all `# type: ignore`, `# noqa`, and `# pragma:` directives by default.
- Safely handles edge cases like functions consisting solely of a docstring without syntax errors.
- Unit test suite passes cleanly with `python3 -m unittest discover -s tests -v`.
