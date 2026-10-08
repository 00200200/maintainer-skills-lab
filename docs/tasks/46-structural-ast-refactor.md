# [Feature] AST-Grep Structural Refactoring Integration (tools/structural_refactor.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Problem & Context
When AI agents perform wide-ranging refactorings across a codebase—such as updating deprecated API invocations, altering function signatures, standardizing error handling, or modernizing type annotations—current models are forced to rewrite each affected file individually. In projects where an API change impacts 20 to 50 files, this approach requires generating tens of thousands of output tokens, incurring massive API expenses and taking several minutes to complete.

Furthermore, naive alternatives like regex search-and-replace frequently fail on code due to multi-line function calls, varying whitespace, comments, and operator precedence subtleties. Generating 500 lines of Python code just to swap `logger.warn($$$ARGS)` for `logger.warning($$$ARGS)` across dozens of files represents an enormous waste of context window and generation budget.

## Prior Art & Industry Standards
- **ast-grep (`sg`) & Comby**: Structural search and rewrite tools that operate on Concrete Syntax Trees (CST) and Abstract Syntax Trees (AST). Instead of regular expressions or full file generation, developers define intuitive patterns with metavariables (e.g., `rule: pattern: $OBJ.fetch($URL, timeout=$T)` -> `rewrite: $OBJ.get($URL, timeout=$T)`). The engine searches and rewrites code deterministically across hundreds of files in milliseconds.
- **OpenRewrite**: Automated semantic refactoring engine that applies declarative rewrite recipes to modern enterprise codebases.
- **Aider Refactoring Workflows**: Explores concise search/replace pattern representations to minimize model output token generation.

## Proposed Solution
Build `tools/structural_refactor.py` to allow maintainer agents to specify concise AST rewrite rules (~10 to 30 tokens) that execute deterministically across the repository:

```bash
# Apply a structural rewrite pattern across the codebase
python3 tools/structural_refactor.py \
  --pattern "$LOGGER.warn($$$ARGS)" \
  --rewrite "$LOGGER.warning($$$ARGS)" \
  --path src/ \
  --lang python

# Dry-run preview generating a compact unified diff
python3 tools/structural_refactor.py \
  --pattern "assert $A == $B" \
  --rewrite "self.assertEqual($A, $B)" \
  --dry-run
```

### Architecture Details
1. **Dual-Engine Execution**:
   - **Native Engine**: If `ast-grep` (`sg`) is installed on the host system PATH, delegating to the native binary for lightning-fast, multi-language structural rewriting.
   - **Zero-Dependency Fallback Engine**: If `ast-grep` is not present, falls back to a pure Python AST transformer using standard library `ast` (with support for Python pattern matching and metavariables).
2. **Token Economy for Refactoring**:
   - Instead of emitting hundreds of lines of updated source code, the agent outputs a compact, structured rewrite spec (< 30 tokens):
     ```yaml
     structural_refactor:
       language: "python"
       pattern: "dict.get($KEY, None)"
       rewrite: "dict.get($KEY)"
       target_paths: ["src/maintainer_skills/"]
     ```
3. **Safety Verification & Diff Review**:
   - Validates that all transformed files compile cleanly (`python3 -m py_compile`) before persisting modifications to disk.
   - Outputs a unified diff summary with stats (`X files changed, Y insertions(+), Z deletions(-)`).
   - Supports `--dry-run` to allow the agent or human maintainer to inspect changes before committing.

## Implementation Tasks
- [ ] Implement `tools/structural_refactor.py` supporting CLI flags (`--pattern`, `--rewrite`, `--lang`, `--path`, `--dry-run`, `--json`).
- [ ] Implement detection and execution via `ast-grep` CLI when present in environment.
- [ ] Implement pure Python stdlib `ast` pattern matcher and rewriter fallback for basic method, call, and attribute transformations.
- [ ] Add pre-commit syntax validation ensuring transformed files compile without errors.
- [ ] Integrate structural refactoring guidance into `skills/mkl-review-pr/SKILL.md` and relevant maintainer agent profiles.
- [ ] Add unit tests in `tests/test_structural_refactor.py` validating pattern matching, metavariable bindings, dry-run diffs, and syntax validation.
- [ ] Document usage examples in `docs/tools/structural_refactor.md`.

## Acceptance Criteria
- Enables multi-file refactoring using under 30 output tokens from the calling agent.
- Seamlessly utilizes `ast-grep` when installed, with reliable stdlib `ast` fallback when absent.
- Automatically prevents syntax-breaking rewrites via built-in syntax compilation checks.
- Pure Python 3.11+ fallback works with zero external pip dependencies.
- All unit tests pass (`python3 -m unittest discover -s tests -v`).
