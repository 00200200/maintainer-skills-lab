"""Arena unit checks: all container process execution is mocked."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from evals.arena import cli, runner
from evals.arena.scenarios import mini_scenarios
from tools import container_sandbox as sandbox


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.scenarios = mini_scenarios()
        self.script_paths = []
        runtime = patch.object(sandbox, "detect_container_runtime", return_value="docker")
        self.detect = runtime.start()
        self.addCleanup(runtime.stop)
        controls = patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "sha256:local-image\n", ""),
        )
        self.control = controls.start()
        self.addCleanup(controls.stop)
        self.original_executor = sandbox.execute_sandbox
        execution = patch.object(sandbox, "execute_sandbox", side_effect=self.successful_execution)
        self.execute = execution.start()
        self.addCleanup(execution.stop)

    def execution(self, index=0, status="COMPLETED", code=0, stdout=None, stderr=""):
        return sandbox.SandboxResult(
            status=status,
            exit_code=code,
            duration_seconds=0.01,
            timed_out=status == "TIMED_OUT",
            runtime_detected="docker",
            stdout=self.scenarios[index].expected_stdout + "\n" if stdout is None else stdout,
            stderr=stderr,
            security=sandbox.SecurityConfig(memory_limit=runner.MEMORY, cpu_limit=runner.CPUS),
        )

    def successful_execution(self, **kwargs):
        path = kwargs["script_path"]
        self.script_paths.append(path)
        index = next(i for i, item in enumerate(self.scenarios) if item.id == path.stem)
        self.assertEqual(path.read_text(encoding="utf-8"), self.scenarios[index].source)
        return self.execution(index)

    def test_five_fixed_benign_scenarios_and_existing_harness_helpers(self):
        self.assertEqual(self.scenarios, mini_scenarios())
        self.assertEqual(len({item.id for item in self.scenarios}), 5)
        self.assertEqual(len({item.expected_stdout for item in self.scenarios}), 5)
        for item in self.scenarios:
            compile(item.source, item.id, "exec")
            self.assertIn("sys.version_info < (3, 11) or not __debug__", item.source)
        with (
            patch("evals.arena.scenarios.wrap_untrusted_input", return_value="framed") as frame,
            patch(
                "evals.arena.scenarios.redact_sensitive_content", return_value=("redacted", [])
            ) as redact,
        ):
            mini_scenarios()
        frame.assert_called_once()
        redact.assert_called_once()
        self.control.assert_not_called()
        self.execute.assert_not_called()

    def test_all_pass_uses_shared_sandbox_and_removes_host_fixture_files(self):
        with (
            patch(
                "evals.behavior_harness.get_current_git_commit",
                side_effect=AssertionError("No Git"),
            ),
            patch(
                "evals.injection_harness.generate_simulated_safe_response",
                side_effect=AssertionError("No simulated agents"),
            ),
        ):
            report = runner.run_mini()
        self.assertEqual(report.status, "PASS")
        self.assertEqual(report.summary["PASS"], 5)
        self.assertEqual(self.execute.call_count, 5)
        names = set()
        for call in self.execute.call_args_list:
            args = call.kwargs
            self.assertFalse(args["allow_network"])
            self.assertFalse(args["mount_workspace"])
            self.assertEqual(args["timeout_seconds"], runner.TIMEOUT_SECONDS)
            self.assertEqual(args["memory"], runner.MEMORY)
            self.assertEqual(args["cpus"], runner.CPUS)
            self.assertEqual(args["runtime_override"], "docker")
            self.assertTrue(args["pull_never"])
            self.assertRegex(args["container_name"], r"^msl-arena-[a-f0-9]{32}$")
            names.add(args["container_name"])
        self.assertEqual(len(names), 5)
        self.assertTrue(all(not path.exists() for path in self.script_paths))
        self.control.assert_called_once_with(
            ["docker", "image", "inspect", "--format", "{{.Id}}", runner.DEFAULT_IMAGE],
            capture_output=True,
            text=True,
            timeout=runner.CONTROL_TIMEOUT_SECONDS,
            check=False,
        )
        data = report.to_dict()
        self.assertFalse(data["agent_evaluation"])
        self.assertEqual(data["evidence_kind"], "infrastructure-smoke")
        self.assertEqual(data["limits"]["network"], "none")

    def test_shared_builder_adds_named_offline_container_without_changing_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "probe.py"
            path.write_text("print('probe')", encoding="utf-8")
            args = sandbox.build_container_args(
                "podman",
                script_path=path,
                memory=runner.MEMORY,
                cpus=runner.CPUS,
                pull_never=True,
                container_name="msl-arena-probe",
            )
            self.assertIn("--pull=never", args)
            self.assertEqual(args[args.index("--name") + 1], "msl-arena-probe")
            self.assertEqual(args[args.index("--network") + 1], "none")
            self.assertEqual(args[args.index("--memory") + 1], runner.MEMORY)
            self.assertEqual(args[args.index("--cpus") + 1], runner.CPUS)
            self.assertIn("--read-only", args)
            self.assertIn(f"{path.resolve()}:/repro/probe.py:ro", args)
            defaults = sandbox.build_container_args("docker", script_path=path)
            self.assertNotIn("--name", defaults)
            self.assertNotIn("--pull=never", defaults)

    def test_no_runtime_reports_five_unavailable_not_success(self):
        self.detect.return_value = None
        report = runner.run_mini()
        self.assertEqual(report.status, "UNAVAILABLE")
        self.assertEqual(report.summary["UNAVAILABLE"], 5)
        self.assertEqual(report.summary["PASS"], 0)
        self.assertTrue(all(item.execution is None for item in report.results))
        self.control.assert_not_called()
        self.execute.assert_not_called()

    def test_shared_executor_forwards_offline_and_cleanup_identity_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "probe.py"
            path.write_text("print('probe')", encoding="utf-8")
            result = self.original_executor(
                script_path=path,
                runtime_override="docker",
                pull_never=True,
                container_name="msl-arena-probe",
            )
        self.assertEqual(result.status, "COMPLETED")
        args = self.control.call_args.args[0]
        self.assertIn("--pull=never", args)
        self.assertEqual(args[args.index("--name") + 1], "msl-arena-probe")

    def test_missing_image_daemon_and_preflight_timeouts_are_unavailable(self):
        cases = (
            subprocess.CompletedProcess([], 1, "", "image or daemon unavailable"),
            subprocess.CompletedProcess([], 0, "", ""),
            OSError("daemon unavailable"),
            subprocess.TimeoutExpired("image inspect", runner.CONTROL_TIMEOUT_SECONDS),
        )
        for response in cases:
            with self.subTest(response=response):
                self.control.side_effect = response if isinstance(response, Exception) else None
                self.control.return_value = response
                report = runner.run_mini()
                self.assertEqual(report.status, "UNAVAILABLE")
                self.assertEqual(report.summary["UNAVAILABLE"], 5)
        self.execute.assert_not_called()

    def test_podman_runtime_is_reused(self):
        self.detect.return_value = "podman"
        report = runner.run_mini()
        self.assertEqual(report.runtime, "podman")
        self.assertEqual(self.control.call_args.args[0][0], "podman")
        self.assertTrue(
            all(call.kwargs["runtime_override"] == "podman" for call in self.execute.call_args_list)
        )

    def test_fail_timeout_unavailable_and_marker_mismatch_are_distinct(self):
        self.execute.side_effect = [
            self.execution(0),
            self.execution(1, code=1),
            self.execution(2, status="TIMED_OUT", code=124),
            self.execution(3, status="RUNTIME_UNAVAILABLE", code=127),
            self.execution(4, stdout="wrong marker"),
        ]
        report = runner.run_mini()
        self.assertEqual(
            [item.status for item in report.results],
            ["PASS", "FAIL", "TIMEOUT", "UNAVAILABLE", "FAIL"],
        )
        self.assertEqual(report.status, "FAIL")
        self.assertEqual(report.summary["TIMEOUT"], 1)
        cleanup_calls = self.control.call_args_list[1:]
        self.assertEqual(len(cleanup_calls), 2)
        for cleanup, invocation in zip(
            cleanup_calls, self.execute.call_args_list[2:4], strict=True
        ):
            self.assertEqual(
                cleanup.args[0], ["docker", "rm", "--force", invocation.kwargs["container_name"]]
            )
            self.assertEqual(cleanup.kwargs["timeout"], runner.CONTROL_TIMEOUT_SECONDS)

    def test_runtime_start_codes_and_errors_never_pass(self):
        for status, code in (
            ("COMPLETED", 125),
            ("COMPLETED", 126),
            ("COMPLETED", 127),
            ("ERROR", 1),
        ):
            with self.subTest(status=status, code=code):
                self.execute.side_effect = [self.execution(i, status, code) for i in range(5)]
                report = runner.run_mini()
                self.assertEqual(report.summary["UNAVAILABLE"], 5)
                self.assertEqual(report.summary["PASS"], 0)

    def test_unexpected_security_settings_or_status_fail(self):
        for execution in (
            replace(self.execution(), security=sandbox.SecurityConfig(network="bridge")),
            replace(self.execution(), status="UNKNOWN"),
        ):
            with self.subTest(execution=execution):
                self.execute.side_effect = None
                self.execute.return_value = execution
                report = runner.run_mini()
                self.assertEqual(report.status, "FAIL")
                self.assertEqual(report.summary["PASS"], 0)

    def test_timeout_cleanup_failure_remains_visible(self):
        self.execute.side_effect = [self.execution(i, "TIMED_OUT", 124) for i in range(5)]
        self.control.side_effect = [subprocess.CompletedProcess([], 0, "sha256:local", "")] + [
            subprocess.TimeoutExpired("container rm", runner.CONTROL_TIMEOUT_SECONDS)
        ] * 5
        report = runner.run_mini()
        self.assertEqual(report.status, "TIMEOUT")
        self.assertTrue(all(item.cleanup_error for item in report.results))
        self.assertIn("container may remain", runner.markdown_report(report))

    def test_unexpected_invocation_error_is_recorded_and_cleaned_up(self):
        self.execute.side_effect = RuntimeError("fixture invocation failed")
        report = runner.run_mini()
        self.assertEqual(report.summary["FAIL"], 5)
        self.assertEqual(self.control.call_count, 6)

    def test_interrupt_attempts_named_cleanup_and_propagates(self):
        self.execute.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            runner.run_mini()
        self.assertEqual(self.control.call_count, 2)
        self.assertEqual(self.control.call_args.args[0][1:3], ["rm", "--force"])

    def test_diagnostics_reuse_redaction_and_output_bounds(self):
        secret = "ghp_" + "B" * 36
        self.execute.side_effect = [
            self.execution(i, stdout="wrong " + secret, stderr="x" * 20_000) for i in range(5)
        ]
        report = runner.run_mini()
        serialized = json.dumps(report.to_dict())
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED_SECRET]", serialized)
        self.assertLess(len(report.results[0].execution.stderr), 11_000)

    def test_markdown_summary_and_json_do_not_claim_agent_evaluation(self):
        report = runner.run_mini()
        markdown = runner.markdown_report(report)
        self.assertIn("no model, agent run or resistance evaluation", markdown)
        self.assertIn("PASS: 5", markdown)
        self.assertNotIn("Attack Success Rate", markdown)
        self.assertNotIn("DEFENDED", markdown)
        data = json.loads(json.dumps(report.to_dict()))
        self.assertEqual(len(data["results"]), 5)
        self.assertFalse(data["agent_evaluation"])
        self.assertEqual(data["summary"]["PASS"], 5)

    def test_empty_or_skipped_report_is_not_success(self):
        report = runner.ArenaReport(image=runner.DEFAULT_IMAGE, runtime=None)
        self.assertEqual(report.status, "UNAVAILABLE")
        report.results = [runner.ArenaResult("one", "Not run", "SKIPPED", "Skipped fixture")]
        self.assertEqual(report.status, "SKIPPED")

    def test_markdown_escapes_runtime_diagnostics(self):
        report = runner.run_mini()
        report.results[
            0
        ].reason = "<script>alert(1)</script> | [link](https://example.invalid)\nnext"
        markdown = runner.markdown_report(report)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("[link]", markdown)
        self.assertIn("&lt;script&gt;", markdown)
        self.assertIn("&#124;", markdown)

    def test_cli_writes_markdown_and_optional_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            markdown = Path(temporary) / "reports/arena.md"
            structured = Path(temporary) / "reports/arena.json"
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = cli.main(
                    [
                        "--benchmark",
                        "mini",
                        "--report",
                        str(markdown),
                        "--output-json",
                        str(structured),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), markdown.read_text().strip())
            self.assertEqual(json.loads(structured.read_text())["status"], "PASS")

    def test_cli_unavailable_and_failures_have_nonzero_exit_codes(self):
        self.detect.return_value = None
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(cli.main(["--benchmark", "mini"]), 2)
        self.assertIn("UNAVAILABLE: 5", stdout.getvalue())
        self.detect.return_value = "docker"
        for status, code in (("COMPLETED", 1), ("TIMED_OUT", 124)):
            self.execute.side_effect = [self.execution(i, status, code) for i in range(5)]
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(cli.main(["--benchmark", "mini"]), 1)

    def test_cli_rejects_unknown_benchmarks_invalid_images_and_output_collision(self):
        for args in (
            ["--benchmark", "swe-bench"],
            ["--benchmark", "mini", "--report", "same", "--output-json", "same"],
        ):
            with (
                self.subTest(args=args),
                patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                cli.main(args)
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(cli.main(["--benchmark", "mini", "--image=-unsafe"]), 1)
        self.execute.assert_not_called()

    def test_cli_report_write_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(cli.main(["--benchmark", "mini", "--report", temporary]), 1)
            self.assertIn("Arena error", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
