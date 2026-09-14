#!/usr/bin/env python3
"""Demonstrate Humanizer's token checker and a limitation without invoking a model."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE.parents[1] / "skills/mkl-humanize/scripts/check_facts.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="show structured checker results")
    args = parser.parse_args()
    cases = []
    expected_changes = {
        ("flag", "dropped", "--dry-run"),
        ("flag", "added", "--force"),
        ("number", "dropped", "20"),
        ("number", "added", "200"),
        ("negation", "dropped", "not"),
    }
    for name, expected in (("clear", set()), ("changed", expected_changes), ("blind-spot", set())):
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                str(CHECKER),
                str(HERE / "fixtures/draft.md"),
                str(HERE / f"fixtures/{name}.md"),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if process.returncode not in (0, 1):
            print(f"Checker failed for {name}: {process.stderr}", file=sys.stderr)
            return 1
        result = json.loads(process.stdout)
        actual = {(d["kind"], d["change"], d["value"]) for d in result["differences"]}
        verified = actual == expected and process.returncode == int(bool(expected))
        cases.append(
            {"case": name, "exit_code": process.returncode, "verified": verified, **result}
        )
    report = {
        "evaluation_kind": "authored fixture; no model run",
        "cases": cases,
        "verified": all(c["verified"] for c in cases),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for case in cases:
            print(f"{case['case']}: {len(case['differences'])} tracked token changes")
            for change in case["differences"]:
                print(f"  {change['kind']} {change['change']}: {change['value']}")
        print("The blind-spot rewrite changes Linux to macOS; the checker misses it.")
        print("Read every claim. A clean token report does not prove preserved meaning.")
        print(f"Fixture verified: {report['verified']} (not a writing-quality evaluation)")
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
