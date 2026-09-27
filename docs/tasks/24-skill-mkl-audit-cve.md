# [Feature] Token-Optimized Security & CVE Dependency Auditor (`mkl-audit-cve`)

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Motivation
Maintainers regularly receive automated Dependabot or Renovate alerts regarding CVE security advisories. When investigating these alerts, maintainers need to answer two critical questions:
1. Is our codebase actually calling the vulnerable code path?
2. Does upgrading to the patched version introduce breaking API changes?

Existing agents often attempt to analyze entire dependencies or pull in massive vulnerability databases, wasting thousands of tokens without delivering a clear verdict.

## Prior Art & Industry Standards
- **GitHub Security Advisories (GHSA) API**: Structured vulnerability data (affected versions, patched versions, vulnerable methods).
- **Renovate / Dependabot triage workflows**.

## Proposed Solution
Create a new canonical skill `skills/mkl-audit-cve/SKILL.md`:
- **Name**: `"mkl-audit-cve"`
- **Description**: `"Audit CVE advisories against codebase usage with minimal token context."`

### Workflow Specification
1. **Targeted Extraction**:
   - Extract the specific vulnerable symbol or function mentioned in the CVE/GHSA advisory.
2. **Usage Verification**:
   - Run ripgrep (`rg`) or AST search across the repository to check if the vulnerable function is actually imported or called.
3. **Verdict Generation**:
   - If not called: Mark as `Low Immediate Risk / Trivial Upgrade`.
   - If called: Highlight the exact invocation line and recommend either an upgrade or an immediate input sanitization workaround.
4. **Output Constraint**: Max 200 words (< 260 tokens).

## Implementation Tasks
- [ ] Author `skills/mkl-audit-cve/SKILL.md`.
- [ ] Include worked examples for both a direct vulnerability and a transitive uninvoked vulnerability.
- [ ] Run `python3 tools/kit.py sync` to propagate across all clients.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Skill delivers a precise, actionable CVE impact summary under 260 tokens.
- Works across Python, Node, and Rust ecosystems.
