# [New Skill] `mkl-bisect-regression` — Token-Efficient Git Bisect Automator

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Motivation
When a regression is discovered in a large project, naive AI agents attempt to inspect commit diffs across weeks of history, burning tens of thousands of tokens and hallucinating causes.

Experienced maintainers know that the fastest, zero-token way to find the breaking commit is **`git bisect run <test_script>`**.

## Prior Art & Industry Standards
- **Linux Kernel / Git Maintainer Practices**: Automating binary search across commits using minimal standalone shell test scripts.

## Proposed Solution
Create a new canonical skill `skills/mkl-bisect-regression/SKILL.md`:
- **Name**: `"mkl-bisect-regression"`
- **Description**: `"Pinpoint regressions using automated git bisect test scripts with zero prompt token waste."`

### Workflow Specification
1. **Minimal Test Script**:
   - Guide the agent to write a standalone `bisect_test.sh` that exits with code `0` on success and non-zero on failure.
2. **Automated Bisect Execution**:
   - Run `git bisect start <bad_commit> <good_commit>`.
   - Run `git bisect run ./bisect_test.sh`.
   - Notice: Git automatically checks out and runs tests locally without sending intermediate commit diffs to the LLM!
3. **Targeted Culprit Analysis**:
   - Once git identifies the exact commit hash, inspect **only** that commit's diff (`git show <commit_hash>`) to determine why the regression occurred.

## Implementation Tasks
- [ ] Author `skills/mkl-bisect-regression/SKILL.md`.
- [ ] Include worked examples and failure case handling (unbuildable intermediate commits with `exit 125`).
- [ ] Run `python3 tools/kit.py sync` across all clients.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Bisect workflow saves > 90% tokens compared to manual diff scanning.
- Skill teaches agents how to handle flaky tests and unbuildable commits.
