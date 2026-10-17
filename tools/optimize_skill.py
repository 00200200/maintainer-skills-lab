#!/usr/bin/env python3
"""Automated DSPy-Style Skill Prompt & Demonstration Optimizer.

Iteratively optimizes skill instructions and few-shot worked examples to reduce
token footprint while ensuring evaluation benchmarks and validation checks pass 100%.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def approximate_tokens(text: str) -> int:
    """Standard token estimator matching kit.approximate_tokens."""
    return max(1, (len(text) + 3) // 4)


@dataclass
class ValidationResult:
    passed: bool
    score: float = 1.0
    details: str = ""
    raw_output: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    skill_name: str
    baseline_tokens: int
    optimized_tokens: int
    tokens_saved: int
    reduction_ratio: float
    target_reduction: float
    target_achieved: bool
    validation_passed: bool
    baseline_score: float
    optimized_score: float
    transformations_applied: list[str]
    diff: str = ""
    optimized_content: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Omit full content from default dict display if empty
        if not self.optimized_content:
            data.pop("optimized_content", None)
        return data


# Phrase simplification mapping (verbose phrase -> concise replacement)
FILLER_REPLACEMENTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to"),
    (re.compile(r"\bat this point in time\b", re.IGNORECASE), "now"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "because"),
    (re.compile(r"\bwith reference to\b", re.IGNORECASE), "regarding"),
    (re.compile(r"\bwith regard to\b", re.IGNORECASE), "regarding"),
    (re.compile(r"\btake into consideration\b", re.IGNORECASE), "consider"),
    (re.compile(r"\bmake sure that\b", re.IGNORECASE), "ensure"),
    (re.compile(r"\bmake sure to\b", re.IGNORECASE), "ensure to"),
    (re.compile(r"\bhas the ability to\b", re.IGNORECASE), "can"),
    (re.compile(r"\bin the event that\b", re.IGNORECASE), "if"),
    (re.compile(r"\bis able to\b", re.IGNORECASE), "can"),
    (re.compile(r"\bfor the purpose of\b", re.IGNORECASE), "for"),
    (re.compile(r"\bprior to\b", re.IGNORECASE), "before"),
    (re.compile(r"\bsubsequent to\b", re.IGNORECASE), "after"),
    (re.compile(r"\bas a means of\b", re.IGNORECASE), "to"),
    (re.compile(r"\ba large number of\b", re.IGNORECASE), "many"),
    (re.compile(r"\ba majority of\b", re.IGNORECASE), "most"),
    (re.compile(r"\butilize\b", re.IGNORECASE), "use"),
    (re.compile(r"\butilizes\b", re.IGNORECASE), "uses"),
    (re.compile(r"\butilizing\b", re.IGNORECASE), "using"),
    (re.compile(r"\butilization\b", re.IGNORECASE), "use"),
]

# AI cliches and preamble fluff that waste token budget
CLICHE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bIt is important to remember that\s*", re.IGNORECASE), ""),
    (re.compile(r"\bPlease note that\s*", re.IGNORECASE), ""),
    (re.compile(r"\bNote that\s*", re.IGNORECASE), ""),
    (re.compile(r"\bKeep in mind that\s*", re.IGNORECASE), ""),
    (re.compile(r"\bIt is worth noting that\s*", re.IGNORECASE), ""),
    (re.compile(r"\bIn general,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bEssentially,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bBasically,\s*", re.IGNORECASE), ""),
    (re.compile(r"\bNeedless to say,\s*", re.IGNORECASE), ""),
]


def extract_fences(markdown: str) -> tuple[str, list[str]]:
    """Protect code blocks from being modified by regex transformations."""
    fences: list[str] = []
    fence_pattern = re.compile(r"(```[\s\S]*?```|`[^`\n]+`)")

    def repl(m: re.Match) -> str:
        idx = len(fences)
        fences.append(m.group(0))
        return f"@@TOKEN_FENCE_{idx}@@"

    masked = fence_pattern.sub(repl, markdown)
    return masked, fences


def restore_fences(masked: str, fences: list[str]) -> str:
    """Restore code blocks back into the text."""
    result = masked
    for idx, fence in enumerate(fences):
        result = result.replace(f"@@TOKEN_FENCE_{idx}@@", fence)
    return result


def parse_skill_sections(content: str) -> tuple[str, str, dict[str, str]]:
    """Parse skill into frontmatter, preamble, and section dictionary."""
    frontmatter = ""
    body = content
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            frontmatter = content[: end + 5]
            body = content[end + 5 :]

    # Split by markdown H2 headers
    sections: dict[str, str] = {}
    splits = re.split(r"\n(?=## )", body)
    preamble = splits[0].strip() if splits else ""

    for s in splits[1:]:
        s = s.strip()
        if not s:
            continue
        lines = s.split("\n", 1)
        header = lines[0].strip()
        sec_body = lines[1].strip() if len(lines) > 1 else ""
        sections[header] = sec_body

    return frontmatter, preamble, sections


def reconstruct_skill(frontmatter: str, preamble: str, sections: dict[str, str]) -> str:
    """Reconstruct valid SKILL.md content from components."""
    parts: list[str] = []
    if frontmatter:
        parts.append(frontmatter.strip())
        parts.append("")
    if preamble:
        parts.append(preamble.strip())
        parts.append("")

    for header, sec_body in sections.items():
        parts.append(header)
        if sec_body:
            parts.append("")
            parts.append(sec_body)
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def prune_fillers(text: str) -> str:
    """Replace wordy phrases with concise equivalents outside code blocks."""
    masked, fences = extract_fences(text)
    for pattern, replacement in FILLER_REPLACEMENTS:
        masked = pattern.sub(replacement, masked)
    return restore_fences(masked, fences)


def prune_cliches(text: str) -> str:
    """Remove AI cliches and preamble filler outside code blocks."""
    masked, fences = extract_fences(text)
    for pattern, replacement in CLICHE_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return restore_fences(masked, fences)


def compact_whitespace(text: str) -> str:
    """Collapse excess blank lines and strip trailing whitespace."""
    masked, fences = extract_fences(text)
    # Collapse 3 or more newlines to 2
    masked = re.sub(r"\n{3,}", "\n\n", masked)
    lines = [line.rstrip() for line in masked.split("\n")]
    result = "\n".join(lines).strip()
    return restore_fences(result, fences)


def compact_worked_example(section_body: str) -> str:
    """Compact worked example commentary while strictly preserving input/output blocks."""
    if not section_body:
        return ""
    masked, fences = extract_fences(section_body)
    # Remove repetitive narrative transitions like "Here is an example:" or "Consider the following:"
    narrative_transitions = [
        re.compile(r"Here is a worked example demonstrating the workflow:?", re.IGNORECASE),
        re.compile(r"Consider the following concrete example:?", re.IGNORECASE),
        re.compile(r"The following example illustrates this:?", re.IGNORECASE),
        re.compile(r"As shown in this worked example:?", re.IGNORECASE),
    ]
    for p in narrative_transitions:
        masked = p.sub("", masked)
    # Clean up resulting empty lines
    masked = re.sub(r"\n{3,}", "\n\n", masked)
    return restore_fences(masked, fences).strip()


def run_dataset_validator(
    dataset_path: Path | None,
    validation_cmd: str | None,
    skill_file: Path,
    skill_content: str,
) -> ValidationResult:
    """Execute evaluation benchmark or test runner against the candidate skill."""
    # Write temporary candidate to skill path for validation
    original_bytes = skill_file.read_bytes() if skill_file.exists() else None
    try:
        skill_file.write_text(skill_content, encoding="utf-8")

        if validation_cmd:
            cmd = validation_cmd
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            passed = proc.returncode == 0
            raw: dict[str, Any] = {}
            try:
                raw = json.loads(proc.stdout)
            except Exception:
                pass
            return ValidationResult(
                passed=passed,
                score=1.0 if passed else 0.0,
                details=proc.stdout or proc.stderr,
                raw_output=raw,
            )

        if dataset_path:
            ds_dir = (
                (ROOT / dataset_path).resolve() if not dataset_path.is_absolute() else dataset_path
            )
            if ds_dir.is_dir():
                runner = ds_dir / "run.py"
                if runner.is_file():
                    proc = subprocess.run(
                        [sys.executable, str(runner), "--json"],
                        cwd=ds_dir,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    passed = proc.returncode == 0
                    raw: dict[str, Any] = {}
                    try:
                        raw = json.loads(proc.stdout)
                        if "verified" in raw:
                            passed = passed and bool(raw["verified"])
                    except Exception:
                        pass
                    return ValidationResult(
                        passed=passed,
                        score=1.0 if passed else 0.0,
                        details=proc.stdout or proc.stderr,
                        raw_output=raw,
                    )

        # Default fallback structural validation: frontmatter, headers, markdown validity
        if not skill_content.startswith("---\n"):
            return ValidationResult(passed=False, score=0.0, details="Missing frontmatter")
        if "# " not in skill_content:
            return ValidationResult(passed=False, score=0.0, details="Missing H1 title")
        return ValidationResult(passed=True, score=1.0, details="Structural validation passed")

    finally:
        if original_bytes is not None:
            skill_file.write_bytes(original_bytes)


def optimize_skill(
    skill_file: Path,
    dataset_path: Path | None = None,
    validation_cmd: str | None = None,
    target_reduction: float = 0.15,
    metric: str = "token_efficiency",
    validator: Callable[[Path, str], ValidationResult] | None = None,
) -> OptimizationResult:
    """Optimize a skill's prompt and demonstrations iteratively."""
    original_text = skill_file.read_text(encoding="utf-8")
    skill_name = skill_file.parent.name if skill_file.name == "SKILL.md" else skill_file.stem
    name_match = re.search(r'^name:\s*["\']?([^"\'\n]+)["\']?', original_text, re.MULTILINE)
    if name_match:
        skill_name = name_match.group(1).strip()
    base_tokens = approximate_tokens(original_text)

    def eval_candidate(candidate: str) -> ValidationResult:
        if validator:
            return validator(skill_file, candidate)
        return run_dataset_validator(dataset_path, validation_cmd, skill_file, candidate)

    # 1. Establish baseline
    base_eval = eval_candidate(original_text)
    if not base_eval.passed:
        return OptimizationResult(
            skill_name=skill_name,
            baseline_tokens=base_tokens,
            optimized_tokens=base_tokens,
            tokens_saved=0,
            reduction_ratio=0.0,
            target_reduction=target_reduction,
            target_achieved=False,
            validation_passed=False,
            baseline_score=base_eval.score,
            optimized_score=base_eval.score,
            transformations_applied=[],
            diff="",
            optimized_content=original_text,
        )

    current_text = original_text
    applied_transformations: list[str] = []

    transformations: list[tuple[str, Callable[[str], str]]] = [
        ("prune_fillers", prune_fillers),
        ("prune_cliches", prune_cliches),
        ("compact_whitespace", compact_whitespace),
    ]

    # Iterative transformation pipeline
    for name, transform_fn in transformations:
        frontmatter, preamble, sections = parse_skill_sections(current_text)

        # Apply transformation to preamble
        new_preamble = transform_fn(preamble)

        # Apply transformation to sections (with specialized handling for worked examples)
        new_sections: dict[str, str] = {}
        for header, sec_body in sections.items():
            if "worked example" in header.lower() and name == "compact_whitespace":
                sec_body = compact_worked_example(sec_body)
            new_sections[header] = transform_fn(sec_body)

        candidate = reconstruct_skill(frontmatter, new_preamble, new_sections)
        candidate_tokens = approximate_tokens(candidate)

        if candidate_tokens < approximate_tokens(current_text):
            val = eval_candidate(candidate)
            if val.passed and val.score >= base_eval.score:
                current_text = candidate
                applied_transformations.append(name)

                # Check if target reduction reached
                current_ratio = (base_tokens - candidate_tokens) / max(1, base_tokens)
                if current_ratio >= target_reduction:
                    break

    # Calculate final results
    final_tokens = approximate_tokens(current_text)
    saved_tokens = max(0, base_tokens - final_tokens)
    ratio = saved_tokens / max(1, base_tokens)
    final_eval = eval_candidate(current_text)

    # Generate unified diff
    diff_lines = list(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=f"a/{skill_file.name}",
            tofile=f"b/{skill_file.name}",
        )
    )
    diff_str = "".join(diff_lines)

    return OptimizationResult(
        skill_name=skill_name,
        baseline_tokens=base_tokens,
        optimized_tokens=final_tokens,
        tokens_saved=saved_tokens,
        reduction_ratio=round(ratio, 4),
        target_reduction=target_reduction,
        target_achieved=ratio >= target_reduction,
        validation_passed=final_eval.passed,
        baseline_score=base_eval.score,
        optimized_score=final_eval.score,
        transformations_applied=applied_transformations,
        diff=diff_str,
        optimized_content=current_text,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated DSPy-Style Skill Prompt & Demonstration Optimizer"
    )
    parser.add_argument(
        "--skill",
        required=True,
        help="Skill name (e.g. mkl-humanize) or path to SKILL.md",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Path to evaluation benchmark dataset or directory with run.py",
    )
    parser.add_argument(
        "--validation-cmd",
        default=None,
        help="Custom shell command to validate the candidate prompt",
    )
    parser.add_argument(
        "--metric",
        default="token_efficiency",
        choices=["token_efficiency", "pass_rate", "pareto"],
        help="Optimization objective metric (default: token_efficiency)",
    )
    parser.add_argument(
        "--target-reduction",
        type=float,
        default=0.15,
        help="Target token reduction ratio, e.g. 0.20 for 20% (default: 0.15)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write optimized prompt directly to the skill file",
    )
    parser.add_argument(
        "--output-diff",
        action="store_true",
        help="Print unified diff of optimized prompt",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON optimization report",
    )

    args = parser.parse_args(argv)

    # Locate skill file
    skill_input = Path(args.skill)
    if skill_input.is_file():
        skill_path = skill_input
    else:
        skill_path = ROOT / "skills" / args.skill / "SKILL.md"
        if not skill_path.is_file():
            print(f"Error: Skill file not found: {skill_path}", file=sys.stderr)
            return 1

    result = optimize_skill(
        skill_file=skill_path,
        dataset_path=args.dataset,
        validation_cmd=args.validation_cmd,
        target_reduction=args.target_reduction,
        metric=args.metric,
    )

    if args.apply and result.tokens_saved > 0 and result.validation_passed:
        skill_path.write_text(result.optimized_content, encoding="utf-8")

    if args.json:
        report = result.to_dict()
        print(json.dumps(report, indent=2))
    else:
        status_icon = "✅" if result.validation_passed else "❌"
        pct = result.reduction_ratio * 100
        print(f"{status_icon} Skill Optimization: {result.skill_name}")
        print(f"  • Baseline Tokens:  {result.baseline_tokens:,}")
        print(f"  • Optimized Tokens: {result.optimized_tokens:,}")
        print(f"  • Tokens Saved:     {result.tokens_saved:,} (-{pct:.1f}%)")
        print(f"  • Validation:       {'PASSED' if result.validation_passed else 'FAILED'}")
        print(
            f"  • Transformations:  {', '.join(result.transformations_applied) or 'none applied'}"
        )

        if args.output_diff and result.diff:
            print("\n--- Proposed Diff ---")
            print(result.diff)

    return 0 if result.validation_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
