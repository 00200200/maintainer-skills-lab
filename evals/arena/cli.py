#!/usr/bin/env python3
"""Run smoke checks, score recorded responses, or generate offline adversarial fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arena import fuzzer, redteam
from evals.arena.runner import DEFAULT_IMAGE, markdown_report, run_mini, safe_text


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (
        left.exists() and right.exists() and left.samefile(right)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", choices=["mini", "redteam", "generate"], required=True)
    parser.add_argument(
        "--image", help="Mini only: already-present local Python image; never pulled"
    )
    parser.add_argument(
        "--responses", type=Path, help="Redteam only: JSON file of recorded responses"
    )
    parser.add_argument(
        "--fixtures", type=Path, help="Redteam only: alternate JSON fixture catalogue"
    )
    parser.add_argument("--output-fixtures", type=Path, help="Generate only: new JSON fixture file")
    parser.add_argument(
        "--seed",
        type=int,
        help="Generate only: deterministic unsigned 64-bit seed (default 0)",
    )
    parser.add_argument("--report", type=Path, help="Also write the Markdown report to this file")
    parser.add_argument("--output-json", type=Path, help="Also write a structured JSON report")
    args = parser.parse_args(argv)
    if args.benchmark == "redteam" and args.responses is None:
        parser.error("--benchmark redteam requires --responses")
    if args.benchmark == "redteam" and args.image is not None:
        parser.error("--image is only supported by --benchmark mini")
    if args.benchmark == "mini" and args.responses is not None:
        parser.error("--responses requires --benchmark redteam")
    if args.fixtures is not None and args.benchmark != "redteam":
        parser.error("--fixtures requires --benchmark redteam")
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
        if args.benchmark == "redteam":
            fixtures_path = args.fixtures if args.fixtures is not None else fuzzer.DEFAULT_FIXTURES
            if any(
                output is not None and _same_file(output, fixtures_path)
                for output in (args.report, args.output_json)
            ):
                parser.error("Report outputs must not overwrite the fixtures file")
        if args.benchmark == "mini":
            report = run_mini(image=DEFAULT_IMAGE if args.image is None else args.image)
            markdown = markdown_report(report)
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
    if args.benchmark == "redteam":
        if report.status == "DEFENDED":
            return 0
        return 1 if report.status == "COMPROMISED" else 2
    if report.status == "PASS":
        return 0
    return 1 if report.status in {"FAIL", "TIMEOUT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
