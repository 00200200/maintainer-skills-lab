#!/usr/bin/env python3
"""Measure Python and optional native minification on a fixed synthetic corpus."""

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
    from . import kit
else:
    import kit


def corpus(size: int) -> dict[str, str]:
    blocks = {
        "prose": "## Steps\n\n\n1. Read the change.   \n2. Check the evidence.\t\n",
        "tables": "|  Name   |  Value   |\n| :--- | ---: |\n|  alpha   |   42  |\n\n\n",
        "comments": "Before <!-- single --> after.\n<!--\nmultiple lines\n-->\n\n\n",
        "fences": "Intro   \n```python\n# unchanged  \nprint(1)\n<!-- keep -->\n```\n\n\n",
        "crlf": "Intro   \r\n|  a  | b  |\r\n\r\n\r\n",
        "unicode": "Zażółć 🙂 漢字\n\u2003|\u2009name\u202f|\x1cvalue\x1f|\n\n\n",
    }
    blocks["mixed"] = "".join(blocks.values())
    return {name: text * size for name, text in blocks.items()}


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=positive_integer, default=64, help="Copies per corpus block")
    parser.add_argument(
        "--repeat", type=positive_integer, default=5, help="Timing samples per engine"
    )
    parser.add_argument(
        "--iterations", type=positive_integer, default=10, help="Corpus passes per sample"
    )
    args = parser.parse_args(argv)
    native = kit._native_minify_markdown
    if native is None:
        print("msl_core is not installed; no native comparison was measured.", file=sys.stderr)
        return 2
    inputs = corpus(args.size)
    python = kit._minify_markdown_python
    # Verify outputs and warm both engines before measuring call time.
    for name, text in inputs.items():
        if python(text) != native(text):
            print(f"Parity mismatch in corpus block {name}; no timings reported.", file=sys.stderr)
            return 1
    samples = {"python": [], "native": []}
    engines = (("python", python), ("native", native))
    for sample in range(args.repeat):
        order = engines if sample % 2 == 0 else reversed(engines)
        for name, function in order:
            start = time.perf_counter_ns()
            for _ in range(args.iterations):
                for text in inputs.values():
                    function(text)
            samples[name].append((time.perf_counter_ns() - start) / 1e9 / args.iterations)
    medians = {name: statistics.median(values) for name, values in samples.items()}
    try:
        native_version = metadata.version("msl-core")
    except metadata.PackageNotFoundError:
        native_version = "unregistered-extension"
    data = {
        "scope": "In-process synthetic corpus only; not an end-to-end kit benchmark.",
        "python": sys.version,
        "platform": platform.platform(),
        "native_distribution_version": native_version,
        "corpus_sha256": hashlib.sha256(
            json.dumps(inputs, ensure_ascii=False).encode()
        ).hexdigest(),
        "corpus_utf8_bytes": sum(len(text.encode("utf-8")) for text in inputs.values()),
        "corpus_blocks": list(inputs),
        "size": args.size,
        "repeat": args.repeat,
        "iterations": args.iterations,
        "seconds_per_corpus_samples": samples,
        "seconds_per_corpus_median": medians,
        "python_over_native_ratio": medians["python"] / medians["native"]
        if medians["native"]
        else None,
    }
    print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
