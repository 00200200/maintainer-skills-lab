# Compatibility and evidence

This preview targets project-local installation. The following are distinct:

1. **Source and export checks:** metadata, dependencies, and serialization.
2. **Tool and fixture tests:** filesystem behavior and the included regression example.
3. **Live-client evaluation:** discovery, invocation, and task outcomes in an actual client.

Passing the first two does not establish the third.

The writing catalogue includes authored worked examples and manual acceptance
scenarios. Export and installation checks cover those skills as files, including
Polish text in the embedded writing agent. No writing-quality benchmark or
independent live-client evaluation is claimed.

| Surface | Format | Current evidence | Live-client status |
| --- | --- | --- | --- |
| Codex skills | `SKILL.md` under `.agents/skills/` | Export and installer tests | Not yet evaluated |
| Codex agents | Standalone `.codex/agents/*.toml` | TOML parsing and embedded-workflow tests | Not yet evaluated |
| Claude Code | `.claude/skills/` and YAML-frontmatter agent Markdown | Export and installer tests | Not yet evaluated |
| Cursor | `.cursor/skills/` and YAML-frontmatter agent Markdown | Export and installer tests | Not yet evaluated |
| Grok Bot | Role, first-task, save-skill, and routine instructions | Setup recipes based on documentation | Not yet evaluated; no verified share template |

The suite runs locally without API keys. CI targets Linux and macOS on Python
3.11 and 3.13. Windows has not been tested; do not infer support from Python
compatibility alone.

## Known limits

- Multiple clients can discover files in each other's directories. Start with a
  single installation target per project. Installing several bundles into the
  same project may expose duplicate names; mixed-client discovery remains untested.
- Source skills use only `name` and `description` as single-line, double-quoted
  YAML strings. The repository checker validates this subset, not all Agent
  Skills syntax. Native agents are generated from TOML source definitions.
- Agent descriptions and instructions guide behavior. The exports do not add
  permission grants, force a model, or claim to impose a cross-client sandbox.
- A Grok Bot configuration is distinct from a Cursor IDE subagent. Follow the
  supported Bot UI rather than assuming local files create cloud resources.
- No marketplace plugin or general ChatGPT/Claude web-chat compatibility is
  claimed by this local-file release.

## Primary format references

Checked 2026-09-13; these are documentation references, not live-run evidence:

- [Agent Skills specification](https://agentskills.io/specification)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Cursor skills](https://cursor.com/docs/skills)
- [Cursor subagents](https://cursor.com/docs/subagents)
- [Grok Bot workflows](https://cursor.com/docs/grok-bot/work)
