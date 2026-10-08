# [Automation] Token-Budget Contributor Onboarding Action (.github/workflows/onboarding.yml)

**Labels**: `enhancement`, `dx`, `good first issue`

## Context & Problem
Maintainer Skills Lab is an open-source framework dedicated to token-efficient AI software engineering. New contributors contributing skills, agent profiles, or tools frequently miss key maintainer standards:
1. **Unchecked Token Bloat**: Adding verbose Markdown sections or lengthy examples that push skill files past the 800-token limit or descriptions beyond 60 tokens.
2. **Missing Client Sync**: Modifying canonical skill files in `skills/*/SKILL.md` but forgetting to run `python3 tools/kit.py sync` to regenerate target exports in `.claude/`, `.cursor/`, and `.codex/`.
3. **Skipping Pre-PR Token Benchmarking**: Opening pull requests without running `python3 tools/kit.py tokens` to benchmark context consumption.

Because there is no automated welcoming and onboarding bot on PR creation, maintainers must repeatedly write the same manual review comments, leading to slower review cycles and friction for first-time contributors.

## Prior Art & Industry Standards
- **Probot / Welcome Action**: Standard GitHub automation for welcoming first-time contributors and providing essential repository orientation.
- **Kubernetes / CNCF Prow & Welcome Automation**: Automatically comments on new PRs with verification checklists and automated test guidelines.
- **Astral (Ruff / uv) PR Bots**: Provides instant, friendly contributor onboarding guidance detailing required pre-commit hooks and local linting commands.

## Proposed Solution
Create `.github/workflows/onboarding.yml`, an automated GitHub Actions workflow using `actions/github-script@v7` that automatically detects first-time contributors and posts an actionable, friendly onboarding guide.

### Trigger & Workflow Behavior
1. **Trigger Condition**:
   - `pull_request_target: types: [opened]`
   - Ignores automated bot accounts (e.g. `dependabot[bot]`, `renovate[bot]`, `github-actions[bot]`).
   - Checks `payload.pull_request.author_association`: triggers when author is `FIRST_TIME_CONTRIBUTOR` or `FIRST_TIMER`.

2. **Onboarding Message Template**:
   ```markdown
   👋 Welcome @${author} to **Maintainer Skills Lab**! Thank you for your contribution.

   Maintainer Skills Lab is built around **strict token budgeting and minimal context footprints**. To ensure your PR gets reviewed and merged quickly, please complete this quick checklist:

   ### 🛠️ Pre-Review Contributor Checklist
   - [ ] **Validate Schemas & Lints**:
     ```bash
     python3 tools/kit.py check
     ```
   - [ ] **Audit Token Budget**:
     ```bash
     python3 tools/kit.py tokens
     ```
     *Rule: Skills must stay under 800 tokens; skill descriptions must stay under 60 tokens.*
   - [ ] **Synchronize Client Exporters**:
     ```bash
     python3 tools/kit.py sync
     ```
     *Ensure generated client exports in `.claude/`, `.cursor/`, and `.codex/` are committed.*
   - [ ] **Run Unit Tests**:
     ```bash
     python3 -m unittest discover -s tests -v
     ```

   ### 📚 Helpful Resources
   - 📖 [Contributing Guide](CONTRIBUTING.md)
   - 🎯 [Contributor Task Catalog & SOTA Roadmap](docs/tasks/INDEX.md)
   - 💡 Looking for your next issue? Check out our [`good first issue`](https://github.com/maintainerskillslab/maintainer-skills-lab/labels/good%20first%20issue) label.
   ```

3. **Idempotence & Safety**:
   - Inspects existing issue comments before posting to prevent duplicate comments on re-opened or re-triggered workflows.
   - Minimal required permissions (`pull-requests: write`, `issues: write`).

## Implementation Tasks
- [ ] Create `.github/workflows/onboarding.yml` with secure `pull_request_target` configuration.
- [ ] Implement author association check and bot filter using `actions/github-script@v7`.
- [ ] Implement duplicate comment detection to ensure idempotence.
- [ ] Format onboarding comment markdown with clear copy-pasteable commands and token rules.
- [ ] Add YAML workflow linting / validation tests in `tests/test_ci_workflows.py`.
- [ ] Update `CONTRIBUTING.md` mentioning the onboarding bot and contributor checklist.

## Acceptance Criteria
- Workflow triggers automatically when a first-time contributor opens a pull request.
- Bot posts exactly one formatted welcome comment containing the token verification commands (`kit.py check`, `kit.py tokens`, `kit.py sync`).
- Bot ignores automated dependency bots (`dependabot`, `renovate`).
- Does not comment on subsequent pull requests from returning contributors.
- Workflow file passes GitHub Actions schema linting.
