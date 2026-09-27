# [Feature] Tail-and-Filter Command Output Compressor (`tools/log_compressor.py`)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
When coding agents execute builds, test suites, or package installations (e.g. `pytest`, `cargo test`, `npm test`, PyTorch compilation), a failure can produce 2,000 to 10,000 lines of standard output and compiler noise.

Dumping raw test outputs directly into an LLM context window causes:
- Massive token waste (often 10k–30k tokens for a single compiler error).
- "Lost in the middle" attention failure: models fail to spot the actual `AssertionError` buried between thousands of passing log lines.
- Premature context exhaustion in long sessions.

## Prior Art & Industry Standards
- **Anthropic Claude Code**: Employs an intelligent output truncation filter that keeps the initial command, the tail of the stream, and regex-matches for failure patterns (`FAILED`, `Error:`, `Traceback`).
- **OpenHands / SWE-bench Harness**: Masks repetitive test logs and compresses terminal observations to only lines containing diagnostic value.

## Proposed Solution
Create a zero-dependency CLI utility `tools/log_compressor.py` and integrate it into maintainer workflow instructions:
```bash
# Pipe any noisy command through the compressor
pytest | python3 tools/log_compressor.py --max-lines 50
```

### Compression Heuristics
1. **Error Anchor Detection**:
   - Detects stack trace starts (`Traceback (most recent call last):`).
   - Detects test assertion failures (`AssertionError:`, `FAILED tests/...`, `E   assert ...`).
   - Detects fatal exit codes and compiler errors (`error[E0...]:`, `SyntaxError:`, `npm ERR!`).
2. **Context Window Slicing**:
   - Retains 5 lines before the first error anchor and 15 lines after.
   - Retains the final 20 lines of the terminal output (summary line).
   - Replaces middle chatter (e.g. 500 lines of `.test_foo ok`) with a compact token marker:
     `[... 420 lines of passing tests omitted ...]`
3. **Token Budget Cap**:
   - Hard cap on compressed output (default: 800 tokens / ~3,200 chars).

## Implementation Tasks
- [ ] Implement `tools/log_compressor.py` supporting stdin piping and file input.
- [ ] Add regex patterns for Python (`pytest`, `unittest`), Node (`jest`, `npm`), Rust (`cargo`), and C/C++ (`gcc`, `clang`).
- [ ] Add CLI flags: `--max-tokens`, `--max-lines`, `--json`.
- [ ] Add unit tests in `tests/test_log_compressor.py` with noisy real-world fixtures (e.g. 2,000-line pytest run).
- [ ] Update `skills/mkl-reproduce-bug/SKILL.md` and `skills/mkl-verify-fix/SKILL.md` to instruct agents to use log compression.

## Acceptance Criteria
- A 2,500-line noisy pytest log is compressed to < 60 lines (< 600 tokens) while preserving the exact `AssertionError` and failure summary.
- Pure Python standard library (no dependencies).
- Test suite passes cleanly.
