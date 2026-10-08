# [Feature] Shadow Git Worktree for Speculative Fix Verification (tools/worktree_sandbox.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Problem & Context
When maintainer agents test speculative bug fixes, run exploratory refactorings, or evaluate alternative patch candidates, they typically modify the user's primary working tree directly. If a speculative patch fails, introduces compilation/syntax errors, or causes test hangs, the maintainer's workspace is left in a dirty, broken state with uncommitted changes, modified timestamps, and leftover untracked artifacts.

The developer is forced to manually intervene with `git reset --hard` or `git clean -fd`, which risks destroying their own uncommitted edits. Furthermore, because testing occurs in the main working tree, agents cannot evaluate multiple competing hypotheses or candidate patches in parallel without constant branch switching and build artifact collisions.

## Prior Art & Industry Standards
- **Cursor / GitHub Copilot Shadow Workspaces**: Leading AI IDEs utilize shadow workspaces in the background to speculatively apply completions, compile code, and run language server diagnostics before presenting suggestions to the user.
- **Git Worktree (`git worktree`)**: Native Git feature allowing multiple working trees to be linked to a single `.git` repository. Creating a worktree takes milliseconds (< 50ms), shares the object database without duplicating repository history, and isolates file modifications completely.
- **SWE-bench & Docker Test Environments**: Use isolated containers for evaluating code patches, but container spin-up introduces significant latency (5–30 seconds) compared to instantaneous git worktrees.

## Proposed Solution
Build `tools/worktree_sandbox.py` to provide lightweight, ephemeral Git worktrees for speculative patch execution and validation:

```bash
# Apply and verify a candidate patch speculatively in an isolated worktree
python3 tools/worktree_sandbox.py run \
  --patch /tmp/candidate_fix.diff \
  --cmd "pytest tests/test_core.py -q --tb=short" \
  --timeout 60

# Run a custom verification script in a dedicated ephemeral worktree
python3 tools/worktree_sandbox.py run \
  --branch speculative-branch-v1 \
  --cmd "python3 -m py_compile src/core.py"
```

### Architecture Details
1. **Lifecycle & Worktree Management**:
   - Creates an isolated ephemeral worktree directory located under `.git/mkl-shadow/<uuid>` (or within a system temporary directory pointing to `.git`).
   - Uses `git worktree add --detach <sandbox-path> HEAD` to instantly branch from the current commit without checking out or disturbing uncommitted files in the primary tree.
   - Applies candidate patches via `git apply --check` followed by `git apply`.
2. **Context Manager Guarantees**:
   - Enforces automatic, robust teardown using Python's `contextlib.contextmanager`.
   - On completion, command timeout, process interrupt (`SIGINT`), or unhandled exception, executes `git worktree remove --force <sandbox-path>` and removes any leftover temporary directory.
   - Primary working tree index, working tree files, and `git status` remain 100% untouched.
3. **Structured Diagnostic Output**:
   - Captures process exit code, stdout, stderr, and elapsed execution time.
   - Outputs structured JSON or clean terminal logs:
     ```json
     {
       "status": "passed",
       "exit_code": 0,
       "duration_ms": 420,
       "patch_applied": true,
       "output_summary": "1 passed in 0.12s"
     }
     ```
   - Integrates with `tools/log_compressor.py` to compress verbose output before returning it to the agent.

## Implementation Tasks
- [ ] Implement `tools/worktree_sandbox.py` with standard library `subprocess`, `tempfile`, `pathlib`, and `signal`.
- [ ] Implement `ShadowWorktree` context manager handling setup, patch application, execution, and guaranteed teardown.
- [ ] Add CLI arguments: `--patch`, `--cmd`, `--timeout`, `--base-commit`, `--json`, and `--keep-on-failure` (for manual debugging).
- [ ] Ensure proper signal handling (`SIGINT`, `SIGTERM`) to prevent orphaned git worktrees when interrupted.
- [ ] Add helper function `is_worktree_supported(repo_path: Path) -> bool` to check Git repository health before spawning worktrees.
- [ ] Add unit and integration tests in `tests/test_worktree_sandbox.py` verifying clean setup, isolation from host repository, patch testing, and teardown.
- [ ] Reference `worktree_sandbox.py` in `skills/mkl-reproduce-bug/SKILL.md` and `skills/mkl-resolve-merge-conflict/SKILL.md`.

## Acceptance Criteria
- Spawning, executing a command, and tearing down an ephemeral worktree incurs under 500ms of harness overhead.
- Running speculative patches never alters `git status` or file contents in the host working directory.
- Worktrees are guaranteed to be cleaned up even if the command times out or is killed with `SIGINT`.
- Pure Python 3.11+ using native Git CLI commands.
- All unit tests pass.
