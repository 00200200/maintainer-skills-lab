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
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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
    pull_never: bool = False,
    container_name: str | None = None,
    adapter: bool = False,
) -> list[str]:
    """Assembles container CLI command with strict security and isolation flags."""
    if adapter:
        pull_never = True
    args = [
        runtime,
        "run",
        "--rm",
        "--interactive",
    ]
    if pull_never:
        args.append("--pull=never")
    if container_name is not None:
        args.extend(["--name", container_name])

    # 1. Network isolation
    if allow_network:
        pass  # default bridge network
    else:
        args.extend(["--network", "none"])

    # 2. Resource limits
    args.extend(["--memory", memory])
    args.extend(["--cpus", cpus])
    if adapter:
        if script_path is not None or command is not None or mount_workspace or allow_network:
            raise ValueError("Adapter isolation forbids commands, mounts and network access")
        args.extend(
            [
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--memory-swap",
                memory,
                "--ipc",
                "private",
                "--log-driver",
                "none",
                "--no-healthcheck",
                "--ulimit",
                "core=0",
                "--ulimit",
                "nofile=256:256",
                "--entrypoint",
                "/opt/msl-arena/adapter",
            ]
        )
        if Path(runtime).stem == "podman":
            args.append("--http-proxy=false")

    # 3. Read-only filesystem with scoped tmpfs
    args.append("--read-only")
    args.extend(
        ["--tmpfs", "/tmp:rw,size=64m,nosuid,nodev,noexec" if adapter else "/tmp:rw,size=64m"]
    )

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
        elif adapter:
            container_cmd = ["--protocol-version=1"]
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
    pull_never: bool = False,
    container_name: str | None = None,
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
        pull_never=pull_never,
        container_name=container_name,
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


@dataclass
class BoundedProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    output_limited: bool = False


def local_runtime_args(runtime: str) -> list[str]:
    """Select and verify a local rootless engine for Arena adapters only."""
    executable = shutil.which(runtime)
    if executable is None:
        raise OSError("Container runtime executable is unavailable")
    if runtime == "podman":
        args = [executable, "--remote=false"]
        template = "{{json .Host.Security.Rootless}}"
    elif runtime == "docker":
        if os.name == "nt" or not hasattr(os, "getuid"):
            raise OSError("Arena adapters require a local rootless Unix engine")
        rootless = Path(f"/run/user/{os.getuid()}/docker.sock")
        if not rootless.is_socket():
            raise OSError(
                "Local rootless Docker socket is unavailable; rootful fallback is forbidden"
            )
        args = [executable, "--host", f"unix://{rootless}"]
        template = "{{json .SecurityOptions}}"
    else:
        raise ValueError("Only Docker and Podman are supported")
    try:
        result = run_bounded(
            args + ["info", "--format", template],
            timeout_seconds=5,
            stdout_limit=16_384,
            stderr_limit=4096,
        )
        if result.exit_code or result.timed_out or result.output_limited:
            raise ValueError("Engine info was unavailable or exceeded its limits")
        mode = json.loads(result.stdout.decode("utf-8"))
        confirmed = (
            mode is True
            if runtime == "podman"
            else (
                isinstance(mode, list)
                and all(isinstance(option, str) for option in mode)
                and "name=rootless" in mode
            )
        )
        if not confirmed:
            raise ValueError("Engine did not report rootless mode")
    except (OSError, ValueError, RecursionError) as error:
        raise ValueError(
            "Cannot confirm a local rootless engine; adapter execution is unavailable"
        ) from error
    return args


def run_bounded(
    args: list[str],
    *,
    input_bytes: bytes = b"",
    timeout_seconds: int = 30,
    stdout_limit: int = 65_536,
    stderr_limit: int = 16_384,
) -> BoundedProcessResult:
    """Bound pipe memory while draining concurrently, with no inherited credentials.

    Used only by the opt-in adapter path. The legacy sandbox executor is unchanged.
    Docker gets a fresh HOME/config. Podman retains HOME only to locate its local
    image store, with separate empty auth and container configuration. Runtime
    arguments explicitly select a local engine.
    """
    if (
        not 1 <= timeout_seconds <= 300
        or not 1 <= stdout_limit <= 262_144
        or not 1 <= stderr_limit <= 262_144
    ):
        raise ValueError("Invalid subprocess bounds")
    if len(input_bytes) > 131_072:
        raise ValueError("Adapter request exceeds the input size limit")
    with tempfile.TemporaryDirectory(prefix="msl-arena-runtime-") as home:
        environment = {"PATH": os.defpath, "HOME": home, "DOCKER_CONFIG": home}
        if Path(args[0]).stem == "podman":
            environment["HOME"] = str(Path.home())
            if hasattr(os, "getuid"):
                environment["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
            auth = Path(home) / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            configuration = Path(home) / "containers.conf"
            configuration.write_text(
                "[containers]\nmounts=[]\nvolumes=[]\nenv_host=false\nhttp_proxy=false\n"
                'base_hosts_file="none"\n[engine]\nhooks_dir=[]\n',
                encoding="utf-8",
            )
            environment.update(REGISTRY_AUTH_FILE=str(auth), CONTAINERS_CONF=str(configuration))
            hooks = Path(home) / "hooks"
            hooks.mkdir()
            args = [
                args[0],
                "--default-mounts-file",
                os.devnull,
                "--hooks-dir",
                str(hooks),
                *args[1:],
            ]
        for name in ("SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            cwd=home,
            shell=False,
            bufsize=0,
        )
        buffers = [bytearray(), bytearray()]
        overflow = threading.Event()
        io_failed = threading.Event()

        def drain(stream, buffer, limit):
            try:
                while chunk := stream.read(4096):
                    remaining = limit - len(buffer)
                    buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
                        return
            except OSError:
                io_failed.set()
            finally:
                stream.close()

        def feed():
            try:
                view = memoryview(input_bytes)
                while view:
                    written = process.stdin.write(view)
                    if not written:
                        raise OSError("Adapter input pipe closed")
                    view = view[written:]
            except OSError:
                io_failed.set()
            finally:
                process.stdin.close()

        threads = [
            threading.Thread(
                target=drain, args=(process.stdout, buffers[0], stdout_limit), daemon=True
            ),
            threading.Thread(
                target=drain, args=(process.stderr, buffers[1], stderr_limit), daemon=True
            ),
            threading.Thread(target=feed, daemon=True),
        ]
        start = time.monotonic()
        timed_out = False
        try:
            for thread in threads:
                thread.start()
            while process.poll() is None or any(thread.is_alive() for thread in threads):
                if overflow.is_set() or io_failed.is_set():
                    break
                if time.monotonic() - start >= timeout_seconds:
                    timed_out = True
                    break
                overflow.wait(0.01)
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise OSError("Container runtime process could not be reaped") from error
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=1)
        if any(thread.is_alive() for thread in threads):
            raise OSError("Container runtime pipes did not close")
        if io_failed.is_set() and not (timed_out or overflow.is_set()):
            raise OSError("Container runtime pipe I/O failed")
        return BoundedProcessResult(
            process.returncode, bytes(buffers[0]), bytes(buffers[1]), timed_out, overflow.is_set()
        )


@dataclass
class AdapterResult(SandboxResult):
    output_limited: bool = False
    cleanup_error: str = ""


def execute_adapter(
    *,
    runtime: str,
    image: str,
    request: bytes,
    container_name: str,
    timeout_seconds: int = 60,
) -> AdapterResult:
    """Run the image's fixed adapter, never a shell or scenario-derived command."""
    security = SecurityConfig()
    started = time.monotonic()
    result = AdapterResult("ERROR", 1, 0, False, runtime, "", "", security)
    cleanup_needed = True
    try:
        runtime_args = local_runtime_args(runtime)
    except (OSError, ValueError):
        result.status = "RUNTIME_UNAVAILABLE"
        result.exit_code = 127
        result.stderr = "Cannot confirm a local rootless engine; adapter execution is unavailable"
        return result
    try:
        args = build_container_args(
            runtime,
            image=image,
            pull_never=True,
            container_name=container_name,
            adapter=True,
        )
        execution = run_bounded(
            runtime_args + args[1:],
            input_bytes=request,
            timeout_seconds=timeout_seconds,
        )
        result.exit_code = execution.exit_code
        result.timed_out = execution.timed_out
        result.output_limited = execution.output_limited
        result.status = "TIMED_OUT" if execution.timed_out else "COMPLETED"
        result.stdout = execution.stdout.decode("utf-8", errors="strict")
        result.stderr = execution.stderr.decode("utf-8", errors="replace")
        cleanup_needed = execution.timed_out or execution.output_limited or execution.exit_code != 0
    except UnicodeError:
        result.status = "INVALID_OUTPUT"
        result.stdout = ""
        result.stderr = "Adapter stdout is not valid UTF-8"
    except OSError as error:
        result.status = "ERROR"
        result.stdout = ""
        result.stderr = f"Adapter execution failed: {type(error).__name__}"
    finally:
        # Killing the host CLI does not guarantee container termination.
        if cleanup_needed:
            try:
                cleanup = run_bounded(
                    runtime_args + ["rm", "--force", container_name],
                    timeout_seconds=5,
                    stdout_limit=1024,
                    stderr_limit=1024,
                )
                missing = any(
                    marker in cleanup.stderr.decode("utf-8", errors="replace").lower()
                    for marker in ("no such container", "no container with name or id")
                )
                if (
                    cleanup.timed_out
                    or cleanup.output_limited
                    or (cleanup.exit_code and not missing)
                ):
                    result.cleanup_error = "Container cleanup failed; inspect the local engine."
            except OSError:
                result.cleanup_error = "Container cleanup failed; inspect the local engine."
        result.duration_seconds = round(time.monotonic() - started, 3)
    return result


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
