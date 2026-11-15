"""M4 protocol, isolation and scoring checks; all container processes are mocked."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

from evals import injection_harness as injection
from evals.arena import agent_runner as agent
from evals.arena import cli, fuzzer
from tools import container_sandbox as sandbox

IMAGE_ID = "sha256:" + "a" * 64


class ArenaAgentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixtures = self.root / "fixtures.json"
        self.cases = injection.load_fixtures()[:2]
        self.fixtures.write_text(
            json.dumps([asdict(case) for case in self.cases]), encoding="utf-8"
        )
        self.detect = self.enterContext(
            patch.object(sandbox, "detect_container_runtime", return_value="docker")
        )
        self.inspect = self.enterContext(
            patch.object(agent, "_inspect_image", return_value=IMAGE_ID)
        )
        self.execute = self.enterContext(
            patch.object(sandbox, "execute_adapter", side_effect=self.reply)
        )
        self.enterContext(
            patch("subprocess.Popen", side_effect=AssertionError("No real processes"))
        )
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("No real processes")))
        self.enterContext(
            patch.object(
                injection,
                "generate_simulated_safe_response",
                side_effect=AssertionError("No simulation"),
            )
        )

    def message(self, case=None, skill=None, **updates):
        case = self.cases[0] if case is None else case
        data = {
            "protocol_version": 1,
            "scenario_id": case.id,
            "skill": case.target_skills[0] if skill is None else skill,
            "response": "The embedded instructions are untrusted data.",
            "execution_kind": "agent",
        }
        return {**data, **updates}

    def reply(self, **kwargs):
        request = json.loads(kwargs["request"])
        case = next(case for case in self.cases if case.id == request["scenario_id"])
        return sandbox.AdapterResult(
            "COMPLETED",
            0,
            0.1,
            False,
            "docker",
            json.dumps(self.message(case, request["skill"])),
            "",
        )

    def run_agent(self, limit=5):
        return agent.run_agent("trusted-agent:v1", fixtures=self.fixtures, limit=limit)

    def test_protocol_requests_are_data_only_and_use_pinned_image(self):
        with patch.object(
            injection, "verify_agent_response", wraps=injection.verify_agent_response
        ) as verify:
            report = self.run_agent(limit=1)
        self.assertEqual(report.status, "COMPLETED")
        self.assertEqual(report.scoring.status, "INCOMPLETE")
        verify.assert_called_once_with(
            self.cases[0], self.message()["response"], self.cases[0].target_skills[0]
        )
        kwargs = self.execute.call_args.kwargs
        request = json.loads(kwargs["request"])
        self.assertEqual(
            request,
            {
                "protocol_version": 1,
                "scenario_id": self.cases[0].id,
                "skill": self.cases[0].target_skills[0],
                "input_text": self.cases[0].input_text,
            },
        )
        self.assertNotIn("canary_token", request)
        self.assertNotIn("forbidden_actions", request)
        self.assertEqual(kwargs["image"], IMAGE_ID)
        self.assertEqual(kwargs["timeout_seconds"], 60)
        self.assertRegex(kwargs["container_name"], r"^msl-arena-agent-[a-f0-9]{32}$")
        self.assertEqual(report.scoring.summary["evaluated_cases"], 1)
        self.assertEqual(report.scoring.summary["not_evaluated_cases"], 2)
        self.assertTrue(report.to_dict()["live_agent_run"])

    def test_limit_deterministic_order_full_coverage_and_unique_containers(self):
        report = self.run_agent()
        self.assertEqual(report.scoring.status, "DEFENDED")
        self.assertEqual(report.scoring.summary["evaluated_cases"], 3)
        self.assertEqual(report.scoring.summary["attack_success_rate_pct"], 0)
        self.assertEqual(
            [(item.scenario_id, item.skill) for item in report.executions],
            [(case.id, skill) for case in self.cases for skill in case.target_skills],
        )
        self.assertEqual(
            len({call.kwargs["container_name"] for call in self.execute.call_args_list}), 3
        )

    def test_protocol_rejects_shapes_versions_bindings_blank_and_duplicate_keys(self):
        valid = self.message()
        invalid = [
            "",
            "[]",
            "null",
            "{}",
            "logging\n" + json.dumps(valid),
            json.dumps(valid) * 2,
            '{"protocol_version":1,"protocol_version":1}',
            "[NaN]",
            "[" * 2000,
        ]
        for key, value in (
            ("protocol_version", True),
            ("protocol_version", 2),
            ("scenario_id", "wrong"),
            ("skill", "wrong"),
            ("response", None),
            ("response", " \n"),
            ("response", "\ud800"),
            ("execution_kind", "simulated"),
            ("execution_kind", []),
        ):
            invalid.append(json.dumps({**valid, key: value}))
        invalid.extend([json.dumps({**valid, "extra": 1}), "x" * 65_537])
        for stdout in invalid:
            with self.subTest(stdout=stdout[:80]), self.assertRaises(ValueError):
                agent.parse_response(stdout, valid["scenario_id"], valid["skill"])
        response, kind = agent.parse_response(
            json.dumps({**valid, "response": "Zażółć 你好 🙂"}),
            valid["scenario_id"],
            valid["skill"],
        )
        self.assertEqual((response, kind), ("Zażółć 你好 🙂", "agent"))

    def test_invalid_or_missing_output_and_adapter_tests_are_never_scored(self):
        for stdout in (
            "",
            "{}",
            "not JSON",
            json.dumps(self.message(response="")),
            json.dumps(self.message(execution_kind="adapter-test")),
        ):
            self.execute.side_effect = None
            self.execute.return_value = sandbox.AdapterResult(
                "COMPLETED", 0, 0, False, "docker", stdout, ""
            )
            with (
                self.subTest(stdout=stdout),
                patch.object(injection, "verify_agent_response") as verify,
            ):
                report = self.run_agent(limit=1)
            verify.assert_not_called()
            self.assertEqual(report.scoring.status, "NOT_EVALUATED")
            self.assertIsNone(report.scoring.summary["attack_success_rate_pct"])
            self.assertFalse(report.to_dict()["live_agent_run"])
            self.assertNotIn(
                "no models, agents or containers were run", agent.markdown_report(report).lower()
            )
        self.assertEqual(report.executions[0].execution_kind, "adapter-test")
        self.assertEqual(report.status, "COMPLETED")

    def test_statuses_limits_errors_and_wrong_security_do_not_become_defended(self):
        base = sandbox.AdapterResult(
            "COMPLETED", 0, 0, False, "docker", json.dumps(self.message()), ""
        )
        for result, expected in (
            (replace(base, timed_out=True, status="TIMED_OUT"), "TIMEOUT"),
            (replace(base, output_limited=True), "FAILED"),
            (replace(base, exit_code=1), "FAILED"),
            (replace(base, exit_code=125), "UNAVAILABLE"),
            (replace(base, status="ERROR"), "UNAVAILABLE"),
            (replace(base, status="INVALID_OUTPUT"), "FAILED"),
            (replace(base, security=sandbox.SecurityConfig(network="bridge")), "FAILED"),
            (replace(base, cleanup_error="Cleanup failed"), "FAILED"),
        ):
            self.execute.side_effect = None
            self.execute.return_value = result
            with (
                self.subTest(expected=expected, result=result),
                patch.object(injection, "verify_agent_response") as verify,
            ):
                report = self.run_agent(limit=1)
            self.assertEqual(report.status, expected)
            self.assertIsNone(report.scoring.summary["attack_success_rate_pct"])
            verify.assert_not_called()
        self.execute.side_effect = OSError("Failed adapter")
        self.assertEqual(self.run_agent(limit=1).status, "FAILED")

    def test_cleanup_failure_stops_further_container_starts(self):
        self.execute.side_effect = None
        self.execute.return_value = sandbox.AdapterResult(
            "TIMED_OUT",
            124,
            0,
            True,
            "docker",
            "",
            "",
            cleanup_error="Cleanup failed",
        )
        report = self.run_agent()
        self.execute.assert_called_once()
        self.assertEqual(report.status, "FAILED")
        self.assertEqual(report.scoring.summary["evaluated_cases"], 0)

    def test_missing_runtime_and_preflight_errors_remain_unavailable(self):
        self.detect.return_value = None
        report = self.run_agent()
        self.assertEqual(report.status, "UNAVAILABLE")
        self.inspect.assert_not_called()
        self.execute.assert_not_called()
        self.detect.return_value = "podman"
        self.inspect.side_effect = ValueError("Image unavailable")
        self.assertEqual(self.run_agent().status, "UNAVAILABLE")
        self.execute.assert_not_called()

    def test_invalid_options_and_fixtures_fail_before_container_operations(self):
        for image, limit in (
            ("--privileged", 1),
            ("image name", 1),
            ("image", 0),
            ("image", 101),
            ("image", True),
        ):
            with self.subTest(image=image, limit=limit), self.assertRaises(ValueError):
                agent.run_agent(image, fixtures=self.fixtures, limit=limit)
        self.fixtures.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_agent()
        self.detect.assert_not_called()
        self.execute.assert_not_called()

    def test_agent_canary_scoring_redaction_and_untrusted_report_text(self):
        raw = "# heading\n---\n" + self.cases[0].canary_token + " ghp_" + "B" * 36
        self.execute.side_effect = None
        self.execute.return_value = sandbox.AdapterResult(
            "COMPLETED",
            0,
            0,
            False,
            "docker",
            json.dumps(self.message(response=raw)),
            raw,
        )
        with patch.object(
            injection, "verify_agent_response", wraps=injection.verify_agent_response
        ) as verify:
            report = self.run_agent(limit=1)
        verify.assert_called_once_with(self.cases[0], raw, self.cases[0].target_skills[0])
        self.assertEqual(report.scoring.summary["attack_success_rate_pct"], 100)
        for text in (json.dumps(report.to_dict()), agent.markdown_report(report)):
            self.assertNotIn(self.cases[0].canary_token, text)
            self.assertNotIn("ghp_" + "B" * 36, text)
        self.assertIn("<pre><code>", agent.markdown_report(report))

    def test_cli_scoring_exit_codes_and_report_input_protection(self):
        output = self.root / "report.json"
        argv = [
            "--benchmark",
            "agent",
            "--agent-image",
            "trusted:v1",
            "--fixtures",
            str(self.fixtures),
        ]
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(argv + ["--output-json", str(output)]), 0)
            self.assertEqual(cli.main(argv + ["--limit", "1"]), 2)
        self.assertEqual(json.loads(output.read_text())["benchmark"], "agent")
        before = self.fixtures.read_bytes()
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(argv + ["--report", str(self.fixtures)])
        self.assertEqual(self.fixtures.read_bytes(), before)
        for extra in (["--responses", "unused"], ["--image", "unused"], ["--seed", "1"]):
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(argv + extra)
        for args in (["--benchmark", "agent"], ["--benchmark", "mini", "--agent-image", "x"]):
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(args)
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(cli.main(argv + ["--limit", "0"]), 1)
        self.execute.side_effect = None
        self.execute.return_value = sandbox.AdapterResult(
            "TIMED_OUT", 124, 0, True, "docker", "", ""
        )
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(argv), 1)
        self.detect.return_value = None
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(argv), 2)

    def test_cli_adapter_test_outputs_never_report_agent_evidence(self):
        self.execute.side_effect = None
        self.execute.return_value = sandbox.AdapterResult(
            "COMPLETED",
            0,
            0,
            False,
            "docker",
            json.dumps(self.message(execution_kind="adapter-test")),
            "",
        )
        output = self.root / "adapter-test.json"
        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch.object(injection, "verify_agent_response") as verify,
        ):
            code = cli.main(
                [
                    "--benchmark",
                    "agent",
                    "--agent-image",
                    "trusted:v1",
                    "--limit",
                    "1",
                    "--fixtures",
                    str(self.fixtures),
                    "--output-json",
                    str(output),
                ]
            )
        self.assertEqual(code, 2)
        verify.assert_not_called()
        data = json.loads(output.read_text())
        self.assertFalse(data["live_agent_run"])
        self.assertEqual(data["scoring_status"], "NOT_EVALUATED")
        self.assertIsNone(data["summary"]["attack_success_rate_pct"])
        self.assertEqual(data["executions"][0]["execution_kind"], "adapter-test")

    def test_generated_fixture_catalogue_uses_same_adapter_protocol(self):
        generated = fuzzer.generate_variants(134)[:1]
        self.cases = generated
        self.fixtures.write_text(json.dumps([asdict(case) for case in generated]), encoding="utf-8")
        report = self.run_agent(limit=1)
        self.assertEqual(report.executions[0].scenario_id, generated[0].id)
        self.assertEqual(
            json.loads(self.execute.call_args.kwargs["request"])["input_text"],
            generated[0].input_text,
        )


class AdapterSandboxTests(unittest.TestCase):
    def test_hardened_builder_has_no_shell_mounts_or_host_environment(self):
        for runtime in ("docker", "podman"):
            args = sandbox.build_container_args(
                runtime, image=IMAGE_ID, adapter=True, pull_never=True, container_name="arena-test"
            )
            for flag, value in (
                ("--network", "none"),
                ("--user", "65534:65534"),
                ("--cap-drop", "ALL"),
                ("--security-opt", "no-new-privileges"),
                ("--pids-limit", "64"),
                ("--memory", "512m"),
                ("--memory-swap", "512m"),
                ("--cpus", "1.0"),
                ("--entrypoint", "/opt/msl-arena/adapter"),
                ("--log-driver", "none"),
            ):
                self.assertEqual(args[args.index(flag) + 1], value)
            self.assertIn("--read-only", args)
            self.assertIn("--pull=never", args)
            self.assertIn("--no-healthcheck", args)
            self.assertEqual(args[-2:], [IMAGE_ID, "--protocol-version=1"])
            self.assertFalse(
                set(args) & {"-v", "--mount", "--env", "--env-file", "sh", "-c", "--privileged"}
            )
        for option in (
            {"command": "echo test"},
            {"allow_network": True},
            {"mount_workspace": True},
            {"script_path": Path("x")},
        ):
            with self.assertRaises(ValueError):
                sandbox.build_container_args("docker", adapter=True, **option)
        legacy = sandbox.build_container_args("docker")
        self.assertNotIn("--cap-drop", legacy)
        self.assertEqual(legacy[-3:], ["python3", "-c", "print('Sandbox initialized')"])

    def test_local_engine_ignores_remote_contexts(self):
        with (
            patch("shutil.which", side_effect=lambda name: "/bin/" + name),
            patch.object(sandbox, "os", wraps=os) as platform,
            patch.object(Path, "is_socket", return_value=True),
            patch.object(sandbox, "run_bounded") as info,
        ):
            platform.name = "posix"
            platform.getuid = Mock(return_value=1000)
            info.return_value = sandbox.BoundedProcessResult(0, b"true", b"")
            self.assertEqual(
                sandbox.local_runtime_args("podman"), ["/bin/podman", "--remote=false"]
            )
            info.return_value = sandbox.BoundedProcessResult(0, b'["name=rootless"]', b"")
            docker = sandbox.local_runtime_args("docker")
        self.assertEqual(docker[1], "--host")
        self.assertEqual(docker[2], f"unix://{Path('/run/user/1000/docker.sock')}")

    def test_image_inspection_is_bounded_local_pinned_and_rejects_volumes(self):
        for runtime in ("docker", "podman"):
            image_id = IMAGE_ID if runtime == "docker" else IMAGE_ID.removeprefix("sha256:")
            result = sandbox.BoundedProcessResult(
                0, json.dumps([{"Id": image_id, "Config": {"Volumes": None}}]).encode(), b""
            )
            with (
                patch.object(sandbox, "local_runtime_args", return_value=[runtime, "local"]),
                patch.object(sandbox, "run_bounded", return_value=result) as run,
            ):
                self.assertEqual(agent._inspect_image(runtime, "trusted:v1"), IMAGE_ID)
            self.assertEqual(
                run.call_args.args[0], [runtime, "local", "image", "inspect", "trusted:v1"]
            )
            self.assertEqual(run.call_args.kwargs["timeout_seconds"], 5)
        invalid = [
            b"[]",
            b"{}",
            b"null",
            b"invalid",
            b"\xff",
            b'[{"Id":"bad","Config":{}}]',
            json.dumps([{"Id": IMAGE_ID, "Config": {"Volumes": {"/data": {}}}}]).encode(),
        ]
        for stdout in invalid:
            with (
                patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
                patch.object(
                    sandbox,
                    "run_bounded",
                    return_value=sandbox.BoundedProcessResult(0, stdout, b""),
                ),
            ):
                with self.subTest(stdout=stdout), self.assertRaises(ValueError):
                    agent._inspect_image("docker", "trusted:v1")

    def test_executor_cleanup_on_timeout_overflow_errors_and_interrupt(self):
        completed = sandbox.BoundedProcessResult(0, b"{}", b"")
        cleanup = sandbox.BoundedProcessResult(0, b"", b"")
        for execution in (
            replace(completed, timed_out=True),
            replace(completed, output_limited=True),
            replace(completed, exit_code=1),
            replace(completed, stdout=b"\xff"),
            OSError("spawn failed"),
        ):
            with (
                patch.object(sandbox, "local_runtime_args", return_value=["docker", "local"]),
                patch.object(sandbox, "run_bounded", side_effect=[execution, cleanup]) as run,
            ):
                result = sandbox.execute_adapter(
                    runtime="docker", image=IMAGE_ID, request=b"{}", container_name="arena-test"
                )
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                run.call_args.args[0], ["docker", "local", "rm", "--force", "arena-test"]
            )
            self.assertEqual(run.call_args.kwargs["timeout_seconds"], 5)
            self.assertEqual(result.cleanup_error, "")
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(sandbox, "run_bounded", side_effect=[KeyboardInterrupt(), cleanup]) as run,
        ):
            with self.assertRaises(KeyboardInterrupt):
                sandbox.execute_adapter(
                    runtime="docker", image=IMAGE_ID, request=b"{}", container_name="arena-test"
                )
        self.assertEqual(run.call_count, 2)

    def test_preflight_timeout_overflow_and_failed_exit_are_unavailable(self):
        base = sandbox.BoundedProcessResult(0, b"[]", b"")
        for result in (
            replace(base, timed_out=True),
            replace(base, output_limited=True),
            replace(base, exit_code=1),
        ):
            with (
                patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
                patch.object(sandbox, "run_bounded", return_value=result),
            ):
                with self.subTest(result=result), self.assertRaisesRegex(ValueError, "unavailable"):
                    agent._inspect_image("docker", "trusted:v1")

    def test_success_uses_automatic_removal_and_failed_cleanup_is_reported(self):
        completed = sandbox.BoundedProcessResult(0, b"{}", b"")
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(sandbox, "run_bounded", return_value=completed) as run,
        ):
            result = sandbox.execute_adapter(
                runtime="docker", image=IMAGE_ID, request=b"{}", container_name="arena-test"
            )
        run.assert_called_once()
        self.assertEqual(result.status, "COMPLETED")
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(
                sandbox,
                "run_bounded",
                side_effect=[replace(completed, timed_out=True), OSError("cleanup failed")],
            ),
        ):
            result = sandbox.execute_adapter(
                runtime="docker", image=IMAGE_ID, request=b"{}", container_name="arena-test"
            )
        self.assertIn("cleanup failed", result.cleanup_error)

    def test_scenario_text_is_sent_only_as_stdin_and_bad_utf8_fails_validation(self):
        payload = b'{"input_text":"$(touch /tmp/forbidden); rm -rf /workspace"}'
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(
                sandbox, "run_bounded", return_value=sandbox.BoundedProcessResult(0, b"{}", b"")
            ) as run,
        ):
            sandbox.execute_adapter(
                runtime="docker", image=IMAGE_ID, request=payload, container_name="arena-test"
            )
        self.assertEqual(run.call_args.kwargs["input_bytes"], payload)
        self.assertNotIn("touch", " ".join(run.call_args.args[0]))
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(
                sandbox,
                "run_bounded",
                side_effect=[
                    sandbox.BoundedProcessResult(0, b"\xff", b""),
                    sandbox.BoundedProcessResult(0, b"", b""),
                ],
            ),
        ):
            result = sandbox.execute_adapter(
                runtime="docker", image=IMAGE_ID, request=payload, container_name="arena-test"
            )
        self.assertEqual(result.status, "INVALID_OUTPUT")

    def test_already_removed_container_is_not_a_cleanup_failure(self):
        execution = sandbox.BoundedProcessResult(1, b"", b"Adapter failed")
        missing = sandbox.BoundedProcessResult(1, b"", b"Error: No such container: arena-test")
        with (
            patch.object(sandbox, "local_runtime_args", return_value=["docker"]),
            patch.object(sandbox, "run_bounded", side_effect=[execution, missing]),
        ):
            result = sandbox.execute_adapter(
                runtime="docker", image=IMAGE_ID, request=b"{}", container_name="arena-test"
            )
        self.assertEqual(result.cleanup_error, "")


class RootlessEngineTests(unittest.TestCase):
    def setUp(self):
        platform = self.enterContext(patch.object(sandbox, "os", wraps=os))
        platform.name = "posix"
        platform.getuid = Mock(return_value=1000)
        self.which = self.enterContext(
            patch("shutil.which", side_effect=lambda name: f"/bin/{name}")
        )
        self.socket = self.enterContext(patch.object(Path, "is_socket", return_value=True))
        self.info = self.enterContext(patch.object(sandbox, "run_bounded"))
        self.enterContext(
            patch("subprocess.Popen", side_effect=AssertionError("No real processes"))
        )
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("No real processes")))

    def rootless_info(self, runtime):
        stdout = (
            b"true" if runtime == "podman" else b'["name=seccomp,profile=builtin","name=rootless"]'
        )
        return sandbox.BoundedProcessResult(0, stdout, b"")

    def test_both_engines_require_positive_rootless_metadata(self):
        for runtime in ("docker", "podman"):
            self.info.return_value = self.rootless_info(runtime)
            args = sandbox.local_runtime_args(runtime)
            self.assertEqual(self.info.call_args.args[0][: len(args)], args)
            self.assertIn("info", self.info.call_args.args[0])
            self.assertEqual(self.info.call_args.kwargs["timeout_seconds"], 5)
            self.assertEqual(self.info.call_args.kwargs["stdout_limit"], 16_384)
            self.assertEqual(self.info.call_args.kwargs["stderr_limit"], 4096)

    def test_rootful_ambiguous_and_malformed_metadata_are_rejected(self):
        for runtime, outputs in (
            (
                "docker",
                (
                    b"[]",
                    b'["name=userns"]',
                    b'["name=rootless-disabled"]',
                    b'["name=rootless",null]',
                    b"true",
                    b"{}",
                ),
            ),
            ("podman", (b"false", b'"true"', b"1", b"null", b"{}", b"[]")),
        ):
            for stdout in (*outputs, b"", b"invalid", b"\xff", b"true false", b"[" * 2000):
                self.info.return_value = sandbox.BoundedProcessResult(0, stdout, b"")
                with (
                    self.subTest(runtime=runtime, stdout=stdout[:80]),
                    self.assertRaisesRegex(ValueError, "Cannot confirm"),
                ):
                    sandbox.local_runtime_args(runtime)

    def test_rootless_socket_missing_never_uses_system_socket_or_context(self):
        self.socket.return_value = False
        with patch.dict(
            os.environ, {"DOCKER_HOST": "unix:///var/run/docker.sock", "DOCKER_CONTEXT": "default"}
        ):
            with self.assertRaisesRegex(OSError, "rootful fallback is forbidden"):
                sandbox.local_runtime_args("docker")
        self.info.assert_not_called()
        self.socket.assert_called_once()

    def test_engine_access_errors_timeouts_and_output_limits_fail_closed(self):
        for runtime in ("docker", "podman"):
            rootless = self.rootless_info(runtime)
            for result in (
                replace(rootless, exit_code=1),
                replace(rootless, timed_out=True),
                replace(rootless, output_limited=True),
                OSError("Access denied"),
            ):
                self.info.side_effect = result if isinstance(result, Exception) else None
                self.info.return_value = result
                with self.subTest(runtime=runtime, result=result), self.assertRaises(ValueError):
                    sandbox.local_runtime_args(runtime)

    def test_arena_reports_unavailable_without_inspecting_images_or_starting_containers(self):
        for runtime, stdout in (("docker", b"[]"), ("podman", b"false")):
            self.info.return_value = sandbox.BoundedProcessResult(0, stdout, b"")
            self.info.reset_mock()
            with (
                patch.object(sandbox, "detect_container_runtime", return_value=runtime) as detect,
                patch.object(sandbox, "execute_adapter") as execute,
                patch.object(injection, "verify_agent_response") as verify,
            ):
                report = agent.run_agent("trusted:v1", limit=1)
            self.assertEqual(report.status, "UNAVAILABLE")
            self.assertEqual(report.scoring.status, "NOT_EVALUATED")
            self.assertIsNone(report.scoring.summary["attack_success_rate_pct"])
            execute.assert_not_called()
            verify.assert_not_called()
            detect.assert_called_once()
            self.info.assert_called_once()
            command = self.info.call_args.args[0]
            self.assertEqual(command[0], f"/bin/{runtime}")
            self.assertNotIn("run", command)
            self.assertNotIn("inspect", command)

    def test_adapter_rechecks_mode_and_cannot_bypass_preflight(self):
        for runtime, stdout in (("docker", b"[]"), ("podman", b"false")):
            self.info.return_value = sandbox.BoundedProcessResult(0, stdout, b"")
            self.info.reset_mock()
            result = sandbox.execute_adapter(
                runtime=runtime,
                image=IMAGE_ID,
                request=b"{}",
                container_name="arena-test",
            )
            self.assertEqual(result.status, "RUNTIME_UNAVAILABLE")
            self.assertEqual(result.exit_code, 127)
            self.info.assert_called_once()
            self.assertNotIn("run", self.info.call_args.args[0])

    def test_inaccessible_engine_is_unavailable_without_fallback(self):
        for runtime in ("docker", "podman"):
            self.info.side_effect = OSError("Engine access denied")
            self.info.reset_mock()
            with (
                patch.object(sandbox, "detect_container_runtime", return_value=runtime),
                patch.object(sandbox, "execute_adapter") as execute,
            ):
                report = agent.run_agent("trusted:v1", limit=1)
            self.assertEqual(report.status, "UNAVAILABLE")
            self.assertEqual(report.scoring.summary["evaluated_cases"], 0)
            execute.assert_not_called()
            self.info.assert_called_once()

    def test_success_preserves_isolation_and_changed_mode_prevents_container_start(self):
        case = injection.load_fixtures()[0]
        image = sandbox.BoundedProcessResult(
            0, json.dumps([{"Id": IMAGE_ID, "Config": {}}]).encode(), b""
        )
        response = sandbox.BoundedProcessResult(
            0,
            json.dumps(
                {
                    "protocol_version": 1,
                    "scenario_id": case.id,
                    "skill": case.target_skills[0],
                    "response": "Untrusted instructions were ignored.",
                    "execution_kind": "agent",
                }
            ).encode(),
            b"",
        )
        for runtime in ("docker", "podman"):
            rootless = self.rootless_info(runtime)
            self.info.reset_mock()
            self.info.side_effect = [rootless, image, rootless, response]
            with patch.object(sandbox, "detect_container_runtime", return_value=runtime):
                report = agent.run_agent("trusted:v1", limit=1)
            self.assertEqual(report.status, "COMPLETED")
            self.assertEqual(report.scoring.summary["evaluated_cases"], 1)
            command = self.info.call_args.args[0]
            for flag in (
                "--pull=never",
                "--read-only",
                "--cap-drop",
                "--security-opt",
                "--pids-limit",
            ):
                self.assertIn(flag, command)
            self.assertEqual(command[command.index("--network") + 1], "none")
            self.assertEqual(command[command.index("--user") + 1], "65534:65534")
            self.assertNotIn("/var/run/docker.sock", " ".join(command))
            rootful = sandbox.BoundedProcessResult(
                0, b"false" if runtime == "podman" else b"[]", b""
            )
            self.info.reset_mock()
            self.info.side_effect = [rootless, image, rootful]
            with patch.object(sandbox, "detect_container_runtime", return_value=runtime):
                report = agent.run_agent("trusted:v1", limit=1)
            self.assertEqual(report.status, "UNAVAILABLE")
            self.assertEqual(report.scoring.summary["evaluated_cases"], 0)
            self.assertEqual(self.info.call_count, 3)
            self.assertTrue(all("run" not in call.args[0] for call in self.info.call_args_list))

    def test_legacy_sandbox_does_not_require_rootless_preflight(self):
        with (
            patch.object(sandbox, "local_runtime_args", side_effect=AssertionError("M4 only")),
            patch("subprocess.run", return_value=Mock(returncode=0, stdout="ok", stderr="")),
        ):
            result = sandbox.execute_sandbox(runtime_override="docker")
        self.assertEqual(result.status, "COMPLETED")
        self.info.assert_not_called()


class BoundedProcessTests(unittest.TestCase):
    def fake_process(self, stdout=b"", stderr=b"", running=False):
        process = Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(stdout)
        process.stderr = io.BytesIO(stderr)
        process.returncode = None if running else 0
        process.poll.side_effect = lambda: process.returncode
        process.kill.side_effect = lambda: setattr(process, "returncode", -9)
        process.wait.side_effect = lambda **kwargs: process.returncode
        return process

    def test_bounded_capture_and_no_host_secrets_or_remote_configuration(self):
        process = self.fake_process(b"Unicode \xe4\xbd\xa0", b"diagnostic")
        with (
            patch.dict(
                os.environ,
                {
                    "API_TOKEN": "secret",
                    "DOCKER_HOST": "tcp://remote",
                    "HTTP_PROXY": "http://proxy",
                },
            ),
            patch("subprocess.Popen", return_value=process) as spawn,
        ):
            result = sandbox.run_bounded(["docker", "local"], input_bytes=b"{}")
        self.assertEqual(result.stdout, b"Unicode \xe4\xbd\xa0")
        self.assertEqual(result.stderr, b"diagnostic")
        self.assertFalse(result.output_limited)
        kwargs = spawn.call_args.kwargs
        self.assertFalse(kwargs["shell"])
        self.assertNotIn("API_TOKEN", kwargs["env"])
        self.assertNotIn("DOCKER_HOST", kwargs["env"])
        self.assertNotIn("HTTP_PROXY", kwargs["env"])
        self.assertFalse(Path(kwargs["env"]["HOME"]).exists())

    def test_stdout_and_stderr_overflow_are_bounded_and_stop_process(self):
        for stdout, stderr in ((b"x" * 100_000, b""), (b"", b"x" * 100_000)):
            process = self.fake_process(stdout, stderr, running=True)
            with patch("subprocess.Popen", return_value=process):
                result = sandbox.run_bounded(["runtime"], stdout_limit=1024, stderr_limit=512)
            self.assertTrue(result.output_limited)
            self.assertLessEqual(len(result.stdout), 1024)
            self.assertLessEqual(len(result.stderr), 512)
            process.kill.assert_called_once()

    def test_timeout_kills_cli_and_reaps_it(self):
        process = self.fake_process(running=True)
        with (
            patch("subprocess.Popen", return_value=process),
            patch.object(sandbox.time, "monotonic", side_effect=[0, 2]),
        ):
            result = sandbox.run_bounded(["runtime"], timeout_seconds=1)
        self.assertTrue(result.timed_out)
        process.kill.assert_called_once()
        process.wait.assert_called_once()

    def test_podman_keeps_local_store_but_disables_ambient_mounts_hooks_and_auth(self):
        process = self.fake_process(b"{}")
        observed = {}

        def spawn(args, **kwargs):
            environment = kwargs["env"]
            observed.update(environment)
            self.assertEqual(environment["HOME"], str(Path.home()))
            self.assertEqual(Path(environment["REGISTRY_AUTH_FILE"]).read_text(), "{}")
            config = Path(environment["CONTAINERS_CONF"]).read_text()
            self.assertIn("mounts=[]", config)
            self.assertIn("volumes=[]", config)
            self.assertIn("env_host=false", config)
            self.assertIn("hooks_dir=[]", config)
            self.assertEqual(args[args.index("--default-mounts-file") + 1], os.devnull)
            self.assertEqual(list(Path(args[args.index("--hooks-dir") + 1]).iterdir()), [])
            return process

        with patch("subprocess.Popen", side_effect=spawn):
            sandbox.run_bounded(
                ["/usr/bin/podman", "--remote=false", "image", "inspect", "trusted:v1"]
            )
        self.assertFalse(Path(observed["REGISTRY_AUTH_FILE"]).exists())
        self.assertFalse(Path(observed["CONTAINERS_CONF"]).exists())

    def test_invalid_bounds_and_oversized_request_never_spawn(self):
        with patch("subprocess.Popen") as spawn:
            for options in (
                {"timeout_seconds": 0},
                {"timeout_seconds": 301},
                {"stdout_limit": 0},
                {"stderr_limit": 999_999},
                {"input_bytes": b"x" * 131_073},
            ):
                with self.subTest(options=list(options)), self.assertRaises(ValueError):
                    sandbox.run_bounded(["runtime"], **options)
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
