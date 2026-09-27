# [Feature] Continue.dev Slash Command & Prompt Generator (`.continue/prompts`)

**Labels**: `enhancement`, `good first issue`

## Context & Motivation
Continue (`continue.dev`) is the leading open-source AI code assistant for VS Code and JetBrains, with tens of thousands of active users. Continue supports custom **slash commands** and custom prompt templates located in `.continue/prompts/*.prompt`.

Providing native Continue.dev exports allows users to trigger maintainer skills instantly via `/reproduce`, `/review-pr`, `/humanize` in their IDE chat.

## Prior Art & Industry Standards
- **Continue.dev Prompt Format**: Single `.prompt` files containing Markdown template instructions with `{{{ input }}}` variable placeholders.

## Proposed Solution
Add a `continue` target in `tools/kit.py`:
- Compile each `skills/mkl-*/SKILL.md` into `.continue/prompts/<name>.prompt`.
- Format placeholders so users can simply type `/mkl-humanize` or `/mkl-reproduce` in Continue.

## Implementation Tasks
- [ ] Add `continue` target to `tools/kit.py`.
- [ ] Implement `.prompt` file generator with variable substitutions.
- [ ] Update `providers/README.md` and `docs/install.md`.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Running `python3 tools/kit.py install --target continue --project <dir>` generates valid `.continue/prompts/*.prompt` files.
- All unit tests pass.
