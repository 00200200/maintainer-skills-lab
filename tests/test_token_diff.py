from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.token_diff import (
    approximate_tokens,
    compare_skill_tokens,
    get_filesystem_skill_tokens,
    main,
    render_markdown_report,
)


class ApproximateTokensTests(unittest.TestCase):
    def test_empty_string(self) -> None:
        self.assertEqual(approximate_tokens(""), 0)

    def test_short_string(self) -> None:
        self.assertEqual(approximate_tokens("test"), 1)
        self.assertEqual(approximate_tokens("hello world"), 3)

    def test_longer_string(self) -> None:
        text = "a" * 400
        self.assertEqual(approximate_tokens(text), 100)


class CompareSkillTokensTests(unittest.TestCase):
    def test_unchanged_skills(self) -> None:
        base = {"skill-a": 1000, "skill-b": 2000}
        head = {"skill-a": 1000, "skill-b": 2000}
        res = compare_skill_tokens(base, head)
        self.assertTrue(res.passed)
        self.assertEqual(res.total_delta, 0)
        self.assertEqual(res.total_pct_change, 0.0)
        self.assertEqual(len(res.skill_violations), 0)
        self.assertIsNone(res.total_violation)

    def test_single_skill_within_threshold(self) -> None:
        base = {"skill-a": 1000, "skill-b": 10000}
        head = {"skill-a": 1100, "skill-b": 10000}  # +10% on skill-a, but total is +0.9% (< 5%)
        res = compare_skill_tokens(base, head)
        self.assertTrue(res.passed)
        self.assertEqual(len(res.skill_violations), 0)
        self.assertIsNone(res.total_violation)

    def test_single_skill_exceeds_threshold(self) -> None:
        base = {"skill-a": 1000}
        head = {"skill-a": 1200}  # +20% (over 15% threshold)
        res = compare_skill_tokens(base, head)
        self.assertFalse(res.passed)
        self.assertEqual(len(res.skill_violations), 1)
        self.assertIn("skill-a", res.skill_violations[0])
        self.assertTrue(res.skills[0].regressed)

    def test_single_skill_override_approved(self) -> None:
        base = {"skill-a": 1000}
        head = {"skill-a": 1200}  # +20%
        res = compare_skill_tokens(base, head, approved=True)
        self.assertTrue(res.passed)
        self.assertTrue(res.approved)
        self.assertEqual(len(res.skill_violations), 1)

    def test_total_creep_without_new_skill(self) -> None:
        # Four skills each increase by 8% (below 15% individual threshold),
        # but total increases by 8% (>5% total threshold) with no new skill added.
        base = {"s1": 1000, "s2": 1000, "s3": 1000, "s4": 1000}
        head = {"s1": 1080, "s2": 1080, "s3": 1080, "s4": 1080}
        res = compare_skill_tokens(base, head)
        self.assertFalse(res.passed)
        self.assertEqual(len(res.skill_violations), 0)  # No individual skill violated 15%
        self.assertIsNotNone(res.total_violation)
        self.assertIn("Total library tokens increased by +8.0%", res.total_violation or "")

    def test_new_skill_exempts_total_threshold(self) -> None:
        base = {"s1": 1000}
        head = {"s1": 1000, "s2": 500}  # New skill added, total +50%
        res = compare_skill_tokens(base, head)
        self.assertTrue(res.passed)
        self.assertIsNone(res.total_violation)
        self.assertEqual(res.new_skills_count, 1)

    def test_removed_skill(self) -> None:
        base = {"s1": 1000, "s2": 500}
        head = {"s1": 1000}
        res = compare_skill_tokens(base, head)
        self.assertTrue(res.passed)
        self.assertEqual(res.total_delta, -500)
        s2 = next(s for s in res.skills if s.name == "s2")
        self.assertTrue(s2.is_removed)
        self.assertEqual(s2.pct_change, -100.0)


class FilesystemAndReportTests(unittest.TestCase):
    def test_filesystem_tokens_and_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill1 = root / "skills" / "my-skill"
            skill1.mkdir(parents=True)
            (skill1 / "SKILL.md").write_text("# My Skill\n" + "word " * 100, encoding="utf-8")

            counts = get_filesystem_skill_tokens(root)
            self.assertIn("my-skill", counts)
            self.assertGreater(counts["my-skill"], 50)

            # Compare against modified head
            head_counts = {"my-skill": counts["my-skill"] + 500}
            res = compare_skill_tokens(counts, head_counts)
            md = render_markdown_report(res)

            self.assertIn("## 📊 Token Footprint Regression Report", md)
            self.assertIn("`my-skill`", md)
            self.assertIn("Total Library", md)
            self.assertIn("Token Regressions Detected", md)

    def test_cli_main_exit_codes_and_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_dir = root / "base"
            head_ok_dir = root / "head_ok"
            head_bad_dir = root / "head_bad"

            for d in (base_dir, head_ok_dir, head_bad_dir):
                (d / "skills" / "skill-test").mkdir(parents=True)

            (base_dir / "skills" / "skill-test" / "SKILL.md").write_text(
                "Initial content " * 100, encoding="utf-8"
            )
            (head_ok_dir / "skills" / "skill-test" / "SKILL.md").write_text(
                "Initial content " * 100, encoding="utf-8"
            )
            # Drastic increase (>15%)
            (head_bad_dir / "skills" / "skill-test" / "SKILL.md").write_text(
                "Initial content " * 300, encoding="utf-8"
            )

            comment_file = root / "comment.md"
            json_file = root / "report.json"

            # 1. OK run should exit 0
            code = main(
                [
                    "--base",
                    str(base_dir),
                    "--head",
                    str(head_ok_dir),
                    "--output-comment",
                    str(comment_file),
                    "--output-json",
                    str(json_file),
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(comment_file.exists())
            self.assertTrue(json_file.exists())
            data = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertTrue(data["passed"])

            # 2. Bad run without approval should exit 1
            code_bad = main(
                [
                    "--base",
                    str(base_dir),
                    "--head",
                    str(head_bad_dir),
                    "--output-json",
                    str(json_file),
                ]
            )
            self.assertEqual(code_bad, 1)
            data_bad = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertFalse(data_bad["passed"])

            # 3. Bad run with approval should exit 0
            code_approved = main(
                [
                    "--base",
                    str(base_dir),
                    "--head",
                    str(head_bad_dir),
                    "--approved",
                    "--output-json",
                    str(json_file),
                ]
            )
            self.assertEqual(code_approved, 0)
            data_app = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertTrue(data_app["passed"])
            self.assertTrue(data_app["approved"])


if __name__ == "__main__":
    unittest.main()
