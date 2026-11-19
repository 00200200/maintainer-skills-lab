"""Manual Actions bridge tests; synthetic reports and no benchmark execution."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals import injection_harness as injection
from evals.arena import redteam, reporting
from tools import arena_regression as bridge


class ArenaRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repository = self.root / "repository"
        self.trusted = self.repository.joinpath(*bridge.TRUSTED_DIRECTORY)
        self.trusted.mkdir(parents=True)
        self.temporary = self.root / "runner-temp"
        self.temporary.mkdir()
        self.output = self.temporary / "outputs.txt"
        self.summary = self.temporary / "summary.md"
        self.output.write_text("", encoding="utf-8")
        self.summary.write_text("", encoding="utf-8")
        self.environment = {
            "RUNNER_TEMP": str(self.temporary),
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "ARENA_BASELINE": "baseline.json",
            "ARENA_HEAD": "head.json",
            "ARENA_PROVENANCE": "provenance.json",
        }
        self.inputs()
        self.guards = []
        for target in (
            "subprocess.run",
            "subprocess.Popen",
            "urllib.request.urlopen",
            "tools.container_sandbox.execute_sandbox",
            "tools.container_sandbox.execute_adapter",
            "tools.container_sandbox.detect_container_runtime",
            "evals.arena.runner.run_mini",
            "evals.arena.agent_runner.run_agent",
            "evals.arena.swebench_runner.run",
            "evals.arena.swebench_eval.import_results",
            "evals.injection_harness.verify_agent_response",
        ):
            self.guards.append(
                self.enterContext(
                    patch(target, side_effect=AssertionError("Offline reporting only"))
                )
            )

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def inputs(self, *, regression=False):
        declarations = {}
        for name, compromised in (("baseline.json", False), ("head.json", regression)):
            # Simulated report shapes exercise the gate; these are not actual agent results.
            report = redteam.RedteamReport(
                [
                    injection.EvaluationResult(
                        "CASE-1",
                        "direct_override",
                        "mkl-review-pr",
                        "Synthetic contract fixture",
                        "COMPROMISED" if compromised else "DEFENDED",
                        ["Synthetic unit fixture"],
                        compromised,
                        False,
                        f"$(never_execute_this) PRIVATE_EXCERPT {name}",
                    )
                ]
            ).to_dict()
            raw = json.dumps(report).encode()
            (self.trusted / name).write_bytes(raw)
            key = hashlib.sha256(raw).hexdigest()
            declarations[key] = {
                "report_sha256": key,
                "origin": "recorded-agent",
                "evaluation_set_sha256": "a" * 64,
                "evaluator_sha256": "b" * 64,
            }
        (self.trusted / "provenance.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "reports": list(declarations.values()),
                }
            ),
            encoding="utf-8",
        )

    def collect(self):
        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            return bridge.collect(repository=self.repository, environment=self.environment)

    def outputs(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def enforce(self, *, outcome="success", **overrides):
        values = self.outputs()
        environment = {
            **self.environment,
            "ARENA_REPORTING_COMPLETED": values.get("reporting_completed", ""),
            "ARENA_RESULT_STATUS": values.get("result_status", ""),
            "ARENA_REPORTING_OUTCOME": outcome,
            **overrides,
        }
        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            return bridge.enforce(repository=self.repository, environment=environment)

    def artifacts(self):
        return bridge.output_directory(self.repository, self.environment)

    def test_valid_collection_delegates_to_m6a_and_preserves_repository_bytes(self):
        before = {
            path.relative_to(self.repository): path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }
        with patch.object(bridge.reporting, "aggregate", wraps=reporting.aggregate) as aggregate:
            self.assertEqual(self.collect(), 0)
        aggregate.assert_called_once_with(
            [],
            baseline=self.trusted / "baseline.json",
            head=self.trusted / "head.json",
            provenance=self.trusted / "provenance.json",
        )
        self.assertEqual(self.outputs()["reporting_completed"], "true")
        self.assertEqual(self.outputs()["result_status"], "NO_REGRESSION")
        self.assertEqual(self.enforce(), 0)
        directory = self.artifacts()
        self.assertEqual(
            {path.name for path in directory.iterdir()}, {"report.json", "report.md", "result.json"}
        )
        report = json.loads((directory / "report.json").read_text())
        self.assertEqual(report["benchmark"], "reporting")
        self.assertIn("NO_REGRESSION", self.summary.read_text())
        self.assertNotIn("PRIVATE_EXCERPT", self.summary.read_text())
        self.assertNotIn(b"\r\n", (directory / "report.json").read_bytes())
        after = {
            path.relative_to(self.repository): path.read_bytes()
            for path in self.repository.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_regression_and_incomparable_artifacts_exist_before_nonzero_gate(self):
        self.inputs(regression=True)
        self.assertEqual(self.collect(), 0)
        self.assertEqual(self.outputs()["result_status"], "REGRESSION")
        self.assertEqual(self.enforce(), 1)
        self.assertTrue((self.artifacts() / "report.json").is_file())
        self.assertTrue((self.artifacts() / "report.md").is_file())
        self.environment["GITHUB_RUN_ATTEMPT"] = "2"
        self.environment["ARENA_PROVENANCE"] = ""
        self.assertEqual(self.collect(), 0)
        self.assertEqual(self.outputs()["result_status"], "INCOMPARABLE")
        self.assertEqual(self.enforce(), 2)
        self.assertIn("INCOMPARABLE", self.summary.read_text())

    def test_identical_reports_keep_diagnostics_but_fail_the_gate(self):
        baseline = self.trusted / "baseline.json"
        (self.trusted / "head.json").write_bytes(baseline.read_bytes())
        provenance = self.trusted / "provenance.json"
        declarations = json.loads(provenance.read_text(encoding="utf-8"))
        digest = hashlib.sha256(baseline.read_bytes()).hexdigest()
        declarations["reports"] = [
            item for item in declarations["reports"] if item["report_sha256"] == digest
        ]
        provenance.write_text(json.dumps(declarations), encoding="utf-8")
        for attempt, head in enumerate(("baseline.json", "head.json"), 1):
            with self.subTest(head=head):
                self.environment["GITHUB_RUN_ATTEMPT"] = str(attempt)
                self.environment["ARENA_HEAD"] = head
                self.assertEqual(self.collect(), 0)
                self.assertEqual(self.outputs()["reporting_completed"], "true")
                self.assertEqual(self.outputs()["result_status"], "INCOMPARABLE")
                directory = self.artifacts()
                self.assertEqual(
                    {path.name for path in directory.iterdir()},
                    {"report.json", "report.md", "result.json"},
                )
                report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["comparison"]["baseline"], digest)
                self.assertEqual(report["comparison"]["head"], digest)
                self.assertEqual(report["comparison"]["metrics"], [])
                self.assertEqual(report["regressions"], [])
                self.assertIn("identical report SHA-256", " ".join(report["comparison"]["reasons"]))
                self.assertIn(
                    "identical report SHA-256",
                    (directory / "report.md").read_text(encoding="utf-8"),
                )
                self.assertIn("INCOMPARABLE", self.summary.read_text(encoding="utf-8"))
                self.assertEqual(self.enforce(), 2)
                self.assertTrue((directory / "report.json").is_file())
                self.assertTrue((directory / "report.md").is_file())

    def test_strict_paths_reject_traversal_absolute_urls_shell_globs_and_bad_types(self):
        for value in (
            "",
            "../baseline.json",
            "folder/../../baseline.json",
            "./baseline.json",
            "a//b.json",
            "/tmp/baseline.json",
            "C:/baseline.json",
            "C:\\baseline.json",
            "\\\\host\\file.json",
            "https://example.invalid/report.json",
            "*.json",
            "$(touch marker).json",
            "`command`.json",
            "file;command.json",
            "file\ncommand.json",
            "--head.json",
            "%2e%2e/report.json",
            "~/.config.json",
            "report.json/",
            "report.jsonl",
            None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.trusted_report(self.repository, value, "baseline")
        nested = self.trusted / "experiment"
        nested.mkdir()
        (nested / "baseline.json").write_text("{}", encoding="utf-8")
        self.assertEqual(
            bridge.trusted_report(self.repository, "experiment/baseline.json", "baseline"),
            nested / "baseline.json",
        )

    def test_symlinks_are_rejected_even_when_they_stay_inside_the_trusted_directory(self):
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        for name, target, directory in (
            ("inside.json", self.trusted / "baseline.json", False),
            ("outside.json", outside, False),
            ("directory", self.trusted, True),
        ):
            path = self.trusted / name
            try:
                path.symlink_to(target, target_is_directory=directory)
            except (OSError, NotImplementedError):
                continue
            value = name + "/baseline.json" if directory else name
            with self.assertRaises(ValueError):
                bridge.trusted_report(self.repository, value, "baseline")
        alternative = self.root / "other-repository"
        alternative.mkdir()
        try:
            (alternative / "evals").symlink_to(self.repository / "evals", target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(ValueError):
            bridge.trusted_report(alternative, "baseline.json", "baseline")

    def test_missing_malformed_and_directory_inputs_never_emit_success_artifacts(self):
        for name, content in (
            ("missing.json", None),
            ("malformed.json", "{broken"),
            ("empty.json", "{}"),
            ("folder.json", "directory"),
        ):
            if content == "directory":
                (self.trusted / name).mkdir()
            elif content is not None:
                (self.trusted / name).write_text(content, encoding="utf-8")
            self.environment["ARENA_HEAD"] = name
            self.environment["GITHUB_RUN_ATTEMPT"] = str(
                int(self.environment["GITHUB_RUN_ATTEMPT"]) + 1
            )
            self.assertEqual(self.collect(), 1)
            self.assertEqual(self.outputs()["reporting_completed"], "false")
            self.assertEqual(self.outputs()["result_status"], "ERROR")
            self.assertFalse((self.artifacts() / "result.json").exists())
            self.assertEqual(self.enforce(outcome="failure"), 1)
        self.assertIn("ERROR", self.summary.read_text())

    def test_failed_collection_cannot_reuse_an_earlier_pass_receipt(self):
        self.assertEqual(self.collect(), 0)
        self.assertEqual(self.enforce(), 0)
        self.environment["ARENA_HEAD"] = "missing.json"
        self.assertEqual(self.collect(), 1)  # The output directory also cannot be reused.
        self.assertEqual(self.outputs()["reporting_completed"], "false")
        self.assertEqual(self.enforce(outcome="failure"), 1)

    def test_each_dispatch_input_is_validated_and_bad_provenance_cannot_pass(self):
        for attempt, name in enumerate(("ARENA_BASELINE", "ARENA_HEAD", "ARENA_PROVENANCE"), 1):
            with self.subTest(name=name):
                original = self.environment[name]
                self.environment["GITHUB_RUN_ATTEMPT"] = str(attempt)
                self.environment[name] = "../escape.json"
                self.assertEqual(self.collect(), 1)
                self.assertEqual(self.outputs()["reporting_completed"], "false")
                self.assertEqual(self.enforce(outcome="failure"), 1)
                self.environment[name] = original
        self.environment["GITHUB_RUN_ATTEMPT"] = "4"
        (self.trusted / "provenance.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.collect(), 1)
        self.assertFalse((self.artifacts() / "result.json").exists())
        self.assertEqual(self.enforce(outcome="failure"), 1)

    def test_gate_requires_valid_receipt_both_files_and_unchanged_hashes(self):
        self.assertEqual(self.enforce(), 1)
        self.assertEqual(self.collect(), 0)
        self.assertEqual(self.enforce(ARENA_REPORTING_COMPLETED="false"), 1)
        self.assertEqual(self.enforce(ARENA_RESULT_STATUS="REGRESSION"), 1)
        directory = self.artifacts()
        original = (directory / "report.json").read_bytes()
        (directory / "report.json").write_bytes(original + b" ")
        self.assertEqual(self.enforce(), 1)
        (directory / "report.json").write_bytes(original)
        (directory / "report.md").unlink()
        self.assertEqual(self.enforce(), 1)

    def test_summary_failure_still_preserves_valid_reports_but_cannot_pass_the_gate(self):
        with patch.object(bridge, "_summary", side_effect=OSError("Summary unavailable")):
            self.assertEqual(self.collect(), 1)
        self.assertEqual(self.outputs()["reporting_completed"], "true")
        self.assertTrue((self.artifacts() / "result.json").exists())
        self.assertEqual(self.enforce(outcome="failure"), 1)

    def test_configuration_cannot_redirect_outputs_into_the_repository(self):
        self.environment["RUNNER_TEMP"] = str(self.repository)
        self.assertEqual(self.collect(), 1)
        self.environment["RUNNER_TEMP"] = str(self.root)
        self.environment["GITHUB_OUTPUT"] = str(self.trusted / "baseline.json")
        original = (self.trusted / "baseline.json").read_bytes()
        self.assertEqual(self.collect(), 1)
        self.assertEqual((self.trusted / "baseline.json").read_bytes(), original)
        self.environment["RUNNER_TEMP"] = str(self.temporary)
        self.environment["GITHUB_OUTPUT"] = str(self.output)
        for value in ("", "../escape", "1\nreporting_completed=true", "01"):
            self.environment["GITHUB_RUN_ID"] = value
            self.assertEqual(self.collect(), 1)

    def test_status_contract_rejects_summary_missing_evidence_and_contradictions(self):
        data = reporting.aggregate(
            [],
            baseline=self.trusted / "baseline.json",
            head=self.trusted / "head.json",
            provenance=self.trusted / "provenance.json",
        )
        self.assertEqual(bridge.result_status(data), "NO_REGRESSION")
        for mutate in (
            lambda value: value.update(status="SUMMARY"),
            lambda value: value.update(comparison=None),
            lambda value: value["comparison"].update(metrics=[]),
            lambda value: value["reports"][0].update(value=None),
            lambda value: value["reports"][0].update(reliability="SYNTHETIC"),
            lambda value: value["comparison"]["metrics"][0].update(regression=True),
        ):
            broken = copy.deepcopy(data)
            mutate(broken)
            with self.assertRaises(ValueError):
                bridge.result_status(broken)


class ArenaWorkflowContractTests(unittest.TestCase):
    def test_workflow_is_manual_read_only_offline_and_preserves_reports_before_enforcement(self):
        path = Path(__file__).resolve().parents[1] / ".github/workflows/arena-regression.yml"
        text = path.read_text(encoding="utf-8")
        # These checks constrain this deliberately small YAML contract without a YAML dependency.
        triggers = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(
            re.findall(r"^  ([a-z_]+):$", triggers, re.MULTILINE), ["workflow_dispatch"]
        )
        permissions = text.split("\npermissions:\n", 1)[1].split("\njobs:", 1)[0]
        self.assertEqual(permissions.strip(), "contents: read")
        self.assertEqual(text.count("permissions:"), 1)
        self.assertIn("timeout-minutes: 5", text)
        self.assertIn("runs-on: ubuntu-latest", text)
        self.assertIn("ref: ${{ github.event.repository.default_branch }}", text)
        self.assertIn(
            "github.ref != format('refs/heads/{0}', github.event.repository.default_branch)", text
        )
        self.assertIn("persist-credentials: false", text)
        self.assertIn("submodules: false", text)
        self.assertIn("lfs: false", text)
        for name in ("baseline", "head", "provenance"):
            self.assertIn(f"${{{{ inputs.{name} }}}}", text)
        runs = re.findall(r"^\s+run: (.+)$", text, re.MULTILINE)
        self.assertEqual(
            runs,
            [
                "exit 1",
                "python3 -B tools/arena_regression.py collect",
                "python3 -B tools/arena_regression.py enforce",
            ],
        )
        self.assertEqual(
            re.findall(r"^\s+uses: (.+)$", text, re.MULTILINE),
            ["actions/checkout@v7", "actions/setup-python@v7", "actions/upload-artifact@v7"],
        )
        self.assertIn("python-version: '3.11'", text)
        self.assertIn("always() && steps.reporting.outputs.reporting_completed == 'true'", text)
        self.assertIn(
            "ARENA_REPORTING_COMPLETED: ${{ steps.reporting.outputs.reporting_completed }}", text
        )
        self.assertIn("ARENA_REPORTING_OUTCOME: ${{ steps.reporting.outcome }}", text)
        self.assertIn("ARENA_RESULT_STATUS: ${{ steps.reporting.outputs.result_status }}", text)
        self.assertLess(
            text.index("tools/arena_regression.py collect"),
            text.index("actions/upload-artifact@v7"),
        )
        self.assertLess(
            text.index("actions/upload-artifact@v7"),
            text.index("tools/arena_regression.py enforce"),
        )
        for artifact in ("report.json", "report.md", "result.json"):
            self.assertIn("${{ steps.reporting.outputs.artifact_dir }}/" + artifact, text)
        self.assertIn("if-no-files-found: error", text)
        for forbidden in (
            "schedule:",
            "pull_request",
            "secrets.",
            "continue-on-error",
            "download-artifact",
            "pip install",
            "pytest",
            "kit.py",
            "token_diff.py",
            "container:",
            "services:",
            "shell:",
            "<<:",
            "!!",
            "git push",
            "git commit",
        ):
            self.assertNotIn(forbidden, text)
        self.assertTrue(all("${{" not in command for command in runs))


if __name__ == "__main__":
    unittest.main()
