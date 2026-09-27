# [Feature] Two-Tier "Progressive Disclosure" (Lazy Loading) for Skills in Agent Profiles

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Currently, when an agent profile (e.g. `mkl-source-reviewer`, `mkl-bug-investigator`) is loaded, `tools/kit.py` embeds the entire Markdown text of all dependent skills into the agent file.

For agents depending on 3-5 skills, this dumps 3,000 to 6,000 tokens into the prompt on every session startup, even if the user only asks a simple question that uses just one skill (or none at all). This leads to:
- Excessive token usage and higher inference costs.
- Model distraction (instruction crowding / prompt dilution).
- Context window exhaustion on smaller models.

## Prior Art & Industry Standards
- **Anthropic Model Context Protocol (MCP)**: Supports dynamic tool discovery where the model sees only tool names and descriptions, loading schemas and calling tools dynamically.
- **ChatGPT Custom Actions / OpenAI Function Calling**: Only the OpenAPI summary is present in the system prompt; endpoints are fetched when needed.
- **Cursor Semantic Rules**: Matches rules based on file globs or intent triggers rather than dumping all rules into every prompt.

## Proposed Solution
Introduce a two-tier **Progressive Disclosure (Lazy Loading)** mode in `tools/kit.py`:
1. **Tier 1 (Index / Trigger Manifest)**:
   - The agent's prompt contains only a compact table or list of available skills with their single-line `description` and trigger keyword (< 40 tokens per skill).
   - E.g.:
     ```markdown
     Available Maintainer Skills:
     - `mkl-reproduce-bug`: Reproduce a bug with minimal isolated script. (Run: `cat .claude/skills/mkl-reproduce-bug/SKILL.md`)
     - `mkl-review-pr`: Catch logic errors and security regressions in PRs. (Run: `cat .claude/skills/mkl-review-pr/SKILL.md`)
     ```
2. **Tier 2 (Full Execution Workflow)**:
   - When the agent identifies that a task requires a specific skill, it reads the skill file on-demand using its native file-reading tool (or MCP tool).
3. **CLI Support**:
   - `python3 tools/kit.py sync --mode full` (default, backward-compatible).
   - `python3 tools/kit.py sync --mode lazy` (progressive disclosure).

## Implementation Tasks
- [ ] Add `--mode {full,lazy}` flag to `kit.py sync` and `kit.py build`.
- [ ] Implement lazy agent template rendering: generate skill index summaries with on-demand read instructions instead of inlined markdown bodies.
- [ ] Ensure skills are installed to the client directory (`.claude/skills/`, `.cursor/skills/`) so the agent can read them via standard tools.
- [ ] Add unit tests in `tests/test_kit.py` testing both `full` and `lazy` sync modes.
- [ ] Benchmark token savings between `full` and `lazy` mode on `mkl-source-reviewer` (target: 65%+ reduction in initial prompt tokens).

## Acceptance Criteria
- Running `python3 tools/kit.py sync --mode lazy` generates compact agent profiles with token savings of > 60% on initial prompt injection.
- Agent instructions provide clear guidance on how the agent reads the full skill when triggered.
- All existing tests pass.
