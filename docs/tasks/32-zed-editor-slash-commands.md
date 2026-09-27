# [Feature] Zed Editor Slash Commands & Assistant Support (`.zed/`)

**Labels**: `enhancement`, `good first issue`

## Context & Motivation
Zed is a high-performance, Rust-built code editor rapidly gaining adoption among systems and backend developers. Zed features a built-in AI Assistant panel supporting custom slash commands and prompt templates in `.zed/prompts/`.

Adding support for Zed makes Maintainer Skills Lab available to developers seeking maximum editor speed and low latency.

## Prior Art & Industry Standards
- **Zed Assistant Prompts**: Markdown files placed in `.zed/prompts/*.md` accessible via `/` in the Zed Assistant panel.

## Proposed Solution
Add a `zed` target to `tools/kit.py`:
- Export all 17 skills into `.zed/prompts/mkl-<name>.md`.
- Ensure templates use Zed's native context placeholders (`/file`, `/tab`).

## Implementation Tasks
- [ ] Add `zed` target in `tools/kit.py`.
- [ ] Implement `.zed/prompts` generator.
- [ ] Update `providers/README.md`.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Running `python3 tools/kit.py install --target zed --project <dir>` generates working Zed prompt templates.
- Tests pass cleanly.
