# mkl-generate-commit

Generate concise Conventional Commits under 50 tokens from staged git diffs.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-generate-commit."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

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
