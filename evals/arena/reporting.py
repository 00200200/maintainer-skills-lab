"""Offline, provenance-aware report tables; never run benchmarks or rescore responses."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from pathlib import Path

from evals import injection_harness as injection
from evals.arena import agent_runner, fuzzer, redteam, runner, swebench_eval

MAX_REPORTS = 100
MAX_REPORT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_CASES = 2400
METRICS = {
    "attack_success_rate_pct": "lower",
    "resolution_rate_pct": "higher",
    "infrastructure_pass_pct": "higher",
}
LIMITATIONS = [
    "Offline JSON validation cannot authenticate execution, dataset provenance or freshness.",
    "Provenance declarations and M5b harness confirmation are user assertions, not attestation.",
    "Different benchmarks, evaluation sets and evaluators are never pooled into a global score.",
    "Legacy M1/M2/M4 comparisons require explicit evaluation-set and evaluator fingerprints.",
    "Missing, partial, synthetic, adapter-test and unverified evidence has no ranked metric or delta.",
    "Preparation, fixture generation and harness process completion are not model successes.",
    "Report excerpts, private task data, predictions and host commands are omitted from this table.",
]


def _require(condition, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value, label: str, limit: int = 2048) -> str:
    _require(
        isinstance(value, str) and len(value) <= limit and "\x00" not in value, f"Invalid {label}"
    )
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"Invalid Unicode in {label}") from error
    return value


def _id(value) -> str:
    return swebench_eval._identifier(value, "report identifier")


def _arena_id(value) -> str:
    _text(value, "scenario/skill identifier", 256)
    _require(bool(fuzzer.IDENTIFIER.fullmatch(value)), "Invalid scenario/skill identifier")
    return value


def _model(value) -> str:
    _text(value, "model identity", 200)
    _require(
        bool(swebench_eval.MODEL.fullmatch(value))
        and all(part not in ("", ".", "..") for part in value.split("/")),
        "Invalid model identity",
    )
    return value


def _sha(value) -> str:
    _require(
        isinstance(value, str) and bool(swebench_eval.SHA256.fullmatch(value)),
        "Invalid report SHA-256",
    )
    return value


def _number(value, *, maximum: float = 100) -> float:
    _require(
        type(value) in (int, float) and 0 <= value <= maximum and math.isfinite(value),
        "Invalid finite report number",
    )
    return float(value)


def _integer(value, minimum=0, maximum=MAX_CASES) -> int:
    _require(type(value) is int and minimum <= value <= maximum, "Invalid report count")
    return value


def _equal(actual, expected) -> None:
    # JSON canonicalization distinguishes booleans from integers.
    _require(
        swebench_eval._canonical(actual) == swebench_eval._canonical(expected),
        "Report summary/status contradicts its records",
    )


def _metric(actual, expected) -> None:
    if expected is None:
        _require(actual is None, "A missing metric must be null")
    else:
        _require(
            math.isclose(_number(actual), expected, rel_tol=0, abs_tol=1e-9),
            "Report metric contradicts its counts",
        )


def _list(value, minimum=0, maximum=MAX_CASES) -> list:
    _require(isinstance(value, list) and minimum <= len(value) <= maximum, "Invalid report list")
    return value


def _ids(value, minimum=1, maximum=MAX_CASES) -> list[str]:
    values = [_id(item) for item in _list(value, minimum, maximum)]
    _require(len(set(values)) == len(values), "Duplicate report identifiers")
    return values


def _base(benchmark: str, phase: str, source_status: str, total: int, evaluated: int) -> dict:
    return {
        "benchmark": benchmark,
        "phase": phase,
        "source_status": source_status,
        "evaluation_status": "NOT_EVALUATED"
        if not evaluated
        else "INCOMPLETE"
        if evaluated < total
        else "EVALUATED",
        "coverage": {
            "evaluated": evaluated,
            "total": total,
            "pct": 100.0 * evaluated / total if total else None,
        },
        "metric": None,
        "value": None,
        "comparison_key": None,
        "reliability": "UNVERIFIED",
        "subject": None,
        "run_id": None,
        "notes": [],
    }


def _mini(data: dict) -> tuple[dict, dict, float | None]:
    _require(
        data.get("agent_evaluation") is False
        and data.get("evidence_kind") == "infrastructure-smoke",
        "Invalid Mini evidence flags",
    )
    for key in ("image", "image_id", "scope"):
        _text(data[key], key)
    if data["image_id"]:
        _sha(data["image_id"].removeprefix("sha256:"))
    _require(data["runtime"] in (None, "docker", "podman"), "Invalid Mini runtime")
    _require(isinstance(data["limits"], dict), "Missing Mini limits")
    template = runner.ArenaReport(data["image"], data["runtime"])
    _equal(data["limits"], template.to_dict()["limits"])
    results, seen = [], set()
    reliable = bool(data["image_id"]) and data["runtime"] in {"docker", "podman"}
    scope = []
    for item in _list(data["results"], 5, 5):
        _require(
            isinstance(item, dict)
            and set(item)
            == {"scenario_id", "title", "status", "reason", "execution", "cleanup_error"},
            "Invalid Mini result schema",
        )
        key = _id(item["scenario_id"])
        _require(
            key not in seen and item["status"] in runner.STATUSES,
            "Duplicate Mini ID or unknown outcome",
        )
        seen.add(key)
        for name in ("title", "reason", "cleanup_error"):
            _text(item[name], name, 20_000)
        execution = item["execution"]
        if execution is not None:
            _require(
                isinstance(execution, dict)
                and set(execution)
                == {
                    "status",
                    "exit_code",
                    "duration_seconds",
                    "timed_out",
                    "runtime_detected",
                    "stdout",
                    "stderr",
                    "security",
                },
                "Invalid Mini execution",
            )
            _require(
                type(execution["exit_code"]) is int and type(execution["timed_out"]) is bool,
                "Invalid Mini execution flags",
            )
            _number(execution["duration_seconds"], maximum=86_400)
            _text(execution["stdout"], "stdout", 20_000)
            _text(execution["stderr"], "stderr", 20_000)
            _require(
                execution["status"] in {"COMPLETED", "TIMED_OUT", "ERROR", "RUNTIME_UNAVAILABLE"},
                "Unknown sandbox status",
            )
            _require(
                execution["runtime_detected"] in (None, "docker", "podman"),
                "Invalid sandbox runtime",
            )
            security = execution["security"]
            _require(
                isinstance(security, dict)
                and set(security)
                == {"network", "memory_limit", "cpu_limit", "read_only", "tmpfs_mounted"},
                "Invalid sandbox security metadata",
            )
            for name in ("network", "memory_limit", "cpu_limit"):
                _text(security[name], name)
            _require(
                type(security["read_only"]) is bool and type(security["tmpfs_mounted"]) is bool,
                "Invalid sandbox security flags",
            )
        if item["status"] == "PASS":
            _require(
                bool(data["image_id"]) and data["runtime"] in {"docker", "podman"},
                "PASS without Mini image/runtime metadata",
            )
            _require(
                execution is not None
                and execution["status"] == "COMPLETED"
                and execution["exit_code"] == 0
                and not execution["timed_out"],
                "PASS without completed Mini execution",
            )
            _equal(
                execution["security"],
                {
                    "network": "none",
                    "memory_limit": runner.MEMORY,
                    "cpu_limit": runner.CPUS,
                    "read_only": True,
                    "tmpfs_mounted": True,
                },
            )
        reliable = (
            reliable
            and item["status"] in {"PASS", "FAIL"}
            and execution is not None
            and execution["status"] == "COMPLETED"
            and not item["cleanup_error"]
        )
        results.append(runner.ArenaResult(key, item["title"], item["status"], ""))
        scope.append([key, item["title"]])
    _equal(sorted(seen), [f"mini-{number:02d}" for number in range(1, 6)])
    template.results = results
    _equal(data["summary"], template.summary)
    _equal(data["status"], template.status)
    evaluated = sum(
        item["status"] in {"PASS", "FAIL"}
        and isinstance(item["execution"], dict)
        and item["execution"]["status"] == "COMPLETED"
        and not item["execution"]["timed_out"]
        for item in data["results"]
    )
    row = _base("mini", "infrastructure", data["status"], 5, evaluated)
    row["counts"] = template.summary
    row["subject"] = data["image_id"] or data["image"]
    row["notes"].append("Infrastructure smoke outcomes only; never a model score.")
    if not reliable:
        row["notes"].append("Incomplete execution or cleanup diagnostics block comparisons.")
    context = {
        "scope": sorted(scope),
        "image_id": data["image_id"],
        "runtime": data["runtime"],
        "limits": data["limits"],
    }
    return row, context, 100.0 * template.summary["PASS"] / 5 if reliable else None


def _responses(data: dict) -> tuple[dict, dict, float | None]:
    results, pairs = [], set()
    for item in _list(data["results"], 1):
        _require(
            isinstance(item, dict)
            and set(item) == {field.name for field in fields(injection.EvaluationResult)},
            "Invalid response-result schema",
        )
        pair = (_arena_id(item["test_id"]), _arena_id(item["skill"]))
        _require(
            pair not in pairs and item["verdict"] in {"DEFENDED", "COMPROMISED", "NOT_EVALUATED"},
            "Duplicate response pair or unknown verdict",
        )
        pairs.add(pair)
        for name in ("category", "title", "output_summary"):
            _text(item[name], name)
        for reason in _list(item["reasons"], maximum=100):
            _text(reason, "reason", 20_000)
        flags = [item["canary_leaked"], item["forbidden_action_detected"]]
        if item["verdict"] == "NOT_EVALUATED":
            _require(flags == [None, None], "Missing responses must have unchecked flags")
        else:
            _require(all(type(flag) is bool for flag in flags), "Invalid response detection flags")
            _require(
                any(flags) == (item["verdict"] == "COMPROMISED"),
                "Verdict contradicts detection flags",
            )
        results.append(injection.EvaluationResult(**item))
    scoring = redteam.RedteamReport(results)
    expected = scoring.summary
    _require(
        isinstance(data["summary"], dict) and set(data["summary"]) == set(expected),
        "Invalid response summary fields",
    )
    for name, value in expected.items():
        if name == "attack_success_rate_pct":
            _metric(data["summary"][name], value)
        else:
            _equal(data["summary"][name], value)
    _text(data["scope"], "scope", 4096)
    benchmark = data["benchmark"]
    row = _base(
        benchmark,
        "recorded-responses" if benchmark == "redteam" else "container-agent",
        data["status"],
        len(results),
        expected["evaluated_cases"],
    )
    row["outcome_status"] = scoring.status
    row["counts"] = {
        "DEFENDED": expected["defended_cases"],
        "COMPROMISED": expected["compromised_cases"],
        "NOT_EVALUATED": expected["not_evaluated_cases"],
    }
    context = {
        "scope": sorted([[item.test_id, item.skill, item.category] for item in results]),
        "scope_statement": data["scope"],
    }
    value = expected["attack_success_rate_pct"] if expected["not_evaluated_cases"] == 0 else None
    if benchmark == "redteam":
        _equal(data["status"], scoring.status)
        _require(
            data.get("evidence_kind") == "heuristic-recorded-responses"
            and data.get("live_agent_run") is False,
            "Invalid recorded-response evidence flags",
        )
        row["notes"].append(
            "Heuristic recordings; old reports do not authenticate agent or fixture provenance."
        )
        return row, context, value
    _equal(data["scoring_status"], scoring.status)
    _require(
        type(data.get("live_agent_run")) is bool
        and data["live_agent_run"] == bool(expected["evaluated_cases"]),
        "Invalid agent-run evidence flag",
    )
    kind = (
        "container-adapter-agent-responses"
        if expected["evaluated_cases"]
        else "container-adapter-no-agent-responses"
    )
    _equal(data["evidence_kind"], kind)
    _require(isinstance(data["limits"], dict), "Missing adapter limits")
    maximum = _integer(data["limits"].get("max_pairs"), 1, 100)
    executions, by_pair = [], {}
    result_map = {(item.test_id, item.skill): item for item in results}
    for item in _list(data["executions"], 1, maximum):
        _require(
            isinstance(item, dict)
            and set(item) == {field.name for field in fields(agent_runner.AgentExecution)},
            "Invalid adapter execution schema",
        )
        pair = (_arena_id(item["scenario_id"]), _arena_id(item["skill"]))
        _require(
            pair in pairs and pair not in by_pair and item["status"] in agent_runner.STATUSES,
            "Unknown or duplicate adapter execution",
        )
        _require(
            item["execution_kind"] in (None, "agent", "adapter-test"),
            "Invalid adapter execution kind",
        )
        _number(item["duration_seconds"], maximum=86_400)
        _text(item["detail"], "detail", 20_000)
        _text(item["cleanup_error"], "cleanup error", 20_000)
        if item["status"] == "COMPLETED":
            _require(
                item["execution_kind"] in {"agent", "adapter-test"} and not item["cleanup_error"],
                "Completed adapter result has no valid execution kind",
            )
        scored = (
            item["status"] == "COMPLETED"
            and item["execution_kind"] == "agent"
            and not item["cleanup_error"]
        )
        _require(
            scored == (result_map[pair].verdict != "NOT_EVALUATED"),
            "Adapter execution and scoring coverage disagree",
        )
        by_pair[pair] = item
        executions.append(agent_runner.AgentExecution(**item))
    _require(
        all(
            item.verdict == "NOT_EVALUATED" or pair in by_pair for pair, item in result_map.items()
        ),
        "Scored response has no adapter execution",
    )
    template = agent_runner.AgentReport(
        scoring,
        _text(data["image"], "image"),
        data["runtime"],
        maximum,
        _text(data["image_id"], "image ID"),
        executions,
    )
    _require(data["runtime"] in (None, "docker", "podman"), "Invalid adapter runtime")
    _equal(data["limits"], template.to_dict()["limits"])
    _equal(data["execution_summary"], template.to_dict()["execution_summary"])
    _equal(data["status"], template.status)
    row["execution_status"] = data["status"]
    context.update(runtime=data["runtime"], execution_limits=data["limits"])
    if expected["evaluated_cases"]:
        _require(
            data["runtime"] in {"docker", "podman"} and data["image_id"].startswith("sha256:"),
            "Scored agent report lacks local image/runtime metadata",
        )
        _sha(data["image_id"][7:])
    row["subject"] = data["image_id"] or data["image"]
    if any(item.execution_kind == "adapter-test" for item in executions):
        row["notes"].append("Adapter-test outputs are not model evaluations.")
    if data["status"] != "COMPLETED" or any(item.cleanup_error for item in executions):
        value = None
        row["notes"].append("Adapter execution failures block comparison.")
    row["notes"].append("Agent execution is adapter-declared, not independently attested.")
    return row, context, value


def _prediction_rows(value) -> list[dict]:
    records = _list(value, 1, 50)
    seen = set()
    for item in records:
        _require(isinstance(item, dict), "Invalid prediction binding")
        key = _id(item["instance_id"])
        _require(
            key not in seen and item["prediction_status"] in {"READY", "MISSING", "INVALID_PATCH"},
            "Duplicate or invalid prediction binding",
        )
        seen.add(key)
        if item["prediction_status"] == "MISSING":
            _require(
                item["prediction_sha256"] is None and item["model_patch_sha256"] is None,
                "Missing prediction has hashes",
            )
        else:
            _sha(item["prediction_sha256"])
            if item["prediction_status"] == "READY" or item["model_patch_sha256"] is not None:
                _sha(item["model_patch_sha256"])
    return records


def _swe_results(data: dict) -> tuple[dict, dict, float | None]:
    _id(data["run_id"])
    for name in (
        "manifest_sha256",
        "source_sha256",
        "predictions_sha256",
        "export_sha256",
        "run_manifest_sha256",
    ):
        _sha(data[name])
    _equal(data["results_format"], swebench_eval.RESULTS_FORMAT)
    _text(data["scope"], "scope", 4096)
    _text(data["results_directory"], "results directory", 8192)
    rows = _prediction_rows(data["results"])
    counts = {status: 0 for status in ("RESOLVED", "UNRESOLVED", "ERROR", "NOT_EVALUATED")}
    for item in rows:
        _require(
            set(item).issubset(
                {
                    "instance_id",
                    "prediction_status",
                    "prediction_sha256",
                    "model_patch_sha256",
                    "status",
                    "reason",
                    "report_sha256",
                    "artifact_patch_sha256",
                }
            ),
            "Unsupported SWE-bench result fields",
        )
        _require(item.get("status") in counts, "Unknown SWE-bench result outcome")
        _text(item["reason"], "result reason")
        counts[item["status"]] += 1
        if item["prediction_status"] == "MISSING":
            _equal(item["status"], "NOT_EVALUATED")
        elif item["prediction_status"] == "INVALID_PATCH":
            _equal(item["status"], "ERROR")
        if item["status"] in {"RESOLVED", "UNRESOLVED"}:
            _equal(item["prediction_status"], "READY")
            _equal(item["reason"], "BOUND_HARNESS_REPORT")
            _sha(item["report_sha256"])
            _equal(_sha(item["artifact_patch_sha256"]), item["model_patch_sha256"])
        for name in ("report_sha256", "artifact_patch_sha256"):
            if name in item:
                _sha(item[name])
    evaluated = counts["RESOLVED"] + counts["UNRESOLVED"]
    present = sum(item["prediction_status"] != "MISSING" for item in rows)
    confirmed = data["harness_run_confirmed_by_user"]
    _require(type(confirmed) is bool, "Invalid harness confirmation flag")
    _equal(
        data["evidence_kind"],
        "user-attested-official-harness-artifacts" if confirmed else "unattested-harness-artifacts",
    )
    complete = evaluated == len(rows)
    available = complete and confirmed
    expected = {
        **counts,
        "selected_tasks": len(rows),
        "predictions_present": present,
        "evaluated_tasks": evaluated,
        "coverage_pct": 100.0 * evaluated / len(rows),
        "prediction_coverage_pct": 100.0 * present / len(rows),
        "metrics_available": available,
        "resolution_rate_pct": 100.0 * counts["RESOLVED"] / len(rows) if available else None,
        "pass_at_1": counts["RESOLVED"] / len(rows) if available else None,
    }
    _require(
        isinstance(data["summary"], dict) and set(data["summary"]) == set(expected),
        "Invalid SWE-bench summary fields",
    )
    for name, value in expected.items():
        if name in {"coverage_pct", "prediction_coverage_pct", "resolution_rate_pct", "pass_at_1"}:
            _metric(data["summary"][name], value)
        else:
            _equal(data["summary"][name], value)
    _equal(data["status"], "COMPLETE" if complete else "INCOMPLETE")
    row = _base("swebench-results", "harness-results", data["status"], len(rows), evaluated)
    if counts["ERROR"]:
        row["evaluation_status"] = "ERROR"
    row["counts"] = counts
    row["run_id"] = data["run_id"]
    row["subject"] = data["model_name_or_path"]
    _require(
        row["subject"] is None
        if not present
        else isinstance(row["subject"], str) and bool(row["subject"].strip()),
        "Invalid SWE-bench model identity",
    )
    if row["subject"] is not None:
        _model(row["subject"])
    row["reliability"] = "USER_ATTESTED" if confirmed else "UNVERIFIED"
    context = {
        "scope": sorted(item["instance_id"] for item in rows),
        "manifest_sha256": data["manifest_sha256"],
        "source_sha256": data["source_sha256"],
        "results_format": data["results_format"],
    }
    if not confirmed:
        row["notes"].append("Harness artifacts were not confirmed by the user.")
    return row, context, expected["resolution_rate_pct"]


def _preparation(data: dict, path: Path, digest: str) -> dict:
    benchmark = data["benchmark"]
    if benchmark == "swebench":
        manifest, tasks, checked_hash = swebench_eval.load_manifest(path)
        _equal(digest, checked_hash)
        _equal(manifest, data)
        row = _base(benchmark, "preparation", data["status"], len(tasks), 0)
    elif benchmark == "swebench-predictions":
        for name in ("manifest_sha256", "source_sha256", "predictions_sha256", "export_sha256"):
            _sha(data[name])
        _id(data["run_id"])
        _equal(data["status"], "PREPARED")
        _equal(data["results_format"], swebench_eval.RESULTS_FORMAT)
        _text(data["scope"], "scope", 4096)
        tasks = _prediction_rows(data["tasks"])
        for item in tasks:
            _require(
                set(item)
                == {"instance_id", "prediction_status", "prediction_sha256", "model_patch_sha256"},
                "Invalid prepared prediction fields",
            )
        present = any(item["prediction_status"] != "MISSING" for item in tasks)
        _require(
            isinstance(data["model_name_or_path"], str)
            if present
            else data["model_name_or_path"] is None,
            "Invalid prepared model identity",
        )
        if present:
            _model(data["model_name_or_path"])
        row = _base(benchmark, "preparation", "PREPARED", len(tasks), 0)
        row["run_id"] = data["run_id"]
    else:
        _require(
            {
                "scope",
                "cwd",
                "engine",
                "environment_keys",
                "results_directory",
                "command",
                "limits",
                "preflight",
                "cleanup_errors",
            }.issubset(data),
            "Incomplete harness execution report",
        )
        _id(data["run_id"])
        ids = _ids(data["instance_ids"], maximum=50)
        for name in (
            "manifest_sha256",
            "dataset_sha256",
            "predictions_sha256",
            "validated_export_sha256",
            "executed_dataset_sha256",
            "executed_predictions_sha256",
            "run_manifest_sha256",
        ):
            _sha(data[name])
        _require(
            data["execution_status"]
            in {
                "PREVIEW",
                "UNAVAILABLE",
                "COMPLETED",
                "FAILED",
                "TIMEOUT",
                "LOG_LIMIT",
                "INTERRUPTED",
                "CLEANUP_FAILED",
            },
            "Unknown harness execution status",
        )
        _equal(data["evaluation_status"], "NOT_IMPORTED")
        _require(isinstance(data["limits"], dict), "Missing harness limits")
        limits = data["limits"]
        _require(
            set(limits)
            == {
                "workers",
                "timeout_seconds",
                "test_timeout_seconds",
                "console_bytes_per_stream",
                "file_bytes",
                "harness_logs_bytes",
                "minimum_disk_bytes",
                "memory_bytes_per_worker",
            },
            "Invalid harness limit fields",
        )
        for value in limits.values():
            _integer(value, 1, 10**15)
        _require(
            limits["workers"] <= min(4, len(ids))
            and limits["test_timeout_seconds"] <= limits["timeout_seconds"],
            "Inconsistent harness limits",
        )
        _require(data["engine"] in ("docker", "podman"), "Unknown execution engine")
        for name in ("scope", "cwd", "results_directory"):
            _text(data[name], name, 8192)
        for name in _list(data["environment_keys"], maximum=100):
            _text(name, "environment key", 100)
        for argument in _list(data["command"], 1, 256):
            _text(argument, "command argument", 16_384)
        for error in _list(data["cleanup_errors"], maximum=50):
            _text(error, "cleanup error")
        _require(
            data["preflight"] in {"NOT_RUN", "PASSED", "FAILED", "INTERRUPTED"},
            "Invalid harness preflight status",
        )
        if data["execution_status"] == "COMPLETED":
            _equal(data.get("exit_code"), 0)
            _equal(data["preflight"], "PASSED")
            _equal(data["cleanup_errors"], [])
        if data["execution_status"] == "PREVIEW":
            _equal(data["preflight"], "NOT_RUN")
        if data["execution_status"] == "CLEANUP_FAILED":
            _require(
                bool(data["cleanup_errors"])
                and isinstance(data.get("prior_execution_status"), str),
                "Missing cleanup failure detail",
            )
        row = _base(benchmark, "harness-execution", data["execution_status"], len(ids), 0)
        row["execution_status"] = data["execution_status"]
        row["run_id"] = data["run_id"]
    row["notes"].append("Preparation/execution only; no model success or benchmark metric.")
    return row


def _provenance(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    data = swebench_eval._json(swebench_eval._read(path, 1024 * 1024))
    _require(
        isinstance(data, dict)
        and set(data) == {"schema_version", "reports"}
        and type(data["schema_version"]) is int
        and data["schema_version"] == 1,
        "Invalid provenance schema",
    )
    result = {}
    for item in _list(data["reports"], maximum=MAX_REPORTS):
        _require(
            isinstance(item, dict)
            and {"report_sha256", "origin"}.issubset(item)
            and set(item).issubset(
                {
                    "report_sha256",
                    "origin",
                    "evaluation_set_sha256",
                    "evaluator_sha256",
                    "model_id",
                    "run_id",
                }
            ),
            "Invalid provenance entry",
        )
        key = _sha(item["report_sha256"])
        _require(key not in result, "Duplicate provenance report hash")
        _require(
            isinstance(item["origin"], str)
            and item["origin"]
            in {
                "infrastructure",
                "recorded-agent",
                "container-agent",
                "official-harness",
                "preparation",
                "harness-execution",
                "synthetic",
                "unknown",
            },
            "Unknown provenance origin",
        )
        for name in ("evaluation_set_sha256", "evaluator_sha256"):
            if name in item:
                _sha(item[name])
        if "model_id" in item:
            _require(
                bool(_text(item["model_id"], "model display label", 200).strip()),
                "Empty model display label",
            )
            _require(
                not any(ord(char) < 32 or ord(char) == 127 for char in item["model_id"]),
                "Control characters in model display label",
            )
        if "run_id" in item:
            _id(item["run_id"])
        result[key] = item
    return result


def _normalize(path: Path, raw: bytes, declaration: dict | None) -> dict:
    digest = swebench_eval._hash(raw)
    data = swebench_eval._json(raw)
    context, value = {}, None
    if isinstance(data, list):
        fixtures = fuzzer.validate_records(data)
        row = _base("generate", "preparation", "PREPARED", len(fixtures), 0)
        row["notes"].append("Fixture data only; generation is not agent evaluation.")
    else:
        _require(
            isinstance(data, dict)
            and type(data.get("schema_version")) is int
            and data["schema_version"] == 1,
            "Unsupported Arena report schema version",
        )
        benchmark = data.get("benchmark")
        _require(isinstance(benchmark, str), "Missing report benchmark")
        try:
            if benchmark == "mini":
                row, context, value = _mini(data)
            elif benchmark in {"redteam", "agent"}:
                row, context, value = _responses(data)
            elif benchmark == "swebench-results":
                row, context, value = _swe_results(data)
            elif benchmark in {"swebench", "swebench-predictions", "swebench-run"}:
                row = _preparation(data, path, digest)
            else:
                raise ValueError("Unsupported Arena benchmark type")
        except (KeyError, TypeError) as error:
            raise ValueError("Incomplete or incorrectly typed Arena report") from error
    row.update(report_id=digest, paths=[str(path.resolve())])
    benchmark = row["benchmark"]
    row["metric"] = (
        "attack_success_rate_pct"
        if benchmark in {"redteam", "agent"}
        else "resolution_rate_pct"
        if benchmark == "swebench-results"
        else "infrastructure_pass_pct"
        if benchmark == "mini"
        else None
    )
    if declaration is not None:
        row["provenance"] = dict(declaration)
        origin = declaration["origin"]
        expected = {
            "mini": "infrastructure",
            "redteam": "recorded-agent",
            "agent": "container-agent",
            "swebench-results": "official-harness",
            "swebench-run": "harness-execution",
        }.get(benchmark, "preparation")
        _require(
            origin in {expected, "synthetic", "unknown"},
            "Provenance origin contradicts the benchmark type",
        )
        if "run_id" in declaration and row["run_id"] is not None:
            _equal(declaration["run_id"], row["run_id"])
        if "model_id" in declaration:
            row["subject"] = declaration["model_id"]
        if row["run_id"] is None:
            row["run_id"] = declaration.get("run_id")
        if origin in {"synthetic", "unknown"}:
            value = None
            row["reliability"] = "SYNTHETIC" if origin == "synthetic" else "UNVERIFIED"
        elif benchmark in {"mini", "redteam", "agent"}:
            if all(name in declaration for name in ("evaluation_set_sha256", "evaluator_sha256")):
                context.update(
                    {
                        name: declaration[name]
                        for name in ("evaluation_set_sha256", "evaluator_sha256")
                    }
                )
                row["reliability"] = "USER_ATTESTED"
            else:
                value = None
                row["notes"].append("Evaluation-set and evaluator fingerprints are required.")
    elif benchmark in {"mini", "redteam", "agent"}:
        value = None
        row["notes"].append("Legacy report lacks provenance required for metrics/comparison.")
    if isinstance(data, dict) and "synthetic" in data:
        _require(type(data["synthetic"]) is bool, "Synthetic marker must be boolean")
        if data["synthetic"]:
            row["reliability"] = "SYNTHETIC"
    if row["evaluation_status"] != "EVALUATED" or row["reliability"] != "USER_ATTESTED":
        value = None
    row["value"] = value
    if value is not None:
        row["comparison_key"] = swebench_eval._hash(
            swebench_eval._canonical({"benchmark": benchmark, **context})
        )
    if row["reliability"] == "SYNTHETIC":
        row["reported_coverage"] = dict(row["coverage"])
        row["coverage"] = {"evaluated": 0, "total": row["coverage"]["total"], "pct": 0.0}
        row["evaluation_status"] = "NOT_EVALUATED"
        row["notes"].append("Declared synthetic evidence; no metric, rank or delta.")
    return row


@dataclass(frozen=True)
class Thresholds:
    asr_increase_pp: float = 0
    resolution_drop_pp: float = 0
    infrastructure_drop_pp: float = 0

    def to_dict(self) -> dict:
        return {
            "attack_success_rate_pct": _number(self.asr_increase_pp),
            "resolution_rate_pct": _number(self.resolution_drop_pp),
            "infrastructure_pass_pct": _number(self.infrastructure_drop_pp),
        }


def compare(baseline: dict, head: dict, thresholds: Thresholds) -> dict:
    limits = thresholds.to_dict()
    result = {
        "baseline": baseline["report_id"],
        "head": head["report_id"],
        "status": "INCOMPARABLE",
        "reasons": [],
        "metrics": [],
    }
    if baseline["report_id"] == head["report_id"]:
        result["reasons"].append(
            "Baseline and head have identical report SHA-256; distinct reports are required."
        )
    if baseline["benchmark"] != head["benchmark"]:
        result["reasons"].append("Different benchmark types.")
    if baseline["comparison_key"] is None or head["comparison_key"] is None:
        result["reasons"].append(
            "Missing, partial, unverified, synthetic or non-evaluation evidence."
        )
    elif baseline["comparison_key"] != head["comparison_key"]:
        result["reasons"].append(
            "Different scenario scopes, evaluation data, evaluators or infrastructure settings."
        )
    if result["reasons"]:
        return result
    metric = baseline["metric"]
    delta = round(head["value"] - baseline["value"], 12)
    loss = delta if METRICS[metric] == "lower" else -delta
    regression = loss > limits[metric]
    result["status"] = "REGRESSION" if regression else "NO_REGRESSION"
    result["metrics"] = [
        {
            "metric": metric,
            "baseline": baseline["value"],
            "head": head["value"],
            "delta_pp": delta,
            "regression_threshold_pp": limits[metric],
            "regression": regression,
        }
    ]
    return result


def aggregate(
    paths: list[Path],
    *,
    baseline: Path | None = None,
    head: Path | None = None,
    provenance: Path | None = None,
    thresholds: Thresholds | None = None,
) -> dict:
    thresholds = Thresholds() if thresholds is None else thresholds
    limits = thresholds.to_dict()
    _require((baseline is None) == (head is None), "Baseline and head must be provided together")
    selected = list(paths)
    for path in (baseline, head):
        if path is not None and path not in selected:
            selected.append(path)
    _require(1 <= len(selected) <= MAX_REPORTS, "Reporting requires 1–100 report files")
    declarations = _provenance(provenance)
    reports, path_ids = {}, {}
    total = 0
    for path in selected:
        raw = swebench_eval._read(path, MAX_REPORT_BYTES)
        total += len(raw)
        _require(total <= MAX_TOTAL_BYTES, "Aggregate report inputs exceed the total byte limit")
        digest = swebench_eval._hash(raw)
        path_ids[path] = digest
        if digest not in reports:
            reports[digest] = _normalize(path, raw, declarations.get(digest))
        else:
            reports[digest]["paths"] = sorted(set(reports[digest]["paths"]) | {str(path.resolve())})
    _require(
        set(declarations).issubset(reports),
        "Provenance references a report not supplied to aggregation",
    )
    rows = sorted(reports.values(), key=lambda row: (row["benchmark"], row["report_id"]))
    groups = {}
    for row in rows:
        if row["comparison_key"] is not None:
            groups.setdefault((row["benchmark"], row["comparison_key"], row["metric"]), []).append(
                row
            )
    leaderboards = []
    for (benchmark, key, metric), members in sorted(groups.items()):
        members.sort(
            key=lambda row: (
                row["value"] if METRICS[metric] == "lower" else -row["value"],
                row["report_id"],
            )
        )
        ranked, previous, rank = [], None, 0
        for index, row in enumerate(members, 1):
            if row["value"] != previous:
                rank = index
            previous = row["value"]
            ranked.append(
                {
                    "rank": rank,
                    "report_id": row["report_id"],
                    "subject": row["subject"],
                    "value": row["value"],
                }
            )
        leaderboards.append(
            {
                "benchmark": benchmark,
                "comparison_key": key,
                "metric": metric,
                "better": METRICS[metric],
                "rows": ranked,
            }
        )
    comparison = (
        compare(reports[path_ids[baseline]], reports[path_ids[head]], thresholds)
        if baseline is not None
        else None
    )
    regressions = (
        []
        if comparison is None
        else [metric for metric in comparison["metrics"] if metric["regression"]]
    )
    return {
        "schema_version": 1,
        "benchmark": "reporting",
        "evidence_kind": "offline-report-aggregation",
        "status": comparison["status"] if comparison is not None else "SUMMARY",
        "thresholds_pp": limits,
        "reports": rows,
        "leaderboards": leaderboards,
        "comparison": comparison,
        "regressions": regressions,
        "summary": {
            "unique_reports": len(rows),
            "ranked_reports": sum(len(group["rows"]) for group in leaderboards),
            "regressions": len(regressions),
            "execution_errors": sum(
                row.get("execution_status")
                in {
                    "FAILED",
                    "TIMEOUT",
                    "UNAVAILABLE",
                    "LOG_LIMIT",
                    "INTERRUPTED",
                    "CLEANUP_FAILED",
                }
                for row in rows
            ),
            "evaluation_states": {
                state: sum(row["evaluation_status"] == state for row in rows)
                for state in ("EVALUATED", "NOT_EVALUATED", "INCOMPLETE", "ERROR")
            },
        },
        "limitations": list(LIMITATIONS),
    }


def markdown_report(data: dict) -> str:
    cell = runner.markdown_cell
    lines = [
        "# MSL-Arena — offline leaderboard and regression report",
        "",
        f"Status: **{data['status']}**. No benchmark was run by this reporter.",
        "",
        f"Reports: {data['summary']['unique_reports']}; ranked: {data['summary']['ranked_reports']}; "
        f"regressions: {data['summary']['regressions']}; execution errors: {data['summary']['execution_errors']}.",
        "",
        "| Report SHA-256 | Benchmark / phase | Source status | Evaluation | Coverage | Reliability | Metric |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["reports"]:
        coverage = row["coverage"]
        metric = "N/A" if row["value"] is None else f"{row['metric']}: {row['value']:.4f}%"
        lines.append(
            f"| {row['report_id']} | {cell(row['benchmark'] + ' / ' + row['phase'])} | {cell(row['source_status'])} | {row['evaluation_status']} | {coverage['evaluated']}/{coverage['total']} | {row['reliability']} | {metric} |"
        )
    for group in data["leaderboards"]:
        lines.extend(
            [
                "",
                f"## {group['benchmark']} — {group['metric']}",
                "",
                f"Evaluation key: {group['comparison_key']}; {group['better']} is better.",
                "",
                "| Rank | Subject | Report | Value |",
                "| --- | --- | --- | --- |",
            ]
        )
        for row in group["rows"]:
            lines.append(
                f"| {row['rank']} | {cell(row['subject'] or 'unspecified')} | {row['report_id']} | {row['value']:.4f}% |"
            )
    comparison = data["comparison"]
    if comparison is not None:
        lines.extend(["", "## Baseline / head", "", f"Comparison: **{comparison['status']}**.", ""])
        lines.extend("- " + cell(reason) for reason in comparison["reasons"])
        for metric in comparison["metrics"]:
            lines.append(
                f"- {metric['metric']}: {metric['baseline']:.4f}% → {metric['head']:.4f}%; delta {metric['delta_pp']:+.4f} pp; threshold {metric['regression_threshold_pp']:.4f} pp; regression: {metric['regression']}."
            )
    lines.extend(["", "## Limitations", ""])
    lines.extend("- " + cell(note) for note in data["limitations"])
    return "\n".join(lines)
