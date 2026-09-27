# [CI/Check] Prompt Drift & Token Regression Detector in GitHub Actions

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
As contributors open Pull Requests to add features or refine instructions, individual skills often experience "token creep"—adding 50 tokens here, 100 tokens there. Over months, total library token size doubles, slowing down all users.

We need automated CI regression gates that flag any pull request that inflates token counts without corresponding new capability.

## Prior Art & Industry Standards
- **Bundlephobia / Size Limit**: Web development CI checks that fail if a JS bundle increases by more than 5%.
- **Promptfoo CI / Langfuse**: Detects prompt regression and token usage inflation on every PR commit.

## Proposed Solution
Add a GitHub Actions workflow `.github/workflows/token-regression.yml`:
1. Calculate total token count for base branch (`origin/main`).
2. Calculate total token count for PR branch (`HEAD`).
3. If any single modified skill increases token count by > 15%, or if total library tokens increase by > 5% without adding a new skill:
   - Post an automated comment on the PR showing a before/after token diff table.
   - Fail the CI check unless marked with an explicit override label (`token-increase-approved`).

## Implementation Tasks
- [ ] Add `tools/token_diff.py` to compare token footprints across two git refs.
- [ ] Create GitHub Action `.github/workflows/token-regression.yml`.
- [ ] Add PR comment generation with markdown comparison table.
- [ ] Test locally using git branches.

## Acceptance Criteria
- PRs introducing significant token inflation are automatically detected and commented on in GitHub Actions.
