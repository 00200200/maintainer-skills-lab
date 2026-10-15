#!/usr/bin/env python3
"""Tail-and-filter terminal test output and build log compressor.

Extracts critical failure tracebacks, compiler diagnostics, and summary statistics
from noisy test/build logs while stripping thousands of passing lines.
Saves 80-95% of LLM context tokens during automated bug reproduction and verification.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Common failure and diagnostic anchor patterns across ecosystems
ERROR_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(
        r"^[ \t]*(?:AssertionError|AttributeError|TypeError|ValueError|KeyError|"
        r"IndexError|ImportError|ModuleNotFoundError|RuntimeError|SyntaxError|NameError|"
        r"ZeroDivisionError|FileNotFoundError|PermissionError|NotImplementedError):"
    ),
    re.compile(r"^[ \t]*FAILED\s+[^\s]+", re.IGNORECASE),
    re.compile(r"^[ \t]*E\s{2,}.*"),  # pytest failure indicator
    re.compile(r"error\[E\d+\]:", re.IGNORECASE),  # rustc
    re.compile(r"npm ERR!", re.IGNORECASE),
    re.compile(r"fatal error:", re.IGNORECASE),
    re.compile(r"^FAIL\s+[^\s]+", re.IGNORECASE),  # jest/vitest
    re.compile(r"=== FAILURES ===", re.IGNORECASE),
    re.compile(r"=== ERRORS ===", re.IGNORECASE),
    re.compile(r"=== short test summary info ===", re.IGNORECASE),
]


RE_PY_TRACEBACK_LINE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+([^\n]+))?')
RE_PY_EXC_LINE = re.compile(
    r"^([A-Z][a-zA-Z0-9_.]*(?:Error|Exception|Warning|Interrupt|Exit|Fault|Violation))(?::\s*(.*))?$",
    re.MULTILINE,
)
RE_PYTEST_FAILED = re.compile(
    r"FAILED\s+([^:]+)::([^\s]+)\s*-\s*([A-Za-z0-9_.]+(?:Error|Exception)?)(?::\s*(.*))?"
)
RE_PYTEST_SHORT = re.compile(
    r"^([^\n:]+):(\d+):\s*([A-Za-z0-9_.]+(?:Error|Exception)?(?::\s*.*)?)$",
    re.MULTILINE,
)
RE_RUST_ERROR = re.compile(
    r"error\[(E\d+)\]:\s*([^\n]+).*?-->\s*([^:\n]+):(\d+)",
    re.DOTALL,
)


def approximate_tokens(text: str) -> int:
    """Standard ~4 chars per token heuristic used across maintainer-skills-lab."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def extract_error_signature(text: str) -> str | None:
    """Extract a normalized error signature (exception, message, file:line) from terminal logs."""
    if not text or not text.strip():
        return None

    # 1. Rust error
    rust_match = RE_RUST_ERROR.search(text)
    if rust_match:
        code, msg, filepath, lineno = rust_match.groups()
        filename = Path(filepath).name
        return f"error[{code}]: {msg.strip()} at {filename}:{lineno}"

    # 2. Pytest FAILED line
    pytest_match = RE_PYTEST_FAILED.search(text)
    if pytest_match:
        testfile, testfn, exc, msg = pytest_match.groups()
        filename = Path(testfile).name
        msg_str = f": {msg.strip()}" if msg else ""
        return f"{exc}{msg_str} at {filename}::{testfn}"

    # 3. Python traceback
    tb_lines = list(RE_PY_TRACEBACK_LINE.finditer(text))
    if tb_lines:
        last_tb = tb_lines[-1]
        filepath = last_tb.group(1)
        lineno = last_tb.group(2)
        filename = Path(filepath).name

        tail_text = text[last_tb.end() :]
        exc_match = RE_PY_EXC_LINE.search(tail_text)
        if exc_match:
            exc_type = exc_match.group(1)
            exc_msg = (exc_match.group(2) or "").strip()
            clean_msg = exc_msg.strip("'\"")
            msg_str = f'("{clean_msg}")' if clean_msg else ""
            return f"{exc_type}{msg_str} at {filename}:{lineno}"
        return f"Traceback at {filename}:{lineno}"

    # 4. Pytest short file:line: Error
    pytest_short = RE_PYTEST_SHORT.search(text)
    if pytest_short:
        filepath, lineno, err = pytest_short.groups()
        filename = Path(filepath).name
        return f"{err.strip()} at {filename}:{lineno}"

    # 5. Direct exception line anywhere in text
    exc_direct = RE_PY_EXC_LINE.search(text)
    if exc_direct:
        exc_type = exc_direct.group(1)
        exc_msg = (exc_direct.group(2) or "").strip()
        clean_msg = exc_msg.strip("'\"")
        msg_str = f'("{clean_msg}")' if clean_msg else ""
        return f"{exc_type}{msg_str}"

    return None


def mask_repeated_observation(
    current: str,
    previous: str | None = None,
    turn: int | None = None,
) -> tuple[str, bool]:
    """
    Mask repeated terminal test failure observations if the error signature is identical.

    Returns:
        tuple[text, is_masked]
        where text is either the compact masked summary (if identical) or the current text (if new).
    """
    if not previous or not previous.strip():
        return current, False

    sig_curr = extract_error_signature(current)
    sig_prev = extract_error_signature(previous)

    is_identical = False
    signature_desc = ""
    if sig_curr and sig_prev and sig_curr == sig_prev:
        is_identical = True
        signature_desc = sig_curr
    elif current.strip() == previous.strip() and sig_curr:
        is_identical = True
        signature_desc = sig_curr

    if is_identical:
        curr_tokens = approximate_tokens(current)
        turn_str = f"Turn {turn}" if turn is not None else "preceding turn"
        saved = max(0, curr_tokens - 30)
        masked_msg = (
            f"[Test failed with IDENTICAL signature as {turn_str}: {signature_desc}. "
            f"Traceback omitted (saved ~{saved} tokens).]"
        )
        return masked_msg, True

    return current, False


def find_error_anchor_indices(lines: list[str]) -> list[int]:
    """Identify line indices matching any error/failure diagnostic anchor."""
    anchors = []
    for idx, line in enumerate(lines):
        for pattern in ERROR_PATTERNS:
            if pattern.search(line):
                anchors.append(idx)
                break
    return anchors


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or contiguous (start, end) index intervals."""
    if not spans:
        return []
    sorted_spans = sorted(spans, key=lambda s: s[0])
    merged = [sorted_spans[0]]
    for current in sorted_spans[1:]:
        prev_start, prev_end = merged[-1]
        if current[0] <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, current[1]))
        else:
            merged.append(current)
    return merged


def compress_log(
    text: str,
    *,
    max_lines: int = 60,
    max_tokens: int = 800,
    context_before: int = 5,
    context_after: int = 15,
    tail_lines: int = 20,
) -> tuple[str, dict]:
    """Compress terminal output preserving error anchors and summary tails.

    Returns:
        tuple[compressed_text, stats_dict]
    """
    if not text.strip():
        stats = {
            "original_lines": 0,
            "compressed_lines": 0,
            "original_tokens": 0,
            "compressed_tokens": 0,
            "reduction_pct": 0.0,
            "anchors_found": 0,
        }
        return "", stats

    lines = text.splitlines()
    total_lines = len(lines)
    orig_tokens = approximate_tokens(text)

    # If already small and within limits, return untouched
    if total_lines <= max_lines and orig_tokens <= max_tokens:
        stats = {
            "original_lines": total_lines,
            "compressed_lines": total_lines,
            "original_tokens": orig_tokens,
            "compressed_tokens": orig_tokens,
            "reduction_pct": 0.0,
            "anchors_found": len(find_error_anchor_indices(lines)),
        }
        return text, stats

    anchor_indices = find_error_anchor_indices(lines)

    spans: list[tuple[int, int]] = []

    # Always keep initial command/header lines if few
    head_count = min(5, total_lines)
    spans.append((0, head_count))

    # Add spans around each anchor
    for anchor in anchor_indices:
        start = max(0, anchor - context_before)
        end = min(total_lines, anchor + context_after + 1)
        spans.append((start, end))

    # Always keep tail summary lines
    tail_start = max(0, total_lines - tail_lines)
    spans.append((tail_start, total_lines))

    merged = merge_spans(spans)

    # Build compressed text with omitted markers
    result_lines: list[str] = []
    last_end = 0

    for start, end in merged:
        if start > last_end:
            omitted = start - last_end
            result_lines.append(f"[... {omitted} lines of passing/standard output omitted ...]")
        result_lines.extend(lines[start:end])
        last_end = end

    if last_end < total_lines:
        omitted = total_lines - last_end
        result_lines.append(f"[... {omitted} lines of passing/standard output omitted ...]")

    compressed_text = "\n".join(result_lines)
    compressed_tokens = approximate_tokens(compressed_text)

    # Hard token cap safeguard
    max_char_budget = max_tokens * 4
    if len(compressed_text) > max_char_budget:
        half_budget = max_char_budget // 2
        compressed_text = (
            compressed_text[:half_budget]
            + f"\n\n[... Truncated to fit {max_tokens} token budget ...]\n\n"
            + compressed_text[-half_budget:]
        )
        compressed_tokens = approximate_tokens(compressed_text)

    comp_lines = len(compressed_text.splitlines())
    reduction = max(0.0, (1.0 - (compressed_tokens / max(1, orig_tokens))) * 100.0)

    stats = {
        "original_lines": total_lines,
        "compressed_lines": comp_lines,
        "original_tokens": orig_tokens,
        "compressed_tokens": compressed_tokens,
        "reduction_pct": round(reduction, 1),
        "anchors_found": len(anchor_indices),
    }

    return compressed_text, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compress noisy test/build terminal output while preserving critical errors."
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Path to log file (reads from stdin if omitted or piped)",
    )
    parser.add_argument(
        "--file",
        "-f",
        dest="file_flag",
        type=Path,
        help="Explicit log file path",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=60,
        help="Target maximum line count (default: 60)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=800,
        help="Strict token budget ceiling (default: 800 tokens)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON containing compressed text and compression metrics",
    )
    parser.add_argument(
        "--mask-previous",
        "-m",
        dest="mask_previous",
        type=Path,
        help="Path to previous turn's log file for observation masking deduplication",
    )
    parser.add_argument(
        "--turn",
        type=int,
        default=None,
        help="Current or reference turn number (for observation masking annotation)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print compression statistics to stderr",
    )

    args = parser.parse_args(argv)

    target_file = args.file_flag or args.file

    if target_file:
        if not target_file.is_file():
            print(f"Error: file not found: {target_file}", file=sys.stderr)
            return 1
        raw_text = target_file.read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        raw_text = sys.stdin.read()
    else:
        parser.print_help(file=sys.stderr)
        return 1

    # Check for observation masking if previous log provided
    if args.mask_previous:
        if not args.mask_previous.is_file():
            print(f"Error: previous log file not found: {args.mask_previous}", file=sys.stderr)
            return 1
        prev_text = args.mask_previous.read_text(encoding="utf-8", errors="replace")
        masked_text, is_masked = mask_repeated_observation(raw_text, prev_text, turn=args.turn)
        if is_masked:
            if args.json:
                payload = {
                    "compressed": masked_text,
                    "masked": True,
                    "signature": extract_error_signature(raw_text),
                    "saved_tokens": approximate_tokens(raw_text) - approximate_tokens(masked_text),
                }
                print(json.dumps(payload, indent=2))
            else:
                print(masked_text)
            return 0

    compressed, stats = compress_log(
        raw_text,
        max_lines=args.max_lines,
        max_tokens=args.max_tokens,
    )

    if args.json:
        payload = {
            "compressed": compressed,
            "masked": False,
            "signature": extract_error_signature(raw_text),
            "stats": stats,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(compressed)
        if args.stats:
            print(
                f"\n[LogCompressor] {stats['original_lines']} -> {stats['compressed_lines']} lines | "
                f"{stats['original_tokens']} -> {stats['compressed_tokens']} tokens "
                f"({stats['reduction_pct']}% reduction, {stats['anchors_found']} error anchors)",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
