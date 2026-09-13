# Grok Bot recipes

These are setup instructions for **Grok Bot by Cursor**, separate from GroqCloud
and Grok Build. They are not a machine-importable Bot manifest.

| Recipe | First useful result |
| --- | --- |
| [Issue Scout](issue-scout.md) | Evidence-backed issue summary and missing information |
| [Release Reporter](release-reporter.md) | Release draft containing only changes in a specified range |

## Set up one recipe

1. Create a Bot in Grok Bot and paste the recipe's name, title, and profile.
2. Give it the first task using public or deliberately provided sample inputs.
3. Compare its result with the recipe's acceptance checks.
4. Once that run works, use the save-skill prompt and check that the skill is
   enabled for the Bot and visible in the `/` menu.
5. If wanted, create the proposed routine in Grok Bot, with your chosen scope
   and timezone. Keep it inactive until a manual run has passed.

Files installed for Cursor IDE do not automatically configure a cloud Bot.
Use the Bot's supported skill and routine controls. Public Bot templates are
another distribution option, but this preview does not include an imported-and-
verified public template. Test a copy on a separate account before advertising
such a template as working.

Status: **documented setup recipes; not yet tested in Grok Bot**.

Source: [Work with Grok Bot](https://cursor.com/docs/grok-bot/work), checked
2026-09-13. Product capabilities and UI can change.
