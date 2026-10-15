---
name: "mkl-isolated-scratchpad"
description: "Offload verbose reasoning, trial commands, and intermediate drafts to ephemeral scratch files to preserve context tokens."
---

# Isolated Scratchpad for Ephemeral Reasoning

Redirect long exploratory traces, speculative diffs, and verbose command outputs into ephemeral scratchpad files to keep the main conversation window compact and token-efficient.

## Workflow & Guidelines

1. **Designated Ephemeral Directory**:
   - Write intermediate files to `.msl/scratch/` or `.scratch/` in the project root (e.g. `.msl/scratch/session_<topic>.md`).
   - Ensure the directory is ignored by git and context indexers so scratch files are never committed.

2. **Command Redirection**:
   - Never print raw multi-page terminal outputs into conversation context.
   - Redirect verbose outputs directly to scratch:
     ```bash
     pytest tests/ > .msl/scratch/test_run.log 2>&1
     ```

3. **Targeted Inspection**:
   - Extract only relevant failure anchors or error spans using filtered queries:
     ```bash
     grep -E "FAILED|ERROR" .msl/scratch/test_run.log
     ```
   - Avoid reading full hundred-line log files back into memory.

4. **Clean Synthesis Handoff**:
   - Return a concise synthesis in under 150 tokens to the main conversation.
   - Reference the scratch file path so the user can inspect detailed trial traces if desired.
   - Clean up or retain scratch files per user preference upon task conclusion.

## Examples

### Anti-pattern (Context Poisoning)
Dumping 120 lines of raw test output directly into chat, consuming 4,000+ tokens and polluting history with transient error noise.

### Recommended Pattern (Isolated Scratchpad)
```bash
npm test > .msl/scratch/build.log 2>&1
python3 tools/log_compressor.py compress .msl/scratch/build.log
```
Returns a 5-line actionable summary in 120 tokens, pointing to `.msl/scratch/build.log`.
