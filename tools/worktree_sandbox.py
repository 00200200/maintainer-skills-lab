#!/usr/bin/env python3
"""tools/worktree_sandbox.py - Shadow Git Worktree for Speculative Fix Verification.

Creates ephemeral Git worktrees to apply candidate patches and execute test commands
without modifying or dirtying the user's primary working tree.

Standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Generator
from dataclasses import asdict, dataclass
from pathlib import Path

# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class ExecutionResult:
    status: str  # passed, failed, timeout, patch_failed, setup_failed
    exit_code: int
    duration_ms: int
    patch_applied: bool
    stdout: str
    stderr: str
    output_summary: str = ""
    sandbox_path: str = ""


# =============================================================================
# Helper Utilities
# =============================================================================


def get_git_repo_root(cwd: Path | None = None) -> Path | None:
    """Returns repository root Path or None if not inside a git repository."""
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd or Path.cwd(),
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return None


def is_worktree_supported(repo_root: Path) -> bool:
    """Verifies git repository supports `git worktree` operations."""
    proc = subprocess.run(
        ["git", "worktree", "list"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return proc.returncode == 0


def prune_stale_worktrees(repo_root: Path) -> None:
    """Prunes stale git worktrees and cleans up leftover .git/mkl-shadow directories."""
    subprocess.run(["git", "worktree", "prune"], check=False, capture_output=True, cwd=repo_root)
    shadow_root = repo_root / ".git" / "mkl-shadow"
    if shadow_root.exists():
        for item in shadow_root.iterdir():
            if item.is_dir():
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(item)],
                        check=False,
                        capture_output=True,
                        cwd=repo_root,
                    )
                    shutil.rmtree(item, ignore_errors=True)
                except Exception:
                    pass


# =============================================================================
# ShadowWorktree Context Manager
# =============================================================================


@contextlib.contextmanager
def shadow_worktree(
    repo_root: Path,
    base_commit: str = "HEAD",
    keep_on_failure: bool = False,
) -> Generator[Path, None, None]:
    """Context manager creating an isolated ephemeral git worktree with guaranteed cleanup."""
    shadow_dir_id = f"wt-{uuid.uuid4().hex[:10]}"
    shadow_base = repo_root / ".git" / "mkl-shadow"
    shadow_base.mkdir(parents=True, exist_ok=True)
    sandbox_path = shadow_base / shadow_dir_id

    # 1. Create worktree detached from base_commit
    cmd_add = ["git", "worktree", "add", "--detach", str(sandbox_path), base_commit]
    proc_add = subprocess.run(cmd_add, check=False, capture_output=True, text=True, cwd=repo_root)
    if proc_add.returncode != 0:
        raise RuntimeError(f"Failed to create git worktree: {proc_add.stderr.strip()}")

    cleaned_up = False

    def cleanup() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(sandbox_path)],
            check=False,
            capture_output=True,
            cwd=repo_root,
        )
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "prune"], check=False, capture_output=True, cwd=repo_root
        )

    # Register signal handler for graceful interrupt cleanup
    old_sigint = signal.getsignal(signal.SIGINT)
    old_sigterm = signal.getsignal(signal.SIGTERM)

    def handle_signal(sig: int, frame: object) -> None:
        cleanup()
        sys.exit(128 + sig)

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass  # Signal handlers can only be set from main thread

    failed = False
    try:
        yield sandbox_path
    except Exception:
        failed = True
        raise
    finally:
        try:
            signal.signal(signal.SIGINT, old_sigint)
            signal.signal(signal.SIGTERM, old_sigterm)
        except (ValueError, AttributeError):
            pass

        if failed and keep_on_failure:
            sys.stderr.write(f"Notice: Keeping worktree for debugging at: {sandbox_path}\n")
        else:
            cleanup()


# =============================================================================
# Patch Application & Command Runner
# =============================================================================


def apply_patch_to_worktree(sandbox_path: Path, patch_source: str | Path) -> tuple[bool, str]:
    """Applies a patch file or diff string to the sandbox worktree."""
    patch_file_to_remove: Path | None = None
    if isinstance(patch_source, Path) or (
        isinstance(patch_source, str) and Path(patch_source).is_file()
    ):
        patch_path = Path(patch_source).resolve()
    else:
        # Patch content provided as string
        patch_file_to_remove = sandbox_path / ".speculative_patch.diff"
        patch_file_to_remove.write_text(str(patch_source), encoding="utf-8")
        patch_path = patch_file_to_remove

    try:
        # 1. Check if patch applies cleanly
        proc_check = subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            check=False,
            capture_output=True,
            text=True,
            cwd=sandbox_path,
        )
        if proc_check.returncode != 0:
            # Try 3-way merge fallback
            proc_3way = subprocess.run(
                ["git", "apply", "-3", str(patch_path)],
                check=False,
                capture_output=True,
                text=True,
                cwd=sandbox_path,
            )
            if proc_3way.returncode == 0:
                return True, "Applied with 3-way fallback"
            return False, f"Patch apply rejected:\n{proc_check.stderr or proc_3way.stderr}"

        # 2. Apply patch
        proc_apply = subprocess.run(
            ["git", "apply", str(patch_path)],
            check=False,
            capture_output=True,
            text=True,
            cwd=sandbox_path,
        )
        if proc_apply.returncode == 0:
            return True, "Patch applied cleanly"
        return False, f"Patch apply failed: {proc_apply.stderr}"
    finally:
        if patch_file_to_remove and patch_file_to_remove.exists():
            patch_file_to_remove.unlink(missing_ok=True)


def run_command_in_sandbox(
    sandbox_path: Path,
    command: str,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str, bool]:
    """Executes command in sandbox directory. Returns (exit_code, stdout, stderr, is_timeout)."""
    custom_env = os.environ.copy()
    if env:
        custom_env.update(env)

    try:
        proc = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            cwd=sandbox_path,
            timeout=timeout,
            env=custom_env,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as e:
        stdout = (
            e.stdout
            if isinstance(e.stdout, str)
            else (e.stdout.decode("utf-8") if e.stdout else "")
        )
        stderr = (
            e.stderr
            if isinstance(e.stderr, str)
            else (e.stderr.decode("utf-8") if e.stderr else "")
        )
        return -1, stdout, f"Command timed out after {timeout} seconds\n{stderr}", True


def execute_speculative_run(
    repo_root: Path,
    command: str,
    patch: str | Path | None = None,
    base_commit: str = "HEAD",
    timeout: int = 60,
    keep_on_failure: bool = False,
) -> ExecutionResult:
    """Spawns an ephemeral worktree, applies patch (if any), executes command, and tears down."""
    start_time = time.perf_counter()
    patch_applied = False

    try:
        with shadow_worktree(
            repo_root, base_commit=base_commit, keep_on_failure=keep_on_failure
        ) as sandbox_path:
            # 1. Apply patch if provided
            if patch is not None:
                success, msg = apply_patch_to_worktree(sandbox_path, patch)
                if not success:
                    duration = int((time.perf_counter() - start_time) * 1000)
                    return ExecutionResult(
                        status="patch_failed",
                        exit_code=1,
                        duration_ms=duration,
                        patch_applied=False,
                        stdout="",
                        stderr=msg,
                        output_summary=f"Patch rejected: {msg.splitlines()[0] if msg else 'Error'}",
                        sandbox_path=str(sandbox_path),
                    )
                patch_applied = True

            # 2. Run verification command
            code, stdout, stderr, timed_out = run_command_in_sandbox(
                sandbox_path, command, timeout=timeout
            )
            duration = int((time.perf_counter() - start_time) * 1000)

            if timed_out:
                status = "timeout"
                summary = f"Command timed out after {timeout}s"
            elif code == 0:
                status = "passed"
                summary = (stdout.strip().splitlines()[-1] if stdout.strip() else "Passed")[:100]
            else:
                status = "failed"
                summary = (
                    stderr.strip().splitlines()[-1]
                    if stderr.strip()
                    else f"Failed with exit code {code}"
                )[:100]

            return ExecutionResult(
                status=status,
                exit_code=code,
                duration_ms=duration,
                patch_applied=patch_applied,
                stdout=stdout,
                stderr=stderr,
                output_summary=summary,
                sandbox_path=str(sandbox_path),
            )
    except Exception as e:
        duration = int((time.perf_counter() - start_time) * 1000)
        return ExecutionResult(
            status="setup_failed",
            exit_code=1,
            duration_ms=duration,
            patch_applied=False,
            stdout="",
            stderr=str(e),
            output_summary=f"Sandbox setup failed: {e}",
            sandbox_path="",
        )


# =============================================================================
# CLI Interface
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ephemeral Git worktree sandbox for speculative patch verification."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run a command inside an ephemeral git worktree.")
    p_run.add_argument("--cmd", "-c", required=True, help="Command to execute inside worktree.")
    p_run.add_argument("--patch", "-p", help="Patch file or diff string to apply before running.")
    p_run.add_argument(
        "--base-commit",
        default="HEAD",
        help="Base commit or branch to detach from (default: HEAD).",
    )
    p_run.add_argument(
        "--timeout", type=int, default=60, help="Command timeout in seconds (default: 60)."
    )
    p_run.add_argument(
        "--keep-on-failure", action="store_true", help="Preserve worktree directory if run fails."
    )
    p_run.add_argument("--json", action="store_true", help="Output results in JSON format.")

    # Subcommand: clean
    p_clean = subparsers.add_parser("clean", help="Prune any orphaned shadow worktrees.")
    p_clean.add_argument("--json", action="store_true", help="Output results in JSON format.")

    args = parser.parse_args(argv)

    repo_root = get_git_repo_root()
    if not repo_root:
        sys.stderr.write("Error: Current directory is not part of a Git repository.\n")
        return 1

    if not is_worktree_supported(repo_root):
        sys.stderr.write("Error: `git worktree` operations are not supported in this repository.\n")
        return 1

    if args.subcommand == "clean":
        prune_stale_worktrees(repo_root)
        if args.json:
            print(json.dumps({"status": "cleaned", "repo": str(repo_root)}))
        else:
            print(f"✓ Pruned stale worktrees in {repo_root}")
        return 0

    if args.subcommand == "run":
        res = execute_speculative_run(
            repo_root=repo_root,
            command=args.cmd,
            patch=args.patch,
            base_commit=args.base_commit,
            timeout=args.timeout,
            keep_on_failure=args.keep_on_failure,
        )

        if args.json:
            print(json.dumps(asdict(res), indent=2))
        else:
            status_icon = "✓" if res.status == "passed" else "✗"
            print(
                f"{status_icon} Sandbox Run [{res.status.upper()}]: {res.output_summary} ({res.duration_ms}ms)"
            )
            if res.status != "passed":
                if res.stderr:
                    print("\n--- Standard Error ---\n" + res.stderr.strip())
                if res.stdout and res.status != "patch_failed":
                    print("\n--- Standard Output ---\n" + res.stdout.strip())

        return 0 if res.status == "passed" else res.exit_code

    return 0


if __name__ == "__main__":
    sys.exit(main())
