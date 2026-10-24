# Maintainer Skills Lab

Shared skills and agent profiles for code review, bug investigation, documentation,
and ML debugging. Edit the source in `skills/` and `agents/`; `tools/kit.py sync`
generates the client-specific files.

[Quick start](#quick-start) · [Skills](#the-skills-library) ·
[Client formats](providers/README.md) · [Task examples](docs/task-gallery.md)

---

## Workflows

The library provides instructions and local tools for coding assistants:

- Rewrite drafts while checking that facts, code, and caveats survive the edit.
- Reproduce reported bugs and compare behavior before and after a fix.
- Investigate shapes, losses, gradients, and other ML training failures.
- Review pull requests and dependency updates against concrete failure cases.

Generated files are checked against their source. That validates the export, not
the behavior of every client or model. See the [evaluation guide](evals/README.md)
for the distinction between fixtures and recorded agent runs.

## Quick start

Start with one skill, or install the full library. The
[installation guide](docs/install.md) covers client-specific paths and removal.

### 1. Claude Code
```bash
/plugin marketplace add 00200200/maintainer-skills-lab
/plugin install mkl-humanize@maintainer-skills-lab
```

### 2. Codex, Cursor, or OpenCode
From your destination project directory, use the Skills CLI with Node.js 22.20.0+ and Git:
```bash
npx skills@1.5.26 add 00200200/maintainer-skills-lab --skill mkl-humanize --agent codex --copy
```
Use `--agent cursor` or `--agent opencode` for those clients. This installs a
project-local copy, not a global skill.

### 3. Python Setup
With Python 3.11+, install the full library into an existing project:
```bash
git clone https://github.com/00200200/maintainer-skills-lab.git
cd maintainer-skills-lab
python3 tools/kit.py install --target claude --project /path/to/your/repo
```

## The skills library

The source library currently contains 30 skills and 9 agent profiles.

| Skill | What it does |
|:---|:---|
| [Humanize](skills/mkl-humanize/SKILL.md) | Edit drafts and check for changed facts or technical details. |
| [Reproduce bug](skills/mkl-reproduce-bug/SKILL.md) | Build a minimal reproduction with observable results. |
| [Verify fix](skills/mkl-verify-fix/SKILL.md) | Compare the regression before and after a change. |
| [Debug ML](skills/mkl-debug-ml-training/SKILL.md) | Investigate NaNs, shape errors, and convergence problems. |
| [Review PR](skills/mkl-review-pr/SKILL.md) | Identify defects with concrete inputs and consequences. |
| [Write README](skills/mkl-write-readme/SKILL.md) | Document features, setup, and limitations supported by the code. |

[Browse the full catalogue and client formats](providers/README.md).

## Development checks

These checks validate sources, generated files, and local fixtures. They do not
start a model session or establish live-client behavior.

```bash
python3 tools/kit.py check
python3 tools/kit.py sync --check
python3 -m unittest discover -s tests -v
python3 examples/bugfix/run.py
python3 tools/kit.py build
```

After editing shared skills or agents, run `python3 tools/kit.py sync` and include
the generated outputs in the same change. Do not edit provider copies directly.

## Contribute

See the [contributor guide](CONTRIBUTING.md), [suggest a workflow](https://github.com/00200200/maintainer-skills-lab/issues/new?template=workflow.yml),
[report a bug](https://github.com/00200200/maintainer-skills-lab/issues/new?template=bug_report.yml),
or [propose a token or latency optimization](https://github.com/00200200/maintainer-skills-lab/issues/new?template=optimization.yml).
You can also browse [help-wanted](https://github.com/00200200/maintainer-skills-lab/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22)
and [good first issues](https://github.com/00200200/maintainer-skills-lab/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22).

## License
[MIT](LICENSE). This is an independent community project.
