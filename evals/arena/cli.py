#!/usr/bin/env python3
"""Run smoke checks or isolated agents, score recordings, and generate offline fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arena import (
    agent_runner,
    fuzzer,
    redteam,
    reporting,
    swebench,
    swebench_eval,
    swebench_runner,
)
from evals.arena.runner import DEFAULT_IMAGE, markdown_report, run_mini, safe_text


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (
        left.exists() and right.exists() and left.samefile(right)
    )


def _swebench_eval_main(args, parser: argparse.ArgumentParser) -> int:
    """Keep offline M5b operations separate from existing benchmark dispatch."""
    if any(
        value is not None
        for value in (
            args.image,
            args.responses,
            args.fixtures,
            args.agent_image,
            args.tasks,
            args.limit,
            args.output_fixtures,
            args.seed,
        )
    ):
        parser.error(
            "SWE-bench prediction/result modes do not accept execution or task-selection flags"
        )
    if args.manifest is None or args.predictions is None or args.run_id is None:
        parser.error(
            "SWE-bench prediction/result modes require --manifest, --predictions and --run-id"
        )
    preparing = args.benchmark == "swebench-predictions"
    if preparing:
        if args.output_predictions is None or args.output_json is None:
            parser.error(
                "Prediction preparation requires --output-predictions and --output-json (run manifest)"
            )
        if (
            any(
                value is not None
                for value in (args.run_manifest, args.harness_results, args.results_format)
            )
            or args.confirm_harness_run
        ):
            parser.error("Harness result options require --benchmark swebench-results")
    else:
        if any(
            value is None
            for value in (args.run_manifest, args.harness_results, args.results_format)
        ):
            parser.error(
                "Result import requires --run-manifest, --harness-results and --results-format"
            )
        if args.output_predictions is not None:
            parser.error("--output-predictions requires --benchmark swebench-predictions")
    try:
        inputs = [args.manifest, args.predictions]
        if args.run_manifest is not None:
            inputs.append(args.run_manifest)
        outputs = [
            value
            for value in (args.report, args.output_json, args.output_predictions)
            if value is not None
        ]
        if any(
            _same_file(left, right)
            for index, left in enumerate(outputs)
            for right in outputs[index + 1 :]
        ):
            parser.error("SWE-bench outputs must use different files")
        if any(_same_file(output, source) for output in outputs for source in inputs):
            parser.error("SWE-bench outputs must not overwrite input files")
        prepared = swebench_eval.prepare_predictions(
            args.manifest, args.predictions, run_id=args.run_id
        )
        if preparing:
            data = prepared.to_dict()
        else:
            root = args.harness_results.resolve()
            if any(output.resolve().is_relative_to(root) for output in outputs):
                parser.error("Report outputs must be outside the harness results directory")
            artifacts = [
                args.harness_results
                / prepared.run_id
                / record["model_name_or_path"].replace("/", "__")
                / instance_id
                / name
                for instance_id, record in prepared.records.items()
                for name in ("report.json", "patch.diff")
            ]
            if any(_same_file(output, artifact) for output in outputs for artifact in artifacts):
                parser.error("Reports must not overwrite harness artifacts or their aliases")
            data = swebench_eval.import_results(
                prepared,
                args.run_manifest,
                args.harness_results,
                results_format=args.results_format,
                confirm_harness_run=args.confirm_harness_run,
            )
        markdown = swebench_eval.markdown_report(data)
        serialized = json.dumps(data, indent=2, allow_nan=False) + "\n"
        if preparing:
            swebench_eval.write_predictions(args.output_predictions, prepared)
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(markdown, encoding="utf-8")
        if args.output_json is not None:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(serialized, encoding="utf-8")
        print(markdown)
    except (OSError, ValueError) as error:
        print(f"Arena error: {safe_text(str(error))}", file=sys.stderr)
        return 1
    if preparing:
        return 0
    if data["summary"]["ERROR"]:
        return 1
    return 0 if data["summary"]["metrics_available"] else 2


def _swebench_run_main(args, parser: argparse.ArgumentParser) -> int:
    if any(
        value is None
        for value in (
            args.manifest,
            args.predictions,
            args.prediction_export,
            args.tasks,
            args.run_manifest,
            args.run_id,
            args.work_dir,
        )
    ):
        parser.error(
            "swebench-run requires --manifest, --predictions, --prediction-export, --tasks, --run-manifest, --run-id and --work-dir"
        )
    if args.confirm_harness_run or any(
        value is not None
        for value in (
            args.image,
            args.agent_image,
            args.responses,
            args.fixtures,
            args.output_fixtures,
            args.output_predictions,
            args.seed,
            args.harness_results,
            args.results_format,
        )
    ):
        parser.error("swebench-run does not accept adapter, generation or result-import options")
    try:
        outputs = [path for path in (args.report, args.output_json) if path is not None]
        sources = [
            args.manifest,
            args.predictions,
            args.prediction_export,
            args.tasks,
            args.run_manifest,
        ]
        if len(outputs) == 2 and _same_file(*outputs):
            parser.error("Runner report outputs must use different paths")
        if any(_same_file(output, source) for output in outputs for source in sources):
            parser.error("Runner reports must not overwrite inputs")
        if any(output.resolve().is_relative_to(args.work_dir.resolve()) for output in outputs):
            parser.error("Runner reports must be outside the fresh harness work directory")
        timeout = 3600 if args.timeout is None else args.timeout
        plan = swebench_runner.plan_run(
            args.manifest,
            args.predictions,
            args.prediction_export,
            args.tasks,
            args.run_manifest,
            run_id=args.run_id,
            work_dir=args.work_dir,
            python=args.harness_python,
            engine="docker" if args.engine is None else args.engine,
            limit=1 if args.limit is None else args.limit,
            workers=1 if args.max_workers is None else args.max_workers,
            timeout=timeout,
            test_timeout=min(1800, timeout) if args.test_timeout is None else args.test_timeout,
            log_limit_mib=128 if args.log_limit_mib is None else args.log_limit_mib,
        )
        report = swebench_runner.run(plan, execute=args.execute)
        markdown = swebench_runner.markdown_report(report)
        for path, content in (
            (args.report, markdown),
            (args.output_json, json.dumps(report, indent=2) + "\n"),
        ):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        print(markdown)
    except (OSError, ValueError) as error:
        print(f"Arena error: {safe_text(str(error))}", file=sys.stderr)
        return 1
    status = report["execution_status"]
    if status in {"PREVIEW", "COMPLETED"}:
        return 0
    if status == "UNAVAILABLE":
        return 2
    return 130 if status == "INTERRUPTED" else 1


def _reporting_main(args, parser: argparse.ArgumentParser) -> int:
    if (
        args.execute
        or args.confirm_harness_run
        or any(
            value is not None
            for value in (
                args.image,
                args.responses,
                args.fixtures,
                args.agent_image,
                args.tasks,
                args.limit,
                args.output_fixtures,
                args.seed,
                args.manifest,
                args.predictions,
                args.run_id,
                args.output_predictions,
                args.run_manifest,
                args.harness_results,
                args.results_format,
                args.prediction_export,
                args.work_dir,
                args.harness_python,
                args.engine,
                args.max_workers,
                args.timeout,
                args.test_timeout,
                args.log_limit_mib,
            )
        )
    ):
        parser.error("Offline reporting does not accept execution, generation or evaluation flags")
    sources = list(args.reports or [])
    sources.extend(path for path in (args.baseline, args.head, args.provenance) if path is not None)
    outputs = [path for path in (args.report, args.output_json) if path is not None]
    try:
        if len(outputs) == 2 and _same_file(*outputs):
            parser.error("Reporting outputs must use different files")
        if any(_same_file(output, source) for output in outputs for source in sources):
            parser.error("Reporting outputs must not overwrite input reports or provenance")
        thresholds = reporting.Thresholds(
            0 if args.asr_increase_pp is None else args.asr_increase_pp,
            0 if args.resolution_drop_pp is None else args.resolution_drop_pp,
            0 if args.infrastructure_drop_pp is None else args.infrastructure_drop_pp,
        )
        data = reporting.aggregate(
            list(args.reports or []),
            baseline=args.baseline,
            head=args.head,
            provenance=args.provenance,
            thresholds=thresholds,
        )
        markdown = reporting.markdown_report(data)
        serialized = (json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        for path, content in (
            (args.report, markdown.encode("utf-8")),
            (args.output_json, serialized),
        ):
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        print(markdown)
    except (OSError, ValueError) as error:
        print(f"Arena reporting error: {safe_text(str(error))}", file=sys.stderr)
        return 1
    if data["status"] == "REGRESSION":
        return 1
    return 2 if data["status"] == "INCOMPARABLE" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        choices=[
            "mini",
            "redteam",
            "generate",
            "agent",
            "swebench",
            "swebench-predictions",
            "swebench-results",
            "swebench-run",
            "reporting",
        ],
        required=True,
    )
    parser.add_argument(
        "--image", help="Mini only: already-present local Python image; never pulled"
    )
    parser.add_argument(
        "--responses", type=Path, help="Redteam only: JSON file of recorded responses"
    )
    parser.add_argument(
        "--fixtures", type=Path, help="Redteam/Agent: alternate JSON fixture catalogue"
    )
    parser.add_argument(
        "--agent-image", help="Agent only: trusted, already-present local adapter image"
    )
    parser.add_argument("--tasks", type=Path, help="SWE-bench only: local legacy JSON/JSONL export")
    parser.add_argument(
        "--limit",
        type=int,
        help="Agent: pairs (default 5/max 100); swebench: tasks (default/max 50); swebench-run: tasks (default 1/max 50)",
    )
    parser.add_argument("--output-fixtures", type=Path, help="Generate only: new JSON fixture file")
    parser.add_argument(
        "--seed",
        type=int,
        help="Generate only: deterministic unsigned 64-bit seed (default 0)",
    )
    parser.add_argument("--report", type=Path, help="Also write the Markdown report to this file")
    parser.add_argument("--output-json", type=Path, help="Also write a structured JSON report")
    parser.add_argument("--manifest", type=Path, help="M5b/runner: M5a preparation manifest")
    parser.add_argument(
        "--predictions", type=Path, help="M5b/runner: original local prediction JSONL"
    )
    parser.add_argument("--run-id", help="M5b/runner: unique classic harness run identifier")
    parser.add_argument(
        "--output-predictions", type=Path, help="M5b preparation: new harness JSONL export"
    )
    parser.add_argument(
        "--run-manifest", type=Path, help="M5b import/runner: saved prediction run manifest"
    )
    parser.add_argument(
        "--harness-results", type=Path, help="M5b import: logs/run_evaluation directory"
    )
    parser.add_argument(
        "--results-format",
        choices=[swebench_eval.RESULTS_FORMAT],
        help="M5b import: explicit supported artifact format",
    )
    parser.add_argument(
        "--confirm-harness-run",
        action="store_true",
        help="M5b import: attest artifacts came from a real official harness run on these exact inputs",
    )
    parser.add_argument("--prediction-export", type=Path, help="swebench-run: validated M5b export")
    parser.add_argument(
        "--work-dir", type=Path, help="swebench-run: fresh directory outside this repository"
    )
    parser.add_argument(
        "--harness-python",
        type=Path,
        help="swebench-run: interpreter with the official v2.1.0 harness installed",
    )
    parser.add_argument(
        "--engine",
        choices=["docker", "podman"],
        help="swebench-run: rootless API (default docker; no automatic fallback)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="swebench-run: explicitly execute instead of previewing",
    )
    parser.add_argument(
        "--max-workers", type=int, help="swebench-run: workers, default 1, maximum 4"
    )
    parser.add_argument(
        "--timeout", type=int, help="swebench-run: overall harness seconds (default 3600)"
    )
    parser.add_argument(
        "--test-timeout",
        type=int,
        help="swebench-run: per-task test seconds (default min(1800, overall timeout))",
    )
    parser.add_argument(
        "--log-limit-mib", type=int, help="swebench-run: total harness log budget (default 128 MiB)"
    )
    parser.add_argument(
        "--reports", nargs="+", type=Path, help="Reporting only: local Arena JSON reports"
    )
    parser.add_argument("--baseline", type=Path, help="Reporting only: baseline report")
    parser.add_argument("--head", type=Path, help="Reporting only: head report")
    parser.add_argument(
        "--provenance", type=Path, help="Reporting only: SHA-256-bound provenance declarations"
    )
    parser.add_argument(
        "--asr-increase-pp",
        type=float,
        help="Reporting only: tolerated ASR increase in percentage points (default 0)",
    )
    parser.add_argument(
        "--resolution-drop-pp",
        type=float,
        help="Reporting only: tolerated resolution rate drop in percentage points (default 0)",
    )
    parser.add_argument(
        "--infrastructure-drop-pp",
        type=float,
        help="Reporting only: tolerated infrastructure pass-rate drop in percentage points (default 0)",
    )
    args = parser.parse_args(argv)
    if args.benchmark == "reporting":
        return _reporting_main(args, parser)
    if any(
        value is not None
        for value in (
            args.reports,
            args.baseline,
            args.head,
            args.provenance,
            args.asr_increase_pp,
            args.resolution_drop_pp,
            args.infrastructure_drop_pp,
        )
    ):
        parser.error("Reporting options require --benchmark reporting")
    if args.benchmark == "swebench-run":
        return _swebench_run_main(args, parser)
    if args.execute or any(
        value is not None
        for value in (
            args.prediction_export,
            args.work_dir,
            args.harness_python,
            args.engine,
            args.max_workers,
            args.timeout,
            args.test_timeout,
            args.log_limit_mib,
        )
    ):
        parser.error("Harness execution options require --benchmark swebench-run")
    if args.benchmark in {"swebench-predictions", "swebench-results"}:
        return _swebench_eval_main(args, parser)
    if args.confirm_harness_run or any(
        value is not None
        for value in (
            args.manifest,
            args.predictions,
            args.run_id,
            args.output_predictions,
            args.run_manifest,
            args.harness_results,
            args.results_format,
        )
    ):
        parser.error(
            "Prediction/result options require --benchmark swebench-predictions or swebench-results"
        )
    if args.benchmark == "redteam" and args.responses is None:
        parser.error("--benchmark redteam requires --responses")
    if args.benchmark in {"redteam", "agent", "swebench"} and args.image is not None:
        parser.error("--image is only supported by --benchmark mini")
    if args.benchmark in {"mini", "agent", "swebench"} and args.responses is not None:
        parser.error("--responses requires --benchmark redteam")
    if args.fixtures is not None and args.benchmark not in {"redteam", "agent"}:
        parser.error("--fixtures requires --benchmark redteam or agent")
    if args.benchmark == "agent" and args.agent_image is None:
        parser.error("--benchmark agent requires --agent-image")
    if args.benchmark != "agent" and args.agent_image is not None:
        parser.error("--agent-image requires --benchmark agent")
    if args.benchmark not in {"agent", "swebench"} and args.limit is not None:
        parser.error("--limit requires --benchmark agent or swebench")
    if args.benchmark == "swebench" and args.tasks is None:
        parser.error("--benchmark swebench requires --tasks")
    if args.benchmark != "swebench" and args.tasks is not None:
        parser.error("--tasks requires --benchmark swebench")
    if args.benchmark != "generate" and (args.output_fixtures is not None or args.seed is not None):
        parser.error("--output-fixtures and --seed require --benchmark generate")
    if args.benchmark == "generate":
        if args.output_fixtures is None:
            parser.error("--benchmark generate requires --output-fixtures")
        if any(
            value is not None
            for value in (args.responses, args.image, args.report, args.output_json)
        ):
            parser.error("Generate supports only --output-fixtures and --seed")
    try:
        if args.benchmark == "generate":
            seed = 0 if args.seed is None else args.seed
            cases = fuzzer.generate_variants(seed)
            fuzzer.write_fixtures(args.output_fixtures, cases)
            print(
                f"Generated {len(cases)} variants from 25 scenarios with seed {seed}.\n"
                "Offline fixture generation only; no agent security evaluation was performed."
            )
            return 0
        if args.report and args.output_json and _same_file(args.report, args.output_json):
            parser.error("Markdown and JSON outputs must use different paths")
        if args.responses and any(
            output is not None and _same_file(output, args.responses)
            for output in (args.report, args.output_json)
        ):
            parser.error("Report outputs must not overwrite the responses file")
        if args.tasks and any(
            output is not None and _same_file(output, args.tasks)
            for output in (args.report, args.output_json)
        ):
            parser.error("Report outputs must not overwrite the SWE-bench tasks file")
        if args.benchmark in {"redteam", "agent"}:
            fixtures_path = args.fixtures if args.fixtures is not None else fuzzer.DEFAULT_FIXTURES
            if any(
                output is not None and _same_file(output, fixtures_path)
                for output in (args.report, args.output_json)
            ):
                parser.error("Report outputs must not overwrite the fixtures file")
        if args.benchmark == "mini":
            report = run_mini(image=DEFAULT_IMAGE if args.image is None else args.image)
            markdown = markdown_report(report)
        elif args.benchmark == "agent":
            report = agent_runner.run_agent(
                args.agent_image,
                fixtures=args.fixtures,
                limit=agent_runner.DEFAULT_LIMIT if args.limit is None else args.limit,
            )
            markdown = agent_runner.markdown_report(report)
        elif args.benchmark == "swebench":
            report = swebench.prepare(
                args.tasks,
                limit=swebench.MAX_SELECTED if args.limit is None else args.limit,
            )
            markdown = swebench.markdown_report(report)
        else:
            if args.fixtures is None:
                report = redteam.run_redteam(args.responses)
            else:
                cases = fuzzer.load_fixture_file(args.fixtures)
                report = redteam.run_redteam(args.responses, cases=cases)
            markdown = redteam.markdown_report(report)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(markdown, encoding="utf-8")
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(
                json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
        print(markdown)
    except (OSError, ValueError) as exc:
        print(f"Arena error: {safe_text(str(exc))}", file=sys.stderr)
        return 1
    if args.benchmark == "swebench":
        return 0  # Successful preparation only; no task resolution was evaluated.
    if args.benchmark == "agent":
        if report.status in {"FAILED", "TIMEOUT"} or report.scoring.status == "COMPROMISED":
            return 1
        return 0 if report.status == "COMPLETED" and report.scoring.status == "DEFENDED" else 2
    if args.benchmark == "redteam":
        if report.status == "DEFENDED":
            return 0
        return 1 if report.status == "COMPROMISED" else 2
    if report.status == "PASS":
        return 0
    return 1 if report.status in {"FAIL", "TIMEOUT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
