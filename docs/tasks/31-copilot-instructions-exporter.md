# [Feature] GitHub Copilot Workspace & Instructions Exporter (`.github/copilot-instructions.md`)

**Labels**: `enhancement`, `good first issue`

## Context & Motivation
GitHub Copilot natively supports project-level instructions via `.github/copilot-instructions.md`. When present, GitHub Copilot loads this file into every interaction across VS Code, JetBrains, and GitHub.com PR reviews.

Exporting our maintainer guidelines into `.github/copilot-instructions.md` enables teams using Copilot to enforce Maintainer Skills Lab quality standards automatically.

## Prior Art & Industry Standards
- **GitHub Copilot Custom Instructions Standard**: A single markdown file located in `.github/copilot-instructions.md` read by Copilot Chat and PR review agents.

## Proposed Solution
Add a `copilot` target to `tools/kit.py`:
- Compile selected core skills (PR review, regression test requirements, concise maintainer tone) into a compact, token-optimized `.github/copilot-instructions.md` (< 800 tokens total).

## Implementation Tasks
- [ ] Add `copilot` target to `tools/kit.py`.
- [ ] Implement consolidated instructions builder.
- [ ] Add unit tests in `tests/test_kit.py`.
- [ ] Document setup in `providers/README.md`.

## Acceptance Criteria
- Running `python3 tools/kit.py install --target copilot --project <dir>` generates a valid `.github/copilot-instructions.md`.
- All tests pass cleanly.
