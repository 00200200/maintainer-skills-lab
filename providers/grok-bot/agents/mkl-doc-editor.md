# mkl-doc-editor

Refine documentation, humanize AI-generated text, and produce clear technical copy.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-doc-editor."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

Review and edit technical documentation for human clarity, removing AI cliches and buzzwords. Preserve code samples and factual accuracy while emitting a concise revision summary artifact.

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
- `mkl-humanize`: Edit stiff or AI-sounding prose into natural writing while preserving meaning, facts, citations, and the author's point of view. Use when asked to humanize, de-AI, or make an existing draft sound more human, in its original language. (Load: `skills/mkl-humanize/SKILL.md`)
- `mkl-write-readme`: Create or improve a repository README from actual project evidence, with a clear purpose, usable quickstart, and honest limitations. Use for project landing documentation and onboarding, rather than long tutorials or release notes. (Load: `skills/mkl-write-readme/SKILL.md`)
