#!/usr/bin/env python3
"""
Dynamic Token Budget Allocator for Long Sessions (tools/budget_allocator.py)

Tracks session token consumption and dynamically allocates token budgets
across tools and skills to prevent context window saturation and emergency truncation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional


MODEL_REGISTRY: Dict[str, int] = {
    # Anthropic Claude
    "claude-3-7-sonnet": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
    # Google Gemini
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    # DeepSeek
    "deepseek-v3": 128_000,
    "deepseek-r1": 128_000,
    # Open Source & Local
    "llama-3.1-70b": 128_000,
    "llama-3.3-70b": 128_000,
    "qwen-2.5-coder": 128_000,
}

DEFAULT_FALLBACK_WINDOW = 128_000


class WindowTier(str, Enum):
    NOMINAL = "NOMINAL"            # < 50%
    CONSERVATIVE = "CONSERVATIVE"  # 50% - 75%
    CRITICAL = "CRITICAL"          # 75% - 90%
    EMERGENCY = "EMERGENCY"        # > 90%


# Tool limits by tier (in tokens)
TIER_TOOL_BUDGETS: Dict[WindowTier, Dict[str, int]] = {
    WindowTier.NOMINAL: {
        "generic_tool": 2500,
        "repomap": 1200,
        "log_compressor": 2500,
        "scope_extract": 2000,
        "patch_applier": 2000,
        "symbol_search": 1500,
    },
    WindowTier.CONSERVATIVE: {
        "generic_tool": 1000,
        "repomap": 600,
        "log_compressor": 1000,
        "scope_extract": 800,
        "patch_applier": 1000,
        "symbol_search": 800,
    },
    WindowTier.CRITICAL: {
        "generic_tool": 400,
        "repomap": 250,
        "log_compressor": 400,
        "scope_extract": 300,
        "patch_applier": 500,
        "symbol_search": 300,
    },
    WindowTier.EMERGENCY: {
        "generic_tool": 150,
        "repomap": 100,
        "log_compressor": 150,
        "scope_extract": 100,
        "patch_applier": 200,
        "symbol_search": 100,
    },
}


@dataclass
class AllocationReport:
    model: str
    context_window: int
    used_tokens: int
    remaining_tokens: int
    utilization_rate: float
    tier: str
    tool_budgets: Dict[str, int]
    should_compact: bool
    turn_count: Optional[int] = None
    recommendations: Optional[list[str]] = None


class ContextBudgetGovernor:
    def __init__(
        self,
        model: str = "claude-3-7-sonnet",
        used_tokens: int = 0,
        context_window: Optional[int] = None,
        turn_count: Optional[int] = None,
    ):
        self.model = model.strip().lower()
        if context_window is not None and context_window > 0:
            self.context_window = context_window
        else:
            self.context_window = MODEL_REGISTRY.get(self.model, DEFAULT_FALLBACK_WINDOW)

        self.used_tokens = max(0, used_tokens)
        self.turn_count = turn_count

    @property
    def utilization_rate(self) -> float:
        if self.context_window <= 0:
            return 1.0
        return min(1.0, self.used_tokens / self.context_window)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.context_window - self.used_tokens)

    @property
    def tier(self) -> WindowTier:
        rate = self.utilization_rate
        if rate < 0.50:
            return WindowTier.NOMINAL
        elif rate < 0.75:
            return WindowTier.CONSERVATIVE
        elif rate < 0.90:
            return WindowTier.CRITICAL
        else:
            return WindowTier.EMERGENCY

    def should_compact(self) -> bool:
        return self.tier == WindowTier.EMERGENCY

    def get_tool_budget(self, tool_name: str) -> int:
        tier_budgets = TIER_TOOL_BUDGETS[self.tier]
        normalized = tool_name.strip().lower()
        return tier_budgets.get(normalized, tier_budgets["generic_tool"])

    def get_recommendations(self) -> list[str]:
        t = self.tier
        recs: list[str] = []
        if t == WindowTier.NOMINAL:
            recs.append("Full context available. Standard tool output limits active.")
        elif t == WindowTier.CONSERVATIVE:
            recs.append("Context reaches 50%+. Omit verbose code commentary; favor scoped diffs.")
        elif t == WindowTier.CRITICAL:
            recs.append("Context exceeds 75%. Compress terminal logs to failure anchors only; avoid whole-file reads.")
        elif t == WindowTier.EMERGENCY:
            recs.append("CRITICAL: Context exceeds 90%. Execute 'mkl-prune-context' or compact conversation immediately.")
        return recs

    def report(self) -> AllocationReport:
        tier_budgets = TIER_TOOL_BUDGETS[self.tier]
        return AllocationReport(
            model=self.model,
            context_window=self.context_window,
            used_tokens=self.used_tokens,
            remaining_tokens=self.remaining_tokens,
            utilization_rate=round(self.utilization_rate, 4),
            tier=self.tier.value,
            tool_budgets=dict(tier_budgets),
            should_compact=self.should_compact(),
            turn_count=self.turn_count,
            recommendations=self.get_recommendations(),
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dynamic token budget allocator for agentic sessions."
    )
    parser.add_argument("--model", default="claude-3-7-sonnet", help="Target model name.")
    parser.add_argument("--context-window", type=int, help="Override context window capacity.")
    parser.add_argument("--used-tokens", type=int, default=0, help="Accumulated session tokens.")
    parser.add_argument("--turn-count", type=int, help="Optional turn count.")
    parser.add_argument("--json", action="store_true", help="Output JSON format.")
    parser.add_argument("--pipe", action="store_true", help="Read JSON session stats from stdin.")

    args = parser.parse_args(argv)

    model = args.model
    used = args.used_tokens
    win = args.context_window
    turns = args.turn_count

    if args.pipe:
        try:
            stdin_data = json.load(sys.stdin)
            model = stdin_data.get("model", model)
            used = stdin_data.get("used_tokens", stdin_data.get("tokens", used))
            win = stdin_data.get("context_window", win)
            turns = stdin_data.get("turn_count", stdin_data.get("turns", turns))
        except Exception as e:
            print(f"Error reading JSON from stdin: {e}", file=sys.stderr)
            return 1

    governor = ContextBudgetGovernor(
        model=model,
        used_tokens=used,
        context_window=win,
        turn_count=turns,
    )
    rep = governor.report()

    if args.json or args.pipe:
        print(json.dumps(asdict(rep), indent=2))
    else:
        status_icons = {
            "NOMINAL": "🟢",
            "CONSERVATIVE": "🟡",
            "CRITICAL": "🟠",
            "EMERGENCY": "🔴",
        }
        icon = status_icons.get(rep.tier, "⚪")
        print(f"=== Dynamic Token Budget Allocation {icon} ===")
        print(f"Model: {rep.model} (Window: {rep.context_window:,} tokens)")
        print(f"Usage: {rep.used_tokens:,} / {rep.context_window:,} tokens ({rep.utilization_rate * 100:.1f}%)")
        print(f"Remaining: {rep.remaining_tokens:,} tokens | Tier: {rep.tier}")
        if rep.turn_count is not None:
            print(f"Turn: #{rep.turn_count}")
        print("\nTool Output Limits:")
        for tool, limit in rep.tool_budgets.items():
            print(f"  - {tool:<16}: {limit:>5} tokens")
        if rep.recommendations:
            print("\nGuidance:")
            for rec in rep.recommendations:
                print(f"  • {rec}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
