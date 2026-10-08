<!-- Attach context with /file or /tab in the Zed Assistant panel. -->

# mkl-generate-changelog

Generate grouped, token-compact changelogs and release notes from git log.

# Generate Grouped, Token-Compact Changelog

Extract revision history and synthesize human-readable release notes grouped by impact.
Preserve user-facing significance while pruning commit noise, internal churn, and redundant entries.

## 1. Log Extraction

1. Identify the baseline tag or revision range (for example `v1.2.0..HEAD` or `<last-tag>..HEAD`).
2. Run single-line log extraction to conserve token context:
   ```bash
   git log <last-tag>..HEAD --oneline --no-merges
   ```
3. Never dump full commit diffs (`git log -p`) or raw merge commit lists into the prompt context.

## 2. Categorization & Grouping

Group extracted commits into standard semantic sections:

- **⚠️ Breaking Changes**: API removals, signature changes, altered defaults, or required migration steps.
- **🚀 Features**: New capabilities, commands, CLI flags, or public user-facing interfaces.
- **🐛 Bug Fixes**: Repaired defects, edge-case fixes, and crash prevention.
- **🛠️ Maintenance**: Performance optimizations, documentation updates, dependency bumps, and tooling.

## 3. De-duplication & Synthesis Rules

1. **Squash Repetitive Commits**: Combine related trial-and-error commits (e.g., multiple "fix typo", "fix linter", "fix CI") into a single concise bullet.
2. **Prune Bot Noise**: Aggregate automated dependency bumps (Dependabot, Renovate) into one summary line:
   - `- Bump dev dependencies: pytest, ruff, hatchling`
3. **Reference Issues & PRs**: Retain PR or issue references (e.g., `(#42)`) when present in the commit title.
4. **Active Voice**: Write bullets in clear, active imperative form ("Add...", "Fix...", "Support...").

## 4. Strict Negative Formatting Constraints

- **No full SHAs**: Never include 40-character Git commit hashes in release bullet items.
- **No churn dumping**: Do not list internal branch syncs, merge commits, or redundant formatting commits.
- **Hard Word Budget**: The generated changelog must not exceed 400 words (< 500 tokens total).

---

## Worked Example

### Raw Git Log Input (Sample):
```text
a1b2c3d feat(auth): add OAuth2 PKCE authorization flow (#101)
e4f5a6b fix(auth): handle token expiration in refresh loop (#102)
c7d8e9f fix(auth): null check on missing refresh token
b1c2d3e fix: fix lint errors in auth
f4a5b6c feat(cli): add --json output flag to inspect command (#103)
d7e8f9a chore(deps): bump ruff from 0.8.0 to 0.9.0
e1a2b3c chore(deps): bump pytest from 8.2 to 8.3
c4d5e6f feat(api)!: remove deprecated v1 legacy auth endpoint (#104)
```

### Compact Generated Changelog (< 120 words):

```markdown
## Release Notes (v1.3.0)

### ⚠️ Breaking Changes
- Remove deprecated `/v1/auth` legacy authentication endpoint (`#104`). Use `/v2/auth` with PKCE instead.

### 🚀 Features
- Add OAuth2 PKCE authorization flow (`#101`).
- Add `--json` structured output flag to `inspect` CLI command (`#103`).

### 🐛 Bug Fixes
- Fix token refresh loop handling on expiration and prevent null reference on missing tokens (`#102`).

### 🛠️ Maintenance
- Bump developer dependencies (`ruff`, `pytest`).
```
