# [Feature] Add Windsurf (Codeium Cascade) Rule & Workflow Exporter Target

**Labels**: `enhancement`, `good first issue`

## Context & Motivation
Windsurf (powered by Codeium) has emerged as one of the leading AI-powered developer IDEs with its "Cascade" multi-file editing agent. Windsurf uses `.windsurfrules` files and `.windsurf/` workflow prompts for customizing agent behavior.

Currently, developers using Windsurf must manually copy rules from the Cursor or Claude exports. Providing native Windsurf support expands Maintainer Skills Lab to the Codeium developer community.

## Prior Art & Industry Standards
- **Windsurf Rules Specification**: `.windsurfrules` placed in the project root or `.windsurf/rules/`.
- **Cascade Workflows**: Markdown workflow files guiding multi-turn edits and terminal interactions.

## Proposed Solution
Add `windsurf` as a target in `tools/kit.py`:
```python
TARGETS = {
    ...
    "windsurf": (".windsurf/skills", ".windsurf/agents", ".md"),
}
```
In addition:
- Provide an option to generate a consolidated `.windsurfrules` file combining selected maintainer skills for projects that prefer single-file configuration.

## Implementation Tasks
- [ ] Add `windsurf` to `TARGETS` in `tools/kit.py`.
- [ ] Implement consolidated `.windsurfrules` generation in `tools/kit.py install --target windsurf`.
- [ ] Update `providers/README.md` and `docs/install.md` with Windsurf installation examples.
- [ ] Run `python3 tools/kit.py sync` to generate provider artifacts.
- [ ] Add unit tests in `tests/test_kit.py` for Windsurf target verification.

## Acceptance Criteria
- Running `python3 tools/kit.py install --target windsurf --project /path/to/project` properly sets up `.windsurf/skills` or `.windsurfrules`.
- `python3 tools/kit.py check` passes with all provider exports validated.
- All test suites pass.
