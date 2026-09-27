# [Feature] Fast Local Test Runner Hook with `pytest -q --tb=short` Defaults

**Labels**: `enhancement`, `optimization`, `good first issue`

## Context & Motivation
Across our skills (`mkl-reproduce-bug`, `mkl-verify-fix`, `mkl-write-regression`), instructions frequently state: *"Run the test suite to verify the fix."*

When an agent executes an unqualified `pytest` or `python3 -m unittest`, it defaults to full tracebacks and verbose progress headers. A single failure often yields 100+ lines of traceback with local variable dumps.

## Prior Art & Industry Standards
- **Pytest options**: `--tb=short` (shows only failing line), `-q` (quiet, suppresses header/footer), `--no-header`.
- High-efficiency agent harnesses standardizing test runner flags.

## Proposed Solution
Update all testing and verification skills to explicitly specify token-efficient test command standards:
- Python: `pytest -q --tb=short -x` (stops on first failure, short traceback).
- Node: `npm test -- --bail --silent`.
- Rust: `cargo test -- --nocapture=false`.

In addition, provide an alias / helper in `tools/test_fast.py` to ensure local developers and agents run tests with minimum token output.

## Implementation Tasks
- [ ] Audit `skills/mkl-reproduce-bug/`, `skills/mkl-verify-fix/`, `skills/mkl-write-regression/` for test command invocations.
- [ ] Update instructions to enforce `-q --tb=short -x`.
- [ ] Run `python3 tools/kit.py sync` across all clients.
- [ ] Verify test suite passes.

## Acceptance Criteria
- Skills consistently instruct agents to run tests with concise traceback flags, cutting test token footprint by > 75%.
