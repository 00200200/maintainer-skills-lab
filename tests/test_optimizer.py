#!/usr/bin/env python3
"""Unit tests for DSPy-style skill prompt and demonstration optimizer."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("optimize_skill", ROOT / "tools/optimize_skill.py")
opt = importlib.util.module_from_spec(spec)
sys.modules["optimize_skill"] = opt
spec.loader.exec_module(opt)


class SkillOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mkl-test-opt-")
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_approximate_tokens(self):
        self.assertEqual(opt.approximate_tokens(""), 1)
        self.assertEqual(opt.approximate_tokens("hello world"), 3)
        self.assertGreater(opt.approximate_tokens("a" * 100), 20)

    def test_extract_and_restore_fences(self):
        text = (
            "Use `in order to` and ```python\n# in order to do something\n``` in order to succeed."
        )
        masked, fences = opt.extract_fences(text)
        self.assertEqual(len(fences), 2)
        self.assertIn("@@TOKEN_FENCE_0@@", masked)
        self.assertIn("@@TOKEN_FENCE_1@@", masked)

        # After filler pruning, text outside fences should change, but inside fences must be preserved
        pruned_masked = opt.prune_fillers(masked)
        restored = opt.restore_fences(pruned_masked, fences)
        self.assertIn("Use `in order to`", restored)
        self.assertIn("# in order to do something", restored)
        self.assertIn("to succeed.", restored)

    def test_parse_and_reconstruct_skill_sections(self):
        raw = """---
name: "test-skill"
description: "A test skill description."
---

# Title of Skill

Some introductory context.

## Instructions

1. Step one.
2. Step two.

## Worked example

Here is an example.
"""
        fm, preamble, sections = opt.parse_skill_sections(raw)
        self.assertIn('name: "test-skill"', fm)
        self.assertIn("# Title of Skill", preamble)
        self.assertIn("## Instructions", sections)
        self.assertIn("## Worked example", sections)

        reconstructed = opt.reconstruct_skill(fm, preamble, sections)
        self.assertEqual(reconstructed.strip(), raw.strip())

    def test_prune_fillers_and_cliches(self):
        text = (
            "Please note that in order to take into consideration all inputs, "
            "it is important to remember that we utilize proper tools due to the fact that we must succeed."
        )
        pruned = opt.prune_cliches(text)
        pruned = opt.prune_fillers(pruned)

        self.assertNotIn("Please note that", pruned)
        self.assertNotIn("in order to", pruned)
        self.assertNotIn("take into consideration", pruned)
        self.assertNotIn("utilize", pruned)
        self.assertNotIn("due to the fact that", pruned)
        self.assertIn("to consider", pruned)
        self.assertIn("use proper tools", pruned)
        self.assertIn("because we must succeed", pruned)

    def test_compact_worked_example(self):
        example_text = """Here is a worked example demonstrating the workflow:

Input: `foo`
Output: `bar`

The following example illustrates this:
```python
assert True
```
"""
        compacted = opt.compact_worked_example(example_text)
        self.assertNotIn("Here is a worked example demonstrating the workflow:", compacted)
        self.assertNotIn("The following example illustrates this:", compacted)
        self.assertIn("Input: `foo`", compacted)
        self.assertIn("Output: `bar`", compacted)
        self.assertIn("assert True", compacted)

    def test_optimizer_achieves_target_reduction_with_passing_validation(self):
        # Create a verbose sample skill
        sample_skill = self.dir_path / "SKILL.md"
        sample_skill.write_text(
            """---
name: "sample-skill"
description: "A sample skill."
---

# Sample Task

Please note that in order to take into consideration the repository state,
make sure that you utilize the recommended tools due to the fact that they are efficient.
Keep in mind that subsequent to running tests, prior to committing changes, you must verify the diff.

## Worked example

Here is a worked example demonstrating the workflow:

```bash
git diff --staged
```

Acceptance: The diff must contain no unmanaged changes.
""",
            encoding="utf-8",
        )

        # Validator checks that "git diff --staged" is preserved and markdown is valid
        def custom_validator(path: Path, content: str) -> opt.ValidationResult:
            if "git diff --staged" not in content:
                return opt.ValidationResult(passed=False, score=0.0, details="Missing command")
            if "Acceptance:" not in content:
                return opt.ValidationResult(passed=False, score=0.0, details="Missing acceptance")
            return opt.ValidationResult(passed=True, score=1.0)

        result = opt.optimize_skill(
            skill_file=sample_skill,
            target_reduction=0.10,
            validator=custom_validator,
        )

        self.assertTrue(result.validation_passed)
        self.assertGreater(result.tokens_saved, 0)
        self.assertGreaterEqual(result.reduction_ratio, 0.10)
        self.assertTrue(result.target_achieved)
        self.assertIn("prune_fillers", result.transformations_applied)
        self.assertIn("git diff --staged", result.optimized_content)
        self.assertTrue(len(result.diff) > 0)

    def test_optimizer_reverts_candidate_on_validation_failure(self):
        sample_skill = self.dir_path / "SKILL.md"
        sample_skill.write_text(
            """---
name: "sample-failing"
description: "A skill whose tests fail on optimization."
---

# Title

In order to test rollback.
""",
            encoding="utf-8",
        )

        # Validator passes only on the exact initial text
        initial_text = sample_skill.read_text(encoding="utf-8")

        def strict_validator(path: Path, content: str) -> opt.ValidationResult:
            if content == initial_text:
                return opt.ValidationResult(passed=True, score=1.0)
            return opt.ValidationResult(passed=False, score=0.0, details="Strict test failed")

        result = opt.optimize_skill(
            skill_file=sample_skill,
            target_reduction=0.15,
            validator=strict_validator,
        )

        self.assertTrue(result.validation_passed)
        self.assertEqual(result.tokens_saved, 0)
        self.assertEqual(result.reduction_ratio, 0.0)
        self.assertFalse(result.target_achieved)
        self.assertEqual(result.transformations_applied, [])
        self.assertEqual(result.optimized_content, initial_text)

    def test_cli_json_and_diff_output(self):
        sample_skill = self.dir_path / "SKILL.md"
        sample_skill.write_text(
            """---
name: "cli-test"
description: "Testing CLI output."
---

# CLI Test

In order to test the CLI output with due to the fact that it is JSON.
""",
            encoding="utf-8",
        )

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = opt.main(
                [
                    "--skill",
                    str(sample_skill),
                    "--output-diff",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        output_data = json.loads(buf.getvalue())
        self.assertEqual(output_data["skill_name"], "cli-test")
        self.assertTrue(output_data["validation_passed"])
        self.assertIn("diff", output_data)

    def test_cli_apply_flag_writes_file(self):
        sample_skill = self.dir_path / "SKILL.md"
        original = (
            '---\nname: "apply-test"\ndescription: "desc"\n---\n\n'
            "# Apply Test\n\nPlease note that in order to test apply."
        )
        sample_skill.write_text(original, encoding="utf-8")

        code = opt.main(
            [
                "--skill",
                str(sample_skill),
                "--apply",
            ]
        )
        self.assertEqual(code, 0)
        new_content = sample_skill.read_text(encoding="utf-8")
        self.assertNotEqual(new_content, original)
        self.assertNotIn("Please note that", new_content)
        self.assertNotIn("in order to", new_content)


if __name__ == "__main__":
    unittest.main()
