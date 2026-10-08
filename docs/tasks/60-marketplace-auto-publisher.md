# [Automation] Automated Marketplace Sync for Claude Code and Cursor (tools/publish_marketplace.py)

**Labels**: `enhancement`, `automation`, `good first issue`

## Context & Problem
MaintainerSkillsLab generates synchronized skill and agent exports across multiple IDE targets via `kit.py sync` (e.g. `.claude/`, `.cursor/`, `.codex/`). However, distributing these skills to developer communities requires packaging and releasing them into external registries and marketplaces:
1. **Claude Code Plugin / MCP Registries**: Requires compliant plugin manifests (`manifest.json`), standardized package layouts, versioned tarballs/zips, and checksum verification.
2. **Cursor Directory / Rules Registries**: Requires `.cursorrules` or `.cursor/rules/*.mdc` bundles with valid frontmatter, tags, and category metadata.

Currently, packaging release bundles is a manual, error-prone task. Maintainers must manually zip export directories, verify version consistency against `pyproject.toml`, check SHA-256 sums, and draft release notes. This manual overhead slows down releases and risks publishing out-of-sync bundles.

## Prior Art & Industry Standards
- **VS Code Extension Manager (`vsce`)**: Standard CLI tool for packaging, validating manifests, and publishing VS Code extensions to the Visual Studio Marketplace.
- **GitHub Marketplace Publisher**: Automates action metadata validation and tagging for GitHub Marketplace listings.
- **Homebrew Core & Cargo Publish**: Automated formula/crate validation and deterministic tarball publishing.

## Proposed Solution
Create `tools/publish_marketplace.py`, a zero-dependency CLI tool and GitHub Actions release workflow that validates marketplace schemas, generates byte-reproducible distribution bundles, and publishes release artifacts.

```bash
# Validate marketplace readiness (manifests, licenses, descriptions, token budgets)
python3 tools/publish_marketplace.py validate

# Build standalone zip bundles for Claude Code and Cursor in dist/
python3 tools/publish_marketplace.py build --version 0.4.0

# Output release changelog and SHA-256 checksums
python3 tools/publish_marketplace.py release-notes --output dist/RELEASE.md

# Publish / sync to target marketplaces (with dry-run option)
python3 tools/publish_marketplace.py publish --target claude --target cursor --dry-run
```

### Key Components
1. **Marketplace Validator**:
   - Validates that every skill description stays under 60 tokens and body under 800 tokens.
   - Ensures required metadata fields (`name`, `version`, `author`, `license`, `repository`) exist and match across `pyproject.toml` and exporter manifests.
   - Verifies all skill references in agent profiles exist and compile without broken links.

2. **Deterministic Packager**:
   - Generates reproducible `.zip` and `.tar.gz` distribution archives inside `dist/`:
     - `maintainer-skills-lab-claude-v<version>.zip`
     - `maintainer-skills-lab-cursor-v<version>.zip`
   - Normalizes file modification timestamps and file permissions in archives to guarantee identical SHA-256 hashes across identical builds.
   - Computes `dist/checksums.txt` (SHA-256).

3. **Release Notes Generator**:
   - Scans commits or PRs since the previous git tag.
   - Summarizes newly added skills, updated agents, and token optimization metrics.

4. **GitHub Actions Automation**:
   - `.github/workflows/release_marketplace.yml`:
     - Triggers on git tag pushes (`v*.*.*`).
     - Runs validator and build steps.
     - Attaches zipped bundles and `checksums.txt` to the GitHub Release.

## Implementation Tasks
- [ ] Implement `tools/publish_marketplace.py` with `validate`, `build`, and `publish` subcommands.
- [ ] Implement manifest validation for Claude Code plugin specifications and Cursor directory formats.
- [ ] Implement deterministic archive generation using standard library `zipfile` and `tarfile`.
- [ ] Implement SHA-256 checksum calculation and `dist/checksums.txt` generation.
- [ ] Implement release notes generator extracting changes since latest git tag.
- [ ] Create GitHub Actions workflow `.github/workflows/release_marketplace.yml`.
- [ ] Add unit tests in `tests/test_publish_marketplace.py` testing validation errors, deterministic zip generation, and checksum verification.
- [ ] Document publishing procedures in `docs/publishing.md`.

## Acceptance Criteria
- Running `python3 tools/publish_marketplace.py validate` verifies all target exports and exits with code 0 on valid bundles.
- `python3 tools/publish_marketplace.py build --version 0.4.0` creates valid distribution zip archives and checksums in `dist/`.
- Pure Python 3.11+ standard library implementation (no third-party dependencies required).
- Unit tests achieve 100% pass rate in `tests/test_publish_marketplace.py`.
