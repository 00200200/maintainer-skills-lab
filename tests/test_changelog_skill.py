"""Unit tests for the mkl-generate-changelog skill structure, frontmatter, and token bounds."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills/mkl-generate-changelog/SKILL.md"


def approximate_tokens(text: str) -> int:
    """Standard MSL token estimation (~4 chars per token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


class TestChangelogSkillStructure(unittest.TestCase):
    """Validate skill file structure, frontmatter format, and content requirements."""

    def test_skill_file_exists(self):
        self.assertTrue(SKILL_PATH.is_file(), f"Missing skill file at {SKILL_PATH}")

    def test_frontmatter_specification(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        lines = content.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertIn("---", lines[1:])
        end_idx = lines.index("---", 1)

        metadata = {}
        for line in lines[1:end_idx]:
            key, sep, val = line.partition(":")
            self.assertTrue(sep, f"Invalid frontmatter line: {line}")
            metadata[key.strip()] = json.loads(val.strip())

        self.assertEqual(metadata.get("name"), "mkl-generate-changelog")
        self.assertEqual(
            metadata.get("description"),
            "Generate grouped, token-compact changelogs and release notes from git log.",
        )

    def test_log_extraction_section(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Log Extraction", content)
        self.assertIn("git log", content)
        self.assertIn("--oneline", content)

    def test_grouping_and_deduplication(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Breaking Changes", content)
        self.assertIn("Features", content)
        self.assertIn("Bug Fixes", content)
        self.assertIn("Maintenance", content)
        self.assertIn("Squash", content)

    def test_negative_formatting_constraints(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("No full SHAs", content)
        self.assertIn("400 words", content)
        self.assertIn("500 tokens", content)


class TestChangelogSkillTokenBounds(unittest.TestCase):
    """Validate that example outputs and word limits remain strictly bounded."""

    def test_skill_instructions_compact(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        word_count = len(content.split())
        self.assertLess(
            word_count,
            600,
            f"Skill instructions too verbose ({word_count} words; must stay under 600 words)",
        )

    def test_sample_output_token_bounds(self):
        sample_output = """## Release Notes (v1.3.0)

### ⚠️ Breaking Changes
- Remove deprecated `/v1/auth` legacy authentication endpoint (`#104`). Use `/v2/auth` with PKCE instead.

### 🚀 Features
- Add OAuth2 PKCE authorization flow (`#101`).
- Add `--json` structured output flag to `inspect` CLI command (`#103`).

### 🐛 Bug Fixes
- Fix token refresh loop handling on expiration and prevent null reference on missing tokens (`#102`).

### 🛠️ Maintenance
- Bump developer dependencies (`ruff`, `pytest`).
"""
        words = len(sample_output.split())
        tokens = approximate_tokens(sample_output)
        self.assertLessEqual(words, 400, f"Exceeded word budget ({words} words > 400)")
        self.assertLessEqual(tokens, 500, f"Exceeded token budget ({tokens} tokens > 500)")


class TestChangelogSkillProviderExports(unittest.TestCase):
    """Verify that kit.py synchronized the changelog skill across all provider targets."""

    def test_provider_files_exist(self):
        expected_paths = [
            ROOT / "providers/claude/.claude/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/codex/.agents/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/cursor/.cursor/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/gemini/.gemini/antigravity/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/opencode/.opencode/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/windsurf/.windsurf/skills/mkl-generate-changelog/SKILL.md",
            ROOT / "providers/continue/.continue/prompts/mkl-generate-changelog.prompt",
            ROOT / "providers/zed/.zed/prompts/mkl-generate-changelog.md",
            ROOT / "providers/grok-bot/skills/mkl-generate-changelog.md",
        ]
        for path in expected_paths:
            self.assertTrue(path.is_file(), f"Missing synchronized provider export at {path}")
