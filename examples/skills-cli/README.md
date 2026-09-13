# Check that Humanizer installs with its script

This optional diagnostic runs **Skills CLI 1.5.26** against the current source
checkout. It creates three temporary projects, installs only Humanizer for
Codex, Claude Code, and Cursor, and compares every copied resource with the
canonical skill directory. It then runs the installed checker against an
unchanged draft and a rewrite with a changed exponent and removed negation.
Finally it removes the skill and verifies that unrelated project files remain.

Use Python 3.11+, Node.js 22.20.0+, Git, and an existing Skills CLI 1.5.26
installation. No client app or model API key is needed. The diagnostic does not
install Node or the CLI for you, change global configuration, or install skills
in your current project.

```sh
python3 examples/skills-cli/check.py --node /path/to/node --skills /path/to/skills
```

`--skills` points to the CLI's JavaScript executable (normally the `skills`
entrypoint in `node_modules/.bin`); `--node` selects its interpreter explicitly.
Both options can be omitted if the corresponding executables are on PATH.
Each command has a 50-second timeout. The test disables Skills CLI telemetry
and its associated security-audit requests. It installs from the local checkout,
so it does not test GitHub cloning, remote updates, or a moving default branch.

Success produces a JSON report with the three targets, `resources_match`,
`installed_checker_executed`, and `removal_verified` set to true. Any failed
check exits nonzero. Temporary projects are removed on exit.

## Recorded check

On 2026-09-13, this diagnostic passed on macOS 26.6.2 arm64 with Node.js 22.20.0,
Skills CLI 1.5.26, and Python 3.11.5. Humanizer's instruction and checker matched
the canonical files from commit `1a57a8b8a64029c774d32a1e9adaf46e1edfb9b0`.
Codex and Cursor used `.agents/skills/`; Claude Code used `.claude/skills/`.

This verifies installer behavior and execution of the copied Python script.
It does not establish live-client invocation, writing quality, global installs,
other operating systems, or other CLI versions. The diagnostic is opt-in and
is not part of the network-free unit suite.
