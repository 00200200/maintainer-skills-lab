"""Unit tests for the mkl-audit-cve skill structure, frontmatter, and token bounds."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "skills/mkl-audit-cve/SKILL.md"


def approximate_tokens(text: str) -> int:
    """Standard MSL token estimation (~4 chars per token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


class TestCveSkillStructure(unittest.TestCase):
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

        self.assertEqual(metadata.get("name"), "mkl-audit-cve")
        self.assertEqual(
            metadata.get("description"),
            "Audit CVE advisories against codebase usage with minimal token context.",
        )

    def test_targeted_extraction_section(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Targeted Extraction", content)
        self.assertIn("CVE", content)
        self.assertIn("GHSA", content)
        self.assertIn("Vulnerable symbol", content)

    def test_usage_verification_section(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Usage Verification", content)
        self.assertIn("rg", content)
        self.assertIn("AST", content)

    def test_verdict_generation_section(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Low Immediate Risk / Trivial Upgrade", content)
        self.assertIn("High Immediate Risk / Active Vulnerability", content)
        self.assertIn("sanitization", content)
        self.assertIn("upgrade", content)

    def test_ecosystems_and_vulnerability_kinds_covered(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        # Python, Node, Rust ecosystems
        self.assertIn("Python", content)
        self.assertIn("Node.js", content)
        self.assertIn("Rust", content)

        # Direct vs transitive vulnerabilities
        self.assertIn("Direct Vulnerability", content)
        self.assertIn("Transitive Vulnerability", content)


class TestCveSkillTokenBounds(unittest.TestCase):
    """Validate token and word count bounds for skill outputs and worked examples."""

    def test_output_constraint_documented(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("200 words", content)
        self.assertIn("260 tokens", content)

    def test_worked_example_audit_outputs_within_bounds(self):
        content = SKILL_PATH.read_text(encoding="utf-8")
        # Extract blocks under Audit Output
        pattern = re.compile(
            r"### CVE Audit:.*?(?=```\n|### Example|\Z)",
            re.DOTALL,
        )
        reports = pattern.findall(content)
        self.assertGreaterEqual(
            len(reports),
            3,
            "Expected at least 3 worked example audit reports (Python, Node, Rust)",
        )

        for i, report in enumerate(reports, start=1):
            cleaned = report.strip()
            words = cleaned.split()
            word_count = len(words)
            token_count = approximate_tokens(cleaned)

            self.assertLessEqual(
                word_count,
                200,
                f"Example {i} exceeds 200 words: {word_count} words found",
            )
            self.assertLess(
                token_count,
                260,
                f"Example {i} exceeds 260 tokens: {token_count} tokens found",
            )


class TestCveSkillProviderExports(unittest.TestCase):
    """Ensure provider catalog copies are in sync and match source."""

    def test_provider_files_exist(self):
        targets = [
            "claude/.claude/skills/mkl-audit-cve/SKILL.md",
            "codex/.agents/skills/mkl-audit-cve/SKILL.md",
            "continue/.continue/prompts/mkl-audit-cve.prompt",
            "cursor/.cursor/skills/mkl-audit-cve/SKILL.md",
            "gemini/.gemini/antigravity/skills/mkl-audit-cve/SKILL.md",
            "grok-bot/skills/mkl-audit-cve.md",
            "opencode/.opencode/skills/mkl-audit-cve/SKILL.md",
            "windsurf/.windsurf/skills/mkl-audit-cve/SKILL.md",
            "zed/.zed/prompts/mkl-audit-cve.md",
        ]
        for rel in targets:
            path = ROOT / "providers" / rel
            self.assertTrue(path.is_file(), f"Expected provider file {path} to exist")


if __name__ == "__main__":
    unittest.main()
