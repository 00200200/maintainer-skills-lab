---
name: "mkl-prune-context"
description: "Prune verbose histories, logs, and resolved turns during long debugging or triage sessions into a stateful compact handoff."
---

# Prune context during long sessions

Compress accumulated conversation history, trial outputs, and resolved turns into a compact handoff artifact (< 300 tokens). Use during long sessions or before subagent delegation to prevent context degradation and eliminate token waste.

## 1. Trigger Conditions

Initiate context pruning when:
- The session reaches 15+ turns or approaches token limits.
- Iterative debugging left long stack traces, compiler dumps, or reverted edits in history.
- The user requests a session summary, checkpoint, `/compact`, or clean handoff.
- Preparing to hand off state to an isolated subagent or fresh prompt session.

## 2. Pruning Strategy: Retain vs. Discard

- **Retain (Keep in Handoff)**: Exact user objective and constraints, deterministic repro command and exit code, verified architectural invariants, target file paths and lines, and 1-line list of disproven theories.
- **Discard (Strip Entirely)**: Chit-chat, full tracebacks, multi-page build logs, speculative opinions, unmodified file reads, and reverted patch diffs.

## 3. Structured Handoff Template

Format the compressed state using this schema (< 250 tokens):

```markdown
## 🧭 Compact Session Handoff

- **Objective**: [1-line problem statement or task goal]
- **Environment & Invariants**: [Python/OS versions, constraints, zero-dependency rules]
- **Verified Findings**:
  - [Root cause anchor or verified reproduction fact]
  - [Key requirement confirmed by tests or maintainer guidelines]
- **Disproven Hypotheses**:
  - [Discarded path 1 — do not re-investigate]
- **Current Suspect Scope**: `path/to/file.py:SymbolName` (lines X-Y)
- **Reproduction**: `pytest tests/test_target.py -k test_case`
- **Next Action**: [Single concrete step to execute next]
```

## 4. Worked Example & Anti-Pattern

### Anti-pattern (Lossy Pruning)
Summarizing as *"Tested a few fixes that failed, now trying the parser"*. This loses negative constraints and the reproduction command, forcing future turns to repeat disproven dead ends.

### Recommended Worked Example
An 18-turn, 4,500-token multi-GPU deadlock debugging log is pruned down to:

```markdown
## 🧭 Compact Session Handoff

- **Objective**: Fix rank-0 NCCL deadlock when worker queue is empty in `torch.distributed`.
- **Environment & Invariants**: Linux, PyTorch 2.4, CUDA 12.4. Zero external dependencies.
- **Verified Findings**:
  - Deadlock triggers only when batch size is indivisible by world size on rank 0.
  - Repro verified: `python3 -m torch.distributed.run --nproc_per_node=2 test_deadlock.py`
- **Disproven Hypotheses**:
  - Not an NCCL timeout (`NCCL_ASYNC_ERROR_HANDLING=1` still hangs).
- **Current Suspect Scope**: `src/distributed/sampler.py:ShardBatchSampler.__iter__` (lines 88-104)
- **Reproduction**: `python3 test_deadlock.py` (exits 124 on hang, 0 on fix)
- **Next Action**: Pad remainder batch with sentinel index on rank 0 instead of early break.
```

Acceptance: The 4,500-token history is replaced with 160 high-signal tokens containing all facts required to continue without prior context.
