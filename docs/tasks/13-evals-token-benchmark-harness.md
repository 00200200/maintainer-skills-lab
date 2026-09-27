# [Evals] Automated Token Usage & Cost Benchmark Runner (`evals/harness.py`)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
In `evals/README.md`, our evaluation policy states:
> "No live-agent runs are included in this preview. The automated suite validates the tooling and a trusted example only."

While this is clean for unit testing, the repository lacks an **objective benchmark harness** to measure how effectively our skills reduce token usage and API cost when solving real maintainer problems (e.g., resolving the bug in `examples/bugfix/slug.py` or triaging issues).

Without empirical token benchmarks, we cannot measure whether prompt optimizations actually save users money or improve task completion efficiency.

## Prior Art & Industry Standards
- **SWE-bench / Lite**: Evaluates agent task completion and reports total token cost per resolved issue.
- **Aider Benchmark**: Runs standard benchmarks measuring pass-rate and cost per solved problem.
- **HumanEval / MultiPL-E**: Standardized test fixture execution with automated metric collection.

## Proposed Solution
Build an opt-in evaluation harness `evals/harness.py`:
1. **Mocked / Offline Token Baseline Runner**:
   - Runs deterministic, offline evaluation of task prompts with and without skill guidance.
   - Measures prompt size, completion size, and estimated cost across major models (Claude 3.7 Sonnet, GPT-4o, Gemini 2.0 Flash).
2. **Opt-in Live Runner**:
   - Supports passing an API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`) to run a real scenario from `examples/bugfix/`.
   - Records:
     - Prompt tokens (cached vs uncached)
     - Completion tokens
     - Cost in USD
     - Task outcome (test pass/fail)
3. **Automated Scorecard**:
   - Generates an `evals/BENCHMARK.md` markdown table comparing baseline performance vs skill-assisted performance.

## Implementation Tasks
- [ ] Create `evals/harness.py` supporting offline token estimation and optional live execution.
- [ ] Implement `CostCalculator` with standard pricing per million tokens for standard models.
- [ ] Create a benchmark scenario for `examples/bugfix/` (bug reproduction & fix).
- [ ] Add CLI flags: `--scenario bugfix`, `--offline`, `--json`, `--output <file>`.
- [ ] Add unit tests in `tests/test_evals.py` verifying metric calculation logic offline without requiring API keys.

## Acceptance Criteria
- Running `python3 evals/harness.py --offline` outputs a complete token and cost breakdown table without network calls or API keys.
- Output includes total tokens, estimated cost, and simulated savings.
- Unit tests pass cleanly.
