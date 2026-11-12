"""Run the fixed mini benchmark through the shared container sandbox."""

from __future__ import annotations

import html
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from evals.arena.scenarios import SmokeScenario, mini_scenarios
from evals.behavior_harness import redact_sensitive_content
from tools import container_sandbox as sandbox

DEFAULT_IMAGE = "python:3.11-alpine"
TIMEOUT_SECONDS = 10
CONTROL_TIMEOUT_SECONDS = 5
MEMORY = "128m"
CPUS = "0.5"
STATUSES = ("PASS", "FAIL", "TIMEOUT", "SKIPPED", "UNAVAILABLE")
SCOPE = "Infrastructure smoke checks only; no model, agent run or resistance evaluation."


def safe_text(text: str) -> str:
    redacted, _ = redact_sensitive_content(text)
    return sandbox.truncate_output(redacted)


@dataclass
class ArenaResult:
    scenario_id: str
    title: str
    status: str
    reason: str
    execution: sandbox.SandboxResult | None = None
    cleanup_error: str = ""


@dataclass
class ArenaReport:
    image: str
    runtime: str | None
    image_id: str = ""
    results: list[ArenaResult] = field(default_factory=list)
    benchmark: str = "mini"
    schema_version: int = 1
    evidence_kind: str = "infrastructure-smoke"
    agent_evaluation: bool = False
    scope: str = SCOPE

    @property
    def summary(self) -> dict[str, int]:
        return {status: sum(item.status == status for item in self.results) for status in STATUSES}

    @property
    def status(self) -> str:
        counts = self.summary
        for status in ("FAIL", "TIMEOUT", "UNAVAILABLE", "SKIPPED"):
            if counts[status]:
                return status
        return "PASS" if len(self.results) == 5 and counts["PASS"] == 5 else "UNAVAILABLE"

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "status": self.status,
            "summary": self.summary,
            "limits": {
                "timeout_seconds": TIMEOUT_SECONDS,
                "control_timeout_seconds": CONTROL_TIMEOUT_SECONDS,
                "pull_policy": "never",
                "mount_workspace": False,
                **asdict(sandbox.SecurityConfig(memory_limit=MEMORY, cpu_limit=CPUS)),
            },
        }


def _unavailable(report: ArenaReport, scenarios: tuple[SmokeScenario, ...], reason: str):
    report.results = [
        ArenaResult(item.id, item.title, "UNAVAILABLE", safe_text(reason)) for item in scenarios
    ]
    return report


def _cleanup(runtime: str, name: str) -> str:
    try:
        result = subprocess.run(
            [runtime, "rm", "--force", name],
            capture_output=True,
            text=True,
            timeout=CONTROL_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode:
            return safe_text(result.stderr or "Container cleanup did not succeed.")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return safe_text(f"Container cleanup failed: {exc}")
    return ""


def _classify(scenario: SmokeScenario, execution: sandbox.SandboxResult) -> tuple[str, str]:
    if execution.timed_out or execution.status == "TIMED_OUT":
        return "TIMEOUT", f"Sandbox exceeded the {TIMEOUT_SECONDS}s execution limit."
    if execution.status in {"RUNTIME_UNAVAILABLE", "ERROR"}:
        return "UNAVAILABLE", "Sandbox could not execute the scenario; see execution diagnostics."
    if execution.status != "COMPLETED":
        return "FAIL", "Unexpected sandbox status."
    if execution.exit_code in {125, 126, 127}:
        return "UNAVAILABLE", "Runtime or image command could not start successfully."
    if execution.exit_code != 0:
        return "FAIL", f"Scenario exited with code {execution.exit_code}."
    expected_security = sandbox.SecurityConfig(memory_limit=MEMORY, cpu_limit=CPUS)
    if execution.security != expected_security:
        return "FAIL", "Sandbox reported unexpected security settings."
    if execution.stdout.strip() != scenario.expected_stdout:
        return "FAIL", "Scenario output did not match its fixed expected marker."
    return "PASS", "Container smoke assertion and expected output matched."


def run_mini(image: str = DEFAULT_IMAGE) -> ArenaReport:
    if not image or image.startswith("-") or any(character.isspace() for character in image):
        raise ValueError("Image must be a nonempty local image reference without whitespace.")
    scenarios = mini_scenarios()
    runtime = sandbox.detect_container_runtime()
    report = ArenaReport(image=image, runtime=runtime)
    if runtime is None:
        return _unavailable(report, scenarios, "No Docker or Podman executable found on PATH.")
    try:
        inspected = subprocess.run(
            [runtime, "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=CONTROL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _unavailable(report, scenarios, f"Local runtime/image preflight failed: {exc}")
    if inspected.returncode or not inspected.stdout.strip():
        return _unavailable(
            report,
            scenarios,
            "Local runtime/image unavailable; no images are pulled. " + inspected.stderr,
        )
    report.image_id = safe_text(inspected.stdout.strip())

    with tempfile.TemporaryDirectory(prefix="msl-arena-") as temporary:
        for scenario in scenarios:
            script = Path(temporary) / f"{scenario.id}.py"
            script.write_text(scenario.source, encoding="utf-8")
            name = f"msl-arena-{uuid.uuid4().hex}"
            cleanup_needed = True
            cleanup_error = ""
            try:
                execution = sandbox.execute_sandbox(
                    script_path=script,
                    timeout_seconds=TIMEOUT_SECONDS,
                    image=image,
                    mount_workspace=False,
                    allow_network=False,
                    memory=MEMORY,
                    cpus=CPUS,
                    runtime_override=runtime,
                    pull_never=True,
                    container_name=name,
                )
                cleanup_needed = execution.timed_out or execution.status != "COMPLETED"
                status, reason = _classify(scenario, execution)
                result = ArenaResult(
                    scenario.id,
                    scenario.title,
                    status,
                    reason,
                    replace(
                        execution,
                        stdout=safe_text(execution.stdout),
                        stderr=safe_text(execution.stderr),
                    ),
                )
            except Exception as exc:
                result = ArenaResult(
                    scenario.id,
                    scenario.title,
                    "FAIL",
                    safe_text(f"Sandbox invocation failed: {exc}"),
                )
            finally:
                # A host CLI timeout does not itself guarantee container termination.
                if cleanup_needed:
                    cleanup_error = _cleanup(runtime, name)
            result.cleanup_error = cleanup_error
            report.results.append(result)
    return report


def markdown_cell(value: str) -> str:
    """Render diagnostic text without interpreting it as report markup."""
    escaped = html.escape(value, quote=False).replace("\r", " ").replace("\n", " ")
    return escaped.translate(
        str.maketrans(
            {
                "|": "&#124;",
                "`": "&#96;",
                "[": "&#91;",
                "]": "&#93;",
                "*": "&#42;",
                "_": "&#95;",
                "\\": "&#92;",
            }
        )
    )


def markdown_report(report: ArenaReport) -> str:
    cell = markdown_cell

    counts = " | ".join(f"{status}: {count}" for status, count in report.summary.items())
    lines = [
        "# MSL-Arena Mini — infrastructure smoke report",
        "",
        SCOPE,
        "",
        f"Overall: **{report.status}**",
        "",
        counts,
        "",
        f"Runtime: {cell(report.runtime or 'unavailable')} · Image: {cell(report.image)}",
        f"Local image ID: {cell(report.image_id or 'unavailable')}",
        "",
        f"Requested limits: {TIMEOUT_SECONDS}s per scenario, {MEMORY} memory, {CPUS} CPUs; "
        "network none, read-only root/script, 64m temporary scratch. No image pulls.",
        "",
        "| Scenario | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for item in report.results:
        lines.append(
            f"| {cell(item.scenario_id + ': ' + item.title)} | {item.status} | {cell(item.reason)} |"
        )
    lines.extend(["", "## Diagnostics", ""])
    for item in report.results:
        lines.extend([f"### {cell(item.scenario_id)}", ""])
        if item.execution is not None:
            lines.append(
                f"Exit code: {item.execution.exit_code}; duration: {item.execution.duration_seconds}s."
            )
            for label, text in (
                ("stdout", item.execution.stdout),
                ("stderr", item.execution.stderr),
            ):
                if text:
                    lines.append(f"- {label}: {cell(text)}")
        if item.cleanup_error:
            lines.append(f"- Cleanup warning (container may remain): {cell(item.cleanup_error)}")
        lines.append("")
    return "\n".join(lines)
