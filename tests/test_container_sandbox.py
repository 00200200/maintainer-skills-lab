"""tests/test_container_sandbox.py - Unit tests for tools/container_sandbox.py.

Tests container runtime detection, security argument construction, output truncation,
timeout handling, JSON serialization, and CLI dry-run execution with mocked subprocesses.
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.container_sandbox import (
    build_container_args,
    detect_container_runtime,
    execute_sandbox,
    main,
    truncate_output,
)


class TestContainerSandbox(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.script_path = Path(self.temp_dir.name) / "repro.py"
        self.script_path.write_text("print('Repro executed')\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_detect_container_runtime_podman(self) -> None:
        with patch(
            "shutil.which", side_effect=lambda cmd: "/usr/bin/podman" if cmd == "podman" else None
        ):
            self.assertEqual(detect_container_runtime(), "podman")

    def test_detect_container_runtime_docker(self) -> None:
        with patch(
            "shutil.which", side_effect=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None
        ):
            self.assertEqual(detect_container_runtime(), "docker")

    def test_detect_container_runtime_none(self) -> None:
        with patch("shutil.which", return_value=None):
            self.assertIsNone(detect_container_runtime())

    def test_build_container_args_defaults(self) -> None:
        args = build_container_args(
            runtime="docker",
            image="python:3.11-alpine",
            script_path=self.script_path,
        )
        self.assertEqual(args[0], "docker")
        self.assertEqual(args[1], "run")
        self.assertIn("--rm", args)
        self.assertIn("--network", args)
        idx = args.index("--network")
        self.assertEqual(args[idx + 1], "none")
        self.assertIn("--read-only", args)
        self.assertIn("--tmpfs", args)
        self.assertIn("--memory", args)
        self.assertIn("--cpus", args)
        self.assertIn(f"{self.script_path.resolve()}:/repro/repro.py:ro", " ".join(args))
        self.assertIn("python:3.11-alpine", args)
        self.assertIn("/repro/repro.py", args)

    def test_build_container_args_allow_network(self) -> None:
        args = build_container_args(
            runtime="docker",
            script_path=self.script_path,
            allow_network=True,
        )
        self.assertNotIn("--network", args)

    def test_truncate_output_short(self) -> None:
        short_text = "line 1\nline 2\nline 3"
        self.assertEqual(truncate_output(short_text, max_lines=10), short_text)

    def test_truncate_output_long(self) -> None:
        long_text = "\n".join(f"line {i}" for i in range(200))
        truncated = truncate_output(long_text, max_lines=20)
        self.assertIn("lines truncated to protect context budget", truncated)
        self.assertIn("line 19", truncated)
        self.assertNotIn("line 150", truncated)

    def test_execute_sandbox_runtime_unavailable(self) -> None:
        with patch("shutil.which", return_value=None):
            res = execute_sandbox(script_path=self.script_path, runtime_override=None)
            self.assertEqual(res.status, "RUNTIME_UNAVAILABLE")
            self.assertEqual(res.exit_code, 127)
            self.assertIn("No container runtime", res.stderr)

    def test_execute_sandbox_script_missing(self) -> None:
        missing_script = Path(self.temp_dir.name) / "missing.py"
        res = execute_sandbox(script_path=missing_script, runtime_override="docker")
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(res.exit_code, 1)
        self.assertIn("not found", res.stderr)

    @patch("subprocess.run")
    def test_execute_sandbox_completed_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["docker", "run"],
            returncode=0,
            stdout="AssertionError: reproduced\n",
            stderr="",
        )
        res = execute_sandbox(script_path=self.script_path, runtime_override="docker")
        self.assertEqual(res.status, "COMPLETED")
        self.assertEqual(res.exit_code, 0)
        self.assertIn("AssertionError", res.stdout)
        self.assertFalse(res.timed_out)

    @patch("subprocess.run")
    def test_execute_sandbox_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["docker", "run"],
            timeout=10,
            output=b"infinite loop output",
            stderr=b"",
        )
        res = execute_sandbox(
            script_path=self.script_path, timeout_seconds=10, runtime_override="docker"
        )
        self.assertEqual(res.status, "TIMED_OUT")
        self.assertEqual(res.exit_code, 124)
        self.assertTrue(res.timed_out)
        self.assertIn("timed out after 10 seconds", res.stderr)

    def test_cli_dry_run(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["--script", str(self.script_path), "--dry-run"])
            self.assertEqual(exit_code, 0)
            output = mock_stdout.getvalue()
            self.assertIn("Dry run container command:", output)
            self.assertIn("--network none", output)

    @patch("tools.container_sandbox.execute_sandbox")
    def test_cli_json_output(self, mock_exec: MagicMock) -> None:
        from tools.container_sandbox import SandboxResult, SecurityConfig

        mock_exec.return_value = SandboxResult(
            status="COMPLETED",
            exit_code=0,
            duration_seconds=1.2,
            timed_out=False,
            runtime_detected="docker",
            stdout="test passed",
            stderr="",
            security=SecurityConfig(),
        )
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            exit_code = main(["--script", str(self.script_path), "--json"])
            self.assertEqual(exit_code, 0)
            data = json.loads(mock_stdout.getvalue())
            self.assertEqual(data["status"], "COMPLETED")
            self.assertEqual(data["security"]["network"], "none")


if __name__ == "__main__":
    unittest.main()
