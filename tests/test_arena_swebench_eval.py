"""Synthetic M5b format tests only; never actual SWE-bench evaluation evidence."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.arena import cli, swebench
from evals.arena import swebench_eval as evaluation


class SWEbenchEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "synthetic-tasks.json"
        self.manifest = self.root / "manifest.json"
        self.predictions = self.root / "predictions.jsonl"
        self.receipt = self.root / "run.json"
        self.results_dir = self.root / "logs" / "run_evaluation"
        self.results_dir.mkdir(parents=True)
        self.run_id = "synthetic-format-test"
        self.guards = []
        for target in (
            "subprocess.run",
            "subprocess.Popen",
            "urllib.request.urlopen",
            "tools.container_sandbox.detect_container_runtime",
            "tools.container_sandbox.execute_sandbox",
            "tools.container_sandbox.execute_adapter",
            "evals.arena.agent_runner.run_agent",
            "evals.arena.cli.run_mini",
        ):
            guard = self.enterContext(
                patch(target, side_effect=AssertionError("Offline import only"))
            )
            self.guards.append(guard)
        self.task_records = [
            {
                "instance_id": f"example__project-{number}",
                "repo": "example/project",
                "base_commit": "a" * 40,
                "problem_statement": "Synthetic schema unit fixture.",
                "FAIL_TO_PASS": [f"test_fix_{number}"],
                "PASS_TO_PASS": [f"test_existing_{number}"],
                "patch": "PRIVATE_GOLD_SENTINEL",
                "test_patch": "PRIVATE_TEST_PATCH_SENTINEL",
            }
            for number in (1, 2)
        ]
        self.source.write_text(json.dumps(self.task_records), encoding="utf-8")
        self.manifest_data = swebench.prepare(self.source).to_dict()
        self.manifest.write_text(json.dumps(self.manifest_data), encoding="utf-8")
        self.records = [self.prediction(task["instance_id"]) for task in self.task_records]
        self.write_predictions(self.records)
        self.prepared = self.prepare()
        self.save_receipt()

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def prediction(self, instance_id, **updates):
        return {
            "instance_id": instance_id,
            "model_name_or_path": "local/test-model",
            "model_patch": "diff --git a/example.py b/example.py\n--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n",
            **updates,
        }

    def write_predictions(self, records):
        self.predictions.write_bytes(
            b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in records)
        )

    def prepare(self, **kwargs):
        return evaluation.prepare_predictions(
            self.manifest, self.predictions, run_id=kwargs.get("run_id", self.run_id)
        )

    def save_receipt(self):
        self.receipt.write_text(json.dumps(self.prepared.to_dict(), indent=2), encoding="utf-8")

    def artifact_directory(self, index):
        record = self.records[index]
        return (
            self.results_dir
            / self.run_id
            / record["model_name_or_path"].replace("/", "__")
            / record["instance_id"]
        )

    def harness_report(self, index, *, resolved=True):
        task = self.prepared.tasks[index]
        return {
            task.instance_id: {
                "patch_is_None": False,
                "patch_exists": True,
                "patch_successfully_applied": True,
                "resolved": resolved,
                "tests_status": {
                    "FAIL_TO_PASS": {
                        "success": list(task.fail_to_pass) if resolved else [],
                        "failure": [] if resolved else list(task.fail_to_pass),
                    },
                    "PASS_TO_PASS": {"success": list(task.pass_to_pass), "failure": []},
                    "FAIL_TO_FAIL": {"success": [], "failure": []},
                    "PASS_TO_FAIL": {"success": [], "failure": []},
                },
            }
        }

    def write_artifacts(self, index, *, resolved=True, report=None):
        directory = self.artifact_directory(index)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "patch.diff").write_bytes(self.records[index]["model_patch"].encode())
        (directory / "report.json").write_text(
            json.dumps(self.harness_report(index, resolved=resolved) if report is None else report),
            encoding="utf-8",
        )
        return directory

    def import_results(self, **kwargs):
        return evaluation.import_results(
            self.prepared,
            self.receipt,
            self.results_dir,
            results_format=kwargs.get("results_format", evaluation.RESULTS_FORMAT),
            confirm_harness_run=kwargs.get("confirm_harness_run", False),
        )

    def test_export_is_classic_jsonl_sorted_deterministic_and_gold_free(self):
        first = self.prepared.export_bytes
        self.write_predictions(list(reversed(self.records)))
        second = self.prepare()
        self.assertEqual(first, second.export_bytes)
        rows = [json.loads(line) for line in first.splitlines()]
        self.assertEqual(rows, self.records)
        for row in rows:
            self.assertEqual(set(row), {"instance_id", "model_name_or_path", "model_patch"})
        self.assertNotIn(b"PRIVATE_GOLD_SENTINEL", first)
        self.assertNotIn(b"PRIVATE_TEST_PATCH_SENTINEL", first)
        receipt = self.prepared.to_dict()
        self.assertEqual(receipt["export_sha256"], hashlib.sha256(first).hexdigest())
        self.assertEqual(
            receipt["manifest_sha256"], hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        )
        self.assertNotIn('model_patch"', json.dumps(receipt))

    def test_missing_prediction_is_distinct_from_null_or_blank_patch(self):
        for invalid in (None, "", " \n\t"):
            self.write_predictions(
                [self.prediction(self.records[0]["instance_id"], model_patch=invalid)]
            )
            self.prepared = self.prepare()
            self.save_receipt()
            data = self.import_results(confirm_harness_run=True)
            self.assertEqual([row["status"] for row in data["results"]], ["ERROR", "NOT_EVALUATED"])
            self.assertEqual(
                [row["prediction_status"] for row in data["results"]], ["INVALID_PATCH", "MISSING"]
            )
            self.assertEqual(self.prepared.export_bytes, b"")
            self.assertIsNone(data["summary"]["pass_at_1"])
        self.predictions.write_bytes(b"")
        empty = self.prepare()
        self.assertEqual(empty.export_bytes, b"")
        self.assertTrue(
            all(row["prediction_status"] == "MISSING" for row in empty.to_dict()["tasks"])
        )
        self.prepared = empty
        self.save_receipt()
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual(data["summary"]["NOT_EVALUATED"], 2)
        self.assertEqual(data["summary"]["coverage_pct"], 0)
        self.assertIsNone(data["summary"]["pass_at_1"])

    def test_prediction_schema_duplicates_models_ids_and_patch_limits(self):
        valid = self.records[0]
        invalid = [None, [], {**valid, "extra": 1}]
        invalid.extend(
            {key: value for key, value in valid.items() if key != field} for field in valid
        )
        for field, value in (
            ("instance_id", "unknown-id"),
            ("instance_id", "../escape"),
            ("model_name_or_path", "../model"),
            ("model_name_or_path", "/model"),
            ("model_name_or_path", "a//b"),
            ("model_name_or_path", None),
            ("model_patch", {}),
            ("model_patch", "\ud800"),
            ("model_patch", "a\x00b"),
            ("model_patch", "x" * 250_001),
        ):
            invalid.append({**valid, field: value})
        for record in invalid:
            if isinstance(record, dict) and record.get("model_patch") == "\ud800":
                self.predictions.write_text(json.dumps(record), encoding="utf-8")
            else:
                self.write_predictions([record])
            with self.subTest(record=repr(record)[:80]), self.assertRaises(ValueError):
                self.prepare()
        for records in (
            [valid, valid],
            [valid, {**self.records[1], "model_name_or_path": "different-model"}],
        ):
            self.write_predictions(records)
            with self.assertRaises(ValueError):
                self.prepare()
        self.write_predictions([valid])
        with patch.object(evaluation, "MAX_PATCH_BYTES", 8), self.assertRaises(ValueError):
            self.prepare()
        for raw in (
            b"\n",
            b"\xff",
            b'{"instance_id":"a","instance_id":"b"}\n',
            b"[NaN]\n",
            b"[" * 2000,
        ):
            self.predictions.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.prepare()
        for run_id in ("../run", "run/child", "bad\nrun", ""):
            with self.assertRaises(ValueError):
                self.prepare(run_id=run_id)

    def test_manifest_validation_reuses_m5a_and_rejects_tampering(self):
        changes = []
        for field, value in (
            ("schema_version", True),
            ("schema_version", 2),
            ("status", "RESOLVED"),
            ("live_agent_run", True),
        ):
            data = copy.deepcopy(self.manifest_data)
            data[field] = value
            changes.append(data)
        for mutate in (
            lambda data: data["agent_tasks"][0].update(patch="LEAK"),
            lambda data: data["evaluation_tasks"][0].update(instance_id="wrong"),
            lambda data: data["summary"].update(selected_tasks=999),
            lambda data: data["selection"].update(limit=True),
            lambda data: data["source"].update(sha256="invalid"),
            lambda data: data["evaluation_tasks"][0].update(FAIL_TO_PASS=[1]),
        ):
            data = copy.deepcopy(self.manifest_data)
            mutate(data)
            changes.append(data)
        for data in changes:
            self.manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.prepare()

    def test_complete_bound_results_only_expose_rates_after_user_confirmation(self):
        self.write_artifacts(0, resolved=True)
        self.write_artifacts(1, resolved=False)
        unconfirmed = self.import_results()
        self.assertEqual(unconfirmed["status"], "COMPLETE")
        self.assertIsNone(unconfirmed["summary"]["resolution_rate_pct"])
        self.assertIsNone(unconfirmed["summary"]["pass_at_1"])
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual([row["status"] for row in data["results"]], ["RESOLVED", "UNRESOLVED"])
        self.assertEqual(data["summary"]["coverage_pct"], 100)
        self.assertEqual(data["summary"]["resolution_rate_pct"], 50)
        self.assertEqual(data["summary"]["pass_at_1"], 0.5)
        self.assertEqual(data["run_id"], self.run_id)
        for row in data["results"]:
            self.assertRegex(row["prediction_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(row["artifact_patch_sha256"], row["model_patch_sha256"])
            self.assertRegex(row["report_sha256"], r"^[0-9a-f]{64}$")
        for text in (json.dumps(data), evaluation.markdown_report(data)):
            self.assertNotIn("PRIVATE_GOLD_SENTINEL", text)
            self.assertNotIn(self.records[0]["model_patch"], text)

    def test_partial_failed_or_missing_evaluations_never_produce_a_rate(self):
        first = self.write_artifacts(0)
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual([row["status"] for row in data["results"]], ["RESOLVED", "NOT_EVALUATED"])
        self.assertEqual(data["summary"]["coverage_pct"], 50)
        self.assertIsNone(data["summary"]["pass_at_1"])
        second = self.artifact_directory(1)
        second.mkdir(parents=True)
        (second / "patch.diff").write_bytes(self.records[1]["model_patch"].encode())
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual(data["results"][1]["status"], "ERROR")
        self.assertIsNone(data["summary"]["resolution_rate_pct"])
        (first / "report.json").write_text("{}", encoding="utf-8")
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual(data["summary"]["evaluated_tasks"], 0)
        self.assertEqual(data["summary"]["ERROR"], 2)

    def test_unknown_malformed_contradictory_and_foreign_report_schemas_are_errors(self):
        directory = self.write_artifacts(0)
        valid = self.harness_report(0)
        key = self.records[0]["instance_id"]
        invalid = [{}, {"resolved_ids": [key]}, {"wrong-id": valid[key]}]
        for field, value in (
            ("resolved", "true"),
            ("resolved", False),
            ("patch_exists", False),
            ("patch_successfully_applied", False),
            ("unknown", True),
        ):
            data = copy.deepcopy(valid)
            data[key][field] = value
            invalid.append(data)
        for field in ("patch_is_None", "tests_status"):
            data = copy.deepcopy(valid)
            del data[key][field]
            invalid.append(data)
        for tests in (
            {"success": ["foreign-test"], "failure": []},
            {"success": ["test_fix_1"], "failure": ["test_fix_1"]},
            {"success": '["test_fix_1"]', "failure": []},
        ):
            data = copy.deepcopy(valid)
            data[key]["tests_status"]["FAIL_TO_PASS"] = tests
            invalid.append(data)
        for data in invalid:
            (directory / "report.json").write_text(json.dumps(data), encoding="utf-8")
            report = self.import_results(confirm_harness_run=True)
            self.assertEqual(report["results"][0]["status"], "ERROR")
            self.assertIsNone(report["summary"]["pass_at_1"])
        (directory / "report.json").write_bytes(b"\xff")
        self.assertEqual(self.import_results()["results"][0]["status"], "ERROR")

    def test_run_receipt_prevents_changed_inputs_and_run_id_reuse(self):
        self.write_artifacts(0)
        old = self.prepared
        for mutate in (
            lambda data: data.update(run_id="other-run"),
            lambda data: data.update(source_sha256="b" * 64),
            lambda data: data.update(predictions_sha256="b" * 64),
            lambda data: data.update(schema_version=True),
        ):
            data = old.to_dict()
            mutate(data)
            self.receipt.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.import_results()
        self.save_receipt()
        self.predictions.write_bytes(self.predictions.read_bytes().replace(b"\n", b"\r\n"))
        self.prepared = self.prepare()
        self.assertEqual(old.export_bytes, self.prepared.export_bytes)
        with self.assertRaises(ValueError):
            self.import_results()

    def test_stale_patch_cache_and_symlink_escapes_cannot_resolve_tasks(self):
        directory = self.write_artifacts(0)
        (directory / "patch.diff").write_text("stale patch", encoding="utf-8")
        data = self.import_results(confirm_harness_run=True)
        self.assertEqual(data["results"][0]["reason"], "PREDICTION_PATCH_MISMATCH")
        self.assertIsNone(data["summary"]["pass_at_1"])
        outside = self.root / "outside-report.json"
        outside.write_text(json.dumps(self.harness_report(0)), encoding="utf-8")
        (directory / "report.json").unlink()
        try:
            (directory / "report.json").symlink_to(outside)
        except (OSError, NotImplementedError):
            return  # Cache mismatch protection above is checked on every platform.
        (directory / "patch.diff").write_bytes(self.records[0]["model_patch"].encode())
        self.assertEqual(self.import_results()["results"][0]["status"], "ERROR")

    def test_changed_task_manifest_cannot_reuse_original_run_receipt(self):
        data = copy.deepcopy(self.manifest_data)
        data["agent_tasks"][0]["base_commit"] = "b" * 40
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.prepared = self.prepare()
        with self.assertRaisesRegex(ValueError, "Run manifest does not match"):
            self.import_results(confirm_harness_run=True)

    def test_bounds_formats_no_clobber_and_failed_export_cleanup(self):
        with patch.object(evaluation, "MAX_INPUT_BYTES", 8), self.assertRaises(ValueError):
            self.prepare()
        directory = self.write_artifacts(0)
        with patch.object(evaluation, "MAX_REPORT_BYTES", 8):
            self.assertEqual(self.import_results()["results"][0]["status"], "ERROR")
        with self.assertRaises(ValueError):
            self.import_results(results_format="unknown-v5")
        with self.assertRaises(ValueError):
            self.import_results(confirm_harness_run=1)
        exported = self.root / "export.jsonl"
        evaluation.write_predictions(exported, self.prepared)
        before = exported.read_bytes()
        with self.assertRaises(FileExistsError):
            evaluation.write_predictions(exported, self.prepared)
        self.assertEqual(exported.read_bytes(), before)
        failed = self.root / "failed" / "export.jsonl"
        with (
            patch.object(evaluation.os, "link", side_effect=OSError("Publication failure")),
            self.assertRaises(OSError),
        ):
            evaluation.write_predictions(failed, self.prepared)
        self.assertEqual(list(failed.parent.iterdir()), [])
        self.assertTrue(directory.exists())

    def test_cli_separate_preparation_and_result_import(self):
        export = self.root / "export.jsonl"
        receipt = self.root / "prepared-run.json"
        base = [
            "--manifest",
            str(self.manifest),
            "--predictions",
            str(self.predictions),
            "--run-id",
            self.run_id,
        ]
        with patch("sys.stdout", new_callable=io.StringIO):
            code = cli.main(
                [
                    "--benchmark",
                    "swebench-predictions",
                    *base,
                    "--output-predictions",
                    str(export),
                    "--output-json",
                    str(receipt),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(export.read_bytes(), self.prepared.export_bytes)
        self.assertEqual(json.loads(receipt.read_text()), self.prepared.to_dict())
        self.write_artifacts(0)
        self.write_artifacts(1, resolved=False)
        output = self.root / "imported.json"
        args = [
            "--benchmark",
            "swebench-results",
            *base,
            "--run-manifest",
            str(receipt),
            "--harness-results",
            str(self.results_dir),
            "--results-format",
            evaluation.RESULTS_FORMAT,
            "--output-json",
            str(output),
        ]
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(args), 2)
            self.assertEqual(cli.main(args + ["--confirm-harness-run"]), 0)
        self.assertEqual(json.loads(output.read_text())["summary"]["pass_at_1"], 0.5)

    def test_cli_rejects_wrong_modes_input_aliases_and_harness_output_mutation(self):
        base = [
            "--benchmark",
            "swebench-predictions",
            "--manifest",
            str(self.manifest),
            "--predictions",
            str(self.predictions),
            "--run-id",
            self.run_id,
            "--output-predictions",
            str(self.root / "export.jsonl"),
        ]
        for args in (
            base,
            base + ["--output-json", str(self.manifest)],
            ["--benchmark", "mini", "--manifest", str(self.manifest)],
            base + ["--output-json", str(self.root / "run-new.json"), "--limit", "1"],
        ):
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(args)
        before = self.manifest.read_bytes()
        self.write_artifacts(0)
        artifact = self.artifact_directory(0) / "report.json"
        alias = self.root / "alias.json"
        try:
            alias.hardlink_to(artifact)
        except (OSError, NotImplementedError):
            alias = artifact
        args = [
            "--benchmark",
            "swebench-results",
            "--manifest",
            str(self.manifest),
            "--predictions",
            str(self.predictions),
            "--run-id",
            self.run_id,
            "--run-manifest",
            str(self.receipt),
            "--harness-results",
            str(self.results_dir),
            "--results-format",
            evaluation.RESULTS_FORMAT,
            "--output-json",
            str(alias),
        ]
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(args)
        self.assertEqual(self.manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
