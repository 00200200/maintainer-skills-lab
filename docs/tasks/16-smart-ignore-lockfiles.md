# [Optimization] Auto-Exclude Lockfiles & Minified Blobs in Context (`tools/smart_ignore.py`)

**Labels**: `enhancement`, `optimization`, `good first issue`

## Context & Motivation
When agents analyze repositories or inspect pull requests, they frequently scan or read lockfiles (`package-lock.json`, `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `uv.lock`) or generated vendor bundles (`bundle.min.js`, `schema.generated.ts`).

A single `package-lock.json` can be 30,000 lines long (over 100,000 tokens!). If an agent accidentally reads this file during a review or bug investigation, it instantly exhausts the session's context limit or incurs significant API bills without gaining any actionable insights.

## Prior Art & Industry Standards
- **Repomix & Gitingest**: Built-in default ignore lists that strictly filter binary files, lockfiles, maps, and minified bundles from repository context packs.
- **Aider (`.aiderignore`)**: Automatically skips lockfiles and vendor assets when building the symbol tree and search index.

## Proposed Solution
Create `tools/smart_ignore.py` and a shared `.mklignore` pattern definition:
1. **Default Ignore Patterns**:
   - Lockfiles: `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `poetry.lock`, `uv.lock`, `Pipfile.lock`.
   - Minified / Compiled: `*.min.js`, `*.min.css`, `*.map`, `*.pyc`, `*.wasm`, `dist/**`, `build/**`.
   - Large Media / Fixtures: `*.bin`, `*.pt`, `*.onnx`, `*.parquet`, `*.sqlite`.
2. **Context Guard**:
   - Provide a check function `is_ignorable_for_context(path: Path) -> bool` used across tools (`kit.py`, `skill_watch.py`, and installer routines).
   - If an agent workflow attempts to read a lockfile, return a 1-line summary:
     `"[File 'package-lock.json' is 45,000 lines (lockfile). Omitted to preserve token budget. Use 'npm list <package>' to inspect dependencies.]"`

## Implementation Tasks
- [ ] Implement `tools/smart_ignore.py` with standard glob matching.
- [ ] Add `.mklignore` default file to the repository root.
- [ ] Update `skills/mkl-review-pr/SKILL.md` and `skills/mkl-review-dependency/SKILL.md` with explicit instructions on ignoring generated lockfiles.
- [ ] Add unit tests in `tests/test_smart_ignore.py`.

## Acceptance Criteria
- Reading or scanning a directory containing lockfiles and minified assets safely skips them.
- Clear, helpful diagnostic message returned instead of dumping giant JSON files into context.
- Unit tests verify all common ecosystem lockfiles are properly identified.
