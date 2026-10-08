# [Feature] Disposable Micro-Container Isolation Runner (tools/container_sandbox.py)

**Labels**: `enhancement`, `security`, `help wanted`

## Context & Problem
The `mkl-reproduce-bug` and `mkl-verify-fix` skills instruct autonomous AI agents to execute reproduction scripts provided in external GitHub issues to confirm reported defects.

When dealing with untrusted public issues, running user-supplied code directly on the host machine presents severe security hazards:
- **Credential Exfiltration**: A malicious script can read `~/.ssh/id_rsa`, `~/.aws/credentials`, `~/.gitconfig`, or current shell environment variables (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`) and POST them to an external server.
- **Host Sabotage**: Accidental or malicious execution of destructive commands (`rm -rf /`, dropping database tables, mutating local configuration).
- **Dynamic Obfuscation**: While `tools/sandbox_check.py` checks static shell commands, static analysis cannot reliably intercept obfuscated Python scripts using dynamic imports (`__import__('os')`), runtime eval (`eval(b64decode(...))`), or malicious C extensions.

To safely reproduce bugs without risking the maintainer's host environment, we need a lightweight, disposable container isolation runner `tools/container_sandbox.py`. It must execute untrusted scripts inside ephemeral, resource-constrained micro-containers (Docker or Podman) with network access disabled by default, strict CPU/memory limits, and automatic cleanup.

## Prior Art & Industry Standards
- **SWE-bench & OpenHands Docker Sandbox**: Executes agent-generated code inside containerized environments with mounted read-only workspace volumes.
- **Docker / Podman Security Primitives**: Ephemeral execution (`--rm`), network isolation (`--network none`), memory caps (`--memory 512m`), read-only root filesystems (`--read-only`), and dropped capabilities (`--cap-drop ALL`).
- **Google gVisor / Firecracker**: Virtualized application sandboxing for executing untrusted user code.

## Proposed Solution
Create `tools/container_sandbox.py`:
- Zero external Python dependencies: uses standard library `subprocess`, `shlex`, `json`, `argparse`.
- Automatically detects available container runtimes (`docker` or `podman`).
- Enforces strict security defaults:
  - `--rm`: Container is completely destroyed upon termination.
  - `--network none`: Network access disabled by default to prevent data exfiltration.
  - `--memory 512m --cpus 1.0`: Strict resource bounding to prevent fork-bombs and denial-of-service.
  - `--read-only`: Root filesystem mounted read-only; only a temporary `tmpfs` volume mounted at `/tmp`.
  - Non-root user execution (`--user 1000:1000` or `--security-opt no-new-privileges`).
  - Strict wall-clock execution timeouts (default: 30 seconds).

```bash
# Execute a reproduction script inside an isolated micro-container
python3 tools/container_sandbox.py --script examples/bugfix/repro.py

# Execute with custom timeout and image
python3 tools/container_sandbox.py --script tests/test_leak.py --timeout 10 --image python:3.11-alpine

# Execute arbitrary test command in disposable container
python3 tools/container_sandbox.py --command "pytest tests/repro_test.py" --mount-workspace

# Machine-readable JSON output for agent workflow integration
python3 tools/container_sandbox.py --script repro.py --json
```

### Sandbox Execution Architecture

```
┌────────────────────────────────────────────────────────┐
│             Host Environment / Maintainer Machine      │
│  - SSH keys, AWS credentials, env tokens PROTECTED     │
└───────────────────────────┬────────────────────────────┘
                            │
              Spawns via tools/container_sandbox.py
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│      Ephemeral Micro-Container (Docker / Podman)       │
│                                                        │
│  - Base Image: python:3.11-alpine (~50 MB)             │
│  - Flags: --rm --read-only --network none              │
│  - Limits: --memory 512m --cpus 1.0 --timeout 30s      │
│  - Mounts: Target script -> /repro/script.py (ro)      │
│            /tmp (tmpfs, 64m)                           │
│                                                        │
│  [ Untrusted Reproduction Script Executes Here ]       │
└───────────────────────────┬────────────────────────────┘
                            │ Captures stdout / stderr
                            ▼
┌────────────────────────────────────────────────────────┐
│ Host: Formatted Execution Summary (Exit code, logs)    │
│  - Truncated output to prevent context window spam     │
│  - Zero leftover artifacts on host system              │
└────────────────────────────────────────────────────────┘
```

### JSON Output Schema
```json
{
  "status": "COMPLETED",
  "exit_code": 1,
  "duration_seconds": 1.42,
  "timed_out": false,
  "runtime_detected": "docker",
  "stdout": "F\n================ FAILURES ================\nAssertionError: expected 'slug' got None\n",
  "stderr": "",
  "security": {
    "network": "none",
    "memory_limit": "512m",
    "cpu_limit": "1.0",
    "read_only": true
  }
}
```

### Integration with Skills
Update `skills/mkl-reproduce-bug/SKILL.md`:
- Direct agents to use `tools/container_sandbox.py` instead of raw `python3 <script>` when executing untrusted user reproduction code.
- If Docker/Podman is unavailable, fall back to `tools/sandbox_check.py` with explicit user confirmation warnings.

## Implementation Tasks
- [ ] Implement `tools/container_sandbox.py` with pure standard library modules (`subprocess`, `shlex`, `argparse`, `json`).
- [ ] Implement runtime detection for `docker` and `podman` with actionable diagnostics if neither is present.
- [ ] Support volume mounts for workspace scratch directories with strict read-only flags.
- [ ] Implement execution timeout enforcement with process group cleanup.
- [ ] Integrate output truncation compatible with `tools/log_compressor.py` conventions to protect LLM context windows.
- [ ] Add unit tests in `tests/test_container_sandbox.py` using mocked subprocess invocations (runs offline without requiring live Docker daemon).
- [ ] Update `skills/mkl-reproduce-bug/SKILL.md` and `skills/mkl-verify-fix/SKILL.md` to recommend micro-container isolation.

## Acceptance Criteria
- Zero external Python dependencies; runs cleanly on Python 3.11+.
- Enforces `--network none` and `--rm` defaults on all spawned containers.
- Safely terminates and reports `timed_out: true` when a reproduction script enters an infinite loop.
- Captures stdout/stderr and encapsulates status cleanly in JSON and human-readable terminal formats.
- All unit tests pass in `tests/test_container_sandbox.py` with mock subprocess calls without requiring Docker to be installed in CI.
