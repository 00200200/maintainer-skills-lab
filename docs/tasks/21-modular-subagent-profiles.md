# [Architecture] Role-Specific Subagent Isolation (Modular Agent Profiles)

**Labels**: `architecture`, `optimization`, `help wanted`

## Context & Motivation
Currently, `agents/*.toml` profiles like `mkl-source-reviewer.toml` bundle multiple heavy workflows together (`mkl-review-pr`, `mkl-review-source-change`, `mkl-review-dependency`, etc.). When an agent starts, all of these workflows are loaded at once.

This monolithic structure:
- Bloats system prompts to 4,000+ tokens before any conversation begins.
- Dilutes model attention, causing agents to confuse instructions across different skills.
- Makes it impossible to delegate subtasks to fast, lightweight models (like Claude 3.5 Haiku or Gemini 2.0 Flash) without paying the overhead of the entire bundle.

## Prior Art & Industry Standards
- **Cline / Roo Code Custom Modes (`.roomodes`)**: Splits agents into isolated personas (e.g. Architect, Code, Ask, Test) with targeted, lean system prompts (< 300 tokens each).
- **Claude Code Subagents**: Launches ephemeral sub-agents with dedicated, single-purpose task contexts.

## Proposed Solution
Refactor agent profiles to support **Modular Subagent Delegation**:
1. **Specialized Core Agents**:
   - Split broad agents into focused roles:
     - `mkl-triage-agent`: Triage, labeling, and bug reproduction only (< 500 tokens).
     - `mkl-pr-auditor`: PR code diff review and security checks only (< 600 tokens).
     - `mkl-doc-editor`: Copywriting, humanization, and README editing only (< 400 tokens).
2. **Subagent Handoff Protocol**:
   - Define a standardized JSON handoff format between agents so the primary agent can invoke a specialized subagent and receive back a concise summary artifact instead of accumulating conversational history.

## Implementation Tasks
- [ ] Define modular agent specs in `agents/`.
- [ ] Update `tools/kit.py` agent generation to compile lean subagent configs.
- [ ] Document agent handoff patterns in `AGENTS.md`.
- [ ] Run `python3 tools/kit.py sync` and ensure all tests pass.

## Acceptance Criteria
- Individual subagent profiles consume less than 600 system prompt tokens on startup.
- Multi-skill tasks can be delegated without prompt contamination.
- Clean verification in `tests/test_kit.py`.
