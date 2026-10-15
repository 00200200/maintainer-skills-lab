# [Architecture / Runtime] MSL-Sandbox: MicroVM / Seccomp Time-Travel Execution Sandbox for Autonomous Code Verification

**Labels**: `security`, `architecture`, `help wanted`

## Context & Problem
When autonomous maintainer skills (such as `mkl-reproduce-bug`, `mkl-verify-fix`, and `mkl-bisect-regression`) run untrusted code supplied in issue reports or candidate pull request patches, executing those commands directly on the host machine presents critical risks:
1. **Security Vulnerabilities & Remote Code Execution**: Malicious issue descriptions, poisoned lockfiles, or hostile reproduction scripts can access host secrets (`~/.ssh`, `~/.aws`, `~/.env`), tamper with local git branches, or establish reverse shells.
2. **Host Workspace Contamination**: Failed test runs frequently leave dirty temporary files, untracked SQLite caches, orphaned background daemons, or modified dependencies that break subsequent developer workflows.
3. **Lack of Checkpointing & Rollback**: When an agent attempts a speculative multi-step refactor or trial test run that fails catastrophically, unwinding the side effects requires complex git recovery rather than an instantaneous VM/container state rewind.

MaintainerSkillsLab requires **MSL-Sandbox** (`tools/sandbox/`), a deterministic, lightweight execution sandbox engine supporting Apple Virtualization.framework, Linux Firecracker / unshare / seccomp-bpf, and disposable OCI containers.

```
       ┌────────────────────────────────────────────────────────┐
       │             Maintainer Agent Execution Request          │
       │           (Run reproduction / Run test suite)          │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │             MSL-Sandbox Supervisor Daemon              │
       │    (Isolation Policy, Resource Limits, Syscall Filter)  │
       └───────────────────────────┬────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
       ┌────────────────────────┐    ┌────────────────────────┐
       │   Read-Only RootFS     │    │ Copy-On-Write OverlayFS│
       │  (Host Python/Binaries)│    │   (Disposable Edits)   │
       └────────────────────────┘    └────────────────────────┘
                    │                             │
                    └──────────────┬──────────────┘
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │             Disposable Micro-Execution Jail            │
       │     (Network Isolated, Time-Travel Checkpoint Snap)    │
       └────────────────────────────────────────────────────────┘
```

## Prior Art & Industry Benchmarks
- **SWE-bench / OpenHands Sandbox**: Docker-based execution environments used for rigorous benchmark evaluation of coding agents.
- **Dagger.io / Fly.io Firecracker MicroVMs**: Sub-second ephemeral virtual machines with hardware-level isolation and copy-on-write root filesystems.
- **Bubblewrap / systemd-nspawn**: Unprivileged Linux container runtimes using namespaces and seccomp filters.
- **macOS `sandbox-exec` / Apple Virtualization framework**: Lightweight hardware-isolated virtualization on Apple Silicon.

## Proposed Architecture & Components

### 1. Sandbox Supervisor & Engine (`tools/sandbox/engine.py`)
- Platform-adaptive execution abstraction:
  - **Linux**: Unprivileged user namespaces (`unshare -U -m -n -p`), bind mounts, and `seccomp-bpf` syscall filters.
  - **macOS**: `sandbox-exec` profiles and Apple Virtualization microVM backend.
  - **Fallback**: Docker / Podman disposable container runner (`--rm --network=none --read-only`).
- Enforces strict limits: CPU timeout (default: 30s), Memory ceiling (default: 1GB), Disk write cap (default: 200MB), Zero network egress unless explicitly authorized (`--allow-net`).

### 2. Copy-On-Write Workspace Layer (`tools/sandbox/overlay.py`)
- Mounts the target repository as a read-only base layer.
- Adds an ephemeral temporary directory (`/tmp/msl_cow_XXXXXX`) as the writable upper overlay.
- Any file edited, created, or deleted by the agent or test runner exists exclusively in the overlay layer.
- Upon completion or teardown, the upper layer is deleted in 10ms, leaving the host repository completely pristine.

### 3. Checkpoint & Time-Travel Rollback (`tools/sandbox/snapshot.py`)
- Provides explicit checkpointing:
  ```bash
  python3 tools/sandbox/cli.py checkpoint create --name "pre_refactor"
  # Agent runs speculative edits and test executions
  python3 tools/sandbox/cli.py checkpoint rollback --name "pre_refactor"
  ```
- Allows autonomous agents to branch multiple trial hypotheses concurrently without fear of irrecoverable side effects.

### 4. Syscall & Mutation Telemetry (`tools/sandbox/audit.py`)
- Intercepts and logs all attempted filesystem modifications, subprocess forks, and network connection attempts.
- Generates an audit report (`audit.json`) containing:
  - Exact files created, modified, or accessed.
  - Maximum memory and wall-clock execution time.
  - Blocked syscalls (e.g. attempted socket connection or privilege escalation).

### 5. CLI Interface (`tools/sandbox/cli.py`)
- Commands:
  ```bash
  # Execute an untrusted reproduction script in complete isolation
  python3 tools/sandbox/cli.py run --cmd "python3 repro.py" --timeout 15
  
  # Run test suite with copy-on-write filesystem
  python3 tools/sandbox/cli.py run --cmd "pytest tests/test_fast.py" --cow
  
  # Check system capabilities (seccomp, namespaces, virtualization)
  python3 tools/sandbox/cli.py doctor
  ```

## Implementation Tasks
- [ ] Implement `tools/sandbox/engine.py` with Linux namespaces/seccomp and Docker/macOS backends.
- [ ] Implement copy-on-write overlay filesystem manager in `tools/sandbox/overlay.py`.
- [ ] Implement checkpoint / rollback snapshots in `tools/sandbox/snapshot.py`.
- [ ] Implement security audit logger in `tools/sandbox/audit.py`.
- [ ] Add CLI interface in `tools/sandbox/cli.py` with `run`, `checkpoint`, and `doctor` commands.
- [ ] Add integration with `skills/mkl-reproduce-bug/SKILL.md` and `skills/mkl-verify-fix/SKILL.md`.
- [ ] Implement security test suite in `tests/test_sandbox_kernel.py` verifying defense against directory escapes (`../../etc/passwd`), network leaks, and host file dirtying.
- [ ] Author documentation in `docs/architecture/sandbox.md`.

## Acceptance Criteria
- Executes commands with zero mutation to the underlying host repository when `--cow` is active.
- Blocks unauthorized network access (`socket.connect`) and file writes outside designated sandbox scope.
- Cold boot to command execution overhead is under 200ms.
- 100% test pass rate across unit and security regression tests in `tests/test_sandbox_kernel.py`.
