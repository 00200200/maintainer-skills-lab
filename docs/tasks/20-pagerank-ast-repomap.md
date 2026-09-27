# [Feature] PageRank AST-Based Symbol Map for Skill Workflows (`tools/repomap.py`)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
When an AI agent starts a complex maintainer task (e.g. `mkl-review-pr`, `mkl-triage-issue`, or `mkl-reproduce-bug`), it lacks awareness of how project files and classes connect. Without a high-level map, the agent either reads dozens of random files (blowing through 30,000+ tokens) or works blind and introduces breaking architectural changes.

## Prior Art & Industry Standards
- **Aider (`repomap.py`)**: Considered state-of-the-art in code context engineering. Aider parses all source files with Tree-sitter or AST, builds a call/reference graph, runs PageRank to determine the most central symbols (classes, functions), and formats a concise (< 1,024 tokens) ASCII map of the repository.
- **Sourcegraph Cody**: Global code graph indexing.

## Proposed Solution
Build `tools/repomap.py` to generate a compact, token-bounded repository symbol map:
```bash
python3 tools/repomap.py --project . --max-tokens 800
```

### Architecture
1. **AST Parser**:
   - Parses Python files in the repository using standard library `ast`.
   - Identifies definitions (`class`, `def`) and references (calls, imports).
2. **Graph Ranking**:
   - Builds an internal graph of dependencies.
   - Computes rank scores (PageRank or in-degree centrality) to prioritize core domain abstractions over utility scripts.
3. **Budgeted Formatting**:
   - Emits an indented tree of filenames and their top-ranked symbols.
   - Enforces a strict token budget (default 800 tokens).

## Implementation Tasks
- [ ] Implement `tools/repomap.py` using Python standard library `ast`.
- [ ] Add PageRank ranking algorithm for symbol centrality.
- [ ] Add CLI flags: `--max-tokens`, `--project`, `--json`.
- [ ] Integrate symbol map generation into `skills/mkl-review-pr/SKILL.md` for evaluating architecture-wide PRs.
- [ ] Add unit tests in `tests/test_repomap.py`.

## Acceptance Criteria
- Running `repomap.py` on `MaintainerSkillsLab` generates a structured repository map under 800 tokens showing core classes and functions.
- Pure Python 3.11+ (no external dependencies required).
- Unit tests verify graph building and ranking logic.
