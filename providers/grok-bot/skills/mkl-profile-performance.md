# mkl-profile-performance

Analyze cProfile or py-spy tables to optimize real bottlenecks without code guessing.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-profile-performance."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Interpret profiler output and optimize hot paths

Do not guess performance bottlenecks by reading code. Human intuition about execution time is notoriously unreliable in dynamic languages like Python. Never rewrite algorithms, add complex caches, or micro-optimize functions without empirical profiler evidence establishing that the target function is a dominant contributor to overall runtime.

## Capture empirical profiler data

Establish a reproducible, deterministic workload that exercises the suspected performance regression or slow operation. Capture profile data using Python's built-in `cProfile` or sampling profilers (`py-spy`, `scalene`).

To capture the top CPU consumers sorted by internal function time:

```bash
python3 -m cProfile -s tottime script.py | head -n 25
```

To capture functions by cumulative time (useful for locating high-level subsystems):

```bash
python3 -m cProfile -s cumtime script.py | head -n 25
```

Record the complete environment: Python version, OS, CPU architecture, library versions, dataset size, and iteration count.

## Interpret the profiler table columns

A standard `cProfile` output presents five critical numeric columns:

1. `ncalls`: The number of times the function was called. If two numbers appear (e.g. `1000/10`), the function is recursive; the first is total calls, the second is primitive calls.
2. `tottime`: Total time spent in the given function's own body, excluding all time spent in calls to subfunctions. **This is the primary indicator of CPU bottlenecks.**
3. `percall` (first): Average time spent per call inside the function body (`tottime / ncalls`).
4. `cumtime`: Cumulative time spent in this function and all called subfunctions. Top-level runners (such as `main` or `run_pipeline`) will naturally have large `cumtime`.
5. `percall` (second): Average cumulative time per call (`cumtime / ncalls`).
6. `filename:lineno(function)`: The exact code site. Distinguish application code from third-party libraries and Python built-ins.

### Distinguish hot bodies from orchestrators

- **High `tottime`, moderate/low `cumtime`**: The function itself executes slow Python bytecode (e.g., tight loops, string concatenations, quadratic lookups). This is an immediate optimization candidate.
- **Low `tottime`, high `cumtime`**: The function is merely an orchestrator or wrapper delegating to subroutines. Do not optimize this function body; drill down into its subcalls to locate where the cumulative time is actually consumed.
- **High `ncalls` with tiny `percall`**: Function overhead multiplied across millions of iterations. Common causes include unmemoized helper calculations, repeated regex compilation, redundant object instantiation, or repeated attribute lookups inside nested loops.

## Focus strictly on the top-3 bottlenecks

Follow Amdahl's Law: optimizing a function that accounts for 2% of total runtime can yield at most a 2% overall improvement even if optimized to zero seconds.

1. Rank all application functions by `tottime`.
2. Select only the top 1 to 3 functions that account for the majority of execution time.
3. Ignore functions below the top tier. Reject PRs and changes that add caching, cythonization, or algorithmic complexity to non-bottleneck functions.

### Select targeted remedies

Match the diagnosed symptom with the appropriate optimization:

- **Repeated idempotent calculation with high `ncalls`**: Apply `functools.lru_cache` or precompute a lookup table outside the loop.
- **Repeated membership tests in lists (`item in sequence`)**: Convert lists to `set` or `dict` to reduce lookup from $O(N)$ to $O(1)$.
- **Repeated string building (`s += chunk`)**: Replace with list collection and `"".join(chunks)`.
- **Heavy element-wise math in nested Python loops**: Replace with vectorized NumPy, PyTorch, or Polars operations to move computation into compiled C/CUDA kernels.
- **Repeated regex compilation inside loops**: Hoist pattern compilation to module level via `re.compile()`.
- **JSON serialization/deserialization hot paths**: Switch to faster native parsers (`orjson`) or defer serialization until transmission.

## Worked Example: Hot path diagnosis and verification

### Baseline Profiler Output

```text
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.002    0.002    4.821    4.821 pipeline.py:1(run)
  1000000    3.210    0.000    3.210    0.000 processor.py:42(is_valid_token)
  1000000    1.120    0.000    1.120    0.000 {method 'match' of 're.Pattern'}
     5000    0.410    0.000    0.480    0.000 processor.py:88(lookup_metadata)
        1    0.079    0.079    4.821    4.821 main.py:1(<module>)
```

**Diagnosis:**
`is_valid_token` consumes 3.21s of 4.82s (66.6% of runtime) with 1,000,000 invocations. Inspecting `processor.py:42` reveals an internal check: `token in self.blacklist` where `self.blacklist` was initialized as a `list` containing 500 items. Searching a 500-element list $10^6$ times performs $5 \times 10^8$ equality checks.

**Remedy:**
Convert `self.blacklist` from `list` to `set` at class initialization.

### Verified Profiler Output

```text
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.002    0.002    1.682    1.682 pipeline.py:1(run)
  1000000    1.115    0.000    1.115    0.000 {method 'match' of 're.Pattern'}
     5000    0.408    0.000    0.478    0.000 processor.py:88(lookup_metadata)
  1000000    0.082    0.000    0.082    0.000 processor.py:42(is_valid_token)
        1    0.075    0.075    1.682    1.682 main.py:1(<module>)
```

**Outcome:**
`is_valid_token` dropped from 3.210s to 0.082s (39x function speedup). Overall execution dropped from 4.821s to 1.682s (2.86x end-to-end speedup).

## Verification and Pull Request checklist

Before committing performance improvements:
1. Re-run the profiler command under the exact same dataset and hardware conditions.
2. Confirm that total elapsed time and target function `tottime` decreased measurably.
3. Run the full unit and regression test suite to ensure functional correctness was not compromised.
4. Include both before and after profiler summaries in the pull request description.
