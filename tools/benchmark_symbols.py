#!/usr/bin/env python3
"""Measure native Tree-sitter extraction on a fixed, generated multilingual corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return number


def corpus(size: int) -> dict[str, str]:
    templates = {
        "py": 'class Box{0}:\n    """Box docs."""\n    def run(self, x):\n        return x\n',
        "js": "export class Box{0} {{ run(x) {{ return x; }} }}\n",
        "ts": "export class Box{0}<T> {{ public run(x: T): T {{ return x; }} }}\n",
        "rs": "pub struct Box{0} {{}}\nimpl Box{0} {{ pub fn run(&self) {{}} }}\n",
        "go": "type Box{0} struct {{}}\nfunc (b *Box{0}) Run(x int) int {{ return x }}\n",
        "cpp": "class Box{0} {{ public: int run(int x) {{ return x; }} }};\n",
        "java": "class Box{0} {{ public int run(int x) {{ return x; }} }}\n",
    }
    result = {
        extension: "".join(template.format(index) for index in range(size))
        for extension, template in templates.items()
    }
    result["go"] = "package bench\n" + result["go"]
    return result


def records(symbols):
    return [
        (s.name, s.kind, s.signature, s.lineno, s.end_lineno, s.parent, s.docstring, s.is_public)
        for s in symbols
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=positive_integer, default=100)
    parser.add_argument("--repeat", type=positive_integer, default=5)
    args = parser.parse_args(argv)
    try:
        import msl_core
    except ModuleNotFoundError as error:
        if error.name != "msl_core":
            raise
        print("msl_core is not installed; no extraction was measured.", file=sys.stderr)
        return 2
    extract = msl_core.extract_ast_symbols
    inputs = corpus(args.size)
    expected = {}
    for extension, code in inputs.items():
        symbols = extract(f"bench.{extension}", code)
        if len(symbols) != args.size * 2:
            print(f"Unexpected symbol count for {extension}; no timings reported.", file=sys.stderr)
            return 1
        expected[extension] = records(symbols)
    samples = {extension: [] for extension in inputs}
    for _ in range(args.repeat):
        for extension, code in inputs.items():
            start = time.perf_counter_ns()
            symbols = extract(f"bench.{extension}", code)
            samples[extension].append((time.perf_counter_ns() - start) / 1_000_000_000)
            if records(symbols) != expected[extension]:
                print("Non-deterministic symbols; no timings reported.", file=sys.stderr)
                return 1
    fingerprint = hashlib.sha256()
    for extension, code in inputs.items():
        fingerprint.update(extension.encode() + b"\0" + code.encode("utf-8") + b"\0")
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "native_version": msl_core.__version__,
                "size": args.size,
                "repeat": args.repeat,
                "corpus_sha256": fingerprint.hexdigest(),
                "utf8_bytes": {
                    extension: len(code.encode("utf-8")) for extension, code in inputs.items()
                },
                "symbol_counts": {extension: len(rows) for extension, rows in expected.items()},
                "symbols_sha256": hashlib.sha256(
                    json.dumps(expected, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "seconds": samples,
                "median_seconds": {
                    extension: statistics.median(values) for extension, values in samples.items()
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
