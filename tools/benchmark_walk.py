#!/usr/bin/env python3
"""Measure the optional native walker on a reproducible temporary project."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=positive_integer, default=2000)
    parser.add_argument("--repeat", type=positive_integer, default=5)
    args = parser.parse_args(argv)
    try:
        import msl_core
    except ModuleNotFoundError as error:
        if error.name != "msl_core":
            raise
        print("msl_core is not installed; no walk was measured.", file=sys.stderr)
        return 2
    if not hasattr(msl_core, "walk_project"):
        print("Rebuild msl_core with M2 walker support before measuring.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="msl-walk-") as temporary:
        root = Path(temporary).resolve()
        rules = {".gitignore": "*.log\n", ".mklignore": "generated/\n"}
        for name, content in rules.items():
            (root / name).write_bytes(content.encode("utf-8"))
        expected = list(rules)
        corpus_hash = hashlib.sha256()
        for name, content in sorted(rules.items()):
            corpus_hash.update(name.encode("utf-8") + b"\0" + content.encode("utf-8") + b"\0")
        for index in range(args.files):
            kind = index % 5
            name = (
                f"generated/file-{index}.txt"
                if kind == 0
                else f"src/{index % 32}/file-{index}.log"
                if kind == 1
                else f"src/{index % 32}/file-{index}.bin"
                if kind == 2
                else f"src/{index % 32}/file-{index}.md"
            )
            content = b"\x00binary\xff" if kind == 2 else b"# Fixture\n\nStable text.\n" * 8
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            corpus_hash.update(name.encode("utf-8") + b"\0" + content + b"\0")
            if kind in (3, 4):
                expected.append(name)
        expected.sort()
        # Warm caches and validate semantics before measuring traversal and I/O.
        if msl_core.walk_project(str(root), []) != expected:
            print("Walker result differs from the fixture; no timings reported.", file=sys.stderr)
            return 1
        samples = []
        for _ in range(args.repeat):
            start = time.perf_counter_ns()
            result = msl_core.walk_project(str(root), [])
            samples.append((time.perf_counter_ns() - start) / 1_000_000_000)
            if result != expected:
                print("Non-deterministic walker result; no timings reported.", file=sys.stderr)
                return 1
        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "native_version": msl_core.__version__,
                    "fixture_files": args.files + len(rules),
                    "returned_paths": len(expected),
                    "corpus_sha256": corpus_hash.hexdigest(),
                    "paths_sha256": hashlib.sha256("\n".join(expected).encode("utf-8")).hexdigest(),
                    "repeat": args.repeat,
                    "seconds": samples,
                    "median_seconds": statistics.median(samples),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
