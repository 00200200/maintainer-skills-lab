"""Prompt drift and token regression detector for Maintainer Skills Lab.

Compares token footprints of skills across two git refs or filesystem states,
detecting single-skill inflation (> 15%) or library-wide creep (> 5% without new skills).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_MAX_SKILL_PCT = 15.0
DEFAULT_MAX_TOTAL_PCT = 5.0


class SkillTokenStats(NamedTuple):
    name: str
    base_tokens: int
    head_tokens: int
    delta: int
    pct_change: float | None
    is_new: bool
    is_removed: bool
    is_modified: bool
    regressed: bool


class ComparisonResult(NamedTuple):
    skills: list[SkillTokenStats]
    base_total: int
    head_total: int
    total_delta: int
    total_pct_change: float
    new_skills_count: int
    skill_violations: list[str]
    total_violation: str | None
    passed: bool
    approved: bool


def approximate_tokens(text: str) -> int:
    """Rough English token estimate standard in maintainer-skills-lab (~4 chars per token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def get_git_skill_tokens(ref: str, repo_root: Path | None = None) -> dict[str, int]:
    """Calculate token counts for all skills at a specific git ref."""
    cwd = str(repo_root) if repo_root else None

    # List all files under skills/ in the given ref
    cmd_tree = ["git", "ls-tree", "-r", "--name-only", ref, "skills/"]
    proc_tree = subprocess.run(cmd_tree, cwd=cwd, capture_output=True, text=True, check=False)
    if proc_tree.returncode != 0:
        raise RuntimeError(f"Failed to list skills for git ref '{ref}': {proc_tree.stderr.strip()}")

    file_paths = [line.strip() for line in proc_tree.stdout.splitlines() if line.strip()]
    skill_tokens: dict[str, int] = {}

    for path_str in file_paths:
        parts = Path(path_str).parts
        if len(parts) < 2 or parts[0] != "skills":
            continue
        skill_name = parts[1]
        if "__pycache__" in parts or path_str.endswith(".pyc"):
            continue

        cmd_show = ["git", "show", f"{ref}:{path_str}"]
        proc_show = subprocess.run(cmd_show, cwd=cwd, capture_output=True, check=False)
        if proc_show.returncode != 0:
            continue

        try:
            content = proc_show.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue

        tokens = approximate_tokens(content)
        skill_tokens[skill_name] = skill_tokens.get(skill_name, 0) + tokens

    return skill_tokens


def get_filesystem_skill_tokens(root_dir: Path) -> dict[str, int]:
    """Calculate token counts for all skills in a directory tree."""
    skills_dir = root_dir / "skills" if (root_dir / "skills").is_dir() else root_dir
    if not skills_dir.exists():
        return {}

    skill_tokens: dict[str, int] = {}
    for skill_path in sorted(skills_dir.iterdir()):
        if not skill_path.is_dir() or skill_path.name.startswith("."):
            continue
        skill_name = skill_path.name
        tokens = 0
        for file_path in skill_path.rglob("*"):
            if not file_path.is_file():
                continue
            if "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                tokens += approximate_tokens(content)
            except (UnicodeDecodeError, OSError):
                continue
        skill_tokens[skill_name] = tokens

    return skill_tokens


def compare_skill_tokens(
    base_counts: dict[str, int],
    head_counts: dict[str, int],
    max_skill_pct: float = DEFAULT_MAX_SKILL_PCT,
    max_total_pct: float = DEFAULT_MAX_TOTAL_PCT,
    approved: bool = False,
) -> ComparisonResult:
    """Compare base and head token counts against regression thresholds."""
    all_skill_names = sorted(set(base_counts.keys()) | set(head_counts.keys()))
    skill_stats: list[SkillTokenStats] = []
    skill_violations: list[str] = []

    new_skills = 0

    for name in all_skill_names:
        in_base = name in base_counts
        in_head = name in head_counts
        b_tok = base_counts.get(name, 0)
        h_tok = head_counts.get(name, 0)
        delta = h_tok - b_tok

        is_new = in_head and not in_base
        is_removed = in_base and not in_head
        is_modified = in_base and in_head and delta != 0

        if is_new:
            new_skills += 1
            pct_change = None
            regressed = False
        elif is_removed:
            pct_change = -100.0
            regressed = False
        elif b_tok == 0:
            pct_change = 100.0 if h_tok > 0 else 0.0
            regressed = h_tok > 0
        else:
            pct_change = round((delta / b_tok) * 100.0, 2)
            regressed = pct_change > max_skill_pct

        if regressed:
            skill_violations.append(
                f"Skill '{name}' increased by {pct_change:+.1f}% "
                f"({b_tok:,} -> {h_tok:,} tokens, threshold: +{max_skill_pct:.1f}%)"
            )

        skill_stats.append(
            SkillTokenStats(
                name=name,
                base_tokens=b_tok,
                head_tokens=h_tok,
                delta=delta,
                pct_change=pct_change,
                is_new=is_new,
                is_removed=is_removed,
                is_modified=is_modified,
                regressed=regressed,
            )
        )

    base_total = sum(base_counts.values())
    head_total = sum(head_counts.values())
    total_delta = head_total - base_total
    total_pct_change = (
        round((total_delta / base_total) * 100.0, 2)
        if base_total > 0
        else (0.0 if head_total == 0 else 100.0)
    )

    total_violation: str | None = None
    if new_skills == 0 and total_pct_change > max_total_pct:
        total_violation = (
            f"Total library tokens increased by {total_pct_change:+.1f}% "
            f"({base_total:,} -> {head_total:,} tokens, threshold: +{max_total_pct:.1f}%) "
            f"without adding any new skill"
        )

    has_violations = bool(skill_violations or total_violation)
    passed = approved or not has_violations

    return ComparisonResult(
        skills=skill_stats,
        base_total=base_total,
        head_total=head_total,
        total_delta=total_delta,
        total_pct_change=total_pct_change,
        new_skills_count=new_skills,
        skill_violations=skill_violations,
        total_violation=total_violation,
        passed=passed,
        approved=approved,
    )


def render_markdown_report(result: ComparisonResult) -> str:
    """Generate GitHub PR markdown comment with before/after comparison table."""
    lines: list[str] = [
        "## 📊 Token Footprint Regression Report",
        "",
        "| Skill | Base Tokens | Head Tokens | Delta | % Change | Status |",
        "|:---|---:|---:|---:|---:|:---|",
    ]

    for s in result.skills:
        b_str = f"{s.base_tokens:,}"
        h_str = f"{s.head_tokens:,}"
        d_str = f"{s.delta:+,}" if s.delta != 0 else "0"

        if s.is_new:
            pct_str = "—"
            status_str = "✨ New skill"
        elif s.is_removed:
            pct_str = "-100.0%"
            status_str = "🗑️ Removed"
        elif s.pct_change is not None:
            pct_str = f"{s.pct_change:+.1f}%"
            if s.regressed:
                status_str = "⚠️ **Regressed (>15%)**"
            elif s.delta > 0:
                status_str = "📈 Minor increase"
            elif s.delta < 0:
                status_str = "📉 Reduced"
            else:
                status_str = "✅ Unchanged"
        else:
            pct_str = "0.0%"
            status_str = "✅ Unchanged"

        lines.append(f"| `{s.name}` | {b_str} | {h_str} | {d_str} | {pct_str} | {status_str} |")

    # Total row
    t_base = f"**{result.base_total:,}**"
    t_head = f"**{result.head_total:,}**"
    t_delta = f"**{result.total_delta:+,}**" if result.total_delta != 0 else "**0**"
    t_pct = f"**{result.total_pct_change:+.1f}%**"
    if result.total_violation:
        t_status = "⚠️ **Regressed (>5%)**"
    elif result.total_delta > 0:
        t_status = "📈 Increase"
    elif result.total_delta < 0:
        t_status = "📉 Reduced"
    else:
        t_status = "✅ Unchanged"

    lines.append(f"| **Total Library** | {t_base} | {t_head} | {t_delta} | {t_pct} | {t_status} |")
    lines.append("")

    all_violations: list[str] = list(result.skill_violations)
    if result.total_violation:
        all_violations.append(result.total_violation)

    if all_violations:
        lines.append("### ⚠️ Token Regressions Detected")
        lines.append("")
        for v in all_violations:
            lines.append(f"- 🔴 {v}")
        lines.append("")
        if result.approved:
            lines.append(
                "> ℹ️ **Override Approved**: Token increase approved via "
                "`token-increase-approved` label."
            )
        else:
            lines.append(
                "> ❌ **Check Failed**: To override and approve this token increase, "
                "add the `token-increase-approved` label to this pull request."
            )
    else:
        lines.append(
            f"> ✅ **Token Check Passed**: No regressions detected. "
            f"Total token delta: {result.total_delta:+,} tokens ({result.total_pct_change:+.1f}%)."
        )

    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect token inflation and prompt drift across git revisions."
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base git ref, branch, or directory (default: origin/main)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Head git ref, branch, or directory (default: HEAD)",
    )
    parser.add_argument(
        "--max-skill-pct",
        type=float,
        default=DEFAULT_MAX_SKILL_PCT,
        help=f"Max allowed percentage increase per skill (default: {DEFAULT_MAX_SKILL_PCT}%%)",
    )
    parser.add_argument(
        "--max-total-pct",
        type=float,
        default=DEFAULT_MAX_TOTAL_PCT,
        help=f"Max allowed total library percentage increase (default: {DEFAULT_MAX_TOTAL_PCT}%%)",
    )
    parser.add_argument(
        "--output-comment",
        type=Path,
        default=None,
        help="Path to write the markdown PR comment report",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Path to write the machine-readable JSON result",
    )
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Override token regression check (e.g. if PR has 'token-increase-approved' label)",
    )
    return parser.parse_args(argv)


def _load_counts(ref_or_dir: str) -> dict[str, int]:
    path = Path(ref_or_dir)
    if path.exists() and path.is_dir():
        return get_filesystem_skill_tokens(path)
    return get_git_skill_tokens(ref_or_dir)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        base_counts = _load_counts(args.base)
    except Exception as exc:
        print(f"Error reading base tokens ({args.base}): {exc}", file=sys.stderr)
        return 2

    try:
        head_counts = _load_counts(args.head)
    except Exception as exc:
        print(f"Error reading head tokens ({args.head}): {exc}", file=sys.stderr)
        return 2

    result = compare_skill_tokens(
        base_counts=base_counts,
        head_counts=head_counts,
        max_skill_pct=args.max_skill_pct,
        max_total_pct=args.max_total_pct,
        approved=args.approved,
    )

    report_md = render_markdown_report(result)
    print(report_md)

    if args.output_comment:
        args.output_comment.parent.mkdir(parents=True, exist_ok=True)
        args.output_comment.write_text(report_md, encoding="utf-8")

    if args.output_json:
        data: dict[str, Any] = {
            "passed": result.passed,
            "approved": result.approved,
            "base_total": result.base_total,
            "head_total": result.head_total,
            "total_delta": result.total_delta,
            "total_pct_change": result.total_pct_change,
            "skill_violations": result.skill_violations,
            "total_violation": result.total_violation,
            "skills": [
                {
                    "name": s.name,
                    "base_tokens": s.base_tokens,
                    "head_tokens": s.head_tokens,
                    "delta": s.delta,
                    "pct_change": s.pct_change,
                    "is_new": s.is_new,
                    "is_removed": s.is_removed,
                    "is_modified": s.is_modified,
                    "regressed": s.regressed,
                }
                for s in result.skills
            ],
        }
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
