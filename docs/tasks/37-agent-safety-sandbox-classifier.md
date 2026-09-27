# [Feature] Agent Safety & Command Sandbox Classifier Tool (`tools/sandbox_check.py`)

**Labels**: `enhancement`, `security`, `help wanted`

## Context & Motivation
When AI agents run maintainer tasks autonomously, they execute shell commands. Occasionally, hallucinating models generate dangerous commands (`rm -rf /`, `git reset --hard` on uncommitted work, or `git push --force` to main).

Maintainer Skills Lab should equip maintainers with a command safety classifier that validates proposed agent actions before execution.

## Prior Art & Industry Standards
- **Claude Code Permission Prompts**: Categorizes commands into read-only (auto-approved) vs destructive (requires confirmation).
- **OpenHands / SWE-bench Sandboxing**: Restricts network access and destructive operations in agent environments.

## Proposed Solution
Create `tools/sandbox_check.py`:
```bash
python3 tools/sandbox_check.py "git push --force origin main"
# Output: {"verdict": "BLOCKED", "reason": "Destructive force push to main branch"}
```

### Safety Categories
1. **READ_ONLY** (Auto-Safe): `git status`, `git diff`, `pytest`, `cat`, `ls`, `grep`, `ruff check`.
2. **LOCAL_MUTATION** (Safe with warning): `git add`, `pytest --fix`, `ruff format`.
3. **HIGH_RISK / DESTRUCTIVE** (Blocked / Requires confirmation): `rm -rf`, `git push --force`, `curl | sh`, `DROP TABLE`, editing files outside repo root.

## Implementation Tasks
- [ ] Implement `tools/sandbox_check.py` with standard library `shlex` and regex.
- [ ] Add JSON output support.
- [ ] Add unit tests in `tests/test_sandbox.py` with 50+ common commands.
- [ ] Document integration in `AGENTS.md`.

## Acceptance Criteria
- Safely flags destructive commands and classifies standard read-only commands without false positives.
- Pure Python 3.11+.
