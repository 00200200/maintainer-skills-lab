# OpenCode discovery check

This integration check uses the actual **OpenCode 1.18.30** diagnostic commands.
It is optional locally and runs in a separate Linux CI job. It does not start a
model session or join the default network-free unit suite. The script requires
an existing CLI; CI downloads its pinned Linux package separately.

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
- A Humanizer copy in `.agents/skills/` (the Skills CLI `--agent opencode` path)
  is discovered with a matching name, description, body, and resolved location.
- Full installation exposes every library skill, with matching names, descriptions,
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

A later local run on **2026-09-17**, same host and OpenCode 1.18.30 binary, used
the current library (17 skills) and also asserted `.agents/skills/` discovery:

```json
{
  "opencode_version": "1.18.30",
  "skills": 17,
  "agents": 6,
  "selected_install_discovery": true,
  "agents_path_discovery": true,
  "removal_discovery": true,
  "skill_content_and_agent_prompts_match": true,
  "model_session_started": false
}
```

This local record does not establish Windows, Linux or OpenCode V2 discovery.
Linux execution is tracked separately by the CI job below.

## Continuous integration

The `OpenCode 1.18.30 discovery (Linux)` job in
[Validate library](../../.github/workflows/ci.yml) runs this same script on pushes
and pull requests, using Python 3.11 and the `opencode-linux-x64@1.18.30` npm
package. Installation stays under the runner's temporary directory, disables
package lifecycle scripts, and does not modify the repository or install a
model provider. The job has a ten-minute limit.

A nonzero diagnostic or assertion result fails the job. A successful run uploads
`opencode-discovery-linux`, containing the version, skill/agent counts and
assertion summary. Inspect the run for the exact commit being evaluated. No
API credentials are supplied, and no model session or paid API call is started.
The macOS result above remains a separately recorded local run; the standard
Python matrix does not imply OpenCode execution on every platform.
