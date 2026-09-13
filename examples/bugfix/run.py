#!/usr/bin/env python3
"""Verify the bundled fixture; does not invoke or evaluate an AI agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_case(source: Path, timeout: float = 10) -> dict:
    # Both cases receive exactly the same independent test and probe.
    with tempfile.TemporaryDirectory(prefix="mkl-example-") as temporary:
        directory = Path(temporary)
        for name, origin in (
            ("slug.py", source),
            ("test_slug.py", HERE / "test_slug.py"),
            ("probe.py", HERE / "probe.py"),
        ):
            shutil.copyfile(origin, directory / name)
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("PYTHON")
        }
        environment["PYTHONNOUSERSITE"] = "1"
        try:
            process = subprocess.run(
                [sys.executable, "-E", "-s", "probe.py"],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"outcome": "execution-error", "details": "timeout"}
        if process.returncode != 0:
            return {
                "outcome": "execution-error",
                "details": process.stderr,
                "exit_code": process.returncode,
            }
        try:
            report = json.loads(process.stdout)
        except json.JSONDecodeError:
            return {"outcome": "execution-error", "details": "invalid probe output"}
        if report["errors"] or not report["tests_run"] or report["skipped"]:
            outcome = "execution-error"
        elif report["failures"]:
            outcome = "assertion-failure"
        elif report["successful"]:
            outcome = "pass"
        else:
            outcome = "execution-error"
        return {"outcome": outcome, **report}


def evaluate(before: Path, after: Path) -> dict:
    baseline, candidate = run_case(before), run_case(after)
    return {
        "evaluation_kind": "bundled-fixture; no live-agent evaluation",
        "runtime": sys.version.split()[0],
        "test_sha256": hashlib.sha256((HERE / "test_slug.py").read_bytes()).hexdigest(),
        "baseline": {"source_sha256": hashlib.sha256(before.read_bytes()).hexdigest(), **baseline},
        "candidate": {"source_sha256": hashlib.sha256(after.read_bytes()).hexdigest(), **candidate},
        "verified": baseline["outcome"] == "assertion-failure" and candidate["outcome"] == "pass",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Include structured results and logs")
    args = parser.parse_args()
    report = evaluate(HERE / "before/slug.py", HERE / "after/slug.py")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Baseline:  {report['baseline']['outcome']}")
        print(f"Candidate: {report['candidate']['outcome']}")
        print(f"Verified for this fixture: {report['verified']}")
        print("This checks the bundled example, not agent performance.")
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
