"""Synthetic report fixtures only; never evidence of real agent/benchmark performance."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from evals import injection_harness as injection
from evals.arena import (
    agent_runner,
    cli,
    redteam,
    reporting,
    runner,
    swebench,
    swebench_eval,
    swebench_runner,
)
from tools import container_sandbox as sandbox


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ArenaReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.guards = []
        for target in (
            "subprocess.run",
            "subprocess.Popen",
            "urllib.request.urlopen",
            "tools.container_sandbox.detect_container_runtime",
            "tools.container_sandbox.execute_sandbox",
            "tools.container_sandbox.execute_adapter",
            "evals.arena.runner.run_mini",
            "evals.arena.agent_runner.run_agent",
            "evals.arena.swebench_runner.run",
            "evals.arena.swebench_eval.import_results",
            "evals.injection_harness.verify_agent_response",
        ):
            self.guards.append(
                self.enterContext(
                    patch(target, side_effect=AssertionError("Offline aggregation only"))
                )
            )

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def write(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def provenance(self, entries):
        records = {}
        for path, origin, extra in entries:
            key = hashlib.sha256(path.read_bytes()).hexdigest()
            records[key] = {"report_sha256": key, "origin": origin, **extra}
        return self.write(
            "provenance.json", {"schema_version": 1, "reports": list(records.values())}
        )

    def witness(self, *paths, origin="recorded-agent"):
        return self.provenance(
            [
                (
                    path,
                    origin,
                    {
                        "evaluation_set_sha256": digest("same-fixtures"),
                        "evaluator_sha256": digest("same-verifier"),
                    },
                )
                for path in paths
            ]
        )

    def response_report(
        self, verdicts=("DEFENDED", "COMPROMISED"), *, agent=False, adapter_test=False
    ):
        results, executions = [], []
        for index, verdict in enumerate(verdicts):
            results.append(
                injection.EvaluationResult(
                    f"CASE:{index}",
                    "direct_override",
                    "skill:review",
                    "Synthetic fixture",
                    verdict,
                    ["Synthetic format result"],
                    verdict == "COMPROMISED",
                    False,
                    "PRIVATE_RESPONSE_DO_NOT_RENDER",
                )
            )
            executions.append(
                agent_runner.AgentExecution(
                    f"CASE:{index}",
                    "skill:review",
                    "COMPLETED",
                    "Synthetic protocol fixture",
                    "adapter-test" if adapter_test else "agent",
                )
            )
        scored = redteam.RedteamReport(results)
        if not agent:
            return scored.to_dict()
        scored.benchmark = "agent"
        scored.scope = agent_runner.SCOPE
        scored.live_agent_run = any(verdict != "NOT_EVALUATED" for verdict in verdicts)
        scored.evidence_kind = (
            "container-adapter-agent-responses"
            if scored.live_agent_run
            else "container-adapter-no-agent-responses"
        )
        return agent_runner.AgentReport(
            scored,
            "synthetic-adapter:v1",
            "docker",
            len(results),
            "sha256:" + digest("adapter"),
            executions,
        ).to_dict()

    def mini_report(self, failed=False):
        report = runner.ArenaReport(
            "synthetic-image:v1", "docker", "sha256:" + digest("mini-image")
        )
        for index in range(1, 6):
            failure = failed and index == 1
            execution = sandbox.SandboxResult(
                "COMPLETED",
                1 if failure else 0,
                0.1,
                False,
                "docker",
                "synthetic output",
                "",
                sandbox.SecurityConfig(memory_limit=runner.MEMORY, cpu_limit=runner.CPUS),
            )
            report.results.append(
                runner.ArenaResult(
                    f"mini-{index:02d}",
                    f"Synthetic smoke {index}",
                    "FAIL" if failure else "PASS",
                    "Synthetic fixture",
                    execution,
                )
            )
        return report.to_dict()

    def swe_report(
        self, outcomes=("RESOLVED", "UNRESOLVED"), *, confirmed=True, run="synthetic-run"
    ):
        rows = []
        for index, status in enumerate(outcomes):
            rows.append(
                {
                    "instance_id": f"example__project-{index}",
                    "prediction_status": "READY",
                    "prediction_sha256": digest(f"{run}-prediction-{index}"),
                    "model_patch_sha256": digest(f"{run}-patch-{index}"),
                    "status": status,
                    "reason": "BOUND_HARNESS_REPORT"
                    if status in {"RESOLVED", "UNRESOLVED"}
                    else "NO_HARNESS_ARTIFACTS",
                }
            )
            if status in {"RESOLVED", "UNRESOLVED"}:
                rows[-1].update(
                    artifact_patch_sha256=rows[-1]["model_patch_sha256"],
                    report_sha256=digest(f"report-{run}-{index}"),
                )
        counts = {
            status: outcomes.count(status)
            for status in ("RESOLVED", "UNRESOLVED", "ERROR", "NOT_EVALUATED")
        }
        evaluated = counts["RESOLVED"] + counts["UNRESOLVED"]
        available = confirmed and evaluated == len(rows)
        return {
            "schema_version": 1,
            "benchmark": "swebench-results",
            "scope": swebench_eval.SCOPE,
            "status": "COMPLETE" if evaluated == len(rows) else "INCOMPLETE",
            "evidence_kind": "user-attested-official-harness-artifacts"
            if confirmed
            else "unattested-harness-artifacts",
            "harness_run_confirmed_by_user": confirmed,
            "results_format": swebench_eval.RESULTS_FORMAT,
            "run_id": run,
            "manifest_sha256": digest("same-manifest"),
            "source_sha256": digest("same-source"),
            "predictions_sha256": digest(run + "-predictions"),
            "export_sha256": digest(run + "-export"),
            "run_manifest_sha256": digest(run + "-receipt"),
            "results_directory": str(self.root / "artifacts"),
            "model_name_or_path": "synthetic/model",
            "results": rows,
            "summary": {
                **counts,
                "selected_tasks": len(rows),
                "predictions_present": len(rows),
                "evaluated_tasks": evaluated,
                "coverage_pct": 100.0 * evaluated / len(rows),
                "prediction_coverage_pct": 100.0,
                "metrics_available": available,
                "resolution_rate_pct": 100.0 * counts["RESOLVED"] / len(rows)
                if available
                else None,
                "pass_at_1": counts["RESOLVED"] / len(rows) if available else None,
            },
        }

    def test_asr_regression_direction_percentage_point_threshold_and_provenance(self):
        baseline = self.write("baseline.json", self.response_report(("DEFENDED", "DEFENDED")))
        head = self.write("head.json", self.response_report())
        provenance = self.witness(baseline, head)
        data = reporting.aggregate([], baseline=baseline, head=head, provenance=provenance)
        self.assertEqual(data["comparison"]["status"], "REGRESSION")
        metric = data["comparison"]["metrics"][0]
        self.assertEqual(metric["delta_pp"], 50)
        self.assertEqual(data["summary"]["regressions"], 1)
        self.assertNotIn(
            "PRIVATE_RESPONSE_DO_NOT_RENDER", json.dumps(data) + reporting.markdown_report(data)
        )
        tolerated = reporting.aggregate(
            [],
            baseline=baseline,
            head=head,
            provenance=provenance,
            thresholds=reporting.Thresholds(asr_increase_pp=50),
        )
        self.assertEqual(tolerated["status"], "NO_REGRESSION")
        self.assertEqual(
            data["leaderboards"][0]["rows"][0]["report_id"], digest(baseline.read_text())
        )

    def test_identical_baseline_head_is_incomparable_without_changing_deduplication(self):
        baseline = self.write("baseline.json", self.response_report())
        duplicate = self.root / "duplicate.json"
        duplicate.write_bytes(baseline.read_bytes())
        provenance = self.witness(baseline)
        for head in (baseline, duplicate):
            with self.subTest(head=head.name):
                data = reporting.aggregate([], baseline=baseline, head=head, provenance=provenance)
                comparison = data["comparison"]
                self.assertEqual(data["status"], "INCOMPARABLE")
                self.assertEqual(comparison["status"], "INCOMPARABLE")
                self.assertEqual(comparison["baseline"], comparison["head"])
                self.assertIn("identical report SHA-256", " ".join(comparison["reasons"]))
                self.assertEqual(comparison["metrics"], [])
                self.assertEqual(data["regressions"], [])
                self.assertEqual(data["summary"]["unique_reports"], 1)
                self.assertEqual(data["summary"]["ranked_reports"], 1)
                inventory = reporting.aggregate([baseline, head], provenance=provenance)
                self.assertEqual(inventory["status"], "SUMMARY")
                self.assertEqual(data["reports"], inventory["reports"])
                self.assertEqual(data["leaderboards"], inventory["leaderboards"])

    def test_swe_rates_are_separate_and_resolution_drop_is_a_regression(self):
        baseline = self.write("baseline.json", self.swe_report(("RESOLVED", "RESOLVED")))
        head = self.write("head.json", self.swe_report(run="synthetic-head"))
        data = reporting.aggregate([], baseline=baseline, head=head)
        self.assertEqual(data["status"], "REGRESSION")
        self.assertEqual(data["comparison"]["metrics"][0]["delta_pp"], -50)
        self.assertEqual(data["comparison"]["metrics"][0]["metric"], "resolution_rate_pct")
        self.assertEqual(len(data["leaderboards"]), 1)
        self.assertEqual(data["leaderboards"][0]["better"], "higher")
        self.assertNotIn("pass_at_1", data["comparison"]["metrics"][0])

    def test_complete_unresolved_results_have_a_genuine_zero_not_a_missing_metric(self):
        path = self.write("unresolved.json", self.swe_report(("UNRESOLVED", "UNRESOLVED")))
        data = reporting.aggregate([path])
        self.assertEqual(data["reports"][0]["evaluation_status"], "EVALUATED")
        self.assertEqual(data["reports"][0]["value"], 0.0)
        self.assertEqual(data["summary"]["ranked_reports"], 1)

    def test_incompatible_benchmarks_scopes_data_and_evaluators_have_no_deltas(self):
        baseline = self.write("baseline.json", self.swe_report())
        for mutate in (
            lambda data: data.update(source_sha256=digest("different-source")),
            lambda data: data.update(manifest_sha256=digest("different-manifest")),
            lambda data: data["results"][0].update(instance_id="different-task"),
        ):
            candidate = self.swe_report(run="head")
            mutate(candidate)
            head = self.write("head.json", candidate)
            data = reporting.aggregate([], baseline=baseline, head=head)
            self.assertEqual(data["status"], "INCOMPARABLE")
            self.assertEqual(data["comparison"]["metrics"], [])
        recorded = self.write("recorded.json", self.response_report())
        data = reporting.aggregate(
            [], baseline=baseline, head=recorded, provenance=self.witness(recorded)
        )
        self.assertEqual(data["status"], "INCOMPARABLE")
        self.assertEqual(len(data["leaderboards"]), 2)
        other = self.write("other.json", self.response_report(("DEFENDED", "DEFENDED")))
        provenance = self.provenance(
            [
                (
                    recorded,
                    "recorded-agent",
                    {"evaluation_set_sha256": digest("set"), "evaluator_sha256": digest("v1")},
                ),
                (
                    other,
                    "recorded-agent",
                    {"evaluation_set_sha256": digest("set"), "evaluator_sha256": digest("v2")},
                ),
            ]
        )
        self.assertEqual(
            reporting.aggregate([], baseline=recorded, head=other, provenance=provenance)["status"],
            "INCOMPARABLE",
        )

    def test_legacy_no_provenance_partial_unconfirmed_and_synthetic_evidence_are_unranked(self):
        recorded = self.write("legacy.json", self.response_report())
        legacy = reporting.aggregate([], baseline=recorded, head=recorded)
        self.assertEqual(legacy["status"], "INCOMPARABLE")
        self.assertIsNone(legacy["reports"][0]["value"])
        self.assertEqual(legacy["leaderboards"], [])
        baseline = self.write("baseline.json", self.swe_report())
        for outcomes, confirmed in (
            (("RESOLVED", "NOT_EVALUATED"), True),
            (("ERROR", "NOT_EVALUATED"), True),
            (("RESOLVED", "UNRESOLVED"), False),
        ):
            head = self.write(
                "head.json", self.swe_report(outcomes, confirmed=confirmed, run="head")
            )
            data = reporting.aggregate([], baseline=baseline, head=head)
            self.assertEqual(data["status"], "INCOMPARABLE")
            self.assertEqual(data["regressions"], [])
        head = self.write(
            "head.json", self.swe_report(("RESOLVED", "RESOLVED"), run="synthetic-head")
        )
        provenance = self.provenance([(head, "synthetic", {})])
        data = reporting.aggregate([], baseline=baseline, head=head, provenance=provenance)
        synthetic = next(row for row in data["reports"] if row["reliability"] == "SYNTHETIC")
        self.assertEqual(synthetic["evaluation_status"], "NOT_EVALUATED")
        self.assertIsNone(synthetic["value"])
        self.assertEqual(synthetic["coverage"]["evaluated"], 0)
        self.assertEqual(synthetic["reported_coverage"]["evaluated"], 2)

    def test_agent_adapter_tests_and_partial_recordings_never_become_success_rates(self):
        adapter = self.write(
            "adapter.json",
            self.response_report(("NOT_EVALUATED", "NOT_EVALUATED"), agent=True, adapter_test=True),
        )
        real = self.write("agent.json", self.response_report(agent=True))
        metadata = self.witness(adapter, real, origin="container-agent")
        data = reporting.aggregate([], baseline=adapter, head=real, provenance=metadata)
        self.assertEqual(data["status"], "INCOMPARABLE")
        adapter_row = next(
            row for row in data["reports"] if row["report_id"] == digest(adapter.read_text())
        )
        self.assertEqual(adapter_row["source_status"], "COMPLETED")
        self.assertEqual(adapter_row["evaluation_status"], "NOT_EVALUATED")
        self.assertIsNone(adapter_row["value"])
        partial = self.write("partial.json", self.response_report(("DEFENDED", "NOT_EVALUATED")))
        partial_data = reporting.aggregate([partial], provenance=self.witness(partial))
        self.assertEqual(partial_data["reports"][0]["evaluation_status"], "INCOMPLETE")
        self.assertIsNone(partial_data["reports"][0]["value"])

    def test_mini_is_an_infrastructure_bucket_separate_from_model_metrics(self):
        baseline = self.write("mini-base.json", self.mini_report())
        head = self.write("mini-head.json", self.mini_report(failed=True))
        metadata = self.witness(baseline, head, origin="infrastructure")
        data = reporting.aggregate([], baseline=baseline, head=head, provenance=metadata)
        self.assertEqual(data["status"], "REGRESSION")
        self.assertEqual(data["comparison"]["metrics"][0]["metric"], "infrastructure_pass_pct")
        self.assertEqual(data["comparison"]["metrics"][0]["delta_pp"], -20)
        self.assertEqual(data["reports"][0]["phase"], "infrastructure")

    def test_m5_preparation_predictions_harness_preview_and_m3_fixtures_are_not_evaluations(self):
        task = {
            "instance_id": "example__project-1",
            "repo": "example/project",
            "base_commit": "a" * 40,
            "problem_statement": "PRIVATE_PROBLEM",
            "FAIL_TO_PASS": ["test_fix"],
            "PASS_TO_PASS": [],
            "patch": "PRIVATE_GOLD",
            "test_patch": "PRIVATE_TEST_PATCH",
            "version": "1.0",
        }
        source = self.write("source.json", [task])
        m5a = swebench.prepare(source)
        manifest = self.write("m5a.json", m5a.to_dict())
        predictions = {
            task["instance_id"]: {
                "instance_id": task["instance_id"],
                "model_name_or_path": "synthetic-model",
                "model_patch": "PRIVATE_PREDICTION",
            }
        }
        prepared = swebench_eval.PredictionSet(
            digest("manifest"),
            digest("source"),
            digest("predictions"),
            "synthetic-run",
            m5a.tasks,
            predictions,
        )
        prediction_report = self.write("m5b.json", prepared.to_dict())
        plan = swebench_runner.RunPlan(
            prepared,
            b"[]",
            b"",
            digest("source"),
            b"{}",
            digest("receipt"),
            self.root / "work",
            self.root / "python",
            "docker",
            1,
            3600,
            1800,
            128 * swebench_runner.MIB,
            (task["instance_id"],),
        )
        preview = self.write("m5c.json", plan.report())
        completed_data = plan.report()
        completed_data.update(execution_status="COMPLETED", preflight="PASSED", exit_code=0)
        completed = self.write("m5c-completed.json", completed_data)
        failed_data = plan.report()
        failed_data.update(
            execution_status="CLEANUP_FAILED",
            preflight="PASSED",
            prior_execution_status="FAILED",
            cleanup_errors=["Synthetic cleanup failure"],
        )
        failed = self.write("m5c-failed.json", failed_data)
        fixture = injection.AdversarialTestCase(
            "INJ-TEST",
            "direct_override",
            "Synthetic fixture",
            "PRIVATE_PAYLOAD",
            ["skill"],
            "Synthetic objective",
            "PRIVATE_CANARY",
            [],
        )
        fixtures = self.write("fixtures.json", [asdict(fixture)])
        data = reporting.aggregate(
            [manifest, prediction_report, preview, completed, failed, fixtures]
        )
        self.assertTrue(all(row["evaluation_status"] == "NOT_EVALUATED" for row in data["reports"]))
        self.assertTrue(all(row["value"] is None for row in data["reports"]))
        self.assertEqual(data["leaderboards"], [])
        self.assertEqual(data["summary"]["execution_errors"], 1)
        text = json.dumps(data) + reporting.markdown_report(data)
        for private in (
            "PRIVATE_PROBLEM",
            "PRIVATE_GOLD",
            "PRIVATE_TEST_PATCH",
            "PRIVATE_PREDICTION",
            "PRIVATE_PAYLOAD",
            "PRIVATE_CANARY",
        ):
            self.assertNotIn(private, text)

    def test_invalid_schema_types_duplicate_ids_flags_summaries_and_hashes_fail_closed(self):
        valid = self.swe_report()
        invalid = [None, {}, {**valid, "benchmark": "unknown"}, {**valid, "schema_version": True}]
        for mutate in (
            lambda data: data["results"].append(copy.deepcopy(data["results"][0])),
            lambda data: data["results"][0].update(instance_id="../unsafe"),
            lambda data: data["results"][0].update(artifact_patch_sha256=digest("wrong-patch")),
            lambda data: data["summary"].update(RESOLVED=99),
            lambda data: data["summary"].update(metrics_available=1),
            lambda data: data.update(harness_run_confirmed_by_user=1),
            lambda data: data.update(source_sha256="bad"),
        ):
            data = copy.deepcopy(valid)
            mutate(data)
            invalid.append(data)
        response = self.response_report()
        for mutate in (
            lambda data: data["results"].append(copy.deepcopy(data["results"][0])),
            lambda data: data["summary"].update(attack_success_rate_pct=0),
            lambda data: data["results"][0].update(canary_leaked=True),
            lambda data: data.pop("summary"),
        ):
            data = copy.deepcopy(response)
            mutate(data)
            invalid.append(data)
        for index, data in enumerate(invalid):
            path = self.write("invalid.json", data)
            with self.subTest(index=index), self.assertRaises(ValueError):
                reporting.aggregate([path])

    def test_report_synthetic_marker_cannot_be_overridden_by_a_positive_declaration(self):
        data = self.swe_report()
        data["synthetic"] = True
        path = self.write("synthetic.json", data)
        metadata = self.provenance([(path, "official-harness", {})])
        summary = reporting.aggregate([path], provenance=metadata)
        self.assertEqual(summary["reports"][0]["reliability"], "SYNTHETIC")
        self.assertEqual(summary["leaderboards"], [])
        self.assertIsNone(summary["reports"][0]["value"])

    def test_json_byte_bounds_nonfinite_duplicate_keys_and_provenance_validation(self):
        path = self.write("valid.json", self.swe_report())
        with patch.object(reporting, "MAX_REPORT_BYTES", 8), self.assertRaises(ValueError):
            reporting.aggregate([path])
        with patch.object(reporting, "MAX_TOTAL_BYTES", 8), self.assertRaises(ValueError):
            reporting.aggregate([path])
        for value in (float("nan"), float("inf"), -1, 101, True, "1"):
            with self.assertRaises(ValueError):
                reporting.Thresholds(asr_increase_pp=value).to_dict()
        for raw in (
            b"\xff",
            b"{",
            b'{"benchmark":"mini","benchmark":"agent"}',
            b"[NaN]",
            b"[" * 2000,
        ):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                reporting.aggregate([path])
        path = self.write("valid.json", self.swe_report())
        bad = self.write(
            "provenance.json",
            {
                "schema_version": 1,
                "reports": [{"report_sha256": digest("unknown"), "origin": "synthetic"}],
            },
        )
        with self.assertRaises(ValueError):
            reporting.aggregate([path], provenance=bad)
        metadata = self.witness(path, origin="official-harness")
        doc = json.loads(metadata.read_text())
        doc["reports"].append(copy.deepcopy(doc["reports"][0]))
        metadata.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(ValueError):
            reporting.aggregate([path], provenance=metadata)

    def test_determinism_ties_content_deduplication_and_markdown_escaping(self):
        first = self.write("first.json", self.swe_report())
        second_data = self.swe_report(run="another-synthetic-run")
        second = self.write("second.json", second_data)
        copy_path = self.write("copy.json", json.loads(first.read_text()))
        metadata = self.provenance(
            [(second, "official-harness", {"model_id": "<script>|# heading"})]
        )
        a = reporting.aggregate([first, second, copy_path], provenance=metadata)
        b = reporting.aggregate([copy_path, second, first], provenance=metadata)
        self.assertEqual(a, b)
        self.assertEqual(a["summary"]["unique_reports"], 2)
        self.assertEqual([row["rank"] for row in a["leaderboards"][0]["rows"]], [1, 1])
        text = reporting.markdown_report(a)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;&#124;# heading", text)
        self.assertNotIn("PRIVATE_RESPONSE_DO_NOT_RENDER", text)

    def test_cli_is_offline_deterministic_and_protects_input_aliases(self):
        baseline = self.write("baseline.json", self.swe_report(("RESOLVED", "RESOLVED")))
        head = self.write("head.json", self.swe_report(run="head"))
        output, markdown = self.root / "summary.json", self.root / "summary.md"
        args = [
            "--benchmark",
            "reporting",
            "--baseline",
            str(baseline),
            "--head",
            str(head),
            "--output-json",
            str(output),
            "--report",
            str(markdown),
        ]
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(args), 1)
            before = output.read_bytes()
            self.assertEqual(cli.main(args), 1)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(cli.main(args + ["--resolution-drop-pp", "50"]), 0)
        self.assertNotIn(b"\r\n", output.read_bytes())
        original = baseline.read_bytes()
        for alias in (baseline, self.root / "alias.json"):
            if alias != baseline:
                try:
                    alias.hardlink_to(baseline)
                except (OSError, NotImplementedError):
                    continue
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(
                    [
                        "--benchmark",
                        "reporting",
                        "--reports",
                        str(baseline),
                        "--output-json",
                        str(alias),
                    ]
                )
        self.assertEqual(baseline.read_bytes(), original)
        for invalid_args in (
            ["--benchmark", "mini", "--baseline", str(baseline)],
            ["--benchmark", "reporting", "--reports", str(baseline), "--execute"],
        ):
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(invalid_args)
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(cli.main(["--benchmark", "reporting", "--baseline", str(baseline)]), 1)
            self.assertEqual(cli.main(args + ["--resolution-drop-pp", "nan"]), 1)
        legacy = self.write("legacy.json", self.response_report())
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(
                cli.main(
                    ["--benchmark", "reporting", "--baseline", str(legacy), "--head", str(legacy)]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
