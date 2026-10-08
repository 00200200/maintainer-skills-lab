# [Architecture] Architect & Editor Two-Model Pipeline (mkl-architect-editor)

**Labels**: `architecture`, `optimization`, `help wanted`

## Problem & Context
In modern agentic development workflows, using top-tier frontier reasoning models (e.g., Claude 3.7 Sonnet, OpenAI o3-mini / o1) for entire conversational turns causes severe token cost inflation and latency bottlenecks. When an agent performs code repair or refactoring, 70% to 80% of the generated output tokens consist of routine source code reproduction, mechanical syntax edits, and boilerplate formatting.

Frontier models command high output token pricing ($12 to $15 per million tokens). Spending high-priced reasoning tokens to mechanically emit unified diffs, search/replace blocks, or unchanged function bodies is economically inefficient. Furthermore, large reasoning models can overthink routine formatting or hallucinate unrelated edits when tasked with rewriting large code chunks under conversational fatigue.

## Prior Art & Industry Standards
- **Aider Architect & Editor Pattern**: Aider demonstrated that decoupling reasoning from mechanical code editing cuts API costs by 70%+ while improving code quality. In Aider's setup:
  - An expensive reasoning model (the **Architect**, e.g., Claude 3.7 Sonnet, o1) analyzes repository context, designs the architectural solution, and outputs a concise high-level specification or pseudo-patch.
  - A fast, low-cost model (the **Editor**, e.g., Claude 3.5 Haiku, GPT-4o-mini) receives the Architect's instructions and the original target file to produce byte-accurate unified diffs or search/replace blocks.
- **OpenHands & SWE-agent Dual-Model Decomposition**: Separates high-level planning from low-level command and patch execution.
- **Anthropic Cost Optimization Recipes**: Recommends routing sub-tasks to smaller models like Claude 3.5 Haiku for deterministic translation and editing tasks.

## Proposed Solution
Introduce a two-model pipeline and canonical skill `skills/mkl-architect-editor/SKILL.md` along with orchestration support in `MaintainerSkillsLab`:

```text
[User Request / Bug Report]
            │
            ▼
┌────────────────────────────────────────┐
│  Architect Model (Claude 3.7 / o3)     │
│  - Repomap & AST scope inspection      │
│  - Deep reasoning & edge-case analysis │
│  - Emits concise Change Specification  │ (< 400 tokens)
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Editor Model (Haiku / GPT-4o-mini)    │
│  - Receives Target Files + Change Spec │
│  - Emits exact Search/Replace blocks   │ (Mechanical Diff)
└──────────────────┬─────────────────────┘
                   │
                   ▼
[Syntax Validation & Verification Hook]
```

### Pipeline Architecture Details
1. **Architect Stage**:
   - Consumes problem description, error traceback, and scoped AST extracts.
   - Prohibits full-file generation.
   - Emits an `ArchitectHandoff` schema:
     - `target_files`: List of files to modify.
     - `invariant_summary`: Core behavioral guarantees to preserve.
     - `change_spec`: Line-targeted pseudo-diff or exact before/after intent.
2. **Editor Stage**:
   - Configured with strict search-and-replace prompting.
   - Ingests only the targeted file slices and the Architect's change specification.
   - Employs fast, inexpensive models (`claude-3-5-haiku`, `gpt-4o-mini`).
3. **Automated Validation & Fallback**:
   - Verifies patch applicability and runs syntax checking (`python3 -m py_compile`).
   - If the patch fails to apply cleanly, retries with the Editor model (up to 2 attempts) with error feedback.
   - Only escalates back to the Architect if the underlying semantic logic fails automated tests.

## Implementation Tasks
- [ ] Create canonical skill `skills/mkl-architect-editor/SKILL.md` defining dual-model roles, prompt contracts, and handoff boundaries.
- [ ] Implement `tools/architect_editor.py` providing the CLI runner and two-model invocation harness.
- [ ] Define structured serialization format (`ArchitectHandoff`) for zero-loss handoff between Architect and Editor.
- [ ] Integrate dual-model configuration into `tools/kit.py` exporter (allowing users to configure distinct `--architect` and `--editor` model endpoints).
- [ ] Add evaluation benchmark in `evals/harness.py` measuring token cost reduction and patch application accuracy against single-model baselines.
- [ ] Add unit tests in `tests/test_architect_editor.py` covering handoff serialization, patch application, and error retry logic.
- [ ] Update documentation in `docs/` detailing two-tier model orchestration.

## Acceptance Criteria
- Token costs for code editing turns decrease by >= 65% compared to running the frontier reasoning model alone.
- Patch application success rate on first attempt is >= 88% using `claude-3-5-haiku` or `gpt-4o-mini` as Editor.
- The skill passes `python3 tools/kit.py check` with zero warnings.
- Unit tests verify graceful retry handling when candidate edits contain syntax or patch alignment errors.
