# [Feature] Resilient Search/Replace Patch Applicator (tools/patch_applier.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Problem
Agentic coding models (such as Claude 3.7 Sonnet, GPT-4o, and DeepSeek-R1) generate code edits most token-efficiently using targeted `SEARCH/REPLACE` blocks rather than re-emitting entire source files. While full-file re-writes consume 2,000+ output tokens per edit, a `SEARCH/REPLACE` block often uses fewer than 150 tokens.

However, standard exact string replacement functions and naive patch utilities frequently fail due to minor whitespace and formatting discrepancies:
1. **Indentation Discrepancies**: Model outputs 2 spaces instead of 4 spaces, or tab/space mismatches.
2. **Line Ending / Trailing Whitespace**: Inconsistent carriage returns (`\r\n` vs `\n`) or invisible trailing spaces in the original file.
3. **Anchor Drift**: The model omits one unchanged line or has a minor casing variance in a surrounding context line.

When an exact match fails, the agent enters an expensive retry loop—burning 3,000 to 10,000 tokens across repeated attempts—or reverts to rewriting the entire file. MaintainerSkillsLab requires a resilient, standalone patch applicator that parses standard `SEARCH/REPLACE` blocks and applies them with fuzzy matching heuristics.

## Prior Art & Industry Standards
- **Aider `coder.apply_edits()`**: Industry benchmark for resilient search/replace editing. Utilizes a progressive 4-tier matching cascade (exact match, whitespace-normalized, relative indentation, and Levenshtein/difflib fuzzy matching with a confidence threshold > 0.85).
- **Mentat Edit Parser**: Parses unified search/replace markers with contextual line tolerance.
- **Git Patch (`git apply --ignore-whitespace --recount`)**: Git's built-in patch tolerance, but requires strict unified diff headers and line counts that LLMs frequently miscount.

## Proposed Solution
Create `tools/patch_applier.py`, a zero-dependency CLI tool and Python library for parsing and applying search/replace blocks with multi-tier fuzzy fallback.

```bash
# Apply a patch block to a target file
python3 tools/patch_applier.py apply --file path/to/file.py --patch patch.txt

# Dry-run validation without touching disk
python3 tools/patch_applier.py apply --file path/to/file.py --patch patch.txt --dry-run

# Process a stream of multiple search/replace blocks from agent stdout
cat agent_output.md | python3 tools/patch_applier.py stream --dry-run
```

### Search/Replace Block Format
Supports the universal format popularized by Aider and Claude Code:
```text
<<<<<<< SEARCH
def calculate_budget(used: int) -> int:
    return max(0, 1000 - used)
=======
def calculate_budget(used: int, limit: int = 2000) -> int:
    return max(0, limit - used)
>>>>>>> REPLACE
```

### Multi-Tier Matching Engine
1. **Tier 1 — Exact Match**:
   - Performs standard exact substring matching. If found uniquely, performs replacement immediately.
2. **Tier 2 — Whitespace & Line-Ending Normalization**:
   - Normalizes `\r\n` to `\n` across both search block and target content.
   - Trims trailing whitespace on all lines.
3. **Tier 3 — Relative Indentation Matching**:
   - Strips common leading indentation from the search block.
   - Finds matching lines regardless of base indentation level.
   - Re-applies the target file's indentation level to the replacement block when writing.
4. **Tier 4 — Fuzzy Sequence Matching**:
   - Uses Python's standard `difflib.SequenceMatcher` to find the highest-probability candidate block in the target file.
   - Rejects matches below a strict threshold (e.g., similarity < 0.85) to avoid erroneous replacements.
   - Detects ambiguity: If multiple blocks have identical or near-identical high similarity scores, halts with an explicit error to prevent corrupting the codebase.

## Implementation Tasks
- [ ] Implement `tools/patch_applier.py` with `SearchReplacePatch` parser and `apply_patch()` engine.
- [ ] Support standard format (`<<<<<<< SEARCH`, `=======`, `>>>>>>> REPLACE`) and Markdown block variants.
- [ ] Implement Tier 1 (exact), Tier 2 (whitespace normalized), and Tier 3 (relative indent) matchers.
- [ ] Implement Tier 4 fuzzy matching using `difflib.SequenceMatcher` with confidence threshold checking.
- [ ] Add ambiguity detection to prevent multiple matching blocks in the same file.
- [ ] Implement atomic file writing (write to temporary file, then atomic rename) and optional `.orig` backup creation.
- [ ] Add CLI commands: `apply`, `stream`, with `--file`, `--patch`, `--dry-run`, `--backup`, and `--json` flags.
- [ ] Add unit tests in `tests/test_patch_applier.py` covering exact match, CRLF variation, tab/space indent drift, fuzzy recovery, and ambiguous match rejection.
- [ ] Document utility in `README.md` and integrate with `skills/mkl-resolve-merge-conflict/SKILL.md`.

## Acceptance Criteria
- Successfully applies patches where target code has differing indentation or trailing whitespace that causes raw `str.replace()` to fail.
- Fails safely and returns non-zero exit code if match similarity is below 0.85 or if multiple identical blocks are found.
- Zero third-party dependencies (runs on standard library Python 3.11+).
- Unit test suite achieves 100% pass rate in `tests/test_patch_applier.py`.
