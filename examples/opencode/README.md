# OpenCode discovery check

This optional integration check uses the actual **OpenCode 1.18.30** diagnostic
commands. It does not start a model session, install the CLI, or join the default
network-free unit suite.

Install the pinned version using an [official installation method](https://opencode.ai/docs/).
With that executable available, run from this repository:

```sh
python3 examples/opencode/check.py --opencode /path/to/opencode
```

The script rejects other versions so changes to diagnostic output do not silently
become evidence for an untested client release. It requires Python 3.11+ and Git.
Allow roughly 30 seconds on the recorded environment; each client process has a
45-second timeout.

It creates a disposable Git project and separate XDG configuration/data/cache/state
paths, uses OpenCode's `OPENCODE_TEST_HOME` isolation override, and passes no API
credentials from the parent environment. Automatic updates and default external
plugins are disabled. This is process configuration isolation, not an OS sandbox
or a guarantee that the executable cannot use the network.

The executable comes from the operator. Run this check only with the expected
OpenCode binary. The script does not change the real home directory, global client
settings or project files, and cleans its temporary project when it finishes.

## What is checked

- An empty project has no `mkl-*` skills.
- Installing only Humanizer exposes exactly that skill; removal hides it again.
- Full installation exposes all 16 skills, with matching names, descriptions,
  resolved paths and complete bodies.
- All six agents load as subagents with matching descriptions and embedded prompts.
- Diagnostic reads leave the installed exports unchanged.
- After full uninstall, no library skills remain discoverable.

These assertions use `opencode debug skill` and `opencode debug agent NAME`.
They test client discovery and configuration loading, not model invocation,
writing quality, tool execution, permission enforcement or GUI behavior.
Built-in client skills are excluded from the library count.

## Recorded result

Passed on **2026-09-13**, **macOS 26.6.2 arm64**, **Python 3.11.5**, using the
`opencode-darwin-arm64@1.18.30` binary distributed as an optional dependency of
`opencode-ai@1.18.30`. The packages were downloaded into a temporary prefix;
no global installation was used. Source exports were from commit
`061cb1bf44732cdf3d962249952282b30c2a0116`.

```json
{
  "opencode_version": "1.18.30",
  "skills": 16,
  "agents": 6,
  "selected_install_discovery": true,
  "removal_discovery": true,
  "skill_content_and_agent_prompts_match": true,
  "model_session_started": false
}
```

No Windows, Linux or OpenCode V2 discovery run is claimed by this record.
