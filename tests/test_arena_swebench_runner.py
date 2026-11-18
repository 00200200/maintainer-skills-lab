"""Synthetic runner control tests; all harness, engine and process execution is mocked."""

from __future__ import annotations

import copy
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evals.arena import cli, swebench, swebench_eval
from evals.arena import swebench_runner as runner

PARAMETERS = [
    "dataset_name",
    "split",
    "instance_ids",
    "predictions_path",
    "max_workers",
    "force_rebuild",
    "cache_level",
    "clean",
    "open_file_limit",
    "run_id",
    "timeout",
]


class SWEbenchRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / "tasks.jsonl"
        self.manifest = self.root / "manifest.json"
        self.predictions = self.root / "predictions.jsonl"
        self.export = self.root / "export.jsonl"
        self.receipt = self.root / "receipt.json"
        self.work = self.root / "fresh-run"
        self.run_id = "synthetic-controlled-run"
        self.rows = [
            {
                "instance_id": f"example__project-{number}",
                "repo": "example/project",
                "base_commit": "a" * 40,
                "problem_statement": "Synthetic schema fixture only.",
                "FAIL_TO_PASS": [f"test_fix_{number}"],
                "PASS_TO_PASS": [f"test_existing_{number}"],
                "version": "1.0",
                "patch": "SYNTHETIC_GOLD_NEVER_A_PREDICTION",
                "test_patch": "Synthetic evaluator test patch, never executed by these tests.",
            }
            for number in (1, 2)
        ]
        self.dataset.write_text(
            "\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8"
        )
        self.records = [
            {
                "instance_id": row["instance_id"],
                "model_name_or_path": "synthetic/model",
                "model_patch": "Synthetic predicted patch; this is not benchmark evidence.",
            }
            for row in self.rows
        ]
        self.refresh_inputs()
        self.enterContext(
            patch.object(
                runner,
                "_registry",
                side_effect=lambda run_id: self.root / "state" / f"{run_id}.json",
            )
        )
        self.endpoint = self.enterContext(
            patch.object(runner, "_endpoint", return_value=self.root / "rootless.sock")
        )
        self.api = self.enterContext(
            patch.object(
                runner,
                "_api",
                side_effect=lambda path, method, route: (
                    (404, b"") if method == "GET" else (204, b"")
                ),
            )
        )
        self.info = {
            "SecurityOptions": ["name=rootless"],
            "OSType": "linux",
            "NCPU": 8,
            "MemTotal": 64 * runner.GIB,
            "DockerRootDir": str(self.root),
        }
        self.api_json = self.enterContext(
            patch.object(runner, "_api_json", side_effect=self.metadata)
        )
        self.disk = self.enterContext(
            patch.object(
                runner.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=runner.MIN_DISK_BYTES + 1),
            )
        )
        self.probe_data = {
            "version": "2.1.0",
            "module_version": "2.1.0",
            "python": [3, 11],
            "parameters": PARAMETERS,
            "supported_tasks": True,
            "ping": True,
            "nofile_hard": 4096,
        }
        self.process = self.enterContext(
            patch.object(runner, "_run_process", return_value=self.probe_result())
        )
        self.enterContext(
            patch("subprocess.Popen", side_effect=AssertionError("No real processes"))
        )
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("No real processes")))
        self.enterContext(patch("urllib.request.urlopen", side_effect=AssertionError("No network")))
        self.importer = self.enterContext(
            patch.object(
                swebench_eval,
                "import_results",
                side_effect=AssertionError("Scoring must be a separate M5b operation"),
            )
        )

    def tearDown(self):
        self.importer.assert_not_called()

    def refresh_inputs(self):
        self.manifest.write_text(
            json.dumps(swebench.prepare(self.dataset).to_dict()), encoding="utf-8"
        )
        self.predictions.write_text(
            "\n".join(json.dumps(record) for record in self.records) + "\n", encoding="utf-8"
        )
        prepared = swebench_eval.prepare_predictions(
            self.manifest, self.predictions, run_id=self.run_id
        )
        self.export.write_bytes(prepared.export_bytes)
        self.receipt.write_text(json.dumps(prepared.to_dict()), encoding="utf-8")

    def metadata(self, path, route):
        if route == "/info":
            return self.info
        if route == "/version":
            return {"ApiVersion": "1.41"}
        return {"host": {"security": {"rootless": True}}}

    def probe_result(self, **changes):
        return runner.ProcessResult(
            "COMPLETED", 0, json.dumps({**self.probe_data, **changes}).encode()
        )

    def plan(self, **options):
        return runner.plan_run(
            self.manifest,
            self.predictions,
            self.export,
            self.dataset,
            self.receipt,
            run_id=self.run_id,
            work_dir=self.work,
            **options,
        )

    def successful_processes(self, status="COMPLETED", code=0):
        self.process.side_effect = [
            self.probe_result(),
            runner.ProcessResult(status, code, b"private console", b"diagnostic"),
        ]

    def test_default_is_preview_only_with_one_instance_one_worker_and_no_side_effects(self):
        before = set(self.root.iterdir())
        plan = self.plan()
        report = runner.run(plan)
        self.assertEqual(report["execution_status"], "PREVIEW")
        self.assertEqual(report["evaluation_status"], "NOT_IMPORTED")
        self.assertEqual(report["instance_ids"], [self.rows[0]["instance_id"]])
        self.assertEqual(report["limits"]["workers"], 1)
        self.assertEqual(set(self.root.iterdir()), before)
        self.endpoint.assert_not_called()
        self.api.assert_not_called()
        self.process.assert_not_called()
        self.disk.assert_not_called()
        self.assertFalse(self.work.exists())

    def test_command_delegates_to_official_module_and_snapshots_exclude_gold(self):
        plan = self.plan()
        command = plan.command
        self.assertIn("runpy.run_module('swebench.harness.run_evaluation'", command[4])
        self.assertIn("resource.setrlimit", command[4])
        self.assertIn("dotenv.load_dotenv = lambda", command[4])
        self.assertEqual(
            command[command.index("--instance_ids") + 1 : command.index("--max_workers")],
            [self.rows[0]["instance_id"]],
        )
        self.assertEqual(command[command.index("--max_workers") + 1], "1")
        self.assertEqual(command[command.index("--timeout") + 1], "1800")
        self.assertNotIn("gold", command)
        snapshot = json.loads(plan.dataset_bytes)
        self.assertEqual(len(snapshot), 1)
        self.assertNotIn("patch", snapshot[0])
        self.assertIn("test_patch", snapshot[0])
        self.assertNotIn(b"SYNTHETIC_GOLD_NEVER_A_PREDICTION", plan.predictions_bytes)
        self.assertEqual(json.loads(plan.predictions_bytes), self.records[0])

    def test_environment_setup_commit_is_preserved_only_in_evaluation_snapshot(self):
        environment_commit = "b" * 40
        self.rows[0]["environment_setup_commit"] = environment_commit
        self.dataset.write_text(
            "\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8"
        )
        self.refresh_inputs()
        plan = self.plan()
        snapshot = json.loads(plan.dataset_bytes)[0]
        self.assertEqual(snapshot["environment_setup_commit"], environment_commit)
        self.assertEqual(snapshot["base_commit"], self.rows[0]["base_commit"])
        self.assertNotEqual(snapshot["environment_setup_commit"], snapshot["base_commit"])
        self.assertNotIn("environment_setup_commit", plan.prepared.tasks[0].agent_input())
        self.process.assert_not_called()

    def test_missing_or_null_environment_commit_leaves_harness_default_unchanged(self):
        for present in (False, True):
            with self.subTest(present=present):
                if present:
                    self.rows[0]["environment_setup_commit"] = None
                else:
                    self.rows[0].pop("environment_setup_commit", None)
                self.dataset.write_text(
                    "\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8"
                )
                self.refresh_inputs()
                plan = self.plan()
                snapshot = json.loads(plan.dataset_bytes)[0]
                self.assertNotIn("environment_setup_commit", snapshot)
                self.assertEqual(snapshot["base_commit"], self.rows[0]["base_commit"])
                self.assertNotIn("environment_setup_commit", plan.prepared.tasks[0].agent_input())
        self.process.assert_not_called()

    def test_interpreter_symlink_retains_virtual_environment_path(self):
        interpreter = self.root / "venv-python"
        try:
            interpreter.symlink_to(Path(sys.executable))
        except (OSError, NotImplementedError):
            return  # Rootless execution itself requires Linux; other hosts can preview.
        self.assertEqual(self.plan(python=interpreter).python, interpreter.absolute())
        with patch.object(runner.sys, "executable", str(interpreter)):
            self.assertEqual(self.plan().command[0], str(interpreter.absolute()))
        self.process.assert_not_called()

    def test_validates_dataset_export_receipt_and_ready_predictions_before_preflight(self):
        before = self.export.read_bytes()
        self.export.write_bytes(b"tampered export")
        with self.assertRaises(ValueError):
            self.plan()
        self.export.write_bytes(before)
        self.dataset.write_text(
            self.dataset.read_text().replace("a" * 40, "b" * 40), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            self.plan()
        self.dataset.write_text(
            "\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8"
        )
        self.receipt.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.plan()
        self.records[0]["model_patch"] = ""
        self.refresh_inputs()
        with self.assertRaises(ValueError):
            self.plan()
        self.process.assert_not_called()

    def test_gold_label_missing_execution_metadata_and_bad_limits_are_rejected(self):
        for options in (
            {"limit": 0},
            {"limit": True},
            {"limit": 51},
            {"workers": 2},
            {"workers": 5},
            {"timeout": 0},
            {"timeout": 10},
            {"log_limit_mib": 1},
            {"engine": "rootful"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.plan(**options)
        for field in ("version", "test_patch"):
            original = self.rows[0].pop(field)
            self.dataset.write_text(
                "\n".join(json.dumps(row) for row in self.rows), encoding="utf-8"
            )
            self.refresh_inputs()
            with self.assertRaises(ValueError):
                self.plan()
            self.rows[0][field] = original
        self.dataset.write_text("\n".join(json.dumps(row) for row in self.rows), encoding="utf-8")
        for row in self.records:
            row["model_name_or_path"] = "gold"
        self.refresh_inputs()
        with self.assertRaisesRegex(ValueError, "Gold"):
            self.plan()

    def test_rootful_docker_and_podman_never_start_harness_or_fallback(self):
        plan = self.plan()
        self.info["SecurityOptions"] = ["name=userns"]
        report = runner.run(plan, execute=True)
        self.assertEqual(report["execution_status"], "UNAVAILABLE")
        self.assertIn("rootless", report["diagnostic"])
        self.process.assert_not_called()
        self.assertFalse(self.work.exists())
        self.api_json.side_effect = lambda path, route: (
            {"host": {"security": {"rootless": False}}} if route == "/libpod/info" else self.info
        )
        report = runner.run(self.plan(engine="podman"), execute=True)
        self.assertEqual(report["execution_status"], "UNAVAILABLE")
        self.assertIn("podman", report["diagnostic"].lower())
        self.process.assert_not_called()
        self.assertFalse(any(call.args[1] == "DELETE" for call in self.api.call_args_list))

    def test_resources_api_failure_and_existing_containers_are_unavailable(self):
        original = copy.deepcopy(self.info)
        for changes in (
            {"NCPU": 1},
            {"MemTotal": 1024},
            {"OSType": "windows"},
            {"DockerRootDir": "relative"},
        ):
            self.info = {**original, **changes}
            report = runner.run(self.plan(), execute=True)
            self.assertEqual(report["execution_status"], "UNAVAILABLE")
        self.info = original
        self.disk.return_value.free = 1
        self.assertEqual(runner.run(self.plan(), execute=True)["execution_status"], "UNAVAILABLE")
        self.disk.return_value.free = runner.MIN_DISK_BYTES + 1
        self.api.return_value = (200, b"existing container")
        self.api.side_effect = None
        self.assertEqual(runner.run(self.plan(), execute=True)["execution_status"], "UNAVAILABLE")
        self.process.assert_not_called()

    def test_missing_or_incompatible_harness_and_podman_sdk_probe_fail_closed(self):
        for result in (
            runner.ProcessResult("FAILED", 1),
            self.probe_result(version="5.0.0"),
            self.probe_result(module_version="5.0.0"),
            self.probe_result(parameters=[]),
            self.probe_result(ping=False),
            self.probe_result(supported_tasks=False),
            self.probe_result(nofile_hard=256),
            self.probe_result(python=[3, 10]),
            runner.ProcessResult("TIMEOUT", -9),
        ):
            self.process.return_value = result
            self.process.reset_mock()
            report = runner.run(self.plan(engine="podman"), execute=True)
            self.assertEqual(report["execution_status"], "UNAVAILABLE")
            self.process.assert_called_once()  # Probe only; never the actual harness module.
            self.assertFalse(self.work.exists())

    def test_success_creates_fresh_inputs_reservation_and_controlled_process_environment(self):
        self.successful_processes()
        with patch.dict(
            os.environ,
            {
                "API_TOKEN": "secret",
                "DOCKER_HOST": "unix:///var/run/docker.sock",
                "SSH_AUTH_SOCK": "/agent",
            },
        ):
            report = runner.run(self.plan(), execute=True)
        self.assertEqual(report["execution_status"], "COMPLETED")
        self.assertEqual(report["evaluation_status"], "NOT_IMPORTED")
        kwargs = self.process.call_args.kwargs
        self.assertEqual(kwargs["cwd"], self.work)
        self.assertEqual(kwargs["timeout"], 3600)
        environment = kwargs["environment"]
        self.assertEqual(environment["DOCKER_HOST"], f"unix://{self.root / 'rootless.sock'}")
        self.assertNotIn("API_TOKEN", environment)
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["HF_DATASETS_OFFLINE"], "1")
        self.assertTrue((self.root / "state" / f"{self.run_id}.json").exists())
        self.assertTrue((self.work / "inputs/dataset.json").exists())
        self.assertEqual(
            (self.work / "inputs/run-manifest.json").read_bytes(), self.receipt.read_bytes()
        )
        self.assertNotIn("private console", json.dumps(report))
        self.assertNotIn("pass_at_1", report)
        self.assertNotIn("RESOLVED", report.values())
        cleanup = [call for call in self.api.call_args_list if call.args[1] == "DELETE"]
        self.assertEqual(len(cleanup), 1)
        self.assertIn(f"sweb.eval.{self.rows[0]['instance_id']}.{self.run_id}", cleanup[0].args[2])

    def test_reused_directory_registry_and_races_never_start_a_process(self):
        plan = self.plan()
        self.work.mkdir()
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(runner.run(plan, execute=True)["execution_status"], "UNAVAILABLE")
        self.process.assert_not_called()
        other = self.root / "another-run"
        registry = runner._registry(self.run_id)
        registry.parent.mkdir()
        registry.write_text("reserved", encoding="utf-8")
        with self.assertRaises(ValueError):
            runner.plan_run(
                self.manifest,
                self.predictions,
                self.export,
                self.dataset,
                self.receipt,
                run_id=self.run_id,
                work_dir=other,
            )
        registry.unlink()
        self.work.rmdir()
        plan = self.plan()
        with patch.object(
            runner,
            "_preflight",
            side_effect=lambda value: (self.work.mkdir(), self.root / "rootless.sock")[1],
        ):
            report = runner.run(plan, execute=True)
        self.assertEqual(report["execution_status"], "UNAVAILABLE")
        self.process.assert_not_called()

    def test_timeout_log_limit_interrupt_and_failed_cleanup_preserve_execution_status(self):
        for status in ("TIMEOUT", "LOG_LIMIT", "INTERRUPTED", "FAILED"):
            with self.subTest(status=status):
                # Each execution must have a fresh ID and work directory.
                self.run_id = "synthetic-" + status.lower()
                self.work = self.root / self.run_id
                self.refresh_inputs()
                self.successful_processes(status, -9)
                report = runner.run(self.plan(), execute=True)
                self.assertEqual(report["execution_status"], status)
                self.assertEqual(report["evaluation_status"], "NOT_IMPORTED")
                self.assertEqual(report["cleanup_errors"], [])
        self.run_id = "synthetic-cleanup-failure"
        self.work = self.root / self.run_id
        self.refresh_inputs()
        self.successful_processes("TIMEOUT", -9)
        self.api.side_effect = lambda path, method, route: (
            (500, b"") if method == "DELETE" else (404, b"")
        )
        report = runner.run(self.plan(), execute=True)
        self.assertEqual(report["execution_status"], "CLEANUP_FAILED")
        self.assertEqual(report["prior_execution_status"], "TIMEOUT")
        self.assertTrue(report["cleanup_errors"])

    def test_host_process_cleanup_failure_is_not_hidden_by_successful_container_cleanup(self):
        self.process.side_effect = [
            self.probe_result(),
            runner.CleanupFailure("Host process could not be killed"),
        ]
        report = runner.run(self.plan(), execute=True)
        self.assertEqual(report["execution_status"], "CLEANUP_FAILED")
        self.assertIn("Host process", report["cleanup_errors"][0])

    def test_api_access_failure_and_preflight_interruption_do_not_start_harness(self):
        self.api_json.side_effect = OSError("API access denied")
        report = runner.run(self.plan(), execute=True)
        self.assertEqual(report["execution_status"], "UNAVAILABLE")
        self.process.assert_not_called()
        self.api_json.side_effect = self.metadata
        self.process.return_value = runner.ProcessResult("INTERRUPTED", -15)
        report = runner.run(self.plan(), execute=True)
        self.assertEqual(report["execution_status"], "INTERRUPTED")
        self.assertFalse(self.work.exists())

    def test_cli_preview_execute_gate_and_input_output_protection(self):
        args = [
            "--benchmark",
            "swebench-run",
            "--manifest",
            str(self.manifest),
            "--predictions",
            str(self.predictions),
            "--prediction-export",
            str(self.export),
            "--tasks",
            str(self.dataset),
            "--run-manifest",
            str(self.receipt),
            "--run-id",
            self.run_id,
            "--work-dir",
            str(self.work),
        ]
        output = self.root / "preview.json"
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(args + ["--output-json", str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())["execution_status"], "PREVIEW")
        self.process.assert_not_called()
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(args + ["--output-json", str(self.manifest)])
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(args + ["--output-json", str(self.work / "report.json")])
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(["--benchmark", "mini", "--execute"])
        self.endpoint.side_effect = runner.Unavailable("No rootless API")
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(args + ["--execute"]), 2)
        self.process.assert_not_called()


class RunnerProcessAndAPITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def process(self, stdout=b"", stderr=b"", running=False):
        process = Mock(pid=12345)
        process.stdout, process.stderr = io.BytesIO(stdout), io.BytesIO(stderr)
        process.returncode = None if running else 0
        process.poll.side_effect = lambda: process.returncode
        process.wait.side_effect = lambda **kwargs: process.returncode
        return process

    def invoke(self, process, **options):
        def kill(pid, sig):
            if process.returncode is None:
                process.returncode = -int(sig)

        with (
            patch("subprocess.Popen", return_value=process) as spawn,
            patch.object(runner.os, "killpg", side_effect=kill, create=True) as stop,
            patch.object(runner.signal, "SIGKILL", 9, create=True),
        ):
            result = runner._run_process(
                ["trusted-python", "-m", "trusted-module"],
                cwd=self.root,
                environment={"HOME": str(self.root)},
                timeout=options.get("timeout", 5),
                log_limit=options.get("log_limit", runner.MIB),
                console_limit=options.get("console_limit", 1024),
            )
        return result, spawn, stop

    def test_process_uses_no_shell_fresh_session_and_bounded_output(self):
        result, spawn, _ = self.invoke(self.process(b"ok", b"diagnostic"))
        self.assertEqual(result.status, "COMPLETED")
        self.assertEqual(result.stdout, b"ok")
        self.assertFalse(spawn.call_args.kwargs["shell"])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        for stdout, stderr in ((b"x" * 100, b""), (b"", b"x" * 100)):
            result, _, stop = self.invoke(
                self.process(stdout, stderr, running=True), console_limit=8
            )
            self.assertEqual(result.status, "LOG_LIMIT")
            self.assertLessEqual(len(result.stdout), 8)
            self.assertLessEqual(len(result.stderr), 8)
            self.assertEqual(stop.call_args.args[1], getattr(signal, "SIGKILL", 9))

    def test_timeout_log_budget_and_interrupt_stop_process_group(self):
        with patch.object(runner.time, "monotonic", side_effect=[0, 10]):
            result, _, _ = self.invoke(self.process(running=True), timeout=1)
        self.assertEqual(result.status, "TIMEOUT")
        with patch.object(runner, "_log_bytes", return_value=100):
            result, _, _ = self.invoke(self.process(running=True), log_limit=8)
        self.assertEqual(result.status, "LOG_LIMIT")
        with patch.object(runner, "_log_bytes", side_effect=KeyboardInterrupt):
            result, _, _ = self.invoke(self.process(running=True))
        self.assertEqual(result.status, "INTERRUPTED")

    def test_interruption_during_term_wait_still_escalates_to_kill(self):
        process = self.process(running=True)
        process.wait.side_effect = [KeyboardInterrupt(), 0]
        with (
            patch.object(runner.os, "killpg", create=True) as kill,
            patch.object(runner.signal, "SIGKILL", 9, create=True),
        ):
            runner._stop(process)
        self.assertEqual(kill.call_args.args, (process.pid, 9))

    def test_endpoint_rejects_system_socket_root_user_and_missing_rootless_socket(self):
        with (
            patch.object(runner.sys, "platform", "linux"),
            patch.object(runner, "os", wraps=os) as platform,
            patch.object(Path, "is_socket", return_value=True),
            patch.object(Path, "stat", return_value=SimpleNamespace(st_uid=1000)),
        ):
            platform.getuid = Mock(return_value=1000)
            self.assertEqual(
                str(runner._endpoint("docker")), str(Path("/run/user/1000/docker.sock"))
            )
            self.assertEqual(
                str(runner._endpoint("podman")), str(Path("/run/user/1000/podman/podman.sock"))
            )
            platform.getuid.return_value = 0
            with self.assertRaises(runner.Unavailable):
                runner._endpoint("docker")
            platform.getuid.return_value = 1000
            with (
                patch.object(Path, "is_socket", return_value=False),
                self.assertRaises(runner.Unavailable),
            ):
                runner._endpoint("docker")

    def test_api_response_limits_and_http_errors_are_checked_without_containers(self):
        response = Mock(status=200)
        response.read.return_value = b"x" * 65_537
        connection = Mock()
        connection.getresponse.return_value = response
        with (
            patch.object(runner, "UnixAPI", return_value=connection),
            self.assertRaises(runner.Unavailable),
        ):
            runner._api(Path("/rootless.sock"), "GET", "/info")
        connection.close.assert_called_once()
        with (
            patch.object(runner, "_api", return_value=(403, b"denied")),
            self.assertRaises(runner.Unavailable),
        ):
            runner._api_json(Path("/rootless.sock"), "/info")

    def test_api_wall_deadline_aborts_even_a_slow_partial_response(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200)
        connection.getresponse.return_value.read.return_value = b"{}"
        deadlines = []

        def timer(seconds, callback):
            self.assertEqual(seconds, 5)
            deadline = Mock()
            deadline.start.side_effect = callback
            deadlines.append(deadline)
            return deadline

        with (
            patch.object(runner, "UnixAPI", return_value=connection),
            patch.object(runner.threading, "Timer", side_effect=timer),
        ):
            with self.assertRaisesRegex(runner.Unavailable, "deadline"):
                runner._api(Path("/rootless.sock"), "GET", "/info")
        connection.abort.assert_called_once()
        connection.close.assert_called_once()
        deadlines[0].cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
