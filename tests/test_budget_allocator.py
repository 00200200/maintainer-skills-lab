"""
Unit tests for tools/budget_allocator.py
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from tools.budget_allocator import (
    ContextBudgetGovernor,
    WindowTier,
    main,
)


class TestContextBudgetGovernor(unittest.TestCase):
    def test_model_registry_resolution(self):
        gov_claude = ContextBudgetGovernor(model="claude-3-7-sonnet")
        self.assertEqual(gov_claude.context_window, 200_000)

        gov_gpt = ContextBudgetGovernor(model="gpt-4o")
        self.assertEqual(gov_gpt.context_window, 128_000)

        gov_gemini = ContextBudgetGovernor(model="gemini-1.5-pro")
        self.assertEqual(gov_gemini.context_window, 1_000_000)

        # Unknown model falls back to 128k
        gov_custom = ContextBudgetGovernor(model="some-unknown-model")
        self.assertEqual(gov_custom.context_window, 128_000)

    def test_custom_window_override(self):
        gov = ContextBudgetGovernor(model="gpt-4o", context_window=64_000)
        self.assertEqual(gov.context_window, 64_000)

    def test_tier_transitions(self):
        # 200,000 window
        # < 50% (0 - 99,999) -> NOMINAL
        gov = ContextBudgetGovernor(model="claude-3-7-sonnet", used_tokens=40_000)
        self.assertEqual(gov.tier, WindowTier.NOMINAL)
        self.assertFalse(gov.should_compact())
        self.assertEqual(gov.get_tool_budget("repomap"), 1200)

        # 50% - 74.9% (100,000 - 149,999) -> CONSERVATIVE
        gov = ContextBudgetGovernor(model="claude-3-7-sonnet", used_tokens=100_000)
        self.assertEqual(gov.tier, WindowTier.CONSERVATIVE)
        self.assertFalse(gov.should_compact())
        self.assertEqual(gov.get_tool_budget("repomap"), 600)

        # 75% - 89.9% (150,000 - 179,999) -> CRITICAL
        gov = ContextBudgetGovernor(model="claude-3-7-sonnet", used_tokens=160_000)
        self.assertEqual(gov.tier, WindowTier.CRITICAL)
        self.assertFalse(gov.should_compact())
        self.assertEqual(gov.get_tool_budget("repomap"), 250)
        self.assertEqual(gov.get_tool_budget("log_compressor"), 400)

        # >= 90% (180,000+) -> EMERGENCY
        gov = ContextBudgetGovernor(model="claude-3-7-sonnet", used_tokens=185_000)
        self.assertEqual(gov.tier, WindowTier.EMERGENCY)
        self.assertTrue(gov.should_compact())
        self.assertEqual(gov.get_tool_budget("repomap"), 100)
        self.assertEqual(gov.get_tool_budget("log_compressor"), 150)

    def test_tool_fallback_to_generic(self):
        gov = ContextBudgetGovernor(model="gpt-4o", used_tokens=10_000)
        self.assertEqual(gov.get_tool_budget("nonexistent_custom_tool"), 2500)

    def test_utilization_and_saturation(self):
        gov = ContextBudgetGovernor(model="gpt-4o", context_window=100_000, used_tokens=120_000)
        self.assertEqual(gov.utilization_rate, 1.0)
        self.assertEqual(gov.remaining_tokens, 0)
        self.assertEqual(gov.tier, WindowTier.EMERGENCY)


class TestCLI(unittest.TestCase):
    def test_cli_json_output(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["--model", "claude-3-7-sonnet", "--used-tokens", "160000", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["tier"], "CRITICAL")
        self.assertEqual(data["used_tokens"], 160000)
        self.assertEqual(data["remaining_tokens"], 40000)
        self.assertFalse(data["should_compact"])
        self.assertEqual(data["tool_budgets"]["repomap"], 250)

    def test_cli_pipe_mode(self):
        input_data = json.dumps({"model": "gpt-4o", "used_tokens": 120000, "turn_count": 8})
        stdout = io.StringIO()
        with patch("sys.stdin", io.StringIO(input_data)), patch("sys.stdout", stdout):
            code = main(["--pipe"])
        self.assertEqual(code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["model"], "gpt-4o")
        self.assertEqual(data["tier"], "EMERGENCY")
        self.assertTrue(data["should_compact"])
        self.assertEqual(data["turn_count"], 8)

    def test_cli_human_readable_output(self):
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["--model", "gpt-4o", "--used-tokens", "10000"])
        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("Dynamic Token Budget Allocation", output)
        self.assertIn("NOMINAL", output)


if __name__ == "__main__":
    unittest.main()
