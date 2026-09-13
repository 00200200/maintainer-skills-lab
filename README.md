# Maintainer Skills Lab

[![Validate library](https://github.com/00200200/maintainer-skills-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/00200200/maintainer-skills-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Investigate bugs, verify fixes, and write project docs people can use.**

Fourteen practical skills, four focused agent profiles, and native bundles
for **Codex, Claude Code, and Cursor**. Includes two **Grok Bot** setup recipes.
Shared instructions stay in one source; client-specific formats are generated.

> **Preview:** source/export checks and the bundled regression example are tested.
> Live-client behavior and Grok Bot template imports have not been evaluated yet.
> See the [compatibility matrix](docs/compatibility.md).

## Try the example — no API key required

```sh
git clone https://github.com/00200200/maintainer-skills-lab.git
cd maintainer-skills-lab
python3 examples/bugfix/run.py
```

```text
Baseline:  assertion-failure
Candidate: pass
Verified for this fixture: True
This checks the bundled example, not agent performance.
```

The [example](examples/bugfix/README.md) runs the same independent test against
two implementations in fresh Python processes. It separates assertion failures
from environment errors and records source/test hashes in its JSON report.

## Install in a project

Requires **Python 3.11+**. No third-party Python dependencies.

```sh
# Inspect planned changes first. The project directory must already exist.
python3 tools/kit.py install --target codex --project /path/to/your/repo --dry-run
python3 tools/kit.py install --target codex --project /path/to/your/repo
```

Use `--target claude` or `--target cursor` for the other coding clients.
Start with one target per project; mixed-client discovery is a [known limitation](docs/compatibility.md).

The installer preserves unrelated files and client settings, refuses conflicting
local edits and symlinked destinations, and records only the files it owns.
An identical pre-existing file remains yours. See [installation](docs/install.md)
for updates, removal, and archive installation.

Once your client discovers the skills, try this in a disposable example project:

> Use mkl-reproduce-bug and mkl-write-regression to investigate issue.md.
> Establish the failure before changing the implementation. Then propose the
> smallest fix and use mkl-verify-fix to check it. Do not publish anything.

Explicit invocation uses `$mkl-reproduce-bug` in Codex CLI and
`/mkl-reproduce-bug` in Claude Code or Cursor. Restart the client if its discovery
list has not refreshed. This preview ships local/project files; it is not a
published ChatGPT, Claude, or Cursor marketplace plugin.

## Pick a workflow

### Maintain code

| Skill | Useful result |
| --- | --- |
| [Triage issue](skills/mkl-triage-issue/SKILL.md) | Evidence, missing information, and a next action |
| [Reproduce bug](skills/mkl-reproduce-bug/SKILL.md) | A minimal reproduction with observed output |
| [Write regression](skills/mkl-write-regression/SKILL.md) | An assertion that catches the original defect |
| [Verify fix](skills/mkl-verify-fix/SKILL.md) | Comparable baseline and candidate evidence |
| [Review PR](skills/mkl-review-pr/SKILL.md) | Actionable findings with locations and consequences |
| [Prepare release](skills/mkl-prepare-release/SKILL.md) | Accurate release notes and migration guidance |

### Write and communicate

| Skill | Useful result |
| --- | --- |
| [Humanizer](skills/mkl-humanize/SKILL.md) | Natural prose that preserves the author's facts and intent |
| [Match voice](skills/mkl-match-voice/SKILL.md) | A draft adapted to supplied writing samples |
| [Write README](skills/mkl-write-readme/SKILL.md) | Project introduction and quickstart grounded in repository evidence |
| [Write tutorial](skills/mkl-write-tutorial/SKILL.md) | A guided outcome with prerequisites and verifiable checkpoints |
| [Write launch post](skills/mkl-write-launch-post/SKILL.md) | A factual announcement or development update ready for review |
| [Write UX copy](skills/mkl-write-ux-copy/SKILL.md) | Clear labels, errors, and empty states with intact placeholders |
| [Localize PL ↔ EN](skills/mkl-localize-pl-en/SKILL.md) | Natural Polish/English with technical tokens and meaning preserved |
| [Write maintainer reply](skills/mkl-write-maintainer-reply/SKILL.md) | A respectful issue or PR reply with a concrete next action |

Try this after installing a bundle:

> Use mkl-humanize to improve this Polish update. Keep the command and limitation:
> „Z przyjemnością informujemy o możliwości podglądu zmian za pomocą `--dry-run`.
> Windows nie został jeszcze przetestowany.”

One possible edit: „Użyj `--dry-run`, żeby podejrzeć zmiany. Nie sprawdziliśmy
jeszcze obsługi Windows.”

Every writing skill includes an inspectable worked example. See the
[writing examples](examples/writing/README.md) for ready-to-use prompts and
acceptance scenarios. These are authored illustrations; writing quality and
live-client invocation have not yet been evaluated.

Agent profiles: **mkl-bug-investigator**, **mkl-pr-reviewer**,
**mkl-release-editor**, and **mkl-writing-editor**. Each exported agent embeds the workflows it needs;
it does not require another skill to be implicitly loaded. Models and execution
permissions inherit from the host session.

For Grok Bot, start with [Issue Scout or Release Reporter](grok-bot/README.md).
These are human-readable setup recipes, not automatic Bot imports.

## Check or build the library

```sh
python3 tools/kit.py list
python3 tools/kit.py check
python3 -m unittest discover -s tests -v
python3 tools/kit.py build
```

Builds produce four deterministic ZIP archives under `dist/`. CI checks Python
3.11 and 3.13 on Linux and macOS and exposes the archives as run artifacts.
Check the linked run before treating any particular revision as verified.

`check` validates this repository's deliberately small authoring format and
generates exports in memory. It is not a general YAML linter, a security audit,
or a live-model benchmark. [Evaluation guide](evals/README.md).

## Contribute

A minimal reproduction, a failing fixture, or a reported client incompatibility
is especially useful. Read [CONTRIBUTING.md](CONTRIBUTING.md).
Include the client version and steps when reporting an
integration problem.

If the library helps your workflow, a star makes it easier to find again.

## Related project

[blader/humanizer](https://github.com/blader/humanizer) is a general-purpose
humanization skill worth exploring. The writing workflows here are independently
authored for project maintenance, documentation, and Polish/English communication.

## License

MIT. Independent community project; not affiliated with or endorsed by OpenAI,
Anthropic, Cursor, xAI, or Groq.
