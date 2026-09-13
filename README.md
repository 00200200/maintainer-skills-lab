<p align="center">
  <img src="assets/hero.svg" alt="Maintainer Skills Lab — Useful skills. One shared source." width="1200">
</p>

<p align="center">
  <a href="https://github.com/00200200/maintainer-skills-lab/actions/workflows/ci.yml"><img src="https://github.com/00200200/maintainer-skills-lab/actions/workflows/ci.yml/badge.svg" alt="Validate library"></a>
  <a href="https://github.com/00200200/maintainer-skills-lab/stargazers"><img src="https://img.shields.io/github/stars/00200200/maintainer-skills-lab?style=flat&amp;color=bced85&amp;label=stars" alt="GitHub stars"></a>
  <a href="https://github.com/00200200/maintainer-skills-lab/forks"><img src="https://img.shields.io/github/forks/00200200/maintainer-skills-lab?style=flat&amp;color=83d2e9" alt="GitHub forks"></a>
  <a href="https://github.com/00200200/maintainer-skills-lab/issues"><img src="https://img.shields.io/github/issues/00200200/maintainer-skills-lab?style=flat&amp;color=e9b293" alt="Open issues"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-bced85" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="#try-humanizer"><b>Try Humanizer</b></a> ·
  <a href="providers/README.md"><b>Explore the skills</b></a> ·
  <a href="https://github.com/00200200/maintainer-skills-lab/releases">Download ZIPs</a> ·
  <a href="grok-bot/README.md">Grok Bot</a> ·
  <a href="hooks/README.md">Hooks</a>
</p>

# Maintainer Skills Lab

**Make stiff drafts readable. Give your coding agent a repeatable way to investigate bugs and review PRs.**

14 skills and 4 agent profiles for **Codex, Claude Code, Cursor, and Grok Bot**.
The workflows share one Markdown source, with generated versions for each client.
Start with one skill, or get the full library with its agents.

## Try Humanizer

The [Humanizer skill](skills/mkl-humanize/SKILL.md) edits a draft in its original
language, keeping facts, code, quotations, and meaningful caveats intact.

| Before | One possible edit |
| --- | --- |
| We are thrilled to announce that you can now leverage `--dry-run` to preview changes. Windows has not been tested yet. | Use `--dry-run` to preview changes. We haven't tested Windows yet. |

This is an authored illustration. [More examples and acceptance checks →](examples/writing/README.md)

### Install one skill

With **Node.js 22.20.0+ and Git**, run this in the project where you want to use it:

```sh
npx skills@1.5.26 add 00200200/maintainer-skills-lab --skill mkl-humanize --agent codex --copy
```

For **Claude Code**, replace `--agent codex` with `--agent claude-code`.
For **Cursor**, use `--agent cursor`. This uses the third-party
[Vercel Skills CLI](https://github.com/vercel-labs/skills) to install one skill
locally in the current project. Read the linked skill before installing it.

Then ask your client:

> Use mkl-humanize to improve this draft. Preserve its facts, code, and limitations.
> Explain any edit that changes the emphasis.

Explicit invocation uses `$mkl-humanize` in Codex CLI or `/mkl-humanize` in
Claude Code and Cursor. [Installation, removal, and recorded checks →](docs/install.md#one-skill-with-the-skills-cli)

Prefer Python or downloadable files? [Install the full library](#start-in-a-minute)
or [get a ZIP](https://github.com/00200200/maintainer-skills-lab/releases).
Grok Bot uses [manual setup recipes](grok-bot/README.md).

## Find your next useful skill

| You want to… | Start here | What you get |
| --- | --- | --- |
| Keep a consistent writing voice | [Match voice](skills/mkl-match-voice/SKILL.md) | An edit grounded in supplied writing samples |
| Fix a bug with evidence | [Reproduce bug](skills/mkl-reproduce-bug/SKILL.md) → [Verify fix](skills/mkl-verify-fix/SKILL.md) | An observed failure and a comparable check of the fix |
| Review a pull request | [Review PR](skills/mkl-review-pr/SKILL.md) | Actionable findings with locations and consequences |
| Explain your project | [Write README](skills/mkl-write-readme/SKILL.md) | An introduction and quickstart grounded in the actual repository |
| Work in Polish and English | [Localize PL ↔ EN](skills/mkl-localize-pl-en/SKILL.md) | Natural wording with commands, placeholders, and meaning preserved |

**[Browse all 14 skills and 4 agents →](providers/README.md)**
Includes tutorials, UX copy, launch posts, maintainer replies, issue triage,
regression tests, and releases. The four agent profiles combine these workflows
for bug investigation, PR review, release editing, and writing.

## Start in a minute

Get the **full library and native agents** with Python 3.11+. The library tools
have no third-party dependencies.

```sh
git clone https://github.com/00200200/maintainer-skills-lab.git
cd maintainer-skills-lab

# The destination must be an existing project. Inspect changes first.
python3 tools/kit.py install --target codex --project /path/to/your/repo --dry-run
python3 tools/kit.py install --target codex --project /path/to/your/repo
```

Use `--target claude` or `--target cursor` for the other coding clients. The installer
adds the full library for one target, preserves unrelated files, and refuses
conflicting local edits. Start with one installation method and target per project;
mixed-client discovery is an [untested limitation](docs/compatibility.md).
[Updates, removal, and ZIPs →](docs/install.md)

## One source, four versions

![Animated illustration of one Markdown source generating Codex, Claude Code, Cursor, and Grok Bot versions. Grok Bot requires manual setup.](assets/workflow.gif)

```sh
python3 tools/kit.py sync
```

Editing `skills/mkl-humanize/SKILL.md` generates:

```text
providers/
├── codex/.agents/skills/mkl-humanize/SKILL.md
├── claude/.claude/skills/mkl-humanize/SKILL.md
├── cursor/.cursor/skills/mkl-humanize/SKILL.md
└── grok-bot/skills/mkl-humanize.md
```

Agent definitions in `agents/*.toml` combine shared skills. Their generated
versions embed the workflows they need, so a source edit also updates dependent
agents. CI checks that the checked-in copies match their source.

| Client | Get the files | How to use them |
| --- | --- | --- |
| Codex | [Skills + native agents](providers/codex/README.md) | Project-local installation |
| Claude Code | [Skills + native agents](providers/claude/README.md) | Project-local installation |
| Cursor | [Skills + native agents](providers/cursor/README.md) | Project-local installation |
| Grok Bot (SpaceXAI) | [Skill + agent recipes](providers/grok-bot/README.md) | Set up in the Bot, try a task, then save the workflow as a skill |

Grok Bot recipes follow the [official x.ai documentation](https://docs.x.ai/grok-bot/skills-routines-and-automations).
They are Markdown instructions for manual setup; copying them does not create a Bot.
[Issue Scout and Release Reporter](grok-bot/README.md) include first-task prompts and optional routines.

## Catch incomplete commits with a hook

Changed a skill but forgot to stage its generated versions? The optional
[staged export guard](hooks/README.md) catches that before the commit is created.
It checks the exact staged files, so a correct working tree cannot hide stale
provider copies in the index. Unstaged edits are left alone.

```sh
python3 -B tools/check_staged.py
```

For contributors to this library and its forks. [Setup, examples, and limits →](hooks/README.md)

## Check the evidence

Run a complete local regression example without a model or API key:

```sh
python3 examples/bugfix/run.py
```

```text
Baseline:  assertion-failure
Candidate: pass
Verified for this fixture: True
This checks the bundled example, not agent performance.
```

The same independent test runs against both implementations in fresh Python
processes. [Inspect the fixture and its limits →](examples/bugfix/README.md)

**Preview status:** source/export checks and tool/fixture tests are automated.
Humanizer installation and removal with Skills CLI 1.5.26 were checked for all
three coding-client targets. Live-client discovery, writing quality, and Grok Bot
execution have not yet been evaluated. Native agents inherit model and execution policy from the host.
[Compatibility matrix](docs/compatibility.md) · [Evaluation guide](evals/README.md)

## Make it useful for you

Missing a workflow or found a rough edge? [Open an issue](https://github.com/00200200/maintainer-skills-lab/issues/new)
with the task and a small example. To contribute a skill, edit one source and
generate the client versions: [contribution guide](CONTRIBUTING.md).

If a skill earns a place in your workflow, **star the repository** to find it again.
To hear about changes, use GitHub's **Watch → Custom → Releases**.

## Community, in numbers

[![GitHub stars and forks, 14-day views and unique visitors, and a star-history snapshot.](assets/community.svg)](https://github.com/00200200/maintainer-skills-lab/stargazers)

Badges above refresh through Shields and GitHub and may be cached. This chart is a
dated snapshot of GitHub data, refreshed alongside substantive changes. Views and
unique visitors cover GitHub's returned **14-day window**. The star chart groups
**current** stargazers by their original star date; removed stars are excluded.
[Aggregate data](assets/community.json) · [How it is generated](assets/README.md)

<details>
<summary><b>Develop and build locally</b></summary>

```sh
python3 tools/kit.py list
python3 tools/kit.py check
python3 tools/kit.py sync --check
python3 -m unittest discover -s tests -v
python3 examples/bugfix/run.py
python3 tools/kit.py build
```

Builds produce four deterministic ZIPs in `dist/`. CI checks Python 3.11 and 3.13
on Linux and macOS and uploads archives as run artifacts. Check the linked run
for the revision you intend to use. The checker validates this repository's
small authoring format; it is not a general YAML validator or a live-model benchmark.

</details>

## Credits and license

[blader/humanizer](https://github.com/blader/humanizer) is a related project in the
same problem space. This library's writing workflows and worked examples are authored here.

[MIT](LICENSE). Independent community project; not affiliated with or endorsed
by OpenAI, Anthropic, Cursor, or SpaceXAI/xAI.
