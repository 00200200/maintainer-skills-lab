#!/usr/bin/env python3
"""Measure cold/warm/changed sync against uncached generation in temporary trees."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import statistics
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

if __package__:
    from . import kit
else:
    import kit


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def timed_sync(root: Path, cached: bool, options: dict) -> tuple[float, dict, int]:
    with ExitStack() as stack:
        generate = stack.enter_context(
            patch.object(kit, "provider_files", wraps=kit.provider_files)
        )
        if not cached:
            stack.enter_context(patch.object(kit, "_sync_cache_key", return_value=None))
        start = time.perf_counter_ns()
        result = kit.sync_providers(root, **options)
        seconds = (time.perf_counter_ns() - start) / 1_000_000_000
    return seconds, result, generate.call_count


def positive_integer(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be a positive integer")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=kit.ROOT)
    parser.add_argument("--repeat", type=positive_integer, default=3)
    parser.add_argument("--minify", action="store_true")
    parser.add_argument("--mode", choices=("full", "lazy"), default="full")
    args = parser.parse_args(argv)
    options = {"minify": args.minify, "mode": args.mode}
    samples = {phase: {"cached": [], "uncached": []} for phase in ("cold", "warm", "changed")}
    output_hashes = {}
    source_hash = hashlib.sha256()
    for directory in ("skills", "agents", "grok-bot", "assets"):
        for name, data in kit.source_files(args.root / directory).items():
            source_hash.update(
                f"{directory}/{name}".encode() + b"\0" + hashlib.sha256(data).digest()
            )
    for repetition in range(args.repeat):
        with tempfile.TemporaryDirectory(prefix="msl-sync-bench-") as temporary:
            base = Path(temporary).resolve()
            roots = {"cached": base / "cached", "uncached": base / "uncached"}
            for root in roots.values():
                root.mkdir()
                for directory in ("skills", "agents", "grok-bot", "assets"):
                    source = args.root / directory
                    if source.exists():
                        shutil.copytree(source, root / directory, symlinks=True)
                (root / "skills/mkl-humanize/cache-benchmark.txt").write_bytes(b"before\n")
            for phase in samples:
                if phase == "changed":
                    for root in roots.values():
                        (root / "skills/mkl-humanize/cache-benchmark.txt").write_bytes(b"after!\n")
                results, calls = {}, {}
                order = list(roots) if repetition % 2 == 0 else list(reversed(roots))
                for engine in order:
                    seconds, result, count = timed_sync(roots[engine], engine == "cached", options)
                    samples[phase][engine].append(seconds)
                    results[engine], calls[engine] = result, count
                actual = snapshot(roots["cached"] / "providers")
                expected = snapshot(roots["uncached"] / "providers")
                if actual != expected or results["cached"] != results["uncached"]:
                    raise RuntimeError(
                        f"{phase}: cached and uncached sync differ; no timings reported"
                    )
                if calls != {"cached": 0 if phase == "warm" else 1, "uncached": 1}:
                    raise RuntimeError(f"{phase}: unexpected generation counts {calls}")
                if not kit.sync_providers(roots["cached"], check=True, **options)["up_to_date"]:
                    raise RuntimeError(f"{phase}: independent --check failed")
                fingerprint = hashlib.sha256()
                for name, data in sorted(actual.items()):
                    fingerprint.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
                output_hashes[phase] = fingerprint.hexdigest()
    medians = {
        phase: {engine: statistics.median(values) for engine, values in engines.items()}
        for phase, engines in samples.items()
    }
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "fingerprint_algorithm": kit._sync_hash_backend()[0],
                "generator_sha256": hashlib.sha256(Path(kit.__file__).read_bytes()).hexdigest(),
                "source_sha256": source_hash.hexdigest(),
                "repeat": args.repeat,
                "options": options,
                "outputs_sha256": output_hashes,
                "seconds": samples,
                "median_seconds": medians,
                "uncached_over_cached_ratio": {
                    phase: values["uncached"] / values["cached"]
                    for phase, values in medians.items()
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
