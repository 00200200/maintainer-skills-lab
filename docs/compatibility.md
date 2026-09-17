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
| Skills CLI 1.5.26 | One selected source skill, copied to a project directory | Public-repository discovery, Humanizer installation/list/removal for four targets (Codex, Claude Code, Cursor, OpenCode); see recorded check below | Installer integration only; clients not invoked |
| Python selected-skill installer | Repeatable `--skill NAME` for install, update, and uninstall | Filesystem tests for four targets, additive selection, resources, retained ownership, conflicts, dry runs, and actual CLI calls | Installer integration only; clients not invoked |
| Git pre-commit hook | Executable shell entry and Python staged-export checker | Actual commit, alternate-index, and partial-staging tests | Git integration only; no client lifecycle hook installed |
| Skill Watch | Local CLI and optional MCP stdio server | Offline change fixture, retrieval/state tests, actual SDK client-to-server stdio calls; [usage and limits](skill-watch.md) | Protocol integration only; individual client apps not evaluated |
| Humanizer fact check | `scripts/check_facts.py` inside the `mkl-humanize` skill folder | Unit tests for code, URLs, placeholders, quotations, numbers, English/Polish negations and hedges, the skill's worked example, and CLI exit codes on Python 3.11/3.13; a manual run with Python 3.9.6 on macOS | Not yet invoked by a live client; not included in Grok Bot recipes, which contain the workflow text only |
| Humanizer Polish notes | `references/pl.md` inside the `mkl-humanize` skill folder | Export and installer tests copy the resource; `check_facts.py` reports no change for the release-note example and one intended dropped „nie” (a filler phrase) for the reply example, as the file states | Authored guidance; no live-client run and no fluent-reader review recorded yet |
| ML training example | Python CPU fixture with selectable PyTorch, Lightning, or TensorFlow/Keras execution | Three local framework runs plus framework-independent oracle tests; [versions and results](../examples/ml-training/README.md#recorded-cpu-check) | Fixture execution only; ML skill and agent not independently evaluated |
| Codex skills | `SKILL.md` under `.agents/skills/` | Export and installer tests | Not yet evaluated |
| Codex agents | Standalone `.codex/agents/*.toml` | TOML parsing and embedded-workflow tests | Not yet evaluated |
| Claude Code | `.claude/skills/` and YAML-frontmatter agent Markdown | Export and installer tests | Not yet evaluated |
| Claude Code plugin marketplace | `.claude-plugin/marketplace.json` with a Humanizer plugin and a full-library plugin | Manifest tests; strict CLI validation, local marketplace add, install and component inventory with Claude Code 2.1.177 ([recorded check](install.md#claude-code-plugin-marketplace)) | Installation only; no model invoked |
| Cursor | `.cursor/skills/` and YAML-frontmatter agent Markdown | Export and installer tests | Not yet evaluated |
| OpenCode | `.opencode/skills/` and `.opencode/agents/*.md` with `mode: subagent` | Source/export, propagation, installer and archive tests; [client check](../examples/opencode/README.md) | 1.18.30 discovery and configuration loading checked on macOS arm64, including a skill copied to `.agents/skills/`; model outcomes not evaluated |
| Grok Bot (SpaceXAI) | Markdown recipe for each skill and agent, plus first-task guides | Source propagation and embedded-workflow tests; documented manual setup | Not yet evaluated in a live Bot |

The suite runs locally without API keys. CI targets Linux and macOS on Python
3.11 and 3.13. Windows has not been tested; do not infer support from Python
compatibility alone.

## Skills CLI installation check

Checked **2026-09-13** on **macOS 26.6.2 arm64**, with **Node.js 24.19.0** and
**Vercel Skills CLI 1.5.26**. The public repository's default branch was at
[`b4ba52d`](https://github.com/00200200/maintainer-skills-lab/commit/b4ba52de87ff5251cbf0ab7632bad0771ec95150).
No coding client or model was invoked.

The CLI's `add ... --list` discovered all **14 source skills** without writing
files into its disposable project directory. In three separate empty projects,
the following commands were run with `AGENT` replaced by `codex`, `claude-code`,
and `cursor`:

```sh
DISABLE_TELEMETRY=1 npx --yes skills@1.5.26 add 00200200/maintainer-skills-lab --skill mkl-humanize --agent AGENT --copy --yes --json
DISABLE_TELEMETRY=1 npx --yes skills@1.5.26 list --agent AGENT --json
DISABLE_TELEMETRY=1 npx --yes skills@1.5.26 remove mkl-humanize --yes
```

Every target produced exactly one regular `SKILL.md`, byte-for-byte identical to
`skills/mkl-humanize/SKILL.md`, plus `skills-lock.json`. The installed paths are
listed in the [installation guide](install.md#one-skill-with-the-skills-cli).
The installed skill's SHA-256 was
`b06fd6512cbbe11af6dbe6c3b78db133e80e3b096eccfd41d31f9c498a1d4ae6`.
The CLI listed the selected skill, and removal deleted its files while preserving
an unrelated sentinel file. Telemetry was disabled for these checks. This historical check predates
`scripts/check_facts.py`. A later [resource installation diagnostic](../examples/skills-cli/README.md)
verified copying, execution, and removal of the checker with Skills CLI 1.5.26
and Node.js 22.20.0 on macOS for Codex, Claude Code, and Cursor. A later run of
the same diagnostic on macOS with Node.js 24.21.0 also covered `--agent opencode`,
which copies into the shared `.agents/skills` path. That diagnostic uses the
local checkout and does not repeat public-repository cloning.

One preliminary `remove mkl-humanize --agent codex --yes` reported success but
retained the shared skill directory. The documented removal command omits the
agent filter and was verified on all three targets. A shared directory can also
be used by other clients; this is not evidence of isolated client discovery.

These are recorded installer checks, separate from the network-free Python CI
suite. They do not establish client loading, writing quality, Windows support,
or protection for locally edited files in the third-party CLI.

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
- The Claude Code plugin marketplace has an installation check only; see the
  [installation guide](install.md#claude-code-plugin-marketplace). No other client marketplace or general ChatGPT/Claude web-chat compatibility is claimed.
- Grok Bot recipes contain workflow instructions. Required access, supporting files,
  and saved skills are configured in the Bot app. Regenerating a Markdown file does
  not update an existing cloud Bot or its routines.

## Primary format references

Checked 2026-09-13; these are documentation references, not live-run evidence:

- [Agent Skills specification](https://agentskills.io/specification)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Cursor skills](https://cursor.com/docs/skills)
- [Cursor subagents](https://cursor.com/docs/subagents)
- [OpenCode skills](https://opencode.ai/docs/skills)
- [OpenCode agents](https://opencode.ai/docs/agents)
- [Grok Bot overview](https://docs.x.ai/grok-bot/overview)
- [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations)
