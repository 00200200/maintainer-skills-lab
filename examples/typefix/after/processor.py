"""examples/typefix/after/processor.py - Clean module with surgical type fixes applied."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class Report:
    title: str
    summary: str


def find_report(report_id: str) -> Report | None:
    if report_id == "active":
        return Report(title="Weekly", summary="All systems normal")
    return None


# Fix 2: Widen concrete list[str] to abstract Sequence[str]
def format_items(items: Sequence[str]) -> str:
    return ", ".join(items)


def generate_digest(report_id: str, tags: tuple[str, ...]) -> str:
    # Fix 1: Add type narrowing guard for Optional[Report]
    report = find_report(report_id)
    if report is None:
        return "No report found"

    summary_text = report.summary.strip()
    tag_list = format_items(tags)
    return f"{summary_text} (tags: {tag_list})"
