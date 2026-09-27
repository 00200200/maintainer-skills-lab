# [Feature] Observation Masking for Repeated Test Failures in Bug Repro

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
During bug reproduction and regression testing (`mkl-reproduce-bug`, `mkl-write-regression`, `mkl-verify-fix`), an AI agent typically runs a reproduction script 3 to 10 times as it iterates on a patch.

On every iteration where the bug is still present, the test runner outputs the **exact same 40-line stack trace**. Sending identical stack traces repeatedly across multi-turn sessions burns thousands of tokens without adding any new information, pushing earlier context and problem constraints out of the attention window.

## Prior Art & Industry Standards
- **SWE-bench & OpenHands Benchmarks**: Observation masking tracks previous environment outputs. If an observation's error signature matches a previously seen signature, the harness masks the repetition with a compact summary.
- **Compiler caching / Test deduplication**: Modern dev tools suppress repeated stack traces across test runs.

## Proposed Solution
Add an **Observation Masking** guideline and helper in `tools/kit.py` and `skills/mkl-reproduce-bug/SKILL.md`:
1. **Signature Hashing**:
   - Compute a hash of the exception type, message, and failing line (`ValueError("bad slug") at slug.py:24`).
2. **Masking Format**:
   - If the error signature is identical to the preceding turn:
     `[Test failed with IDENTICAL signature as Turn 3: ValueError at slug.py:24. Traceback omitted (saved ~400 tokens).]`
   - If the error changes (e.g. progressing from `KeyError` to `AssertionError`), the full new trace is shown.

## Implementation Tasks
- [ ] Implement `mask_repeated_observation(current: str, previous: str) -> str` in `tools/log_compressor.py`.
- [ ] Document the observation masking pattern in `skills/mkl-reproduce-bug/SKILL.md` and `skills/mkl-verify-fix/SKILL.md`.
- [ ] Add unit tests verifying that identical errors are masked while new errors are preserved.

## Acceptance Criteria
- Repeated identical test failures in an iterative agent loop are masked, saving up to 80% of tokens in turns 2 through 10.
- Any change in exception line or type causes the full error to display.
