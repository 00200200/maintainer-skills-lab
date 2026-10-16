---
name: "mkl-profile-performance"
description: "Analyze cProfile or py-spy tables to optimize real bottlenecks without code guessing."
---

# Interpret profiler output and optimize hot paths

Do not guess performance bottlenecks. Human intuition about execution time is unreliable in dynamic languages like Python. Never rewrite algorithms or add caches without empirical profiler evidence establishing that the function is a dominant contributor to runtime.

## Capture empirical profiler data

Establish a reproducible, deterministic workload exercising the suspected slow operation. Capture profile data using `cProfile` or sampling profilers (`py-spy`, `scalene`).

Sort by internal function time (dominant CPU bottlenecks):
```bash
python3 -m cProfile -s tottime script.py | head -n 25
```

Sort by cumulative time (subsystem discovery):
```bash
python3 -m cProfile -s cumtime script.py | head -n 25
```

Record the environment: Python version, OS, CPU architecture, library versions, dataset size, and iteration count.

## Interpret the profiler table columns

A standard `cProfile` table presents five numeric columns:
- `ncalls`: Invocation count. Two numbers (e.g. `1000/10`) denote recursion (total/primitive).
- `tottime`: Total time inside the function body, excluding subcalls. **Primary CPU bottleneck indicator.**
- `percall` (1st): Average time per call inside the body (`tottime / ncalls`).
- `cumtime`: Cumulative time in this function and all subcalls.
- `percall` (2nd): Average cumulative time per call (`cumtime / ncalls`).
- `filename:lineno(function)`: Code site. Distinguish app code from libraries and built-ins.

### Hot bodies vs orchestrators

- **High `tottime`, low `cumtime`**: Function executes slow Python bytecode (tight loops, string concats, quadratic lookups). Prime optimization target.
- **Low `tottime`, high `cumtime`**: Orchestrator delegating to subroutines. Drill into subcalls instead of optimizing this body.
- **High `ncalls` with tiny `percall`**: Overhead multiplied across iterations (e.g. unmemoized helpers, repeated regex compilation).

## Focus on top-3 bottlenecks

Follow Amdahl's Law: optimizing a function taking 2% of runtime yields at most a 2% overall gain.

1. Rank application functions by `tottime`.
2. Select only top 1 to 3 functions accounting for majority of runtime.
3. Reject PRs adding complexity to non-bottleneck functions.

### Targeted remedies

- **Repeated calculation with high `ncalls`**: Apply `functools.lru_cache` or precompute a lookup table.
- **Repeated membership tests in lists (`x in list`)**: Convert to `set` or `dict` ($O(N) \to O(1)$).
- **Repeated string building (`s += chunk`)**: Replace with list appending and `"".join(chunks)`.
- **Heavy math in loops**: Vectorize via NumPy, PyTorch, or Polars.
- **Repeated regex compilation**: Hoist compilation via `re.compile()`.
- **JSON serialization hot paths**: Switch to native parsers (`orjson`) or defer serialization.

## Worked Example: Hot path diagnosis

### Baseline Output
```text
   ncalls  tottime  cumtime filename:lineno(function)
  1000000    3.210    3.210 processor.py:42(is_valid_token)
```
**Diagnosis**: `is_valid_token` consumes 66% of runtime due to `token in self.blacklist` on a 500-element `list` ($5 \times 10^8$ checks).

**Remedy**: Convert `self.blacklist` from `list` to `set` during initialization.

### Verified Output
```text
   ncalls  tottime  cumtime filename:lineno(function)
  1000000    0.082    0.082 processor.py:42(is_valid_token)
```
**Outcome**: `is_valid_token` dropped from 3.21s to 0.082s (39x speedup). Total runtime dropped from 4.82s to 1.68s.

## Verification Checklist

1. Re-run profiler under identical dataset and hardware conditions.
2. Confirm elapsed time and target function `tottime` decreased measurably.
3. Run unit tests to guarantee functional correctness was preserved.
4. Include before/after profiler summaries in the pull request.
