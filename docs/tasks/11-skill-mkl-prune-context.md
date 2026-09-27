# [New Skill] Add `mkl-prune-context` — Active Context Pruner & Session Compactor

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Motivation
During long maintainer workflows—such as complex bug triage, bisecting regressions, or multi-round PR reviews—the agent's conversation history rapidly accumulates thousands of tokens.

Often, 80%+ of this accumulated history consists of:
- Verbose test outputs and stack traces that are already resolved.
- Dead-end debugging hypotheses.
- Repetitive file reading dumps.

Without explicit context pruning, the agent suffers from context degradation (forgetting initial user constraints) and drastically increased inference costs on every follow-up turn.

## Prior Art & Industry Standards
- **Claude Code Compact Mode**: Automatically summarizes prior conversation turns and retains only stateful architectural decisions and pending tasks.
- **Aider Chat Summarizer**: Compresses long conversational histories into concise bulleted takeaways.
- **LangChain Context Trimmer**: Drops earliest user/assistant message pairs while retaining system prompts and recent outputs.

## Proposed Solution
Create a new canonical skill `skills/mkl-prune-context/SKILL.md`:
- **Name**: `"mkl-prune-context"`
- **Description**: `"Use when a long debugging or triage session needs context compression to reduce tokens."`

### Skill Workflow Specifications
1. **Trigger Condition**:
   - The user requests a session summary, or the agent detects high turn count (> 15 turns) or context bloat.
2. **Pruning Strategy**:
   - **Retain**: Core problem statement, validated repro command, verified architectural decisions, active hypotheses, and next test assertion.
   - **Discard**: Full stack traces, redundant file reads, disproven hypotheses, and chatter.
3. **Structured Handoff Artifact**:
   - Guides the agent to output a clean, markdown compact state block that the user (or agent) can copy into a fresh session with minimum token overhead.
4. **Worked Example & Failure Case**:
   - Follow standard `MaintainerSkillsLab` guidelines: include an inspectable before/after example and explicit failure case (e.g. dropping an unresolved regression constraint).

## Implementation Tasks
- [ ] Author `skills/mkl-prune-context/SKILL.md` following canonical source format.
- [ ] Include worked example comparing verbose 4,000-token transcript with 350-token compacted summary.
- [ ] Add `skills/mkl-prune-context` to relevant agents (e.g. `mkl-bug-investigator.toml`).
- [ ] Run `python3 tools/kit.py sync` to propagate across all 5+ client targets.
- [ ] Add unit tests in `tests/test_kit.py` validating frontmatter and export consistency.

## Acceptance Criteria
- `skills/mkl-prune-context/SKILL.md` passes `python3 tools/kit.py check`.
- Provider files are automatically generated across all supported clients.
- All unit tests pass.
