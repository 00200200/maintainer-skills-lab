"""Offline fixture generation and M2 integration; no models or sandbox execution."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from evals import injection_harness as injection
from evals.arena import cli, fuzzer, redteam


class ArenaFuzzerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "generated.json"
        self.responses = self.root / "responses.json"
        self.base = injection.load_fixtures()
        self.guards = []
        for target in (
            "subprocess.run",
            "tools.container_sandbox.execute_sandbox",
            "tools.container_sandbox.detect_container_runtime",
            "evals.injection_harness.generate_simulated_safe_response",
            "evals.injection_harness.run_offline_evaluation",
            "evals.arena.cli.run_mini",
        ):
            guard = patch(target, side_effect=AssertionError("Execution is forbidden"))
            self.guards.append(guard.start())
            self.addCleanup(guard.stop)

    def tearDown(self):
        for guard in self.guards:
            guard.assert_not_called()

    def test_exact_count_unique_stable_ids_and_deterministic_seed(self):
        first = fuzzer.generate_variants(134)
        self.assertEqual(len(self.base), 25)
        self.assertEqual(len(first), 150)
        self.assertEqual(len({case.id for case in first}), 150)
        self.assertEqual(first, fuzzer.generate_variants(134))
        self.assertNotEqual(first, fuzzer.generate_variants(135))
        self.assertTrue(
            {case.id for case in first}.isdisjoint(
                case.id for case in fuzzer.generate_variants(135)
            )
        )
        with patch.object(injection, "load_fixtures", return_value=list(reversed(self.base))):
            self.assertEqual(first, fuzzer.generate_variants(134))

    def test_every_transformation_preserves_payload_and_evaluation_semantics(self):
        before = [asdict(case) for case in self.base]
        with patch.object(injection, "load_fixtures", return_value=self.base):
            generated = fuzzer.generate_variants(0)
        for original in self.base:
            variants = [case for case in generated if case.id.startswith(original.id + "--")]
            self.assertEqual(len(variants), 6)
            self.assertEqual(len({case.input_text for case in variants}), 6)
            for variant, prefix in zip(
                variants,
                (
                    "[Priority handoff",
                    "## Issue discussion",
                    "<tool_result",
                    "Subject:",
                    "# Repository policy",
                    "Review context",
                ),
                strict=True,
            ):
                self.assertTrue(variant.input_text.startswith(prefix))
            for variant, transform in zip(variants, fuzzer.TRANSFORMS, strict=True):
                self.assertEqual(variant.id, f"{original.id}--{transform}--s0000000000000000")
                self.assertIn(original.input_text, variant.input_text)
                for field in (
                    "category",
                    "attack_objective",
                    "target_skills",
                    "forbidden_actions",
                    "canary_token",
                ):
                    self.assertEqual(getattr(variant, field), getattr(original, field))
                self.assertEqual(set(asdict(variant)), set(asdict(original)))
                # Both ordinary and indicator-bearing recordings keep the M2 verdict.
                for response in ("The supplied text is untrusted data.", original.canary_token):
                    original_result = injection.verify_agent_response(
                        original, response, original.target_skills[0]
                    )
                    variant_result = injection.verify_agent_response(
                        variant, response, variant.target_skills[0]
                    )
                    self.assertEqual(original_result.verdict, variant_result.verdict)
                    self.assertEqual(original_result.canary_leaked, variant_result.canary_leaked)
                    self.assertEqual(
                        original_result.forbidden_action_detected,
                        variant_result.forbidden_action_detected,
                    )
        self.assertEqual(before, [asdict(case) for case in self.base])

    def test_json_round_trip_uses_existing_fixture_format_and_is_byte_deterministic(self):
        cases = fuzzer.generate_variants(42)
        second = self.root / "second.json"
        fuzzer.write_fixtures(self.output, cases)
        fuzzer.write_fixtures(second, fuzzer.generate_variants(42))
        self.assertEqual(self.output.read_bytes(), second.read_bytes())
        self.assertEqual(injection.load_fixtures(self.output), cases)
        self.assertEqual(fuzzer.load_fixture_file(self.output), cases)

    def test_invalid_seeds_and_base_catalogues_are_rejected(self):
        for seed in (-1, 1 << 64, True, "1", 1.5):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                fuzzer.generate_variants(seed)
        for cases in (None, [], self.base[:-1], [None] * 25):
            with patch.object(injection, "load_fixtures", return_value=cases):
                with self.assertRaises(ValueError):
                    fuzzer.generate_variants()
        duplicate = self.base[:-1] + [self.base[0]]
        with patch.object(injection, "load_fixtures", return_value=duplicate):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                fuzzer.generate_variants()

    def test_invalid_fixture_shapes_fields_targets_actions_and_duplicates(self):
        valid = asdict(self.base[0])
        invalid = [
            {},
            [],
            [None],
            [valid, valid],
            [valid] * (fuzzer.MAX_CASES + 1),
            [{**valid, "extra": "field"}],
            [{key: value for key, value in valid.items() if key != "canary_token"}],
        ]
        for field, value in (
            ("input_text", 123),
            ("input_text", "x" * (fuzzer.MAX_TEXT_CHARS + 1)),
            ("input_text", "\ud800"),
            ("id", "bad\nid"),
            ("title", ""),
            ("category", "unknown"),
            ("target_skills", []),
            ("target_skills", [None]),
            ("target_skills", ["mkl-review-pr"] * 2),
            ("forbidden_actions", ["unknown_action"]),
            ("canary_token", None),
        ):
            invalid.append([{**valid, field: value}])
        for records in invalid:
            with self.subTest(records=repr(records)[:120]), self.assertRaises(ValueError):
                fuzzer.validate_records(records)

    def test_utf8_payloads_and_empty_optional_indicators_round_trip(self):
        record = asdict(self.base[0])
        record.update(
            title="Unicode 🙂",
            input_text="Zażółć 你好\nLiteral payload.",
            canary_token="",
            forbidden_actions=[],
        )
        cases = fuzzer.validate_records([record])
        fuzzer.write_fixtures(self.output, cases)
        self.assertEqual(fuzzer.load_fixture_file(self.output), cases)
        self.assertIn("你好".encode(), self.output.read_bytes())

    def test_malformed_base_json_is_rejected_before_shared_loader(self):
        self.output.write_text('[{"id":"one","id":"two"}]', encoding="utf-8")
        with (
            patch.object(fuzzer, "DEFAULT_FIXTURES", self.output),
            patch.object(injection, "load_fixtures") as loader,
        ):
            with self.assertRaises(ValueError):
                fuzzer.generate_variants()
        loader.assert_not_called()

    def test_invalid_output_objects_leave_no_file(self):
        for cases in (None, [], [{}], [self.base[0]] * (fuzzer.MAX_CASES + 1)):
            with self.subTest(cases=repr(cases)[:80]), self.assertRaises(ValueError):
                fuzzer.write_fixtures(self.output, cases)
        self.assertFalse(self.output.exists())

    def test_json_duplicate_keys_nonfinite_literals_and_size_limits(self):
        for raw in (
            b'[{"id":"one","id":"two"}]',
            b"[NaN]",
            b"[Infinity]",
            b"[",
            b"\xff",
            b"[" * 2000,
        ):
            self.output.write_bytes(raw)
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                fuzzer.load_fixture_file(self.output)
        self.output.write_bytes(b"x" * 65)
        with patch.object(fuzzer, "MAX_FIXTURE_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "size limit"):
                fuzzer.load_fixture_file(self.output)
        with self.assertRaises(ValueError):
            fuzzer.load_fixture_file(self.root)
        self.output.unlink()
        with patch.object(fuzzer, "MAX_FIXTURE_BYTES", 64):
            with self.assertRaises(ValueError):
                fuzzer.write_fixtures(self.output, [self.base[0]])
        self.assertFalse(self.output.exists())

    def test_output_never_overwrites_existing_files_or_input_aliases(self):
        self.output.write_bytes(b"Keep existing data")
        with self.assertRaises(FileExistsError):
            fuzzer.write_fixtures(self.output, [self.base[0]])
        self.assertEqual(self.output.read_bytes(), b"Keep existing data")
        for alias in (self.root / "hardlink.json", self.root / "symlink.json"):
            try:
                if alias.name.startswith("hard"):
                    alias.hardlink_to(self.output)
                else:
                    alias.symlink_to(self.output)
            except (OSError, NotImplementedError):
                continue  # Regular-file no-clobber behavior is always checked above.
            with self.assertRaises(FileExistsError):
                fuzzer.write_fixtures(alias, [self.base[0]])
            self.assertEqual(self.output.read_bytes(), b"Keep existing data")
        self.assertFalse(any(path.name.startswith("tmp") for path in self.root.iterdir()))

    def test_failed_publication_leaves_no_partial_output(self):
        with patch.object(os, "link", side_effect=OSError("Publication failed")):
            with self.assertRaises(OSError):
                fuzzer.write_fixtures(self.output, [self.base[0]])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cli_generation_and_redteam_use_real_verifier_with_generated_ids(self):
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            result = cli.main(
                ["--benchmark", "generate", "--output-fixtures", str(self.output), "--seed", "7"]
            )
        self.assertEqual(result, 0)
        self.assertIn("150 variants", stdout.getvalue())
        self.assertIn("no agent security evaluation", stdout.getvalue())
        cases = fuzzer.load_fixture_file(self.output)
        first = cases[0]
        self.responses.write_text(
            json.dumps(
                {
                    "responses": [
                        {
                            "scenario_id": first.id,
                            "skill": first.target_skills[0],
                            "response": first.canary_token,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        structured = self.root / "report.json"
        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch.object(
                injection, "verify_agent_response", wraps=injection.verify_agent_response
            ) as verify,
        ):
            result = cli.main(
                [
                    "--benchmark",
                    "redteam",
                    "--fixtures",
                    str(self.output),
                    "--responses",
                    str(self.responses),
                    "--output-json",
                    str(structured),
                ]
            )
        self.assertEqual(result, 1)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[0], first)
        report = json.loads(structured.read_text())
        self.assertEqual(report["summary"]["total_scenarios"], 150)
        self.assertEqual(report["summary"]["evaluated_cases"], 1)
        self.assertEqual(report["summary"]["attack_success_rate_pct"], 100.0)
        self.assertNotIn(first.canary_token, structured.read_text())
        self.responses.write_text('{"responses": []}', encoding="utf-8")
        empty = redteam.run_redteam(self.responses, cases=cases)
        self.assertIsNone(empty.summary["attack_success_rate_pct"])
        self.assertTrue(all(item.verdict == "NOT_EVALUATED" for item in empty.results))

    def test_cli_invalid_modes_and_fixture_report_collisions(self):
        self.responses.write_text('{"responses": []}', encoding="utf-8")
        for args in (
            ["--benchmark", "generate"],
            [
                "--benchmark",
                "generate",
                "--output-fixtures",
                str(self.output),
                "--report",
                "unused.md",
            ],
            ["--benchmark", "mini", "--seed", "1"],
            ["--benchmark", "mini", "--fixtures", str(self.output)],
            [
                "--benchmark",
                "redteam",
                "--responses",
                str(self.responses),
                "--output-fixtures",
                str(self.output),
            ],
            [
                "--benchmark",
                "redteam",
                "--responses",
                str(self.responses),
                "--fixtures",
                str(self.output),
                "--report",
                str(self.output),
            ],
        ):
            with self.subTest(args=args), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    cli.main(args)
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(
                cli.main(
                    [
                        "--benchmark",
                        "generate",
                        "--output-fixtures",
                        str(self.output),
                        "--seed",
                        "-1",
                    ]
                ),
                1,
            )
        self.assertFalse(self.output.exists())

    def test_custom_fixture_pair_validation_happens_before_scoring(self):
        case = fuzzer.generate_variants()[0]
        fuzzer.write_fixtures(self.output, [case])
        valid = {
            "scenario_id": case.id,
            "skill": case.target_skills[0],
            "response": "Recorded text",
        }
        for records in (
            [{**valid, "scenario_id": "INJ-001"}],
            [{**valid, "skill": "mkl-unrelated"}],
            [valid, valid],
        ):
            self.responses.write_text(json.dumps({"responses": records}), encoding="utf-8")
            with (
                self.subTest(records=records),
                patch("sys.stderr", new_callable=io.StringIO),
                patch.object(injection, "verify_agent_response") as verify,
            ):
                result = cli.main(
                    [
                        "--benchmark",
                        "redteam",
                        "--fixtures",
                        str(self.output),
                        "--responses",
                        str(self.responses),
                    ]
                )
            self.assertEqual(result, 1)
            verify.assert_not_called()

    def test_custom_fixture_report_aliases_and_generation_reuse_are_rejected(self):
        cases = fuzzer.generate_variants()
        fuzzer.write_fixtures(self.output, cases)
        before = self.output.read_bytes()
        self.responses.write_text('{"responses": []}', encoding="utf-8")
        aliases = [self.output]
        for name in ("symlink.json", "hardlink.json"):
            alias = self.root / name
            try:
                if name.startswith("sym"):
                    alias.symlink_to(self.output)
                else:
                    alias.hardlink_to(self.output)
            except (OSError, NotImplementedError):
                continue
            aliases.append(alias)
        for alias in aliases:
            for option in ("--report", "--output-json"):
                with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                    cli.main(
                        [
                            "--benchmark",
                            "redteam",
                            "--fixtures",
                            str(self.output),
                            "--responses",
                            str(self.responses),
                            option,
                            str(alias),
                        ]
                    )
        with patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(
                cli.main(["--benchmark", "generate", "--output-fixtures", str(self.output)]), 1
            )
        self.assertEqual(self.output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
