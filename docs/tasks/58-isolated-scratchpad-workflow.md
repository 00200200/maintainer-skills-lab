# [New Skill] Isolated Scratchpad for Reasoning Dump (mkl-isolated-scratchpad)

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Problem
When AI coding agents tackle demanding software maintenance tasks—such as investigating complex race conditions, planning broad refactors, debugging compiler tracebacks, or evaluating multi-step algorithm alternatives—they frequently dump raw exploratory steps directly into the conversation transcript.

This creates severe operational problems:
1. **Context Window Exhaustion**: Intermediate thinking, speculative diffs, and verbose trial command logs quickly consume 15,000 to 50,000 tokens of the main conversational window.
2. **Context Poisoning & Hallucination**: Discarded debugging hypotheses and rejected trial outputs remain visible in conversation history, causing subsequent turns to latch onto invalid assumptions.
3. **Multiplied Inference Costs**: In multi-turn workflows, every subsequent message re-transmits the bloated conversation history back to the model API.

MaintainerSkillsLab needs a structured maintainer skill that teaches agents to redirect voluminous reasoning traces and trial outputs into ephemeral local scratchpad files, returning only clean, synthesized conclusions back to the main conversation.

## Prior Art & Industry Standards
- **Claude Code Scratchpad Pattern**: Utilizes ephemeral scratch files and temporary bash redirection (`> /tmp/scratch.log`), encouraging Claude to inspect specific lines with `grep`/`tail` and return only synthesized takeaways.
- **OpenHands Workspace Scratch**: Dedicated agent scratch files excluded from git commits to store intermediate thoughts and candidate patches.
- **DeepSeek-R1 / OpenAI o1 Context Separation**: Separation of ephemeral chain-of-thought reasoning from conversational state.

## Proposed Solution
Create a new canonical skill `skills/mkl-isolated-scratchpad/SKILL.md`:
- **Name**: `"mkl-isolated-scratchpad"`
- **Description**: `"Offload verbose reasoning, trial commands, and intermediate drafts to ephemeral scratch files to preserve context tokens."`

### Skill Workflow & Guidelines
1. **Designated Ephemeral Scratchpad Directory**:
   - Uses `.msl/scratch/` or `.scratch/` in the project root.
   - Enforce that `.scratch/` and `.msl/scratch/` are listed in `.gitignore` and `tools/smart_ignore.py` so they are never committed or indexed by repomaps.
   - Session file naming: `.msl/scratch/session_<topic>.md`.

2. **Reasoning Dump Protocol**:
   - When generating long plans (> 300 words), detailed architectural breakdowns, or multi-hypothesis matrices, write them to `.msl/scratch/session_<topic>.md`.
   - When executing verbose shell commands (`pytest`, `npm test`, compiler builds), redirect output:
     ```bash
     pytest tests/ > .msl/scratch/test_run.log 2>&1
     ```
   - Never paste 50+ lines of raw command output into the conversation.

3. **Targeted Read / Extraction Protocol**:
   - Use token-bounded tools (`grep`, `tail -n 20`, or `tools/scope_extract.py`) to query specific error lines from the scratchpad rather than re-reading the entire file into conversation memory.

4. **Clean Synthesis Handoff**:
   - Summarize the final conclusion, verified fix, or key decision in under 150 tokens in the conversation.
   - Provide a file reference (`.msl/scratch/session_<topic>.md`) for user inspection if deep audit trails are needed.
   - Clean up scratch files upon task completion or keep them for session handoff.

5. **Worked Examples & Negative Trajectory**:
   - **Negative Trajectory (Anti-pattern)**: Dumping 120 lines of trial test output into chat, burning 3,800 tokens and cluttering context.
   - **Positive Trajectory (Token-efficient)**: Redirecting command output to `.msl/scratch/run.log`, running `grep -E "FAILED|ERROR" .msl/scratch/run.log`, and presenting a 6-line actionable summary, consuming only 180 tokens.

## Implementation Tasks
- [ ] Author canonical skill `skills/mkl-isolated-scratchpad/SKILL.md` following standard frontmatter format.
- [ ] Ensure `.scratch/` and `.msl/scratch/` are added to root `.gitignore` and `tools/smart_ignore.py`.
- [ ] Include detailed positive and negative worked examples comparing raw dump vs. isolated scratchpad token footprints.
- [ ] Add the skill to agent profiles (`mkl-bug-investigator.toml`, `mkl-maintainer-orchestrator.toml`).
- [ ] Run `python3 tools/kit.py sync` to propagate across all client export targets (`.claude/`, `.cursor/`, `.codex/`).
- [ ] Add unit tests in `tests/test_kit.py` validating frontmatter and token count limits (< 800 tokens body, < 60 tokens description).

## Acceptance Criteria
- `skills/mkl-isolated-scratchpad/SKILL.md` passes `python3 tools/kit.py check`.
- Total skill token count remains strictly under 800 tokens; description under 60 tokens.
- All provider exporters compile cleanly with `python3 tools/kit.py sync`.
- Unit tests verify schema compliance and export generation.
