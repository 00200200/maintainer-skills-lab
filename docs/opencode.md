# OpenCode

Install one shared skill into an existing project from this source clone:

```sh
python3 tools/kit.py install --target opencode --project /existing/project --skill mkl-humanize --dry-run
python3 tools/kit.py install --target opencode --project /existing/project --skill mkl-humanize
```

Start OpenCode in the destination project and ask:

> Load the mkl-humanize skill and edit this draft in its original language.
> Preserve facts, quotations, commands and uncertainty. Explain meaningful edits.

Provide the draft with the request. Inspect the output against the
[worked writing examples](../examples/writing/README.md).
This is a suggested acceptance exercise, not a recorded model evaluation.

## Include the agents

Omit `--skill` to install all skills and six agent profiles:

```sh
python3 tools/kit.py install --target opencode --project /existing/project
```

Skills go into `.opencode/skills/<name>/SKILL.md`; agents go into
`.opencode/agents/<name>.md`. Agent names come from filenames and use
`mode: subagent`, with their dependent workflows embedded. After installing the
full library, try `@mkl-writing-editor` with a draft, or `@mkl-bug-investigator`
with a reproducible failure. A selected-skill install does not install agents.

The exporter does not set a model, permission overrides, plugins, or
`opencode.json`. Review your existing client settings before running a task.
OpenCode can also discover `.agents/skills/` and `.claude/skills/`; keep skill
names unique across those locations. See the official [skill locations and
loading rules](https://opencode.ai/docs/skills) and
[agent format](https://opencode.ai/docs/agents), checked 2026-09-13.
The exported fields are also described in the [V2 agent guide](https://opencode.ai/v2/docs/agents).

## Update or remove

Update the source clone, then repeat the installation with the same selection.
Use a full-library install to refresh embedded agent workflows too.

```sh
python3 tools/kit.py uninstall --target opencode --project /existing/project --skill mkl-humanize --dry-run
python3 tools/kit.py uninstall --target opencode --project /existing/project --skill mkl-humanize
```

Local modifications to owned files stop replacement or removal. Unrelated files
and client configuration stay in place. [Full installer semantics](install.md).

## Evidence

The shared filesystem suite covers OpenCode exports, supporting resources,
source-to-agent propagation, installation and removal. It checks agent metadata
without adding model or permission settings. Skill Watch includes existing
OpenCode exports in its impact report, and the builder produces an OpenCode ZIP.

OpenCode 1.18.30 discovery and configuration loading were checked on macOS arm64:
all 16 skill bodies and six agent prompts matched, and selected installation and
skill removal were reflected in client diagnostics.
A separate Linux CI job runs the same discovery assertions against the pinned
client and publishes a result artifact.
[Repeat the client check and inspect the recorded result](../examples/opencode/README.md).

Model invocation, output quality and permission enforcement remain unevaluated.
No API key or paid model call was used. No OpenCode lifecycle hook is installed.
