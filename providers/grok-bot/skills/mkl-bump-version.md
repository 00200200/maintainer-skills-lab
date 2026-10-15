# mkl-bump-version

Evaluate conventional commits since latest tag, determine next SemVer, and surgically update version files.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-bump-version."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# SemVer Version Bump Evaluator

Evaluate conventional commits since the latest git tag, compute the next SemVer 2.0 version, and update repository version files.

## Workflow

1. **Preview Bump**: Run dry-run evaluation to preview the proposed bump:
   ```bash
   python3 tools/bump_version.py --dry-run
   ```
2. **Verify Breaking Changes**:
   - For `MAJOR` bumps, verify breaking changes are intentional before executing `--apply`.
   - Override unintended bumps using `--level <major|minor|patch>`.
3. **Apply Version Bump**:
   ```bash
   python3 tools/bump_version.py --apply
   ```
4. **Output Constraint**: Output a concise confirmation message and the git command to create the tag:
   ```bash
   git tag -a <tag> -m "Release <tag>"
   ```
   Keep output strictly under 100 tokens.
