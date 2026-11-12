#!/usr/bin/env python3
"""Run MSL-Arena Mini infrastructure smoke checks without invoking any agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.arena.runner import DEFAULT_IMAGE, markdown_report, run_mini


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", choices=["mini"], required=True)
    parser.add_argument(
        "--image", default=DEFAULT_IMAGE, help="Already-present local Python image; never pulled"
    )
    parser.add_argument("--report", type=Path, help="Also write the Markdown report to this file")
    parser.add_argument("--output-json", type=Path, help="Also write a structured JSON report")
    args = parser.parse_args(argv)
    if args.report and args.output_json and args.report.resolve() == args.output_json.resolve():
        parser.error("Markdown and JSON outputs must use different paths")
    try:
        report = run_mini(image=args.image)
        markdown = markdown_report(report)
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
        print(f"Arena error: {exc}", file=sys.stderr)
        return 1
    if report.status == "PASS":
        return 0
    return 1 if report.status in {"FAIL", "TIMEOUT"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
