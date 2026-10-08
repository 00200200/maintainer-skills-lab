# [Feature] Dynamic Token Budget Allocator for Long Sessions (tools/budget_allocator.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Problem
During extended agentic workflows—such as multi-turn bug triage, bisecting subtle regressions, large-scale refactoring, or iterative pull request reviews—the conversation context window fills up progressively. In the early stages of a session (< 25% context capacity used), tools can return generous snippets, full diffs, and verbose stack traces without noticeable penalty.

However, as the session reaches 60%, 75%, and 90% of model context capacity (e.g. 128k or 200k tokens), indiscriminate tool outputs cause abrupt context saturation. This leads to:
1. **Model Context Exhaustion**: A single 3,000-token command output or large file dump can trigger emergency session compaction or truncation.
2. **Degraded Instruction Following**: Reasoning quality and attention to system constraints degrade significantly as the context window nears its maximum capacity ("lost in the middle").
3. **Escalating Inference Latency and Cost**: Every follow-up turn re-processes the entire context, dramatically increasing latency and API costs.

Currently, MaintainerSkillsLab enforces static limits (e.g. 800 tokens for repomaps, static log truncators). It lacks an active monitor or dynamic coordinator that calculates the remaining token budget and adjusts tool output quotas and skill verbosity on the fly.

## Prior Art & Industry Standards
- **Claude Code Dynamic Context Governor**: Continuously computes token headroom in the current session window; dynamically scales Bash output caps, switches from full file reads to scoped diff chunks, and prompts session compaction as token consumption crosses 50%, 75%, and 85% thresholds.
- **Aider Context Budgeting**: Computes remaining model window capacity before injecting repo maps or git diffs, scaling map depth down proportionally.
- **OpenHands / SWE-bench Observation Guards**: Dynamically caps tool observation outputs to prevent a single tool execution from consuming more than 10-15% of remaining token capacity.

## Proposed Solution
Create `tools/budget_allocator.py`, a zero-dependency Python utility and importable module that tracks session token consumption and dynamically allocates token budgets across tools and skills.

```bash
# Check current budget recommendation given accumulated token usage
python3 tools/budget_allocator.py --model claude-3-7-sonnet --used-tokens 85000

# Calculate allocated limits for child tools (repomap, log_compressor, scope_extract) in JSON format
python3 tools/budget_allocator.py --model gpt-4o --used-tokens 110000 --json

# Interactive / piping mode for agent session state JSON
cat session_stats.json | python3 tools/budget_allocator.py --pipe
```

### Architecture & Allocation Tiers
1. **Model Context Window Registry**:
   - Built-in profiles for standard foundation models:
     - `claude-3-5-sonnet` / `claude-3-7-sonnet`: 200,000 tokens
     - `gpt-4o` / `gpt-4o-mini`: 128,000 tokens
     - `gemini-1.5-pro` / `gemini-2.0-flash`: 1,000,000+ tokens
     - `deepseek-v3` / `deepseek-r1`: 64,000 / 128,000 tokens
     - Configurable custom capacity via `--context-window <N>`.

2. **Dynamic Operational Tiers**:
   - **Nominal Tier (< 50% used)**:
     - Tool observation cap: 2,500 tokens
     - Repo map budget: 1,200 tokens
     - Skill verbosity: Full examples and explanatory guidelines.
   - **Conservative Tier (50% – 75% used)**:
     - Tool observation cap: 1,000 tokens
     - Repo map budget: 600 tokens
     - Skill verbosity: Standard checklist, strip optional commentary.
   - **Critical Tier (75% – 90% used)**:
     - Tool observation cap: 400 tokens
     - Repo map budget: 250 tokens
     - AST extraction: Signatures only (omit docstrings & bodies).
     - Single-frame stack traces in log compressor.
   - **Emergency Tier (> 90% used)**:
     - Tool observation cap: 150 tokens
     - Triggers recommendation to execute `mkl-prune-context` immediately before proceeding.

3. **Programmatic Python API**:
   ```python
   from tools.budget_allocator import ContextBudgetGovernor, WindowTier

   governor = ContextBudgetGovernor(model="claude-3-7-sonnet", used_tokens=150_000)
   print(governor.tier)  # WindowTier.CRITICAL
   print(governor.get_tool_budget("repomap"))  # 250
   print(governor.get_tool_budget("log_compressor"))  # 400
   print(governor.should_compact())  # False (True if > 90%)
   ```

## Implementation Tasks
- [ ] Implement `tools/budget_allocator.py` with `ContextBudgetGovernor` class and `WindowTier` enum.
- [ ] Support model context window registry with standard models and custom token limit overrides.
- [ ] Implement tier classification (`NOMINAL`, `CONSERVATIVE`, `CRITICAL`, `EMERGENCY`) with configurable thresholds.
- [ ] Provide tool limit calculation API for `repomap`, `log_compressor`, `scope_extract`, and bash tool runners.
- [ ] Add CLI arguments: `--model`, `--context-window`, `--used-tokens`, `--turn-count`, `--json`, and `--pipe`.
- [ ] Integrate with `tools/kit.py tokens` to report headroom against target models.
- [ ] Add unit tests in `tests/test_budget_allocator.py` covering tier transitions, fallback heuristics, and JSON payload contracts.
- [ ] Update `README.md` and reference allocator in `skills/mkl-prune-context/SKILL.md`.

## Acceptance Criteria
- `python3 tools/budget_allocator.py --model claude-3-7-sonnet --used-tokens 160000 --json` returns valid JSON with `tier: "CRITICAL"`, tool quotas, and recommended flags.
- Pure Python 3.11+ standard library implementation (no mandatory third-party dependencies).
- Unit tests verify deterministic threshold calculations and edge cases (0 used tokens, 100% saturation, unknown models).
- Code passes repository linting (`python3 tools/kit.py check`).
