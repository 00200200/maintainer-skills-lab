# [Docs/DX] Add Contributor Guide for Token Optimization & Issue Templates

**Labels**: `documentation`, `good first issue`

## Context & Motivation
Contributors looking to propose new skills, optimize existing agent profiles, or improve tooling need clear guidance on:
1. What "token efficiency" means for Maintainer Skills Lab.
2. How to measure token footprints before submitting a Pull Request.
3. How to submit a structured token optimization proposal.

Currently, `CONTRIBUTING.md` only explains syntax formatting, syncing, and unit testing. There is no guidance on measuring token impact or avoiding prompt bloat.

## Prior Art & Industry Standards
- **HuggingFace / LangChain / FastAPI**: Dedicated contribution guidelines for performance and benchmarking.
- **GitHub Issue Forms (`.github/ISSUE_TEMPLATE/*.yml`)**: Structured templates asking contributors for before/after token metrics and reproduction commands.

## Proposed Solution
1. **New Issue Template**: Add `.github/ISSUE_TEMPLATE/optimization.yml` tailored for token, cost, and latency optimization proposals.
2. **Dedicated Optimization Section in `CONTRIBUTING.md`**:
   - Guidelines for keeping skill descriptions under 60 tokens.
   - Guidelines for concise, action-oriented instructions without polite conversational boilerplate.
   - How to run `python3 tools/kit.py tokens` (once added) or estimate tokens before opening a PR.
3. **Task Gallery Link**:
   - Point contributors to open issues tagged `help wanted` and `good first issue`.

## Implementation Tasks
- [ ] Create `.github/ISSUE_TEMPLATE/optimization.yml` with structured fields for:
  - Target skill / agent / tool
  - Current token usage / problem
  - Proposed optimization / design
  - Before/After token comparison
- [ ] Add "Writing Token-Efficient Skills" section to `CONTRIBUTING.md`.
- [ ] Add links to issue templates in `CONTRIBUTING.md` and `README.md`.
- [ ] Verify that GitHub issue template syntax is valid YAML.

## Acceptance Criteria
- `.github/ISSUE_TEMPLATE/optimization.yml` renders properly in GitHub's new issue interface.
- `CONTRIBUTING.md` provides clear, measurable advice on token budgets.
- All repository check commands (`python3 tools/kit.py check`) continue to pass.
