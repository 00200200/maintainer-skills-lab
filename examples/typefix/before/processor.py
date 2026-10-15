"""examples/typefix/before/processor.py - Sample module with type mismatches."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Report:
    title: str
    summary: str


def find_report(report_id: str) -> Report | None:
    if report_id == "active":
        return Report(title="Weekly", summary="All systems normal")
    return None


def format_items(items: list[str]) -> str:
    return ", ".join(items)


def generate_digest(report_id: str, tags: tuple[str, ...]) -> str:
    # Error 1: Item "None" of "Report | None" has no attribute "summary" [union-attr]
    report = find_report(report_id)
    summary_text = report.summary.strip()

    # Error 2: Argument 1 to "format_items" has incompatible type "tuple[str, ...]"; expected "list[str]" [arg-type]
    tag_list = format_items(tags)
    return f"{summary_text} (tags: {tag_list})"
