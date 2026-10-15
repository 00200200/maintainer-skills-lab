"""tools/container_sandbox.py - Disposable micro-container isolation runner.

Executes untrusted reproduction scripts and test commands inside ephemeral,
resource-constrained micro-containers (Docker or Podman) to protect the maintainer's
host environment from credential exfiltration and destructive sabotage.

Key Security Defaults:
- Automatic cleanup: --rm
- Network isolation: --network none
- Resource bounds: --memory 512m, --cpus 1.0
- Filesystem safety: --read-only root with temporary tmpfs at /tmp
- Execution timeout: 30 seconds default (guaranteed termination)

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SecurityConfig:
    network: str = "none"
    memory_limit: str = "512m"
    cpu_limit: str = "1.0"
    read_only: bool = True
    tmpfs_mounted: bool = True


@dataclass
class SandboxResult:
    status: str  # "COMPLETED" | "TIMED_OUT" | "RUNTIME_UNAVAILABLE" | "ERROR"
    exit_code: int
    duration_seconds: float
    timed_out: bool
    runtime_detected: str | None
    stdout: str
    stderr: str
    security: SecurityConfig = field(default_factory=SecurityConfig)


def detect_container_runtime() -> str | None:
    """Detects available container runtime on system PATH (prefers podman or docker)."""
    for runtime in ("podman", "docker"):
        path = shutil.which(runtime)
        if path:
            return runtime
    return None


def truncate_output(text: str, max_lines: int = 150, max_chars: int = 10_000) -> str:
    """Truncates verbose output to prevent context window saturation."""
    lines = text.splitlines()
    if len(lines) <= max_lines and len(text) <= max_chars:
        return text

    truncated_lines = lines[:max_lines]
    out = "\n".join(truncated_lines)
    if len(out) > max_chars:
        out = out[:max_chars]

    omitted_count = max(0, len(lines) - len(truncated_lines))
    return f"{out}\n\n[... {omitted_count} lines truncated to protect context budget ...]"


def build_container_args(
    runtime: str,
    image: str = "python:3.11-alpine",
    script_path: Path | None = None,
    command: str | None = None,
    mount_workspace: bool = False,
    allow_network: bool = False,
    memory: str = "512m",
    cpus: str = "1.0",
) -> list[str]:
    """Assembles container CLI command with strict security and isolation flags."""
    args = [
        runtime,
        "run",
        "--rm",
        "--interactive",
    ]

    # 1. Network isolation
    if allow_network:
        pass  # default bridge network
    else:
        args.extend(["--network", "none"])

    # 2. Resource limits
    args.extend(["--memory", memory])
    args.extend(["--cpus", cpus])

    # 3. Read-only filesystem with scoped tmpfs
    args.append("--read-only")
    args.extend(["--tmpfs", "/tmp:rw,size=64m"])

    # 4. Mounts and working directory
    container_cmd: list[str] = []
    if script_path is not None:
        abs_script = script_path.resolve()
        script_name = abs_script.name
        # Mount single script into /repro/
        args.extend(["-v", f"{abs_script}:/repro/{script_name}:ro"])
        args.extend(["-w", "/repro"])
        if command:
            container_cmd = ["sh", "-c", command]
        else:
            container_cmd = ["python3", f"/repro/{script_name}"]
    elif mount_workspace:
        cwd = Path.cwd().resolve()
        args.extend(["-v", f"{cwd}:/workspace:ro"])
        args.extend(["-w", "/workspace"])
        if command:
            container_cmd = ["sh", "-c", command]
        else:
            container_cmd = ["sh"]
    else:
        args.extend(["-w", "/tmp"])
        if command:
            container_cmd = ["sh", "-c", command]
        else:
            container_cmd = ["python3", "-c", "print('Sandbox initialized')"]

    args.append(image)
    args.extend(container_cmd)

    return args


def execute_sandbox(
    script_path: Path | None = None,
    command: str | None = None,
    timeout_seconds: int = 30,
    image: str = "python:3.11-alpine",
    mount_workspace: bool = False,
    allow_network: bool = False,
    memory: str = "512m",
    cpus: str = "1.0",
    runtime_override: str | None = None,
) -> SandboxResult:
    """Executes target script or command inside an ephemeral micro-container."""
    runtime = runtime_override or detect_container_runtime()
    sec_config = SecurityConfig(
        network="bridge" if allow_network else "none",
        memory_limit=memory,
        cpu_limit=cpus,
        read_only=True,
        tmpfs_mounted=True,
    )

    if not runtime:
        return SandboxResult(
            status="RUNTIME_UNAVAILABLE",
            exit_code=127,
            duration_seconds=0.0,
            timed_out=False,
            runtime_detected=None,
            stdout="",
            stderr="No container runtime (podman or docker) detected on PATH.",
            security=sec_config,
        )

    if script_path is not None and not script_path.exists():
        return SandboxResult(
            status="ERROR",
            exit_code=1,
            duration_seconds=0.0,
            timed_out=False,
            runtime_detected=runtime,
            stdout="",
            stderr=f"Reproduction script not found: {script_path}",
            security=sec_config,
        )

    cmd_args = build_container_args(
        runtime=runtime,
        image=image,
        script_path=script_path,
        command=command,
        mount_workspace=mount_workspace,
        allow_network=allow_network,
        memory=memory,
        cpus=cpus,
    )

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration = round(time.time() - start_time, 2)
        return SandboxResult(
            status="COMPLETED",
            exit_code=proc.returncode,
            duration_seconds=duration,
            timed_out=False,
            runtime_detected=runtime,
            stdout=truncate_output(proc.stdout),
            stderr=truncate_output(proc.stderr),
            security=sec_config,
        )
    except subprocess.TimeoutExpired as exc:
        duration = round(time.time() - start_time, 2)
        stdout_txt = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr_txt = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        return SandboxResult(
            status="TIMED_OUT",
            exit_code=124,
            duration_seconds=duration,
            timed_out=True,
            runtime_detected=runtime,
            stdout=truncate_output(stdout_txt),
            stderr=f"Execution timed out after {timeout_seconds} seconds.\n{truncate_output(stderr_txt)}",
            security=sec_config,
        )
    except OSError as exc:
        duration = round(time.time() - start_time, 2)
        return SandboxResult(
            status="ERROR",
            exit_code=1,
            duration_seconds=duration,
            timed_out=False,
            runtime_detected=runtime,
            stdout="",
            stderr=f"Failed to spawn container process: {exc}",
            security=sec_config,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Disposable micro-container sandbox runner for untrusted scripts."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--script", "-s", type=Path, help="Path to Python script to isolate")
    group.add_argument("--command", "-c", type=str, help="Command string to run inside container")

    parser.add_argument(
        "--timeout", "-t", type=int, default=30, help="Execution timeout in seconds (default: 30)"
    )
    parser.add_argument(
        "--image",
        "-i",
        default="python:3.11-alpine",
        help="Base container image (default: python:3.11-alpine)",
    )
    parser.add_argument("--memory", default="512m", help="Memory limit cap (default: 512m)")
    parser.add_argument("--cpus", default="1.0", help="CPU quota limit (default: 1.0)")
    parser.add_argument(
        "--mount-workspace", action="store_true", help="Mount current workspace as read-only volume"
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Allow container network access (default: isolated)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print container execution command without running"
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON result")

    args = parser.parse_args(argv)

    runtime = detect_container_runtime()

    if args.dry_run:
        rt = runtime or "docker"
        cmd = build_container_args(
            runtime=rt,
            image=args.image,
            script_path=args.script,
            command=args.command,
            mount_workspace=args.mount_workspace,
            allow_network=args.allow_network,
            memory=args.memory,
            cpus=args.cpus,
        )
        print("Dry run container command:")
        print(" ".join(cmd))
        return 0

    res = execute_sandbox(
        script_path=args.script,
        command=args.command,
        timeout_seconds=args.timeout,
        image=args.image,
        mount_workspace=args.mount_workspace,
        allow_network=args.allow_network,
        memory=args.memory,
        cpus=args.cpus,
    )

    if args.json:
        data = asdict(res)
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return 0 if res.status == "COMPLETED" and res.exit_code == 0 else (res.exit_code or 1)

    # Human-readable output
    print(f"\n📦 Container Sandbox Execution ({res.runtime_detected or 'no runtime'}):")
    print(f"   Status:   {res.status} (exit code: {res.exit_code})")
    print(f"   Duration: {res.duration_seconds}s (limit: {args.timeout}s)")
    print(
        f"   Network:  {res.security.network} | Memory: {res.security.memory_limit} | Read-only: {res.security.read_only}\n"
    )

    if res.stdout:
        print("--- Standard Output ---")
        print(res.stdout)
    if res.stderr:
        print("--- Standard Error ---", file=sys.stderr)
        print(res.stderr, file=sys.stderr)

    return 0 if res.status == "COMPLETED" and res.exit_code == 0 else (res.exit_code or 1)


if __name__ == "__main__":
    sys.exit(main())
