# [Optimization] Smart Diff Chunking and AST-Aware Hunk Pruning in `skill_watch_mcp.py`

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
`MaintainerSkillsLab` includes an MCP (Model Context Protocol) server (`tools/skill_watch_mcp.py`) that monitors upstream framework documentation (PyTorch, TensorFlow, Lightning, Keras) for breaking changes and reports diffs to the LLM agent.

In `skill_watch_check(source_id)`:
```python
diff = source.get("diff", "")
source["diff_truncated"] = len(diff) > 12_000
source["diff"] = diff[:12_000]
```
This naive truncation:
1. Slices arbitrarily mid-sentence or mid-token at 12,000 characters (~3,000 tokens).
2. Transmits large blocks of unchanged context lines that provide zero information to the agent.
3. Often truncates the actual breaking change that occurred at the bottom of the document!

## Prior Art & Industry Standards
- **Aider Unified Diff Minimization**: Strips unchanged context lines down to 3 lines per hunk, discarding identical blocks to preserve token budget.
- **GitHub MCP Server**: Uses structured hunk boundaries and token-limited pagination rather than arbitrary string slicing.
- **Git Diff Compact**: Compresses whitespace changes and filters trivial renames.

## Proposed Solution
Enhance `tools/skill_watch.py` and `tools/skill_watch_mcp.py` with **Smart Diff Pruning**:
1. **Hunk Context Compaction**:
   - Limit unchanged context lines in unified diffs to 3 lines before and after changes.
   - Ignore formatting-only changes (trailing spaces, line-ending differences).
2. **Token-Aware Truncation**:
   - Allow the MCP client or caller to pass `max_tokens: int = 1500` (or character limit).
   - If truncation is necessary, truncate cleanly at hunk boundaries (`@@ ... @@`) with an explicit summary:
     `"[Truncated 4 additional change hunks; check baseline.json for complete diff]"`
3. **Structured Hunk Return**:
   - Provide clean hunk headers highlighting which sections (e.g. function or section headers) changed.

## Implementation Tasks
- [ ] Implement `prune_unified_diff(diff_text: str, context_lines: int = 3, max_chars: int = 8000) -> tuple[str, bool]` in `tools/skill_watch.py`.
- [ ] Ensure hunk boundaries (`@@ -a,b +c,d @@`) remain structurally valid.
- [ ] Add `max_tokens` / `max_chars` parameter to `skill_watch_check` in `tools/skill_watch_mcp.py`.
- [ ] Update tests in `tests/test_skill_watch.py` to verify hunk-preserving truncation and context line reduction.

## Acceptance Criteria
- `skill_watch_check` never cuts a diff mid-line or mid-hunk header.
- Unchanged lines in large diffs are compressed down to 3 context lines, reducing payload tokens by 40-70% on average diffs.
- Existing tests in `tests/test_skill_watch.py` pass without regression.
