"""Local legacy SWE-bench preparation; no agents, harnesses or processes are run."""

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


class SWEbenchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.input = self.root / "local.json"
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
            "evals.injection_harness.verify_agent_response",
        ):
            guard = self.enterContext(
                patch(target, side_effect=AssertionError("Offline preparation only"))
            )
            self.guards.append(guard)

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def record(self, number=1, **updates):
        # Synthetic schema fixtures, never represented as actual SWE-bench tasks.
        return {
            "instance_id": f"example__project-{number:04d}",
            "repo": "example/project",
            "base_commit": "a" * 40,
            "problem_statement": "Synthetic unit fixture: fix a bug.",
            "FAIL_TO_PASS": ["tests/test_fix.py::test_regression"],
            "PASS_TO_PASS": ["tests/test_existing.py::test_existing"],
            **updates,
        }

    def write(self, records, *, jsonl=False):
        self.input = self.root / ("local.jsonl" if jsonl else "local.json")
        if jsonl:
            data = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
        else:
            data = json.dumps(records, ensure_ascii=False)
        self.input.write_bytes(data.encode("utf-8"))
        return self.input

    def test_json_and_jsonl_arrays_and_string_encoded_test_lists(self):
        for jsonl in (False, True):
            record = self.record(
                FAIL_TO_PASS=json.dumps(["tests/test_fix.py::test_regression"]),
                PASS_TO_PASS=json.dumps([]),
                problem_statement="Unicode 你好 🙂\nSecond line\u2028same JSONL record.",
            )
            report = swebench.prepare(self.write([record], jsonl=jsonl))
            self.assertEqual(report.tasks[0].fail_to_pass, ("tests/test_fix.py::test_regression",))
            self.assertEqual(report.tasks[0].pass_to_pass, ())
            self.assertEqual(report.tasks[0].problem_statement, record["problem_statement"])
            self.assertEqual(report.source["format"], "legacy-jsonl" if jsonl else "legacy-json")

    def test_provenance_hash_is_of_exact_source_bytes_and_repeatable(self):
        self.write([self.record(2), self.record(1)])
        first = swebench.prepare(self.input)
        self.assertEqual(first.to_dict(), swebench.prepare(self.input).to_dict())
        self.assertEqual(first.source["path"], str(self.input.resolve()))
        self.assertEqual(
            first.source["sha256"], hashlib.sha256(self.input.read_bytes()).hexdigest()
        )
        self.assertEqual(first.source["size_bytes"], len(self.input.read_bytes()))
        self.assertIn("not authenticated", first.source["provenance"])

    def test_deterministic_selection_is_sorted_capped_and_never_padded(self):
        records = [self.record(i) for i in range(60, 0, -1)]
        first = swebench.prepare(self.write(records))
        self.assertEqual(len(first.tasks), 50)
        self.assertEqual(first.tasks[0].instance_id, self.record(1)["instance_id"])
        self.assertEqual(first.tasks[-1].instance_id, self.record(50)["instance_id"])
        self.assertEqual(first.to_dict()["summary"]["omitted_tasks"], 10)
        second = swebench.prepare(self.write(list(reversed(records))))
        self.assertEqual(first.tasks, second.tasks)
        self.assertEqual(len(swebench.prepare(self.input, limit=3).tasks), 3)
        small = swebench.prepare(self.write([self.record()]))
        self.assertEqual(len(small.tasks), 1)
        self.assertEqual(small.total_tasks, 1)

    def test_selection_does_not_skip_validation_of_unselected_records(self):
        records = [self.record(i) for i in range(1, 52)]
        records[-1]["base_commit"] = "not a commit"
        with self.assertRaises(ValueError):
            swebench.prepare(self.write(records), limit=1)
        records[-1] = self.record(1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            swebench.prepare(self.write(records), limit=1)

    def test_bad_limits_are_rejected_before_reading_input(self):
        for limit in (0, -1, 51, True, "5", 1.5, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                swebench.prepare(self.input, limit=limit)

    def test_required_schema_and_types_and_unknown_fields(self):
        valid = self.record()
        invalid = [None, {}, [], [None], [valid, valid], {"tasks": [valid]}]
        for field in swebench.REQUIRED:
            invalid.append([{key: value for key, value in valid.items() if key != field}])
        for field, value in (
            ("instance_id", "../escape"),
            ("instance_id", "bad\nid"),
            ("instance_id", 1),
            ("repo", "https://example.invalid/org/repo"),
            ("repo", "a/b/c"),
            ("base_commit", "abcdef"),
            ("base_commit", "g" * 40),
            ("base_commit", None),
            ("problem_statement", ""),
            ("problem_statement", "\ud800"),
            ("problem_statement", "contains\x00NUL"),
            ("problem_statement", 123),
            ("patch", None),
            ("test_patch", []),
            ("version", 1),
            ("environment_setup_commit", "bad"),
            ("metadata", []),
        ):
            invalid.append([{**valid, field: value}])
        invalid.extend([[{**valid, "unknown_field": "unsupported"}], [{"task_id": "v5-shape"}]])
        for records in invalid:
            with self.subTest(records=repr(records)[:100]), self.assertRaises(ValueError):
                swebench.validate_records(records)

    def test_test_lists_are_bounded_unique_strings_with_nonconflicting_expectations(self):
        invalid = (
            None,
            1,
            {},
            "not JSON",
            '"not an array"',
            "null",
            "[NaN]",
            [1],
            [""],
            [" "],
            ["test\ncommand"],
            [" test"],
            ["test", "test"],
            ["\ud800"],
        )
        for field in ("FAIL_TO_PASS", "PASS_TO_PASS"):
            for value in invalid:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    swebench.validate_records([self.record(**{field: value})])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            swebench.validate_records([self.record(FAIL_TO_PASS=["same"], PASS_TO_PASS='["same"]')])
        empty = swebench.validate_records([self.record(FAIL_TO_PASS=[], PASS_TO_PASS="[]")])[0]
        self.assertEqual(empty.fail_to_pass, ())
        self.assertEqual(empty.pass_to_pass, ())
        unusual = "tests/测试.py::test_value[with spaces & punctuation]"
        task = swebench.validate_records([self.record(FAIL_TO_PASS=[unusual])])[0]
        self.assertEqual(task.fail_to_pass, (unusual,))

    def test_optional_metadata_stays_private_and_source_objects_are_not_mutated(self):
        record = self.record(
            patch="GOLD_PATCH_SENTINEL",
            test_patch="TEST_PATCH_SENTINEL",
            hints_text="HINT_SENTINEL",
            created_at="2024-01-01T00:00:00Z",
            version="1.0",
            environment_setup_commit="b" * 40,
            difficulty="15 min - 1 hour",
            metadata={
                "answer": "METADATA_SENTINEL",
                "problem_statement": "HIDDEN_OVERRIDE",
                "nested": [None, True, 5, 1.25],
            },
        )
        before = copy.deepcopy(record)
        task = swebench.validate_records([record])[0]
        self.assertEqual(record, before)
        allowed = {"instance_id", "repo", "base_commit", "problem_statement"}
        self.assertEqual(set(task.agent_input()), allowed)
        self.assertEqual(task.agent_input(), {key: record[key] for key in allowed})
        private = task.evaluation_input()
        for field in swebench.OPTIONAL:
            self.assertEqual(private[field], record[field])
        record["metadata"]["answer"] = "Changed by caller"
        self.assertEqual(task.evaluation_input()["metadata"]["answer"], "METADATA_SENTINEL")
        self.write([before])
        report = swebench.prepare(self.input)
        manifest = report.to_dict()
        for secret in (
            "GOLD_PATCH_SENTINEL",
            "TEST_PATCH_SENTINEL",
            "HINT_SENTINEL",
            "METADATA_SENTINEL",
            "HIDDEN_OVERRIDE",
            *record["FAIL_TO_PASS"],
            *record["PASS_TO_PASS"],
        ):
            self.assertNotIn(secret, json.dumps(manifest["agent_tasks"]))
            self.assertNotIn(secret, swebench.markdown_report(report))
        for field in (
            "FAIL_TO_PASS",
            "PASS_TO_PASS",
            "patch",
            "test_patch",
            "metadata",
            "hints_text",
        ):
            self.assertNotIn(field, manifest["agent_tasks"][0])
        self.assertEqual(manifest["evaluation_tasks"][0]["patch"], "GOLD_PATCH_SENTINEL")

    def test_json_duplicate_keys_nonfinite_invalid_utf8_and_excessive_nesting(self):
        for suffix in (".json", ".jsonl"):
            path = self.root / ("bad" + suffix)
            for raw in (
                b"",
                b"\xff",
                b"[NaN]",
                b"[",
                b"[" * 2000,
                b'{"instance_id":"one","instance_id":"two"}',
                b"[Infinity]",
            ):
                path.write_bytes(raw)
                with self.subTest(suffix=suffix, raw=raw[:60]), self.assertRaises(ValueError):
                    swebench.prepare(path)
        for value in (float("inf"), float("nan"), {"nested": {"bad": b"not JSON"}}):
            with self.assertRaises(ValueError):
                swebench.validate_records([self.record(metadata={"value": value})])
        nested = {"value": "deep"}
        for _ in range(10):
            nested = {"value": nested}
        with self.assertRaises(ValueError):
            swebench.validate_records([self.record(metadata=nested)])

    def test_size_record_test_and_metadata_limits(self):
        self.write([self.record()])
        for constant, value in (("MAX_FILE_BYTES", 32), ("MAX_RECORD_BYTES", 32)):
            with patch.object(swebench, constant, value), self.assertRaises(ValueError):
                swebench.prepare(self.input)
        with patch.object(swebench, "MAX_RECORDS", 1), self.assertRaises(ValueError):
            swebench.prepare(self.write([self.record(1), self.record(2)]))
        with patch.object(swebench, "MAX_TESTS", 1), self.assertRaises(ValueError):
            swebench.validate_records([self.record(FAIL_TO_PASS=["one", "two"])])
        with patch.object(swebench, "MAX_TEST_CHARS", 3), self.assertRaises(ValueError):
            swebench.validate_records([self.record(FAIL_TO_PASS=["long"])])
        with patch.object(swebench, "MAX_METADATA_NODES", 2), self.assertRaises(ValueError):
            swebench.validate_records([self.record(metadata={"values": [1, 2, 3]})])
        with self.assertRaises(ValueError):
            swebench.validate_records([self.record(problem_statement="x" * 100_001)])
        with self.assertRaises(ValueError):
            swebench.validate_records([self.record(patch="x" * 250_001)])
        self.write([self.record()], jsonl=True)
        with patch.object(swebench, "MAX_RECORD_BYTES", 32), self.assertRaises(ValueError):
            swebench.prepare(self.input)

    def test_jsonl_blank_rows_crlf_and_missing_or_unsupported_files(self):
        line = json.dumps(self.record()).encode()
        self.input = self.root / "rows.jsonl"
        for raw in (b"\n", b"\n" + line, line + b"\n\n", line + b"\n\n" + line):
            self.input.write_bytes(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                swebench.prepare(self.input)
        self.input.write_bytes(line + b"\r\n")
        self.assertEqual(len(swebench.prepare(self.input).tasks), 1)
        self.input.write_bytes(line)  # A final newline is optional.
        self.assertEqual(len(swebench.prepare(self.input).tasks), 1)
        with self.assertRaises(ValueError):
            swebench.prepare(self.root)
        with self.assertRaises(ValueError):
            swebench.prepare(self.root / "missing.json")
        with self.assertRaises(ValueError):
            swebench.prepare(self.root / "dataset.parquet")

    def test_cli_prepares_reports_without_evaluation_or_input_mutation(self):
        self.write([self.record(2, patch="GOLD_SENTINEL"), self.record(1)])
        before = self.input.read_bytes()
        output, markdown = self.root / "manifest.json", self.root / "report.md"
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            code = cli.main(
                [
                    "--benchmark",
                    "swebench",
                    "--tasks",
                    str(self.input),
                    "--limit",
                    "1",
                    "--output-json",
                    str(output),
                    "--report",
                    str(markdown),
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("NOT_EVALUATED", stdout.getvalue())
        data = json.loads(output.read_text())
        self.assertEqual(data["status"], "PREPARED")
        self.assertEqual(data["summary"]["selected_tasks"], 1)
        self.assertEqual(data["summary"]["evaluated_tasks"], 0)
        self.assertFalse(data["live_agent_run"])
        self.assertFalse(data["evaluation_performed"])
        self.assertNotIn("pass_at_1", data)
        self.assertNotIn("GOLD_SENTINEL", markdown.read_text())
        self.assertEqual(self.input.read_bytes(), before)

    def test_cli_validates_without_outputs_and_invalid_input_creates_no_reports(self):
        self.write([self.record()])
        before = set(self.root.iterdir())
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(cli.main(["--benchmark", "swebench", "--tasks", str(self.input)]), 0)
        self.assertEqual(set(self.root.iterdir()), before)
        output, markdown = self.root / "manifest.json", self.root / "report.md"
        self.input.write_text("{}", encoding="utf-8")
        with patch("sys.stderr", new_callable=io.StringIO):
            code = cli.main(
                [
                    "--benchmark",
                    "swebench",
                    "--tasks",
                    str(self.input),
                    "--output-json",
                    str(output),
                    "--report",
                    str(markdown),
                ]
            )
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertFalse(markdown.exists())

    def test_invalid_private_data_is_not_echoed_in_cli_errors(self):
        self.write([self.record(patch={"private": "GOLD_ERROR_SENTINEL"})])
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = cli.main(["--benchmark", "swebench", "--tasks", str(self.input)])
        self.assertEqual(code, 1)
        self.assertNotIn("GOLD_ERROR_SENTINEL", stderr.getvalue())

    def test_cli_rejects_wrong_mode_options_and_input_output_aliases(self):
        self.write([self.record()])
        argv = ["--benchmark", "swebench", "--tasks", str(self.input)]
        for extra in (
            ["--image", "x"],
            ["--agent-image", "x"],
            ["--responses", "x"],
            ["--fixtures", "x"],
            ["--seed", "1"],
            ["--output-fixtures", "x"],
        ):
            with (
                self.subTest(extra=extra),
                patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                cli.main(argv + extra)
        for args in (
            ["--benchmark", "swebench"],
            ["--benchmark", "mini", "--tasks", str(self.input)],
        ):
            with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                cli.main(args)
        for limit in ("0", "51"):
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(cli.main(argv + ["--limit", limit]), 1)
        before = self.input.read_bytes()
        aliases = [self.input]
        for name in ("hardlink.json", "symlink.json"):
            alias = self.root / name
            try:
                if name.startswith("hard"):
                    alias.hardlink_to(self.input)
                else:
                    alias.symlink_to(self.input)
            except (OSError, NotImplementedError):
                continue
            aliases.append(alias)
        for alias in aliases:
            for option in ("--report", "--output-json"):
                with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                    cli.main(argv + [option, str(alias)])
        output = self.root / "report.json"
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            cli.main(argv + ["--report", str(output), "--output-json", str(output)])
        self.assertEqual(self.input.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
