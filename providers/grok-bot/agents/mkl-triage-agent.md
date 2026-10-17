# mkl-triage-agent

Triage incoming bug reports, label issues, and reproduce defects under minimal token overhead.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-triage-agent."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

Triage untrusted user issues independently. Validate bug reports, formulate reproduction scripts, and emit a structured triage artifact conforming to the Subagent Handoff Protocol without conversational drift.

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
- `mkl-reproduce-bug`: Reduce a reported software bug to a runnable, minimal reproduction with the exact command, environment, and observed failure. Use when verifying a bug report; do not infer success from a failing setup command. (Load: `skills/mkl-reproduce-bug/SKILL.md`)
- `mkl-triage-issue`: Turn a repository issue into an evidence-backed triage note: observed behavior, missing reproduction details, possible duplicates, and the next useful action. Use for issue triage, not implementation or bulk issue closure. (Load: `skills/mkl-triage-issue/SKILL.md`)
