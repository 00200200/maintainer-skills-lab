#!/usr/bin/env python3
"""Compare native BPE counts with Python tiktoken on a fixed corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from importlib import metadata

if __package__:
    from .benchmark_minify import corpus, positive_integer
else:
    from benchmark_minify import corpus, positive_integer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=positive_integer, default=64)
    parser.add_argument("--repeat", type=positive_integer, default=5)
    parser.add_argument("--iterations", type=positive_integer, default=10)
    parser.add_argument("--encoding", choices=("cl100k_base", "o200k_base"), default="cl100k_base")
    args = parser.parse_args(argv)
    try:
        import msl_core
        import tiktoken
    except ModuleNotFoundError as error:
        if error.name not in {"msl_core", "tiktoken"}:
            raise
        print(f"{error.name} is not installed; no comparison was measured.", file=sys.stderr)
        return 2
    # Missing exports in an installed extension are errors, not an absent backend.
    native_count = msl_core.count_tokens
    encoding = tiktoken.get_encoding(args.encoding)
    inputs = corpus(args.size)
    counts = {}
    for name, text in inputs.items():
        expected = len(encoding.encode(text))
        if native_count(text, args.encoding) != expected:
            print(f"Parity mismatch in {name}; no timings reported.", file=sys.stderr)
            return 1
        counts[name] = expected
    engines = (
        ("python_tiktoken", lambda text: len(encoding.encode(text))),
        ("native", lambda text: native_count(text, args.encoding)),
    )
    samples = {name: [] for name, _ in engines}
    for sample in range(args.repeat):
        order = engines if sample % 2 == 0 else tuple(reversed(engines))
        for name, function in order:
            start = time.perf_counter_ns()
            for _ in range(args.iterations):
                for text in inputs.values():
                    function(text)
            samples[name].append((time.perf_counter_ns() - start) / 1_000_000_000)
    medians = {name: statistics.median(values) for name, values in samples.items()}
    fingerprint = hashlib.sha256()
    for name, text in inputs.items():
        fingerprint.update(name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "native_version": msl_core.__version__,
                "tiktoken_version": metadata.version("tiktoken"),
                "encoding": args.encoding,
                "size": args.size,
                "repeat": args.repeat,
                "iterations": args.iterations,
                "corpus_sha256": fingerprint.hexdigest(),
                "corpus_utf8_bytes": sum(len(text.encode("utf-8")) for text in inputs.values()),
                "token_counts": counts,
                "seconds": samples,
                "median_seconds": medians,
                "python_over_native_ratio": medians["python_tiktoken"] / medians["native"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
