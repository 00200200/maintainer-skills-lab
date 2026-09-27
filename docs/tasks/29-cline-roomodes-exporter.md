# [Feature] Cline & Roo Code Custom Modes Exporter (`.roomodes`)

**Labels**: `enhancement`, `good first issue`

## Context & Motivation
Cline (formerly Claude Dev) and Roo Code are among the most popular autonomous open-source coding extensions for VS Code. Their killer feature is **Custom Modes (`.roomodes`)**, allowing developers to create tailored sub-agent personas with custom system prompts, tool permissions, and role instructions.

Currently, Maintainer Skills Lab does not export to the `.roomodes` format.

## Prior Art & Industry Standards
- **Roo Code `.roomodes` specification**: A JSON configuration file defining `customModes` with `slug`, `name`, `roleDefinition`, `groups`, and `customInstructions`.

## Proposed Solution
Add a `roo` / `cline` target to `tools/kit.py`:
- Compile Maintainer Skills Lab agent profiles into a valid `.roomodes` JSON file.
- Map skills into clean `customInstructions` without syntax degradation.

## Implementation Tasks
- [ ] Add `cline` / `roomodes` target in `tools/kit.py`.
- [ ] Implement `.roomodes` JSON serialization.
- [ ] Add installation command: `python3 tools/kit.py install --target cline --project <dir>`.
- [ ] Add unit tests in `tests/test_kit.py`.

## Acceptance Criteria
- Running `kit.py sync` or `kit.py install --target cline` produces a valid `.roomodes` JSON file ready for Roo Code / Cline.
- Unit tests verify schema validity.
