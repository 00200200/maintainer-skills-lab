#!/usr/bin/env python3
"""Run local tests with quiet, short-traceback defaults for agent-friendly output."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Concise defaults: quiet progress, short traceback, stop on first failure.
PYTEST_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-x")
# unittest has no --tb=short; quiet + failfast is the closest built-in equivalent.
UNITTEST_FLAGS: tuple[str, ...] = ("-q", "-f")

NODE_TEST_COMMAND: tuple[str, ...] = ("npm", "test", "--", "--bail", "--silent")
RUST_TEST_COMMAND: tuple[str, ...] = ("cargo", "test", "--", "--nocapture=false")


def pytest_command(extra: list[str] | None = None, *, executable: str | None = None) -> list[str]:
    """Build a pytest argv with token-efficient defaults."""
    runner = executable or "pytest"
    return [runner, *PYTEST_FLAGS, *(extra or [])]


def unittest_command(extra: list[str] | None = None, *, python: str | None = None) -> list[str]:
    """Build a unittest discover argv with quiet + failfast defaults."""
    interpreter = python or sys.executable
    args = list(extra) if extra else ["discover", "-s", "tests"]
    # Place quiet/failfast after discover subcommand flags when using discover.
    if args and args[0] == "discover":
        return [interpreter, "-m", "unittest", *args, *UNITTEST_FLAGS]
    return [interpreter, "-m", "unittest", *UNITTEST_FLAGS, *args]


def resolve_runner(preferred: str = "auto") -> str:
    """Choose pytest when available; otherwise fall back to unittest."""
    if preferred == "pytest":
        return "pytest"
    if preferred == "unittest":
        return "unittest"
    if preferred != "auto":
        raise ValueError(f"Unknown runner: {preferred!r}")
    if shutil.which("pytest") is not None:
        return "pytest"
    try:
        import pytest  # noqa: F401
    except ImportError:
        return "unittest"
    return "pytest"


def build_command(
    runner: str = "auto",
    extra: list[str] | None = None,
    *,
    python: str | None = None,
) -> list[str]:
    """Return the full command for the selected runner."""
    chosen = resolve_runner(runner)
    if chosen == "pytest":
        executable = shutil.which("pytest") or "pytest"
        return pytest_command(extra, executable=executable)
    return unittest_command(extra, python=python)


def run_tests(
    runner: str = "auto",
    extra: list[str] | None = None,
    *,
    cwd: Path | None = None,
    python: str | None = None,
) -> int:
    """Execute the fast test command and return its exit status."""
    command = build_command(runner, extra, python=python)
    result = subprocess.run(command, cwd=str(cwd or ROOT), check=False)
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run tests with quiet, short-traceback defaults (pytest -q --tb=short -x)."
    )
    parser.add_argument(
        "--runner",
        choices=("auto", "pytest", "unittest"),
        default="auto",
        help="Test runner to use (default: auto prefers pytest when installed)",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print the resolved command and exit without running tests",
    )
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="Additional args after -- are forwarded to the test runner",
    )
    args = parser.parse_args(argv)
    extra = list(args.extra)
    if extra and extra[0] == "--":
        extra = extra[1:]
    command = build_command(args.runner, extra or None)
    if args.print_command:
        print(subprocess.list2cmdline(command))
        return 0
    return run_tests(args.runner, extra or None)


if __name__ == "__main__":
    raise SystemExit(main())
