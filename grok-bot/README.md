# Grok Bot workflows

Set up maintainer and writing workflows in **Grok Bot (SpaceXAI)**, using the
[official x.ai guide](https://docs.x.ai/grok-bot/overview).
These are human-readable instructions for the Bot app.

Every library skill and agent has a generated Markdown recipe in the
[provider catalogue](https://github.com/00200200/maintainer-skills-lab/tree/main/providers). From the repository root,
open `providers/grok-bot/skills/` or `providers/grok-bot/agents/` to pick one.
The archive includes those directories alongside this guide.

For a complete first task and an optional recurring routine, use:

| Recipe | First useful result |
| --- | --- |
| [Issue Scout](issue-scout.md) | Evidence-backed issue summary and missing information |
| [Release Reporter](release-reporter.md) | Release draft containing only changes in a specified range |

## Set up a workflow

1. Create a Bot with the intended name, job, and description, or open an existing Bot.
2. Give it the workflow and a concrete first task with the necessary input and access.
3. Compare the actual result with the workflow's acceptance checks.
4. Once it works, ask the Bot to save the validated method as a named skill.
5. In **Settings → Plugins → Yours**, check that the skill is enabled for this Bot.
   Invoke saved skills from the `/` menu.
6. If useful, ask the Bot to create a routine with an explicit owner, schedule,
   timezone, input, output, and approval boundary. Test before enabling recurrence.

An agent recipe embeds its dependent skill instructions. It does not automatically
create a Bot, connect an account, or grant access. Supply any referenced supporting
files from the canonical source when giving the Bot its task. Cursor IDE exports
are a separate installation surface.

Status: **source/export checks only; no live Grok Bot evaluation recorded**.

References, checked 2026-09-13:
[Get started](https://docs.x.ai/grok-bot/get-started) ·
[Skills, routines, and automations](https://docs.x.ai/grok-bot/skills-routines-and-automations).
