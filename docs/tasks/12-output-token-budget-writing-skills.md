# [Optimization] Output Token Budget Constraints & Stopping Guarantees across Writing Skills

**Labels**: `documentation`, `optimization`, `good first issue`

## Context & Motivation
Maintainer Skills Lab includes 8 writing-focused skills:
- `mkl-humanize`
- `mkl-write-readme`
- `mkl-write-tutorial`
- `mkl-write-ux-copy`
- `mkl-write-launch-post`
- `mkl-write-maintainer-reply`
- `mkl-match-voice`
- `mkl-localize-pl-en`

Currently, several of these skills do not enforce explicit **output length bounds** or early stopping conditions. When prompted, LLMs frequently over-generate (e.g. generating a 2,000-word tutorial when a 400-word quickstart was requested, or producing flowery maintainer replies with duplicate conversational fluff).

This results in:
- Wasted output tokens (which cost 3x-5x more than input tokens on all major API providers).
- Slower generation times (high latency).
- Lower quality answers due to rambling prose.

## Prior Art & Industry Standards
- **Anthropic Engineering Best Practices**: Recommends providing explicit length constraints, negative constraints (what NOT to include), and clear termination criteria in prompt instructions.
- **Concise System Prompts**: High-performing open-source developer prompts enforce word caps and single-topic focus.

## Proposed Solution
Audit and update all 8 writing skills to add:
1. **Explicit Output Token / Word Budgets**:
   - `mkl-write-maintainer-reply`: Max 250 words (~320 tokens).
   - `mkl-write-ux-copy`: Microcopy only; provide exactly 2-3 variations with rationale (< 150 tokens).
   - `mkl-write-readme`: Compact, punchy README template (< 600 words).
   - `mkl-write-launch-post`: Under 350 words, optimized for engagement without fluff.
2. **Negative Constraints**:
   - Explicitly instruct the model to decline preamble ("Sure, I can help you with that!"), postscript summary repeats, and unsolicited explanations.
3. **Stopping Guarantees**:
   - Instruct the model to stop output immediately after the required artifact is delivered.

## Implementation Tasks
- [ ] Audit each writing skill in `skills/` for lack of length constraints.
- [ ] Add explicit output constraints and stopping criteria to `SKILL.md` files.
- [ ] Update worked examples to ensure they demonstrate concise outputs adhering to the budgets.
- [ ] Run `python3 tools/kit.py sync` to propagate changes across all client providers.
- [ ] Run `python3 -m unittest discover -s tests -v` to ensure all tests pass.

## Acceptance Criteria
- All 8 writing skills contain clear, measurable output length constraints.
- Generated client provider files are completely synchronized.
- Zero breaking changes to existing tests.
