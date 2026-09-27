# [Feature] Scoped AST Code Extractor Tool for Code Review Skills (`tools/scope_extract.py`)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Skills such as `mkl-review-pr`, `mkl-review-source-change`, and `mkl-reproduce-bug` instruct agents to inspect code files when evaluating patches. In practice, agents often call `read_file` or `cat` on the entire file (frequently 500 to 2,000 lines long), even when the PR only modified a 5-line method!

Reading whole files burns thousands of unnecessary context tokens, clouds the model's attention with irrelevant implementation details, and increases the likelihood of hallucinated critique.

## Prior Art & Industry Standards
- **Aider (`repomap.py`)**: Uses Tree-sitter AST queries to extract only top-level class signatures, method definitions, and docstrings, omitting implementation bodies to fit huge codebases into small token windows.
- **Sourcegraph Cody**: AST-aware symbol indexing that fetches only enclosing scope.
- **GitHub Copilot**: Context selection based on local method scope.

## Proposed Solution
Create a lightweight, zero-dependency Python utility `tools/scope_extract.py` (and an accompanying helper for workflows):
1. **AST Extraction**:
   - Uses Python's built-in `ast` module.
   - Parses Python files and extracts:
     - Class declarations, base classes, and class docstrings.
     - Function/method signatures, parameter type annotations, and return types.
     - Line ranges for each definition.
2. **Diff-Scoped Extraction**:
   - Given a file path and a list of modified line numbers (or a git diff), extract **only** the enclosing class or function body for the affected lines, plus signatures of surrounding sibling methods for context.
   - Replaces a 1,500-line file dump with an 80-line targeted snippet (saving ~90% of tokens).
3. **Skill Workflow Integration**:
   - Update `skills/mkl-review-pr/SKILL.md` and `skills/mkl-review-source-change/SKILL.md` to instruct agents to use scoped extraction when inspecting large files.

## Implementation Tasks
- [ ] Create `tools/scope_extract.py` using standard library `ast`.
- [ ] Support CLI flags:
  - `python3 tools/scope_extract.py --file <path> --outline` (signatures only)
  - `python3 tools/scope_extract.py --file <path> --lines <start>-<end>` (enclosing scope)
- [ ] Add unit tests in `tests/test_scope_extract.py` covering nested classes, async functions, decorators, and syntax errors.
- [ ] Update `mkl-review-pr` and `mkl-review-source-change` instructions and worked examples to showcase scoped inspection.

## Acceptance Criteria
- Running `scope_extract.py --outline` on a 1,000-line Python file outputs signatures and docstrings under 150 lines (< 600 tokens).
- Pure standard library Python 3.11+ (no external dependencies required).
- Comprehensive test coverage in `tests/test_scope_extract.py`.
