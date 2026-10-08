# [Feature] Multi-Agent Adversarial Code Review Skill (mkl-adversarial-review)

**Labels**: `enhancement`, `new skill`, `help wanted`

## Problem & Context
Standard single-agent code review prompts suffer from sycophancy and superficial "rubber-stamping". Language models routinely praise incoming pull requests, approving PRs with generic "LGTM!" comments while only noting cosmetic formatting quirks, naming preferences, or simple typos. As a result, critical defects—such as concurrent race conditions, unhandled null/None states, resource leaks, off-by-one errors, and silent breaking API changes—slip straight into production branches.

Conversely, unrestricted multi-agent debates often devolve into endless philosophical bike-shedding. Without strict token budgeting and clear stopping rules, agent debates consume 20,000+ tokens arguing subjective design choices without producing actionable findings or reaching consensus.

## Prior Art & Industry Standards
- **LangGraph & AutoGen Debate Patterns**: Structuring reasoning through multi-agent adversarial deliberation where agents embody conflicting personas (e.g., proposer vs. red team challenger).
- **Anthropic Constitutional AI & Red Teaming**: Pitting an evaluator model against an author model to uncover corner cases, security vulnerabilities, and behavioral regressions.
- **Maintainer Rigor & Code Review Best Practices**: Proven human review protocols that require reviewers to actively attempt to construct counterexamples and disproving inputs for critical changes.

## Proposed Solution
Create a new canonical skill `skills/mkl-adversarial-review/SKILL.md` that orchestrates a disciplined, bounded adversarial code review debate between two specialized micro-agents:

```text
               ┌───────────────────────────────┐
               │ Incoming PR Diff & Invariants │
               └───────────────┬───────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
┌───────────────────────┐             ┌───────────────────────┐
│ Author Agent (Defense)│             │ Skeptic Agent (Attack)│
│ "Assume correctness;  │ ◄─────────► │ "Assume bug exists;   │
│  defend trade-offs"   │  3 Rounds   │  prove failure mode"  │
└───────────────────────┘ Max 300 tok └───────────────────────┘
            │                                     │
            └──────────────────┬──────────────────┘
                               │
                               ▼
            ┌─────────────────────────────────────┐
            │ Consensus Synthesis & Action Table  │
            │ - Verified Flaws (with repro proof) │
            │ - Dismissed False Positives         │
            │ - Actionable Blockers vs Suggestions│
            └─────────────────────────────────────┘
```

### Protocol Specifications
1. **Micro-Agent Roles**:
   - **Author (Defense)**: Argues why the patch is sound, explains underlying invariants, highlights performance trade-offs, and defends design intent.
   - **Skeptic (Red Team)**: Actively seeks catastrophic failure modes: race conditions, reentrancy issues, edge-case null dereferences, resource leaks, and backward incompatibility. Must provide a concrete scenario or input sequence for every claimed bug.
2. **Strict Turn and Token Budget**:
   - **Maximum 3 Turns Total**:
     - *Turn 1 (Attack)*: Skeptic presents up to 2 concrete failure scenarios (< 300 tokens).
     - *Turn 2 (Defense/Rebuttal)*: Author demonstrates why the invariant holds or concedes the defect (< 300 tokens).
     - *Turn 3 (Synthesis)*: Joint consensus table categorizing findings (< 300 tokens).
   - **Hard Token Budget**: Under 1,500 total output tokens across the entire debate exchange.
3. **Structured Verdict Artifact**:
   - Compiles findings into an actionable table:
     - **Verified Blockers**: Confirmed defects with clear trigger scenarios and suggested fixes.
     - **Disproved Concerns**: Potential issues reviewed and verified as safe by invariant proofs.
     - **Non-blocking Polish**: Minor style or documentation notes.
4. **Worked Examples**:
   - Include a concrete case demonstrating the discovery of a subtle multithreading race condition (e.g., mutating a shared dict during iteration) that single-agent review overlooked.

## Implementation Tasks
- [ ] Author `skills/mkl-adversarial-review/SKILL.md` following canonical MaintainerSkillsLab format.
- [ ] Define precise persona system prompts for Author and Skeptic roles.
- [ ] Implement strict 3-turn stopping criteria and 300-token-per-turn ceiling.
- [ ] Include worked example showcasing discovery of a concurrency or state synchronization defect.
- [ ] Add negative example illustrating uncontrolled agent banter and token exhaustion.
- [ ] Register `mkl-adversarial-review` in orchestrator profiles (`mkl-maintainer-orchestrator.toml`).
- [ ] Synchronize across client export targets using `python3 tools/kit.py sync`.
- [ ] Add unit tests in `tests/test_kit.py` validating frontmatter and token limit compliance.

## Acceptance Criteria
- Debate exchange is strictly bounded to a maximum of 3 turns and under 1,500 total output tokens.
- Review output delivers a structured verdict table with verified defects and concrete counterexamples.
- Passes validation with `python3 tools/kit.py check`.
- Provider configs are cleanly generated across all supported client targets.
- All unit tests pass.
