# [Feature] Three-Way Minimal Git Conflict Solver Skill (`mkl-resolve-merge-conflict`)

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Motivation
Merge conflicts are one of the most frequent and tedious chores maintainers face when managing active open-source repositories. When developers ask an LLM to resolve a merge conflict, naive agents often ask for or read entire conflicting files (thousands of lines), frequently dropping comments, introducing subtle regressions, or hallucinating changes outside the conflict zone.

## Prior Art & Industry Standards
- **Aider Merge Conflict Resolver**: Isolates conflict blocks (`<<<<<<<`, `=======`, `>>>>>>>`), extracts the common ancestor (base), current branch (ours), and incoming branch (theirs), and prompts the LLM only on the conflicting hunk with minimal enclosing function scope.
- **Git `git mergetool` standard 3-way diff format**.

## Proposed Solution
Create a new canonical skill `skills/mkl-resolve-merge-conflict/SKILL.md`:
- **Name**: `"mkl-resolve-merge-conflict"`
- **Description**: `"Resolve git merge conflicts cleanly by analyzing only 3-way conflict hunks."`

### Workflow Specification
1. **Conflict Scanning**:
   - Run `git diff --name-only --diff-filter=U` to identify unmerged paths.
2. **Hunk Isolation**:
   - Extract only the conflict markers (`<<<<<<< HEAD`, `=======`, `>>>>>>> <branch>`) plus 5 lines of surrounding context.
   - Refuse to rewrite or touch code outside the conflict boundaries.
3. **Intent Preservation**:
   - Compare incoming changes against local changes; prioritize non-breaking integration.
4. **Verification**:
   - Immediately run the project test suite (`pytest`, `cargo test`, etc.) to verify syntax and functionality before committing.

## Implementation Tasks
- [ ] Author `skills/mkl-resolve-merge-conflict/SKILL.md` with worked example and failure scenario.
- [ ] Add conflict extraction instructions using standard git commands.
- [ ] Run `python3 tools/kit.py sync` to propagate across all client targets.
- [ ] Add unit tests in `tests/test_kit.py` validating frontmatter and sync.

## Acceptance Criteria
- Skill guides agents to resolve merge conflicts touching strictly the conflict hunk (< 150 tokens context per conflict).
- Includes validation steps ensuring tests pass before resolving `git add`.
