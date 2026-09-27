# [Feature] Add Token Profiler CLI command (`kit.py tokens`) to benchmark skill and agent context consumption

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Currently, Maintainer Skills Lab contains 17 specialized skills and 6 agent profiles. When developers install these skills into client environments (Claude Code, Cursor, Codex, OpenCode, Grok Bot), they inject hundreds or thousands of tokens directly into the LLM context window.

However, maintainers and contributors currently have **no visibility into the exact token footprint** of each skill, agent profile, or client bundle. Without automated token profiling, verbose contributions can silently bloat context windows, reduce effective model reasoning capacity, and drastically increase API costs for end users.

## Prior Art & Industry Standards
- **Repomix**: Provides instant token counts using `tiktoken` (`cl100k_base` and `o200k_base`), giving users immediate feedback on context packing.
- **Aider**: Measures and displays exact token footprints for repository maps, system prompts, and conversation turns.
- **Promptfoo**: Provides token cost and latency benchmarking across models.

## Proposed Solution
Add a new `tokens` command to `tools/kit.py`:
```bash
# Profile all skills and agents using standard tokenization
python3 tools/kit.py tokens

# Filter by target client export
python3 tools/kit.py tokens --target claude

# Output structured JSON for CI and automated tooling
python3 tools/kit.py tokens --json
```

### Architecture Details
1. **Tokenizer Strategy**:
   - Provide zero-dependency estimation by default (e.g., standard ~4 chars/token or word-ratio heuristic) so the command works in vanilla Python 3.11+.
   - If `tiktoken` is installed in the environment (`import tiktoken`), use exact BPE encodings:
     - `cl100k_base` (Claude 3.x / GPT-4)
     - `o200k_base` (GPT-4o)
2. **Analysis Breakdown**:
   - Skill body token count
   - Skill description token count (crucial for system prompts and tool manifests)
   - Agent profile aggregated token count (instructions + referenced skills)
   - Client export bundle totals (`.claude/`, `.cursor/`, `.codex/`)
3. **Threshold Warnings**:
   - Highlight any skill exceeding 800 tokens.
   - Highlight any skill description exceeding 60 tokens.

## Implementation Tasks
- [ ] Add `tokens_subcommand(parser)` to `tools/kit.py`.
- [ ] Implement `count_tokens(text: str, encoding: str = "cl100k_base") -> int` with graceful fallback if `tiktoken` is absent.
- [ ] Implement table formatting (clean ASCII table using standard library `string.format` or `str.ljust`).
- [ ] Support `--json` flag for machine-readable output.
- [ ] Add unit tests in `tests/test_kit.py` covering token counting, threshold warnings, and JSON output format.
- [ ] Update `README.md` and `docs/install.md` with usage instructions.

## Acceptance Criteria
- `python3 tools/kit.py tokens` runs without external dependencies on Python 3.11+.
- If `tiktoken` is installed, it calculates accurate BPE token counts.
- `python3 tools/kit.py tokens --json` outputs valid JSON with a `skills`, `agents`, and `targets` hierarchy.
- All existing tests continue to pass (`python3 -m unittest discover -s tests -v`).
