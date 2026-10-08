# [Feature] Zero-Dependency Local BM25 Symbol Search (tools/local_symbol_search.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Problem
When an AI coding agent navigates an unfamiliar codebase or investigates an issue, finding relevant functions, class declarations, and call sites currently forces the agent into two inefficient extremes:
1. **Unfiltered Grep / Ripgrep**: Running recursive regex searches outputs hundreds of noisy lines, false positives from comments/tests/strings, and consumes thousands of tokens per query.
2. **Full File Loading**: Reading entire 1,000+ line source files into the prompt just to inspect a single helper function, method signature, or dataclass definition.

Heavyweight vector database and embedding solutions (e.g. Chroma, FAISS, LangChain embeddings) require multi-hundred megabyte dependencies (PyTorch, numpy, API keys, or GPU acceleration) that violate MaintainerSkillsLab's lightweight, zero-dependency developer experience. Maintainers need an instant, local, deterministic lexical and symbol search engine that fits within tight token budgets.

## Prior Art & Industry Standards
- **Sourcegraph Cody / Sourcegraph FTS**: Uses BM25 lexical ranking combined with AST symbol extraction to power instant, token-efficient symbol navigation.
- **SQLite FTS5 (Full-Text Search 5)**: Built directly into the standard Python `sqlite3` module on macOS, Linux, and Windows. Provides native BM25 ranking (`bm25(symbol_fts)` function) and tokenized full-text search out of the box with zero third-party dependencies.
- **Aider Symbol Tag Indexer**: Extracts symbol definitions and references to produce bounded code outlines.

## Proposed Solution
Create `tools/local_symbol_search.py`, a zero-dependency Python tool utilizing Python's built-in `sqlite3` FTS5 module and standard library `ast` parser to index and rank repository symbols with BM25.

```bash
# Index the repository symbols into local cache (.msl/symbols.db or in-memory)
python3 tools/local_symbol_search.py index --project .

# Query symbols with BM25 ranking and limit token footprint
python3 tools/local_symbol_search.py query "token budget calculation" --limit 5

# Query specific symbol kind (def, class, method) in JSON format
python3 tools/local_symbol_search.py query "ContextBudgetGovernor" --kind class --json

# One-shot search without persisting disk database
python3 tools/local_symbol_search.py search "minify markdown" --project . --max-tokens 500
```

### Architecture & Indexing Schema
1. **AST Symbol Extractor**:
   - Parses Python files using Python's standard library `ast`.
   - Extracts:
     - Symbol name (`class`, `def`, `async def`)
     - Kind (`class`, `function`, `method`, `constant`)
     - Complete typed signature (parameters, return type annotations)
     - Docstring summary (first paragraph only)
     - Line span (`lineno`, `end_lineno`)
   - Includes regex-based fallback extractors for JavaScript/TypeScript, Go, and Rust files.

2. **SQLite FTS5 Storage Engine**:
   - Creates a virtual FTS5 table:
     ```sql
     CREATE VIRTUAL TABLE IF NOT EXISTS symbol_fts USING fts5(
         filepath,
         symbol_name,
         symbol_kind,
         signature,
         docstring,
         body_snippet,
         tokenize='unicode61'
     );
     ```
   - Queries apply BM25 weights prioritizing `symbol_name` (weight: 10.0), `signature` (5.0), `docstring` (2.0), and `body_snippet` (1.0).

3. **Token-Bounded Output Formatter**:
   - Formats matched symbols as compact Markdown code snippets or one-line index summaries:
     ```markdown
     ### tools/budget_allocator.py (Lines 42-68)
     class ContextBudgetGovernor:
         def __init__(self, model: str, used_tokens: int = 0) -> None: ...
         def get_tool_budget(self, tool_name: str) -> int: ...
     ```
   - Enforces `--max-tokens` strictly (default 600 tokens), truncating low-scoring results gracefully.

## Implementation Tasks
- [ ] Implement `tools/local_symbol_search.py` using `sqlite3` with `FTS5` extension.
- [ ] Implement symbol extractor using standard library `ast` for Python files (functions, classes, async functions, methods, docstrings).
- [ ] Implement regex-based symbol extractor for common non-Python languages (TS, JS, Go, Rust).
- [ ] Implement BM25 query rank scoring and column weighting via SQLite FTS5 `bm25()`.
- [ ] Add CLI commands: `index`, `query`, `search`, with `--project`, `--limit`, `--kind`, `--max-tokens`, and `--json`.
- [ ] Add automatic cache invalidation based on file modification timestamp (`mtime`) and SHA-256 hashes.
- [ ] Add unit tests in `tests/test_local_symbol_search.py` verifying symbol extraction, FTS5 queries, and token constraints.
- [ ] Document tool usage in `README.md` and integrate with `skills/mkl-review-pr/SKILL.md`.

## Acceptance Criteria
- Running `python3 tools/local_symbol_search.py search "parse_issue" --project .` returns the exact function signature and line number in `tools/publish_issues.py` in under 50ms.
- Runs on vanilla Python 3.11+ without any `pip install` or external vector database dependencies.
- `--max-tokens` strictly caps output volume under specified token threshold.
- All unit tests pass in `tests/test_local_symbol_search.py`.
