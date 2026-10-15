---
name: "mkl-generate-commit"
description: "Generate concise Conventional Commits under 50 tokens from staged git diffs."
---

# Generate conventional commits

Generate concise, informative Conventional Commits (v1.0.0) from staged changes without conversational preamble or token waste.

## 1. Inspect Staged Changes Compactly

Assess the size and scope of changes before reading full diffs:

```bash
# Check modified files and diff scale
git diff --staged --stat

# Inspect targeted unified diff
git diff --staged
```

For large diffs (> 100 lines), focus on changed symbol definitions, tests, or modified interfaces (`git diff --staged -U1`) rather than dumping thousands of lines into context.

## 2. Conventional Commit Specification

Format the message strictly according to Conventional Commits:

```text
<type>(<scope>): <imperative summary under 72 characters>

- <Optional bullet point explaining why the change was made>
- <Optional bullet point highlighting key behavioral impact or issue reference>
```

### Type Taxonomy
- `feat`: A new user-visible or API capability.
- `fix`: A bug fix or defect correction.
- `docs`: Documentation changes only.
- `refactor`: Code change that neither fixes a bug nor adds a feature.
- `perf`: Code change that improves performance or latency.
- `test`: Adding or correcting tests without production code changes.
- `build`: Changes to build systems or external dependencies.
- `ci`: Changes to CI configuration files or scripts.
- `chore`: Routine maintenance, repo tooling, or housekeeping.

## 3. Output Constraints & Negative Guidance

- **No Conversational Chatter**: Emit ONLY the commit message text. Do not preface with "Here is your commit message:" or append "Let me know if you want changes."
- **Imperative Mood**: Use "add", "fix", "update", "refactor" (not "added", "fixes", "updating").
- **72-Character Subject Limit**: The summary line must be concise and must not end with a period.
- **Reference Issues**: When closing or addressing an issue, append `(closes #<id>)` or `(fixes #<id>)` to the subject or body.
