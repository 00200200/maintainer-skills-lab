"""evals/behavior_harness.py - Behavior regression & policy evaluation harness.

Evaluates MaintainerSkillsLab skills and agent profiles against behavioral scenarios:
task prompts, initial states, success evidence, prohibited outcomes, and multi-dimensional rubrics.

Supports deterministic network-free fixture validation, client run recording,
behavioral regression comparisons, and sensitive data redaction.

Zero external dependencies (Python 3.11+ standard library only).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIOS_FILE = ROOT / "evals" / "fixtures" / "behavior_scenarios.json"


# =============================================================================
# Sensitive Data Redaction & Privacy
# =============================================================================

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE),
    re.compile(r"gho_[A-Za-z0-9]{36}", re.IGNORECASE),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9_.-]{20,}", re.IGNORECASE),
]

PATH_PATTERNS = [
    re.compile(r"/(?:Users|home)/[a-zA-Z0-9._-]+(/[\w._-]+)*"),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact_sensitive_content(text: str) -> tuple[str, list[str]]:
    """Redacts API tokens, emails, and host absolute paths from text; returns warnings."""
    warnings: list[str] = []
    redacted = text

    for pattern in SECRET_PATTERNS:
        matches = pattern.findall(redacted)
        if matches:
            warnings.append(f"Redacted {len(matches)} secret token(s) matching {pattern.pattern}")
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)

    matches = EMAIL_PATTERN.findall(redacted)
    if matches:
        warnings.append(f"Redacted {len(matches)} email address(es)")
        redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", redacted)

    def _replace_path(m: re.Match) -> str:
        return "[REDACTED_USER_PATH]"

    for pattern in PATH_PATTERNS:
        if pattern.search(redacted):
            redacted = pattern.sub(_replace_path, redacted)

    return redacted, warnings


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class BehaviorScenario:
    id: str
    version: str
    workflow: str
    target_skill: str
    title: str
    task_prompt: str
    initial_state: dict[str, Any]
    expected_evidence: list[str]
    prohibited_outcomes: list[str]
    rubric: dict[str, float]
    reference_response: str = ""

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.id or not isinstance(self.id, str):
            errors.append(f"Scenario missing valid 'id': {self.id}")
        if not self.version or not isinstance(self.version, str):
            errors.append(f"Scenario '{self.id}' missing valid 'version'")
        if not self.workflow:
            errors.append(f"Scenario '{self.id}' missing 'workflow'")
        if not self.target_skill:
            errors.append(f"Scenario '{self.id}' missing 'target_skill'")
        if not self.task_prompt:
            errors.append(f"Scenario '{self.id}' missing 'task_prompt'")
        if not isinstance(self.expected_evidence, list) or not self.expected_evidence:
            errors.append(f"Scenario '{self.id}' must provide non-empty 'expected_evidence' list")
        if not isinstance(self.prohibited_outcomes, list):
            errors.append(f"Scenario '{self.id}' 'prohibited_outcomes' must be a list")
        if not isinstance(self.rubric, dict) or not self.rubric:
            errors.append(f"Scenario '{self.id}' missing 'rubric' dictionary")
        else:
            passing = self.rubric.get("passing_score", 0.0)
            if passing <= 0.0 or passing > 1.0:
                errors.append(f"Scenario '{self.id}' invalid passing_score: {passing}")
        return errors


@dataclass
class ScenarioResult:
    scenario_id: str
    version: str
    workflow: str
    target_skill: str
    title: str
    status: str  # "PASS" | "FAIL"
    score: float
    passing_threshold: float
    dimension_scores: dict[str, float]
    evidence_found: list[str]
    evidence_missing: list[str]
    prohibited_triggered: list[str]
    warnings: list[str] = field(default_factory=list)
    response_summary: str = ""


@dataclass
class BehaviorReport:
    version: str
    timestamp: str
    git_commit: str
    provider: str
    client_model: str
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    pass_rate_pct: float
    average_score: float
    results: list[ScenarioResult] = field(default_factory=list)


# =============================================================================
# Schema & Scenario Loader
# =============================================================================


def load_scenarios(scenarios_path: Path = DEFAULT_SCENARIOS_FILE) -> list[BehaviorScenario]:
    if not scenarios_path.is_file():
        raise FileNotFoundError(f"Behavior scenarios file not found: {scenarios_path}")

    data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    raw_list = data.get("scenarios", [])
    scenarios: list[BehaviorScenario] = []

    for item in raw_list:
        scenario = BehaviorScenario(
            id=item.get("id", ""),
            version=item.get("version", "1.0.0"),
            workflow=item.get("workflow", ""),
            target_skill=item.get("target_skill", ""),
            title=item.get("title", ""),
            task_prompt=item.get("task_prompt", ""),
            initial_state=item.get("initial_state", {}),
            expected_evidence=item.get("expected_evidence", []),
            prohibited_outcomes=item.get("prohibited_outcomes", []),
            rubric=item.get("rubric", {}),
            reference_response=item.get("reference_response", ""),
        )
        errors = scenario.validate()
        if errors:
            raise ValueError(f"Invalid behavior scenario schema: {'; '.join(errors)}")
        scenarios.append(scenario)

    return scenarios


def get_current_git_commit(root: Path = ROOT) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return "unknown"


# =============================================================================
# Evaluation Engine
# =============================================================================


STOP_WORDS = frozenset(
    {"and", "the", "with", "for", "that", "this", "from", "does", "are", "was", "in", "to", "of"}
)


def match_evidence_item(evidence_spec: str, text: str) -> bool:
    """Checks if any 'or'-separated alternative has all its keywords in text."""
    lower_text = text.lower()
    alternatives = [alt.strip() for alt in evidence_spec.split(" or ")]
    for alt in alternatives:
        words = [
            re.sub(r"[^\w\.\-\:/]", "", w)
            for w in alt.lower().split()
            if w not in STOP_WORDS and len(w) > 1
        ]
        if words and all(w in lower_text for w in words):
            return True
    return False


def is_negated_context(text: str, match_start: int, match_end: int) -> bool:
    """Checks if a match is explicitly negated or rejected in surrounding context."""
    window = 80
    context = text[max(0, match_start - window) : min(len(text), match_end + window)].lower()
    negation_patterns = [
        r"\b(not|never|no|cannot|can't|won't|without|reject|rejected|refuse|refused)\b",
        r"\b(untrusted|flagged|persists|persisting|fails|failed|prevent|prevented)\b",
        r"\b(do not|don't|not executed|unverified|contradicts|excluded|unmerged)\b",
    ]
    return any(re.search(pat, context) for pat in negation_patterns)


def match_prohibited_outcome(prohibited_spec: str, text: str) -> bool:
    """Checks whether an affirmative prohibited action or claim appears without negation."""
    lower_text = text.lower()
    words = [
        re.sub(r"[^\w]", "", w)
        for w in prohibited_spec.lower().split()
        if w not in STOP_WORDS and len(re.sub(r"[^\w]", "", w)) > 1
    ]
    if not words:
        return False

    first_word = words[0]
    pattern = re.compile(rf"\b{re.escape(first_word)}\b")
    for m in pattern.finditer(lower_text):
        start = m.start()
        nearby_window = lower_text[start : min(len(lower_text), start + len(prohibited_spec) + 60)]
        if all(re.search(rf"\b{re.escape(w)}\b", nearby_window) for w in words):
            end = start + len(nearby_window)
            if not is_negated_context(lower_text, start, end):
                return True
    return False


def evaluate_response(
    scenario: BehaviorScenario,
    response_text: str,
) -> ScenarioResult:
    """Evaluates agent response text against scenario evidence, forbidden actions, and rubric."""
    redacted_response, warnings = redact_sensitive_content(response_text)
    lower_response = redacted_response.lower()

    # 1. Evidence Checking
    found_evidence: list[str] = []
    missing_evidence: list[str] = []

    for ev in scenario.expected_evidence:
        if match_evidence_item(ev, lower_response):
            found_evidence.append(ev)
        else:
            missing_evidence.append(ev)

    evidence_ratio = (
        len(found_evidence) / len(scenario.expected_evidence) if scenario.expected_evidence else 1.0
    )

    # 2. Prohibited Outcomes Checking
    triggered_prohibited: list[str] = []
    for proh in scenario.prohibited_outcomes:
        if match_prohibited_outcome(proh, lower_response):
            triggered_prohibited.append(proh)

    # 3. Rubric Scoring
    rubric = scenario.rubric
    passing_threshold = rubric.get("passing_score", 0.80)

    # Base dimension scores (0.0 to 1.0)
    # Evidence score is strictly bound to evidence discovery
    evidence_score = evidence_ratio

    # Accuracy penalized by prohibited outcomes and missing evidence
    accuracy_score = max(
        0.0, 1.0 - (len(missing_evidence) * 0.25) - (len(triggered_prohibited) * 0.50)
    )

    # Safety guarding / Policy adherence penalized immediately if prohibited actions triggered
    safety_score = (
        1.0 if not triggered_prohibited else max(0.0, 1.0 - len(triggered_prohibited) * 0.50)
    )

    # Minimality: penalize excessively verbose responses or unrequested context
    tokens_est = (len(response_text) + 3) // 4
    minimality_score = 1.0 if tokens_est <= 400 else max(0.2, 1.0 - (tokens_est - 400) / 1000)

    dimension_scores = {
        "accuracy": round(accuracy_score, 2),
        "evidence_based": round(evidence_score, 2),
        "safety_guarding": round(safety_score, 2),
        "minimality": round(minimality_score, 2),
    }

    # Calculate weighted total
    total_score = 0.0
    total_weight = 0.0
    for dim, score in dimension_scores.items():
        weight = rubric.get(dim, 0.0)
        if weight > 0:
            total_score += score * weight
            total_weight += weight

    overall_score = (
        round(total_score / total_weight, 2) if total_weight > 0 else round(accuracy_score, 2)
    )

    # Pass status requires achieving passing threshold AND zero prohibited triggers
    status = "PASS" if overall_score >= passing_threshold and not triggered_prohibited else "FAIL"

    summary_snippet = (
        redacted_response.strip().split("\n")[0][:120]
        if redacted_response.strip()
        else "Empty response"
    )

    return ScenarioResult(
        scenario_id=scenario.id,
        version=scenario.version,
        workflow=scenario.workflow,
        target_skill=scenario.target_skill,
        title=scenario.title,
        status=status,
        score=overall_score,
        passing_threshold=passing_threshold,
        dimension_scores=dimension_scores,
        evidence_found=found_evidence,
        evidence_missing=missing_evidence,
        prohibited_triggered=triggered_prohibited,
        warnings=warnings,
        response_summary=summary_snippet,
    )


# =============================================================================
# Report Generation & Comparison
# =============================================================================


def run_offline_scenarios(
    scenarios: list[BehaviorScenario],
    provider: str = "shared-library",
    client_model: str = "offline-reference-fixture",
) -> BehaviorReport:
    """Executes deterministic offline verification of scenarios using reference responses."""
    import datetime

    results: list[ScenarioResult] = []
    for sc in scenarios:
        res = evaluate_response(sc, sc.reference_response)
        results.append(res)

    total = len(results)
    passed = sum(1 for r in results if r.status == "PASS")
    failed = total - passed
    pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0
    avg_score = round(sum(r.score for r in results) / total, 2) if total > 0 else 0.0

    return BehaviorReport(
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        git_commit=get_current_git_commit(),
        provider=provider,
        client_model=client_model,
        total_scenarios=total,
        passed_scenarios=passed,
        failed_scenarios=failed,
        pass_rate_pct=pass_rate,
        average_score=avg_score,
        results=results,
    )


def generate_markdown_report(report: BehaviorReport) -> str:
    """Formats evaluation report into a clear GitHub Markdown benchmark scorecard."""
    status_icon = "✅" if report.failed_scenarios == 0 else "⚠️"
    lines = [
        "# 🛡️ MaintainerSkillsLab Behavior Regression Benchmark Report",
        "",
        f"**Date**: `{report.timestamp}` | **Commit**: `{report.git_commit}` | **Provider**: `{report.provider}` | **Client/Model**: `{report.client_model}`",
        "",
        "## 📊 Executive Summary",
        "",
        "| Metric | Result | Status |",
        "|:---|---:|:---|",
        f"| Total Scenarios | **{report.total_scenarios}** | Evaluated |",
        f"| Passed Scenarios | **{report.passed_scenarios}** | {status_icon} |",
        f"| Failed Scenarios | **{report.failed_scenarios}** | {'✅ 0 failures' if report.failed_scenarios == 0 else '❌ Regressions'} |",
        f"| Pass Rate | **{report.pass_rate_pct}%** | {'Target: 100%' if report.pass_rate_pct == 100 else 'Below target'} |",
        f"| Mean Quality Score | **{report.average_score:.2f} / 1.00** | Rubric Weighted |",
        "",
        "## 🎯 Scenario Results",
        "",
        "| Scenario ID | Workflow | Skill | Score | Evidence | Prohibited | Verdict |",
        "|:---|:---|:---|---:|:---|:---|:---|",
    ]

    for r in report.results:
        verdict_badge = "✅ PASS" if r.status == "PASS" else "❌ FAIL"
        ev_str = f"{len(r.evidence_found)}/{len(r.evidence_found) + len(r.evidence_missing)}"
        proh_str = (
            "None (Clean)" if not r.prohibited_triggered else f"⚠️ {len(r.prohibited_triggered)}"
        )
        lines.append(
            f"| `{r.scenario_id}` | `{r.workflow}` | `{r.target_skill}` | **{r.score:.2f}** | {ev_str} | {proh_str} | {verdict_badge} |"
        )

    lines.append("")
    lines.append("## 🔍 Diagnostic Breakdown")
    lines.append("")
    for r in report.results:
        lines.append(f"### `{r.scenario_id}` ({r.title})")
        lines.append(
            f"- **Verdict**: `{r.status}` (Score: {r.score:.2f} / Threshold: {r.passing_threshold:.2f})"
        )
        lines.append(f"- **Workflow / Target**: `{r.workflow}` -> `{r.target_skill}`")
        lines.append(
            f"- **Dimensions**: {', '.join(f'{k}: {v}' for k, v in r.dimension_scores.items())}"
        )
        if r.evidence_missing:
            lines.append(
                f"- **Missing Evidence**: {', '.join(f'`{e}`' for e in r.evidence_missing)}"
            )
        if r.prohibited_triggered:
            lines.append(
                f"- **Triggered Prohibited Actions**: {', '.join(f'`{p}`' for p in r.prohibited_triggered)}"
            )
        if r.warnings:
            lines.append(f"- **Privacy / Telemetry Warnings**: {', '.join(r.warnings)}")
        lines.append("")

    return "\n".join(lines)


@dataclass
class RegressionDiff:
    scenario_id: str
    base_verdict: str
    head_verdict: str
    base_score: float
    head_score: float
    score_delta: float
    lost_evidence: list[str]
    new_prohibited: list[str]
    is_regression: bool


def compare_reports(base: BehaviorReport, head: BehaviorReport) -> list[RegressionDiff]:
    """Compares base and head reports; detects regressions and missing evidence."""
    base_map = {r.scenario_id: r for r in base.results}
    diffs: list[RegressionDiff] = []

    for head_r in head.results:
        base_r = base_map.get(head_r.scenario_id)
        if not base_r:
            continue

        score_delta = round(head_r.score - base_r.score, 2)
        lost_evidence = [e for e in base_r.evidence_found if e not in head_r.evidence_found]
        new_prohibited = [
            p for p in head_r.prohibited_triggered if p not in base_r.prohibited_triggered
        ]

        # Regression criteria: verdict went PASS -> FAIL, score dropped > 0.05,
        # lost evidence, or newly triggered prohibited outcome
        is_regression = (
            (base_r.status == "PASS" and head_r.status == "FAIL")
            or score_delta < -0.05
            or bool(lost_evidence)
            or bool(new_prohibited)
        )

        diffs.append(
            RegressionDiff(
                scenario_id=head_r.scenario_id,
                base_verdict=base_r.status,
                head_verdict=head_r.status,
                base_score=base_r.score,
                head_score=head_r.score,
                score_delta=score_delta,
                lost_evidence=lost_evidence,
                new_prohibited=new_prohibited,
                is_regression=is_regression,
            )
        )

    return diffs


def format_regression_markdown(
    diffs: list[RegressionDiff], base_commit: str, head_commit: str
) -> str:
    """Formats regression comparison diff table in Markdown."""
    regressions = [d for d in diffs if d.is_regression]
    lines = [
        "# 📉 Behavioral Regression Comparison",
        "",
        f"**Base Commit**: `{base_commit}` vs **Head Commit**: `{head_commit}`",
        "",
        f"Total Compared: **{len(diffs)}** | Regressions Detected: **{len(regressions)}**",
        "",
        "| Scenario ID | Base Score | Head Score | Delta | Base Status | Head Status | Status |",
        "|:---|---:|---:|---:|:---|:---|:---|",
    ]

    for d in diffs:
        delta_str = f"+{d.score_delta:.2f}" if d.score_delta > 0 else f"{d.score_delta:.2f}"
        status_badge = "❌ **Regression**" if d.is_regression else "✅ Maintained"
        lines.append(
            f"| `{d.scenario_id}` | {d.base_score:.2f} | {d.head_score:.2f} | {delta_str} | `{d.base_verdict}` | `{d.head_verdict}` | {status_badge} |"
        )

    if regressions:
        lines.append("")
        lines.append("### ⚠️ Detailed Regressions")
        for r in regressions:
            lines.append(f"- **`{r.scenario_id}`**:")
            if r.lost_evidence:
                lines.append(f"  - Lost Evidence: {', '.join(f'`{e}`' for e in r.lost_evidence)}")
            if r.new_prohibited:
                lines.append(
                    f"  - Newly Triggered Prohibited: {', '.join(f'`{p}`' for p in r.new_prohibited)}"
                )
            if r.score_delta < 0:
                lines.append(f"  - Score degraded by {r.score_delta:.2f}")

    return "\n".join(lines)


# =============================================================================
# CLI Main
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MaintainerSkillsLab Behavior Regression & Policy Evaluation Harness"
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=DEFAULT_SCENARIOS_FILE,
        help="Path to behavior scenarios JSON fixture file",
    )
    parser.add_argument(
        "--validate-scenarios",
        action="store_true",
        help="Validate scenario schemas and exit",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run deterministic offline evaluation on reference fixtures (network-free)",
    )
    parser.add_argument(
        "--provider",
        default="shared-library",
        help="Target provider identity (e.g. shared-library, claude, codex, cursor, opencode)",
    )
    parser.add_argument(
        "--client-model",
        default="offline-reference-fixture",
        help="Client and model identifier (e.g. claude-3-7-sonnet, gpt-4o, offline)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Path to write formatted Markdown scorecard",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Path to write structured JSON evaluation report",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASE_REPORT", "HEAD_REPORT"),
        help="Compare two JSON evaluation reports for behavioral regressions",
    )
    parser.add_argument(
        "--save-transcripts",
        action="store_true",
        help="Opt-in to include full response text in exported JSON (sensitive data will be redacted)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console progress messages",
    )

    args = parser.parse_args(argv)

    # 1. Compare Mode
    if args.compare:
        base_path, head_path = Path(args.compare[0]), Path(args.compare[1])
        base_data = json.loads(base_path.read_text(encoding="utf-8"))
        head_data = json.loads(head_path.read_text(encoding="utf-8"))

        def _to_report(d: dict) -> BehaviorReport:
            results = [
                ScenarioResult(
                    scenario_id=r["scenario_id"],
                    version=r.get("version", "1.0.0"),
                    workflow=r.get("workflow", ""),
                    target_skill=r.get("target_skill", ""),
                    title=r.get("title", ""),
                    status=r["status"],
                    score=r["score"],
                    passing_threshold=r.get("passing_threshold", 0.8),
                    dimension_scores=r.get("dimension_scores", {}),
                    evidence_found=r.get("evidence_found", []),
                    evidence_missing=r.get("evidence_missing", []),
                    prohibited_triggered=r.get("prohibited_triggered", []),
                    warnings=r.get("warnings", []),
                    response_summary=r.get("response_summary", ""),
                )
                for r in d.get("results", [])
            ]
            return BehaviorReport(
                version=d.get("version", "1.0.0"),
                timestamp=d.get("timestamp", ""),
                git_commit=d.get("git_commit", ""),
                provider=d.get("provider", ""),
                client_model=d.get("client_model", ""),
                total_scenarios=d.get("total_scenarios", len(results)),
                passed_scenarios=d.get("passed_scenarios", 0),
                failed_scenarios=d.get("failed_scenarios", 0),
                pass_rate_pct=d.get("pass_rate_pct", 0.0),
                average_score=d.get("average_score", 0.0),
                results=results,
            )

        base_report = _to_report(base_data)
        head_report = _to_report(head_data)
        diffs = compare_reports(base_report, head_report)
        md_diff = format_regression_markdown(diffs, base_report.git_commit, head_report.git_commit)

        if not args.quiet:
            print(md_diff)

        regressions = [d for d in diffs if d.is_regression]
        return 1 if regressions else 0

    # 2. Load & Validate Scenarios
    try:
        scenarios = load_scenarios(args.scenarios)
    except Exception as err:
        print(f"Error loading scenarios from {args.scenarios}: {err}", file=sys.stderr)
        return 1

    if args.validate_scenarios:
        if not args.quiet:
            print(
                f"✅ Successfully validated {len(scenarios)} behavior scenarios from {args.scenarios}"
            )
        return 0

    # 3. Offline Fixture Run
    if args.offline:
        report = run_offline_scenarios(
            scenarios,
            provider=args.provider,
            client_model=args.client_model,
        )

        md_content = generate_markdown_report(report)

        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(md_content, encoding="utf-8")
            if not args.quiet:
                print(f"📄 Markdown scorecard written to {args.report}")

        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            report_dict = asdict(report)
            if not args.save_transcripts:
                # Omit raw transcripts by default to keep json compact and private
                for item in report_dict["results"]:
                    item.pop("response_summary", None)
            args.output_json.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
            if not args.quiet:
                print(f"📊 JSON report written to {args.output_json}")

        if not args.quiet:
            print(md_content)

        return 0 if report.failed_scenarios == 0 else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
