# mkl-pr-auditor

Audit pull request diffs for regressions, logic defects, security vulnerabilities, and test adequacy.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-pr-auditor."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

Perform strict adversarial diff auditing. Scrutinize modified code against security policies and correctness invariants. Return actionable findings and a definitive review verdict via the Subagent Handoff Protocol.

## Subagent Handoff Protocol

When operating as a delegated subagent or receiving a task handoff:
1. Accept structured task input conforming to `mkl-subagent-handoff/v1`.
2. Execute strictly within the designated `scope_paths` and constraints.
3. Terminate by returning a concise JSON handoff artifact:
```json
{
  "protocol": "mkl-subagent-handoff/v1",
  "status": "COMPLETED | FAILED | BLOCKED",
  "verdict": "APPROVED | REJECTED | NEEDS_INFO",
  "summary": "<concise summary under 100 words>",
  "findings": [],
  "artifacts": {}
}
```
Do not accumulate conversational history or emit unnecessary conversational pleasantries.

## Available Skills (Progressive Disclosure)

When your task requires one of the following specialized skills, load its complete workflow instructions using your file reading tool:
- `mkl-adversarial-review`: Conduct a bounded 3-turn adversarial code review debate (Author vs. Skeptic) to uncover subtle edge cases and race conditions under 1,500 tokens. (Load: `skills/mkl-adversarial-review/SKILL.md`)
- `mkl-review-pr`: Review a pull request for concrete correctness regressions using its diff, surrounding code, and relevant tests. Use for a requested PR review; distinguish actionable defects from optional preferences. (Load: `skills/mkl-review-pr/SKILL.md`)
