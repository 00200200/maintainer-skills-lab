# [Feature] Token-Budgeted Conventional Commit Message Generator (`mkl-generate-commit`)

**Labels**: `enhancement`, `new skill`, `good first issue`

## Context & Motivation
Writing consistent, informative Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`) is essential for maintainers, changelog generators, and semantic versioning. However, existing commit message generators either:
- Dump the entire multi-thousand-line staged git diff into LLM prompts.
- Produce verbose, multi-paragraph messages loaded with conversational fluff.

## Prior Art & Industry Standards
- **Aider Commit Message Generator**: Runs `git diff --staged --stat` first, inspects only changed function signatures for large diffs, and enforces a strict 1-line summary plus bulleted list under 100 tokens.
- **Conventional Commits v1.0.0 Specification**.

## Proposed Solution
Create a new canonical skill `skills/mkl-generate-commit/SKILL.md`:
- **Name**: `"mkl-generate-commit"`
- **Description**: `"Generate concise Conventional Commits under 50 tokens from staged git diffs."`

### Workflow Specification
1. **Diff Pre-Filtering**:
   - Check `git diff --staged --stat` to evaluate diff magnitude.
   - For small diffs (< 100 lines), inspect unified diff directly.
   - For large diffs, inspect only modified file names and changed symbols, preventing prompt overflow.
2. **Strict Output Format**:
   - Subject: `<type>(<scope>): <concise description under 72 chars>`
   - Body: Max 3-5 bullet points explaining *why* the change was made, not just restating the diff.
   - Output Budget: Max 60 words (< 80 tokens).
3. **No Conversational Preamble**:
   - The model must output *only* the commit message block, ready for `git commit -F`.

## Implementation Tasks
- [ ] Author `skills/mkl-generate-commit/SKILL.md`.
- [ ] Include worked examples and strict negative constraints (no preamble, no emojis unless requested).
- [ ] Run `python3 tools/kit.py sync` to generate provider files.
- [ ] Add tests in `tests/test_kit.py`.

## Acceptance Criteria
- Skill reliably produces clean Conventional Commits conforming to the 72-char line limit.
- Output contains zero conversational chatter.
