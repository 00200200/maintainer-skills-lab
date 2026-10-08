# [Feature] Automated SemVer Version Bumper Skill (mkl-bump-version)

**Labels**: `enhancement`, `new skill`, `good first issue`

## Context & Problem
When preparing a new release in open-source projects, maintainers must analyze all merged commits since the previous Git tag, determine whether changes constitute a `PATCH` (fixes), `MINOR` (features), or `MAJOR` (breaking changes) bump under Semantic Versioning (SemVer 2.0.0), and update version strings across repository configuration files (`pyproject.toml`, `__init__.py`, `package.json`).

Relying on an AI agent to do this by feeding the entire raw `git log` into the LLM context has several major flaws:
1. **Severe Token Waste**: Ingesting dozens or hundreds of commit logs burns 2,000 to 6,000 context tokens on raw git metadata.
2. **Hallucinated Version Arithmetic**: LLMs frequently make arithmetic errors with multi-part SemVer strings (e.g., bumping `0.9.9` to `0.10.0` instead of `0.9.10`, or jumping major versions unnecessarily).
3. **Destructive Configuration Rewrites**: Agents asked to update `version = "1.2.3"` in `pyproject.toml` frequently reformat dependencies, remove comments, or alter unrelated configuration tables.

Conventional Commits (`feat:`, `fix:`, `feat!:`, `BREAKING CHANGE:`) enable **100% deterministic version calculation**. We need a dedicated maintainer skill `mkl-bump-version` paired with a zero-token local helper `tools/bump_version.py` that parses git history locally, computes the exact next SemVer tag, and surgically updates version files with zero token bloat.

## Prior Art & Industry Standards
- **semantic-release & python-semantic-release**: Industry standard automated versioning libraries that calculate SemVer increments from commit history.
- **Commitizen**: CLI tool for conventional commits and automated version bumping.
- **Standard-version**: Utility for version bumping and CHANGELOG generation based on conventional commits.

## Proposed Solution
Create a new skill `skills/mkl-bump-version/SKILL.md` supported by a deterministic Python utility `tools/bump_version.py`.

```bash
# Preview SemVer calculation based on commits since last git tag
python3 tools/bump_version.py --dry-run

# Automatically bump version in pyproject.toml and __init__.py
python3 tools/bump_version.py --apply

# Output structured JSON for release workflows and CI
python3 tools/bump_version.py --json

# Force a specific bump level if manual override is required
python3 tools/bump_version.py --level minor --apply
```

### Deterministic Bumping Workflow

```
┌────────────────────────────────────────────────────────┐
│   Git History: Commit Range (<latest_tag>..HEAD)       │
│    - feat!: drop Python 3.8 support                    │
│    - feat(auth): add OAuth2 provider                   │
│    - fix(parser): handle empty strings                 │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│               tools/bump_version.py                    │
├────────────────────────────────────────────────────────┤
│ 1. Git Tag Discovery: `git describe --tags --abbrev=0` │
│ 2. Conventional Commit Classifier:                     │
│    - Breaking change (BREAKING CHANGE / feat!) -> MAJOR│
│    - New features (feat:)                      -> MINOR│
│    - Fixes & chores (fix:, perf:, refactor:)   -> PATCH│
│ 3. SemVer 2.0 Calculator: v1.4.2 + MINOR = v1.5.0     │
│ 4. Surgical In-Place File Update:                      │
│    - pyproject.toml: version = "1.5.0"                 │
│    - src/__init__.py: __version__ = "1.5.0"            │
└───────────────────────────┬────────────────────────────┘
                            │ (Zero token overhead)
                            ▼
┌────────────────────────────────────────────────────────┐
│               Skill: mkl-bump-version                  │
├────────────────────────────────────────────────────────┤
│ 1. Verifies git diff: only version strings changed     │
│ 2. Confirms package metadata validity                  │
│ 3. Generates release git tag command                   │
└────────────────────────────────────────────────────────┘
```

### JSON Output Schema
```json
{
  "previous_version": "1.4.2",
  "previous_tag": "v1.4.2",
  "next_version": "1.5.0",
  "next_tag": "v1.5.0",
  "bump_type": "minor",
  "summary": {
    "breaking": 0,
    "feat": 3,
    "fix": 5,
    "chore": 4,
    "total_commits": 12
  },
  "files_updated": [
    "pyproject.toml",
    "src/skills_lab/__init__.py"
  ]
}
```

### Skill Instructions (`skills/mkl-bump-version/SKILL.md`)
- Instructs the AI agent to run `tools/bump_version.py --dry-run` to preview the proposed bump.
- Instructs the agent to verify that breaking changes are intentional before executing `--apply`.
- Constrains output to a concise confirmation message and the git command required to create the tag (strictly under 100 output tokens).

## Implementation Tasks
- [ ] Implement `tools/bump_version.py` using standard library `re`, `subprocess`, `argparse`, `pathlib`.
- [ ] Implement robust Git tag resolution with fallback to `0.1.0` if no previous tags exist.
- [ ] Implement Conventional Commit parsing regex supporting scopes and breaking change flags (`feat(api)!:`).
- [ ] Implement file updaters with strict regex targeting only `version = "..."` and `__version__ = "..."` without rewriting whole files.
- [ ] Create `skills/mkl-bump-version/SKILL.md` following Maintainer Skills Lab conventions.
- [ ] Add unit tests in `tests/test_bump_version.py` covering:
  - SemVer increments (`patch`, `minor`, `major`).
  - Pre-release versions (`1.2.0-rc.1`).
  - Dirty working directory detection.
  - Multi-file updates without comment stripping.
- [ ] Register `mkl-bump-version` in `tools/kit.py` and sync client bundles (`.claude/`, `.cursor/`, etc.).

## Acceptance Criteria
- Pure standard library Python 3.11+ (no external dependencies required).
- Accurately classifies conventional commits and calculates correct SemVer transitions.
- `--apply` modifies only the designated version lines, leaving all other lines, comments, and formatting unchanged.
- Skill execution consumes $< 250$ total context tokens when run through maintainer agent interfaces.
- Unit tests pass with `python3 -m unittest discover -s tests -v`.
