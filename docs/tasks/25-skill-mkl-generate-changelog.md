# [Feature] Automated PR Description & Changelog Generator with Strict Length Bounds

**Labels**: `enhancement`, `new skill`, `good first issue`

## Context & Motivation
When preparing pull requests and releases (`mkl-prepare-release`), maintainers spend significant time compiling commit histories, linking issues, and drafting release notes. Existing AI release generators frequently produce bloated, repetitive changelogs that list every chore commit without grouping features logically.

## Prior Art & Industry Standards
- **Google Release Please**: Categorizes commits automatically into Features, Bug Fixes, and Breaking Changes.
- **GitHub Automated Release Notes**: Generates concise markdown summaries based on merged PR titles and contributor handles.

## Proposed Solution
Create a new canonical skill `skills/mkl-generate-changelog/SKILL.md`:
- **Name**: `"mkl-generate-changelog"`
- **Description**: `"Generate grouped, token-compact changelogs and release notes from git log."`

### Workflow Specification
1. **Log Extraction**:
   - Run `git log <last-tag>..HEAD --oneline` to fetch only single-line commit summaries.
2. **Grouping & De-duplication**:
   - Group into: `🚀 Features`, `🐛 Bug Fixes`, `⚠️ Breaking Changes`, `🛠️ Maintenance`.
   - Squash repetitive fix commits into a single bullet.
3. **Budget Limit**:
   - Hard output cap of 400 words (< 500 tokens).

## Implementation Tasks
- [ ] Author `skills/mkl-generate-changelog/SKILL.md`.
- [ ] Include worked examples and strict negative formatting rules.
- [ ] Run `python3 tools/kit.py sync` to propagate across all clients.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Successfully groups 50+ one-line commits into a clean changelog under 500 tokens.
- All tests pass.
