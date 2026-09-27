# [Feature] File-Glob Pattern Matching for Conditional Skill Activation

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Currently, skills like `mkl-debug-ml-training` (for PyTorch/Lightning/TF), `mkl-review-dependency`, or `mkl-localize-pl-en` are either installed globally or into every agent profile.

This means that an agent working on a pure Python documentation fix or a TypeScript frontend file has `mkl-debug-ml-training` loaded into its context, wasting prompt tokens on gradient descent tips and PyTorch reproducibility warnings that have zero relevance to the task.

## Prior Art & Industry Standards
- **Cursor Rules (`.cursor/rules/*.mdc`)**: Supports explicit `globs: ["**/*.py", "**/*.ipynb"]` in frontmatter. Cursor only injects the rule into context when the user is editing matching files.
- **VS Code Language-Specific Settings**: Scoped execution based on active file extensions.

## Proposed Solution
Extend `SKILL.md` frontmatter with an optional `globs` field:
```markdown
---
name: "mkl-debug-ml-training"
description: "Diagnose PyTorch, Lightning, and TensorFlow issues instantly."
globs: ["*.py", "*.ipynb", "models/**"]
---
```

### Exporter Behavior
- In `tools/kit.py`, when exporting to Cursor (`.cursor/rules/`) or Windsurf, preserve and generate native glob matching headers.
- For clients without native glob support (Codex, Claude Code), compile a dynamic router mapping that tells the agent:
  `"Only activate this skill when working on files matching: *.py, *.ipynb"`.

## Implementation Tasks
- [ ] Update `skill_metadata()` in `tools/kit.py` to allow an optional `globs` array in YAML frontmatter.
- [ ] Update Cursor exporter to output `.cursor/rules/<name>.mdc` with frontmatter `globs`.
- [ ] Add `globs` to relevant skills (`mkl-debug-ml-training`, `mkl-review-dependency`, etc.).
- [ ] Run `python3 tools/kit.py sync` and ensure all tests in `tests/test_kit.py` pass.

## Acceptance Criteria
- Cursor exporter generates valid MDC rule files with glob filters.
- Skills without `globs` continue to export normally as general skills.
- Zero extra tokens consumed in editor sessions where file extensions do not match.
