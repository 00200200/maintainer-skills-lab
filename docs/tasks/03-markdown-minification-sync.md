# [Optimization] Automated Markdown Minification & Whitespace Trimming (`kit.py sync --minify`)

**Labels**: `enhancement`, `optimization`, `good first issue`

## Context & Motivation
When `tools/kit.py sync` generates provider files for `.claude/skills`, `.cursor/skills`, `.codex/agents`, and `grok-bot/`, it copies Markdown bodies largely as written.

While human maintainers appreciate extra blank lines, elaborate horizontal separators (`---`), aligned table formatting with extensive whitespace padding, and verbose commentary, **LLMs consume tokens for every byte of whitespace and formatting syntax**. Across 17 skills and 6 agents, unminified markdown wastes 15% to 25% of the input tokens injected into model system prompts.

## Prior Art & Industry Standards
- **Repomix (`--compress`)**: Strips empty lines, trims superfluous markdown spacing, and compresses syntax while preserving semantic meaning for LLMs.
- **LLMLingua**: Removes non-essential tokens while preserving task prompt intent.
- **Minified System Prompts**: Industry agent systems strip human-targeted formatting in production prompt templates.

## Proposed Solution
Add a `--minify` flag to `tools/kit.py sync` and `tools/kit.py build`:
```bash
python3 tools/kit.py sync --minify
```

### Minification Rules (Safe for Markdown & Code)
1. **Whitespace Normalization**:
   - Collapse 3+ consecutive newlines down to 2 (`\n\n`).
   - Strip trailing spaces from all lines (except inside fenced code blocks where indentation matters).
2. **Table Compaction**:
   - Remove extra padding spaces inside markdown table cells (e.g. `|  Cell 1   |   Cell 2   |` → `| Cell 1 | Cell 2 |`).
3. **Comment Stripping**:
   - Strip HTML comments (`<!-- ... -->`) from exported markdown files, as they are maintainer notes never needed by models.
4. **Header and List Compaction**:
   - Normalize list indentation to standard 2-space markdown.

## Implementation Tasks
- [ ] Implement `minify_markdown(text: str) -> str` in `tools/kit.py`.
- [ ] Ensure fenced code blocks (` ```...``` `) are preserved verbatim without altering internal code indentation or whitespace.
- [ ] Add the `--minify` flag to `sync` and `build` subcommands in `tools/kit.py`.
- [ ] Ensure `python3 tools/kit.py sync --minify --check` can verify minified state.
- [ ] Add comprehensive unit tests in `tests/test_kit.py` verifying that:
  - Fenced code indentation is untouched.
  - HTML comments are removed.
  - Multi-line whitespace is compressed.
  - Semantic content and headers remain identical.

## Acceptance Criteria
- Minifying exported files achieves a 10-25% reduction in total byte/token size across the exported provider directories.
- Code blocks inside skills remain completely functional and unaffected.
- Running `python3 -m unittest discover -s tests -v` passes.
