# [Feature] Two-Stage Fault Localization Before Code Repair (mkl-localize-fault)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Problem & Context
When AI agents attempt to fix bugs, solve issue tickets, or pass failing tests, their default behavior is often to dump whole files or entire directories into the active context window. For repositories with files spanning hundreds or thousands of lines, this approach consumes 30,000 to 80,000+ prompt tokens in a single shot.

Whole-repo context dumping causes severe operational failure modes:
1. **Context Window Saturation & Cost**: Reading unpruned files rapidly exhausts token budgets, driving up API expenses.
2. **Attention Degradation (Lost in the Middle)**: Dense, irrelevant context distracts LLMs from the actual faulty logic.
3. **Hallucinatory Side-Effects**: Agents frequently introduce accidental edits into unrelated methods located in the same file.

Empirical studies on benchmarks like SWE-bench demonstrate that the vast majority of real-world bug fixes modify fewer than 20 contiguous lines of code. Dumping full files prior to pinpointing the bug is unnecessary and counterproductive.

## Prior Art & Industry Standards
- **Agentless (SWE-bench SOTA)**: The Agentless framework achieved state-of-the-art results on SWE-bench without running autonomous agent loops by strictly enforcing a two-stage pipeline:
  - **Stage 1 (Hierarchical Localization)**: Pinpoints suspect files, classes, and specific line ranges. The localization artifact is compact (< 300 tokens).
  - **Stage 2 (Local Repair)**: Ingests only the localized function slice or line range (with +/- 15 lines of context padding) into the repair prompt.
- **Spectrum-Based Fault Localization (SBFL)**: Traditional techniques (Tarantula, Ochiai) that narrow down suspect program statements using test execution traces.
- **Aider Scoped Extraction**: Slices relevant symbol definitions without loading entire enclosing files.

## Proposed Solution
Create a new canonical skill `skills/mkl-localize-fault/SKILL.md` and localization utility `tools/localize_fault.py` enforcing a two-phase fault isolation protocol before code repair:

```text
[Failing Test Traceback / Bug Report]
                  │
                  ▼
┌──────────────────────────────────────────────┐
│  Stage 1: Fault Localization                 │
│  - AST skeleton inspection (signatures only) │
│  - Stack trace parsing                       │
│  - Emits: filepath:start_line-end_line       │ (< 300 tokens output)
└─────────────────┬────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────┐
│  tools/localize_fault.py Slice Extractor     │
│  - Extracts localized hunk + 20 lines padding│ (< 1,500 tokens context)
└─────────────────┬────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────┐
│  Stage 2: Targeted Code Repair               │
│  - Ingests only localized slice              │
│  - Generates atomic patch for targeted lines │
└──────────────────────────────────────────────┘
```

### Protocol Specifications
1. **Hierarchical Localization Protocol**:
   - **Step 1 (File Level)**: Analyze test output, issue keywords, and repomap to identify the 1-2 suspect files.
   - **Step 2 (Symbol & Line Level)**: Inspect class/method signatures (via AST skeleton without function bodies) and isolate the specific function and candidate line range.
   - **Output Format**: Enforces a strict, token-budgeted format:
     ```yaml
     fault_localization:
       file: "src/maintainer_skills/triage.py"
       symbol: "TriageClassifier.classify_issue"
       line_range: [142, 168]
       confidence: "high"
       rationale: "Unchecked KeyError when issue labels list is empty."
     ```
2. **Context-Bounded Slicing Tool (`tools/localize_fault.py`)**:
   - Takes localization output or `--file` and `--range` parameters to extract the minimal AST block or line window with configurable padding (`--padding 20`).
   - Replaces all other file contents with `... [rest of file omitted for brevity] ...` markers.
3. **Downstream Integration**:
   - Integrates with `skills/mkl-reproduce-bug/SKILL.md` and bug investigation agent profiles (`mkl-bug-investigator.toml`). Code repair is disallowed until localization has concluded.

## Implementation Tasks
- [ ] Author `skills/mkl-localize-fault/SKILL.md` defining strict localization protocols, token budgets, and YAML output specifications.
- [ ] Implement `tools/localize_fault.py` using Python `ast` to extract target symbols and line ranges with context padding.
- [ ] Add CLI commands to `tools/localize_fault.py`:
  - `python3 tools/localize_fault.py locate --traceback <file>`
  - `python3 tools/localize_fault.py extract --file <path> --lines <start>-<end> --padding 20`
- [ ] Include worked examples contrasting whole-file context loading (18,000 tokens) with localized slicing (1,200 tokens).
- [ ] Add negative examples warning against skipping localization and jumping directly to full-file editing.
- [ ] Integrate localization requirements into `mkl-bug-investigator.toml` agent profile.
- [ ] Add unit tests in `tests/test_localize_fault.py` validating AST extraction, range clamping, and token boundary enforcement.

## Acceptance Criteria
- Fault localization output is strictly capped at under 300 tokens.
- Context provided to the subsequent repair step is reduced by >= 80% compared to full-file loading.
- `tools/localize_fault.py` runs with zero external dependencies on Python 3.11+.
- The skill passes `python3 tools/kit.py check` without warnings.
- All unit tests pass (`python3 -m unittest discover -s tests -v`).
