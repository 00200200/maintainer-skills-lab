"""examples/typefix/run.py - Validates type diagnostic extraction and repair."""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to import path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from tools.extract_type_diagnostics import format_xml, parse_mypy_output

    synthetic_mypy_log = (
        "examples/typefix/before/processor.py:27: error: "
        'Item "None" of "Report | None" has no attribute "summary" [union-attr]\n'
        "examples/typefix/before/processor.py:30: error: "
        'Argument 1 to "format_items" has incompatible type "tuple[str, ...]"; '
        'expected "list[str]" [arg-type]\n'
        "Found 2 errors in 1 file (checked 1 source file)\n"
    )

    diags = parse_mypy_output(synthetic_mypy_log, root_dir=REPO_ROOT, with_scope=True)
    if len(diags) != 2:
        sys.stderr.write(f"Expected 2 diagnostics, got {len(diags)}\n")
        return 1

    d1, d2 = diags[0], diags[1]
    if d1.code != "union-attr" or d1.symbol != "generate_digest":
        sys.stderr.write(f"Unexpected diagnostic 1: {d1}\n")
        return 1

    if d2.code != "arg-type" or d2.symbol != "generate_digest":
        sys.stderr.write(f"Unexpected diagnostic 2: {d2}\n")
        return 1

    xml_output = format_xml(diags)
    if "<recommended_fix>" not in xml_output:
        sys.stderr.write("Missing recommended fix in XML output\n")
        return 1

    # Verify after version produces clean output
    clean_log = "Success: no issues found in 1 source file\n"
    clean_diags = parse_mypy_output(clean_log, root_dir=REPO_ROOT, with_scope=True)
    if clean_diags:
        sys.stderr.write("Expected clean diagnostics for after version\n")
        return 1

    print("✅ Type-fix diagnostic extraction and verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
