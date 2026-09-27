# [CI/Check] Add Token Budget Linter & Pre-commit Check for Skills and Agent Profiles

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
As new skills and agents are contributed, there is a natural tendency for instructions, explanations, and examples to expand. While clarity is important, bloated instructions quickly consume context limits in AI code editors like Cursor, Claude Code, and Codex.

Currently, `tools/kit.py check` checks syntax, YAML frontmatter, directory names, and description string lengths (character cap of 1,024). However, it does not enforce any **token budgets** on skills or agent definitions. A skill could pass CI while dumping 3,000 tokens of redundant verbiage into the user's agent session.

## Prior Art & Industry Standards
- **Cursor Rules**: Best practices recommend keeping `.cursorrules` under 500-800 tokens to prevent "context starvation" of the actual codebase.
- **Anthropic Model Context Protocol**: Recommends keeping tool definitions and skill descriptions ultra-lean (< 50 tokens) to minimize prompt overhead on every turn.
- **Ruff / ESLint**: Automated static analysis preventing bloat before code merges.

## Proposed Solution
Extend `tools/kit.py check` and `tools/check_staged.py` to enforce strict token budgets:
1. **Skill Description Budget**: Max 60 tokens (enforces concise, laser-focused tool descriptions).
2. **Skill Body Budget**:
   - Soft warning: > 600 tokens.
   - Hard error: > 1,000 tokens (requires justification or split into sub-skills).
3. **Agent Profile Budget**:
   - Instructions: Max 400 tokens.
   - Total expanded context (instructions + referenced skills): Max 3,000 tokens.
4. **Integration with Pre-Commit**:
   - Add a check in `tools/check_staged.py` so git commits fail locally if a staged skill exceeds token limits.

## Implementation Tasks
- [ ] Add configurable token budget constants to `tools/kit.py` (`MAX_DESCRIPTION_TOKENS = 60`, `MAX_SKILL_BODY_TOKENS = 1000`).
- [ ] Update `skill_metadata()` and `check_library()` in `tools/kit.py` to calculate tokens and report violations.
- [ ] Add a `--max-skill-tokens` flag to allow custom thresholds during testing.
- [ ] Update `tools/check_staged.py` to validate staged skills against the token budget before commit.
- [ ] Add tests in `tests/test_kit.py` and `tests/test_staged_hook.py` ensuring violations raise a `KitError` with a clear actionable message.
- [ ] Update `.github/workflows/ci.yml` so token checks run automatically on every pull request.

## Acceptance Criteria
- Staging a skill with a 1,200-token body fails `python3 tools/kit.py check` with an informative error message: `error: skills/mkl-example/SKILL.md exceeds body token budget (1200 > 1000 tokens). Consider condensing instructions or splitting into focused workflows.`
- All current 17 skills pass the initial budget threshold (or are adjusted if marginally over).
- Running `python3 -m unittest discover -s tests -v` passes cleanly.
