# Hooks that catch an incomplete change

Skills describe how to work. Hooks run a concrete check at a particular moment.
The first hook in this library checks that a proposed commit contains matching
source skills, agent profiles, and generated provider files.

## Staged export guard

You edit `mkl-humanize`, run `sync`, and stage only the source. The files on disk
look correct, but the proposed commit still contains yesterday's provider copies.
This hook catches that mismatch **before Git creates the commit**.

It reads the active Git index, including partially staged changes and alternate
indexes, and validates a temporary snapshot. It does not run `git add`, regenerate
files, stash changes, or modify your source and provider files. Edits you have
not staged are kept out of the check. When a library path changes, it reads the
full staged library and provider files; documentation-only commits skip that work.
There are no network or model calls. Runtime and temporary disk use scale with
the library size, and each Git subprocess has a 30-second timeout.

**Scope:** this hook is for Maintainer Skills Lab and forks that retain its
`tools/kit.py` authoring layout. It is not a general checker for arbitrary skill
repositories. It works at the Git boundary, regardless of which editor or agent
prepared the commit. Native client hook installation has not been evaluated.

## Try without changing configuration

From a clone of this repository, with Python 3.11+ and Git installed:

```sh
python3 -B tools/check_staged.py
```

The command exits `0` when staged library files match, or when the commit has no
library changes. It exits `1` on a mismatch, unresolved library conflict,
unsupported file type, missing Git context, or validation error.

An incomplete staged change produces a message like:

```text
Maintainer Skills Lab: staged check failed. Staged provider exports do not match the staged source: …
```

Fix the source, run `python3 tools/kit.py sync`, review the diff, and stage the
matching source and generated changes together. The hook leaves those choices
to you. If the exporter itself changes, its working-tree and staged versions
must match so the check uses the intended implementation.

## Enable for commits in this clone

First inspect any existing hook configuration:

```sh
git config --show-origin --get core.hooksPath
git rev-parse --git-path hooks/pre-commit
```

No configured path is reported with exit status `1`; that is normal. If you
already have hooks or a hook manager, add `python3 -B tools/check_staged.py` to
its existing pre-commit chain and propagate a nonzero exit status.

If this clone has no hooks to preserve, enable the checked-in hook:

```sh
git config --local core.hooksPath hooks
```

The executable [pre-commit](pre-commit) file calls the checker. Git invokes it
from the repository root. Configuring `core.hooksPath` selects a hook directory,
so do not replace an existing path without integrating its hooks first. Cloning
or installing the skill bundles does not enable this hook automatically.

To remove the local setting after using the command above:

```sh
git config --local --unset core.hooksPath
```

If you had a previous local value, restore that value instead. Git can bypass
local hooks, so the CI source/export checks remain the publishing check.

## Evidence and client hook references

The test suite creates disposable Git repositories and performs actual commits.
It checks a rejected incomplete commit, a successful synchronized commit,
unstaged broken source, deletions, alternate indexes, symlinks, unmerged entries,
manifest tampering, and resource names containing spaces and Polish characters.
These are local Git integration tests, not model evaluations.

Client lifecycle hooks are separate integration surfaces. These primary guides
explain their current configuration and events, checked 2026-09-13:

| Surface | Official reference |
| --- | --- |
| Git pre-commit | [Git hooks](https://git-scm.com/docs/githooks#_pre_commit) |
| Codex lifecycle hooks | [Codex hooks](https://learn.chatgpt.com/docs/hooks) |
| Claude Code lifecycle hooks | [Claude Code hooks](https://code.claude.com/docs/en/hooks-guide) |
| Cursor lifecycle hooks | [Cursor hooks](https://cursor.com/docs/hooks) |

This release includes the Git hook. It does not install a `Stop`, `PostToolUse`,
or other client lifecycle hook. Hook scripts execute local code; inspect changes
before enabling a repository's hook directory.
