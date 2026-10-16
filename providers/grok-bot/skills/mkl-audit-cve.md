# mkl-audit-cve

Audit CVE advisories against codebase usage with minimal token context.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-audit-cve."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Audit CVE advisories against codebase usage

Auditing alerts from Dependabot, Renovate, or GHSA must not dump dependencies into context.

Execute a targeted audit:
1. Is our codebase importing or calling the vulnerable code path?
2. What is the immediate maintainer action (safe routine upgrade vs. urgent remediation)?

## 1. Targeted Extraction

Extract essential advisory attributes:
- **Identifier**: CVE or GHSA ID (e.g. `CVE-2020-14343`).
- **Affected package**: Package name (e.g. `pyyaml`) and version range.
- **Vulnerable symbol**: Function or class (e.g. `yaml.load`).
- **Trigger**: Input pattern causing exploitability.

## 2. Usage Verification via targeted search

Run ripgrep (`rg`) or AST search for the vulnerable symbol and import entrypoints; exclude test fixtures.

- **Python**: `rg -n "\b<symbol>\s*\("`
- **Node.js**: `rg -n "\b<symbol>\s*\("`
- **Rust**: `rg -n "\b<symbol>\s*::|\b<symbol>\s*\("`

Dependencies:
- **Direct**: Declared in `pyproject.toml`, `package.json`, or `Cargo.toml`.
- **Transitive**: Present in lockfiles (`uv.lock`, `package-lock.json`).

## 3. Verdict Generation

- **Uninvoked / Not called**: Mark `Low Immediate Risk / Trivial Upgrade`. Exploitability absent; merge in regular updates.
- **Invoked / Reachable**: Highlight site (`file:line`). Mark `High Immediate Risk / Active Vulnerability`. Recommend immediate patched version bump or defensive workaround.
- If upstream fixes are unavailable, supply input sanitization or a defensive workaround.

## 4. Standard Output Schema

All audit summaries must stay under 200 words (< 260 tokens):

```text
### CVE Audit: <CVE-ID> (<pkg> <ver>)
- **Symbol**: `<symbol>`
- **Reach**: [Direct at <file:line> | Uninvoked]
- **Kind**: [Direct | Transitive]
- **Verdict**: [Low Immediate Risk / Trivial Upgrade | High Immediate Risk / Active Vulnerability]
- **Action**: <Recommendation or workaround>
```

## 5. Worked Examples

### Example 1: Python — Direct Vulnerability (Invoked)
- **Alert**: `CVE-2020-14343` (`PyYAML < 5.4`). Vulnerable symbol: `yaml.load()`.
- **Search**: `rg -n "\byaml\.load\(" src/` -> `src/config.py:42: yaml.load(stream)`

```text
### CVE Audit: CVE-2020-14343 (PyYAML 5.3.1)
- **Symbol**: `yaml.load()`
- **Reach**: Direct (`src/config.py:42`)
- **Kind**: Direct (`pyproject.toml`)
- **Verdict**: High Immediate Risk / Active Vulnerability
- **Action**: Arbitrary execution. Upgrade PyYAML or use `yaml.safe_load()`.
```

### Example 2: Node.js — Transitive Vulnerability (Uninvoked)
- **Alert**: `CVE-2020-28500` (`lodash < 4.17.21`). Vulnerable symbol: `_.defaultsDeep`.
- **Search**: `rg -n "\bdefaultsDeep\b" src/` -> No matches.

```text
### CVE Audit: CVE-2020-28500 (lodash 4.17.20)
- **Symbol**: `lodash.defaultsDeep`
- **Reach**: Uninvoked
- **Kind**: Transitive (`winston`)
- **Verdict**: Low Immediate Risk / Trivial Upgrade
- **Action**: Uncalled symbol. Merge lockfile bump.
```

### Example 3: Rust — Transitive Vulnerability (Uninvoked)
- **Alert**: `RUSTSEC-2021-0139` (`tokio < 1.8.4`). Vulnerable symbol: `tokio::sync::oneshot`.
- **Search**: `rg -n "\b(sync::oneshot|oneshot::channel)\b" src/` -> No matches.

```text
### CVE Audit: RUSTSEC-2021-0139 (tokio 1.8.0)
- **Symbol**: `tokio::sync::oneshot`
- **Reach**: Uninvoked
- **Kind**: Direct crate, unused module
- **Verdict**: Low Immediate Risk / Trivial Upgrade
- **Action**: Exploitability absent. Upgrade `tokio`.
```
