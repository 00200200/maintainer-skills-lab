import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.harness import (
    MODEL_PRICING,
    CostCalculator,
    estimate_tokens,
    evaluate_scenario,
    generate_scorecard,
    get_builtin_scenarios,
    main,
)


class TestCostCalculator(unittest.TestCase):
    def test_pricing_tiers_defined(self):
        for model in ["claude-3-7-sonnet", "gpt-4o", "gemini-2.0-flash", "deepseek-v3"]:
            self.assertIn(model, MODEL_PRICING)
            self.assertIn("input", MODEL_PRICING[model])
            self.assertIn("cached_input", MODEL_PRICING[model])
            self.assertIn("output", MODEL_PRICING[model])

    def test_cost_calculation(self):
        # 1,000,000 input tokens at $3/MTok = $3.00
        # 1,000,000 output tokens at $15/MTok = $15.00
        cost = CostCalculator.calculate_cost("claude-3-7-sonnet", 1_000_000, 1_000_000)
        self.assertEqual(cost, 18.0)

    def test_caching_discount(self):
        # 1,000,000 input tokens with 800,000 cached:
        # uncached 200,000 at $3/MTok = $0.60
        # cached 800,000 at $0.30/MTok = $0.24
        # total = $0.84
        cost = CostCalculator.calculate_cost(
            "claude-3-7-sonnet", 1_000_000, 0, cached_input_tokens=800_000
        )
        self.assertAlmostEqual(cost, 0.84, places=4)

    def test_unknown_model_fallback(self):
        cost = CostCalculator.calculate_cost("unknown-future-model", 1_000, 500)
        self.assertGreater(cost, 0.0)


class TestTokenEstimator(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_positive_tokens(self):
        text = "def hello_world(): return 'Hello, maintainer!'"
        tokens = estimate_tokens(text)
        self.assertGreater(tokens, 5)


class TestScenarioEvaluation(unittest.TestCase):
    def test_evaluate_builtin_scenarios(self):
        scenarios = get_builtin_scenarios()
        self.assertIn("bugfix", scenarios)
        self.assertIn("pr_review", scenarios)
        self.assertIn("cve_audit", scenarios)

        for name, sc in scenarios.items():
            res = evaluate_scenario(sc, "claude-3-7-sonnet")
            self.assertEqual(res.scenario, name)
            self.assertGreater(res.baseline_total_tokens, res.mkl_total_tokens)
            self.assertGreater(res.baseline_cost_usd, res.mkl_cost_usd)
            self.assertGreater(res.token_savings_pct, 0.0)
            self.assertGreater(res.cost_savings_pct, 0.0)
            self.assertGreater(res.cache_hit_ratio_pct, 0.0)

    def test_generate_scorecard(self):
        scenarios = get_builtin_scenarios()
        results = [evaluate_scenario(sc, "claude-3-7-sonnet") for sc in scenarios.values()]
        scorecard = generate_scorecard(results)
        self.assertIn("# 📊 MaintainerSkillsLab Token & Cost Benchmark Report", scorecard)
        self.assertIn("| Scenario | Model |", scorecard)
        self.assertIn("bugfix", scorecard)
        self.assertIn("pr_review", scorecard)
        self.assertIn("cve_audit", scorecard)
        self.assertIn("Aggregate Token Reduction", scorecard)


class TestHarnessCLI(unittest.TestCase):
    def test_cli_offline_default(self):
        code = main(["--offline"])
        self.assertEqual(code, 0)

    def test_cli_single_scenario(self):
        code = main(["--scenario", "bugfix"])
        self.assertEqual(code, 0)

    def test_cli_json_output(self):
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--json", "--scenario", "bugfix"])

        self.assertEqual(code, 0)
        data = json.loads(buffer.getvalue())
        self.assertEqual(data["scenarios_evaluated"], 1)
        self.assertEqual(data["results"][0]["scenario"], "bugfix")

    def test_cli_file_output(self):
        with TemporaryDirectory() as temp_dir:
            out_file = Path(temp_dir) / "report.md"
            code = main(["--output", str(out_file)])
            self.assertEqual(code, 0)
            self.assertTrue(out_file.is_file())
            content = out_file.read_text(encoding="utf-8")
            self.assertIn("MaintainerSkillsLab Token & Cost Benchmark Report", content)


if __name__ == "__main__":
    unittest.main()
