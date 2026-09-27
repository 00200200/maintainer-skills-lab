# [New Skill] `mkl-profile-performance` — Python CPU & Memory Profiler Interpreter

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Motivation
When optimizing code performance or investigating memory leaks, agents often guess bottlenecks by reading source code. This results in counterproductive micro-optimizations that clutter code without fixing the real slowdown.

Maintainers need agents to interpret empirical profiler data (e.g. `cProfile`, `py-spy`, `scalene`) and target only the true top-10 hot paths.

## Prior Art & Industry Standards
- **Scalene / py-spy / cProfile**: Leading Python profiling tools that produce line-by-line CPU and memory breakdowns.

## Proposed Solution
Create a new canonical skill `skills/mkl-profile-performance/SKILL.md`:
- **Name**: `"mkl-profile-performance"`
- **Description**: `"Analyze cProfile or py-spy tables to optimize real bottlenecks without code guessing."`

### Workflow Specification
1. **Profiler Invocation**:
   - Run `python3 -m cProfile -s tottime script.py | head -n 25` to capture only top execution lines.
2. **Table Interpretation**:
   - Focus strictly on high `tottime` (time spent in function body) vs `cumtime` (time spent in subcalls).
3. **Targeted Optimization**:
   - Propose optimizations (caching, vectorized operations, algorithm redesign) only for the top-3 identified bottlenecks.
4. **Verification**:
   - Re-run the profiler to empirically prove speedup before creating a PR.

## Implementation Tasks
- [ ] Author `skills/mkl-profile-performance/SKILL.md`.
- [ ] Include worked examples comparing profiler tables and verified speedups.
- [ ] Run `python3 tools/kit.py sync` across all clients.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Skill guides agents to demand empirical profiler data before proposing performance changes.
- All tests pass cleanly.
