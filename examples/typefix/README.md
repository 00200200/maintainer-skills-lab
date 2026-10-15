# Type-Guided Self-Healing Code Repair Example

Demonstrates using `mkl-fix-type-errors` and `tools/extract_type_diagnostics.py` to diagnose and fix static type checker errors without whole-file rewrites.

## Problem in `before/processor.py`
1. Accessing `report.summary` when `report` can be `None` (`[union-attr]`).
2. Passing `tuple[str, ...]` to `format_items(items: list[str])` (`[arg-type]`).

## Solution in `after/processor.py`
1. Narrowing type via `if report is None:` guard.
2. Widening parameter annotation from `list[str]` to `Sequence[str]`.

## Verification
Run `python3 examples/typefix/run.py` to verify the diagnostic extractor and clean resolution.
