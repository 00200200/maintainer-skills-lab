"""Opt-in, offline container adapters; only genuine agent responses reach M2."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evals.arena import fuzzer, redteam
from evals.arena.runner import markdown_cell, safe_text
from tools import container_sandbox as sandbox

PROTOCOL_VERSION = 1
DEFAULT_LIMIT = 5
MAX_PAIRS = 100
TIMEOUT_SECONDS = 60
SCOPE = (
    "Offline container adapter execution with heuristic response verification, not a full "
    "security audit. Agent execution is declared by the trusted adapter, not independently "
    "attested. Adapter-test outputs are not scored. DEFENDED means only that the M2 "
    "verifier found no configured indicator in a valid agent response."
)
STATUSES = ("COMPLETED", "FAILED", "TIMEOUT", "UNAVAILABLE")


def parse_response(stdout: str, scenario_id: str, skill: str) -> tuple[str, str]:
    """One strict UTF-8 JSON object; echoes bind the response to the supplied pair."""
    if len(stdout.encode("utf-8")) > 65_536:
        raise ValueError("Adapter response exceeds the output limit")
    try:
        data = json.loads(
            stdout,
            object_pairs_hook=redteam._unique_fields,
            parse_constant=redteam._reject_constant,
        )
    except (ValueError, RecursionError) as error:
        raise ValueError("Adapter stdout is not one valid JSON response") from error
    if (
        not isinstance(data, dict)
        or set(data) != {"protocol_version", "scenario_id", "skill", "response", "execution_kind"}
        or type(data["protocol_version"]) is not int
        or data["protocol_version"] != PROTOCOL_VERSION
        or data["scenario_id"] != scenario_id
        or data["skill"] != skill
        or not isinstance(data["execution_kind"], str)
        or data["execution_kind"] not in {"agent", "adapter-test"}
        or not isinstance(data["response"], str)
        or not data["response"].strip()
    ):
        raise ValueError("Adapter response violates protocol version 1 or scenario/skill binding")
    try:
        data["response"].encode("utf-8")
    except UnicodeError as error:
        raise ValueError("Adapter response contains invalid Unicode") from error
    return data["response"], data["execution_kind"]


@dataclass
class AgentExecution:
    scenario_id: str
    skill: str
    status: str
    detail: str
    execution_kind: str | None = None
    duration_seconds: float = 0
    cleanup_error: str = ""


@dataclass
class AgentReport:
    scoring: redteam.RedteamReport
    image: str
    runtime: str | None
    limit: int
    image_id: str = ""
    executions: list[AgentExecution] = field(default_factory=list)

    @property
    def status(self) -> str:
        for status in ("FAILED", "TIMEOUT", "UNAVAILABLE"):
            if any(item.status == status for item in self.executions):
                return status
        return "COMPLETED" if self.executions else "UNAVAILABLE"

    def to_dict(self) -> dict:
        return {
            **self.scoring.to_dict(),
            "benchmark": "agent",
            "status": self.status,
            "scoring_status": self.scoring.status,
            "image": self.image,
            "image_id": self.image_id,
            "runtime": self.runtime,
            "executions": [asdict(item) for item in self.executions],
            "execution_summary": {
                status: sum(item.status == status for item in self.executions)
                for status in STATUSES
            },
            "limits": {
                "max_pairs": self.limit,
                "timeout_seconds": TIMEOUT_SECONDS,
                "stdout_bytes": 65_536,
                "stderr_bytes": 16_384,
                "memory": "512m",
                "cpus": "1.0",
                "pids": 64,
                "network": "none",
                "read_only": True,
                "user": "65534:65534",
                "mount_workspace": False,
                "pull_policy": "never",
            },
        }


def _inspect_image(runtime: str, image: str) -> str:
    """Inspect only local images, reject implicit volumes, then pin the image ID."""
    result = sandbox.run_bounded(
        sandbox.local_runtime_args(runtime) + ["image", "inspect", image],
        timeout_seconds=5,
        stdout_limit=262_144,
        stderr_limit=4096,
    )
    if result.exit_code or result.timed_out or result.output_limited:
        raise ValueError("Local image/engine unavailable; no image was pulled")
    try:
        images = json.loads(result.stdout.decode("utf-8"))
        if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
            raise ValueError("Invalid image inspection result")
        image_id = images[0].get("Id")
        if (
            runtime == "podman"
            and isinstance(image_id, str)
            and re.fullmatch(r"[0-9a-f]{64}", image_id)
        ):
            image_id = f"sha256:{image_id}"
        config = images[0].get("Config")
        if not isinstance(config, dict) or config.get("Volumes") not in (None, {}):
            raise ValueError("Agent images must not declare VOLUME mounts")
        if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("Image inspection did not return a valid immutable image ID")
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid image inspection result") from error
    return image_id


def run_agent(
    image: str,
    *,
    fixtures: Path | None = None,
    limit: int = DEFAULT_LIMIT,
) -> AgentReport:
    if not isinstance(image, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}", image
    ):
        raise ValueError(
            "Agent image must be a local image reference without options or whitespace"
        )
    if type(limit) is not int or not 1 <= limit <= MAX_PAIRS:
        raise ValueError(f"Agent pair limit must be between 1 and {MAX_PAIRS}")
    cases = fuzzer.load_fixture_file(fixtures if fixtures is not None else fuzzer.DEFAULT_FIXTURES)
    pairs = [(case, skill) for case in cases for skill in case.target_skills][:limit]
    runtime = sandbox.detect_container_runtime()
    report = AgentReport(redteam.score_records({}, cases), image, runtime, limit)
    records = {}
    canaries = sorted(
        {case.canary_token for case in cases if case.canary_token}, key=len, reverse=True
    )

    def clean(text: str) -> str:
        for canary in canaries:
            text = text.replace(canary, "[REDACTED_CANARY]")
        return safe_text(text)

    try:
        if runtime is None:
            raise ValueError("No Docker or Podman executable found on PATH")
        report.image_id = _inspect_image(runtime, image)
    except (OSError, ValueError) as error:
        report.executions = [
            AgentExecution(case.id, skill, "UNAVAILABLE", clean(str(error)))
            for case, skill in pairs
        ]
    else:
        for case, skill in pairs:
            request = (
                json.dumps(
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "scenario_id": case.id,
                        "skill": skill,
                        "input_text": case.input_text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
            item = AgentExecution(case.id, skill, "FAILED", "Adapter execution failed")
            try:
                execution = sandbox.execute_adapter(
                    runtime=runtime,
                    image=report.image_id,
                    request=request,
                    container_name=f"msl-arena-agent-{uuid.uuid4().hex}",
                    timeout_seconds=TIMEOUT_SECONDS,
                )
                item.duration_seconds = execution.duration_seconds
                item.cleanup_error = clean(execution.cleanup_error)
                if execution.timed_out or execution.status == "TIMED_OUT":
                    item.status, item.detail = (
                        "TIMEOUT",
                        "Adapter exceeded its execution time limit",
                    )
                elif execution.output_limited:
                    item.detail = "Adapter stdout/stderr exceeded its byte limit"
                elif execution.status == "ERROR" or execution.exit_code in {125, 126, 127}:
                    item.status, item.detail = "UNAVAILABLE", "Runtime or adapter could not start"
                elif execution.status != "COMPLETED" or execution.exit_code:
                    item.detail = (
                        f"Adapter did not complete successfully (exit {execution.exit_code})"
                    )
                elif execution.security != sandbox.SecurityConfig():
                    item.detail = "Sandbox reported unexpected isolation settings"
                else:
                    response, kind = parse_response(execution.stdout, case.id, skill)
                    item.status, item.execution_kind = "COMPLETED", kind
                    item.detail = (
                        "Valid agent response"
                        if kind == "agent"
                        else "Adapter test only; not evaluated"
                    )
                    if kind == "agent":
                        records[(case.id, skill)] = response
                # Raw stdout/stderr never enter reports; M2 alone renders redacted excerpts.
                if item.cleanup_error:
                    item.status = "FAILED"
                    records.pop((case.id, skill), None)
            except (OSError, ValueError) as error:
                item.detail = clean(str(error))
            report.executions.append(item)
            if item.cleanup_error:
                break  # Do not accumulate more containers after a cleanup failure.
    report.scoring = redteam.score_records(records, cases)
    report.scoring.benchmark = "agent"
    report.scoring.evidence_kind = (
        "container-adapter-agent-responses" if records else "container-adapter-no-agent-responses"
    )
    report.scoring.live_agent_run = bool(records)
    report.scoring.scope = SCOPE
    return report


def markdown_report(report: AgentReport) -> str:
    lines = [
        "# MSL-Arena Agent — isolated adapter execution",
        "",
        SCOPE,
        "",
        f"Execution: **{report.status}**; scoring: **{report.scoring.status}**.",
        "",
        f"Evidence: {report.scoring.evidence_kind}. Valid agent responses: {report.scoring.summary['evaluated_cases']}.",
        "",
        f"Local image ID: {markdown_cell(report.image_id or 'unavailable')}",
        "",
        "| Scenario | Skill | Execution | Kind | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.executions:
        lines.append(
            f"| {markdown_cell(item.scenario_id)} | {markdown_cell(item.skill)} | {item.status} | "
            f"{item.execution_kind or 'none'} | {markdown_cell(item.detail + ' ' + item.cleanup_error)} |"
        )
    lines.extend(
        [
            "",
            redteam.markdown_report(
                report.scoring, heading="Agent response scoring (M2 heuristics)"
            ),
        ]
    )
    return "\n".join(lines)
