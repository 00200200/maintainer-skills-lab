"""Offline prediction export and strictly bound classic SWE-bench result import."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from evals.arena import swebench
from evals.arena.runner import markdown_cell

RESULTS_FORMAT = "swebench-v2.1-instance"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PATCH_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}\Z")
SCOPE = (
    "Offline import only; Arena ran no model, container, project tests or harness. "
    "Artifacts and user attestation cannot independently prove evaluation provenance or freshness. "
    "Rates require complete, consistent results for exactly one prediction per selected task."
)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _read(path: Path, limit: int | None = None) -> bytes:
    if limit is None:
        limit = MAX_INPUT_BYTES
    if not path.is_file():
        raise ValueError("SWE-bench artifact must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("SWE-bench artifact exceeds its byte limit")
    return raw


def _json(raw: bytes):
    try:
        return swebench._loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid SWE-bench artifact JSON") from error


def _identifier(value, label: str) -> str:
    swebench._text(value, label, 200, nonblank=True)
    if not swebench.IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SWE-bench {label}")
    return value


def load_manifest(path: Path) -> tuple[dict, tuple[swebench.SWEbenchTask, ...], str]:
    """Accept the M5a v1 manifest only, reusing its task validator."""
    raw = _read(path)
    data = _json(raw)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        raise ValueError("Expected an M5a v1 preparation manifest")
    agents, evaluations = data.get("agent_tasks"), data.get("evaluation_tasks")
    if (
        not isinstance(agents, list)
        or not 1 <= len(agents) <= swebench.MAX_SELECTED
        or not isinstance(evaluations, list)
        or len(agents) != len(evaluations)
    ):
        raise ValueError("Invalid M5a task sections")
    records = []
    for agent, evaluation in zip(agents, evaluations, strict=True):
        if (
            not isinstance(agent, dict)
            or set(agent) != {"instance_id", "repo", "base_commit", "problem_statement"}
            or not isinstance(evaluation, dict)
            or not {"instance_id", "FAIL_TO_PASS", "PASS_TO_PASS"}.issubset(evaluation)
            or not set(evaluation).issubset(
                {"instance_id", "FAIL_TO_PASS", "PASS_TO_PASS"} | swebench.OPTIONAL
            )
            or evaluation["instance_id"] != agent["instance_id"]
        ):
            raise ValueError("Invalid or mismatched M5a task sections")
        records.append({**agent, **evaluation})
    tasks = swebench.validate_records(records)
    if list(tasks) != sorted(tasks, key=lambda task: task.instance_id):
        raise ValueError("M5a tasks must retain ascending instance order")
    source, selection, summary = data.get("source"), data.get("selection"), data.get("summary")
    if (
        not isinstance(source, dict)
        or set(source) != {"path", "sha256", "size_bytes", "format", "provenance"}
        or not isinstance(source["sha256"], str)
        or not SHA256.fullmatch(source["sha256"])
        or type(source["size_bytes"]) is not int
        or not 1 <= source["size_bytes"] <= swebench.MAX_FILE_BYTES
        or source["format"] not in ("legacy-json", "legacy-jsonl")
        or not isinstance(selection, dict)
        or type(selection.get("limit")) is not int
        or not 1 <= selection["limit"] <= swebench.MAX_SELECTED
        or not isinstance(summary, dict)
        or set(summary) != {"input_tasks", "selected_tasks", "omitted_tasks", "evaluated_tasks"}
        or any(type(value) is not int for value in summary.values())
        or not len(tasks) <= summary["input_tasks"] <= swebench.MAX_RECORDS
        or len(tasks) != min(summary["input_tasks"], selection["limit"])
        or data.get("live_agent_run") is not False
        or data.get("evaluation_performed") is not False
    ):
        raise ValueError("Invalid M5a provenance or selection")
    swebench._text(source["path"], "source path", 8192, nonblank=True)
    swebench._text(source["provenance"], "source provenance", 2048, nonblank=True)
    expected = swebench.SWEbenchReport(
        source, tasks, summary["input_tasks"], selection["limit"]
    ).to_dict()
    if data != expected:
        raise ValueError("Manifest does not match the M5a v1 schema")
    return data, tasks, _hash(raw)


@dataclass
class PredictionSet:
    manifest_sha256: str
    source_sha256: str
    predictions_sha256: str
    run_id: str
    tasks: tuple[swebench.SWEbenchTask, ...]
    records: dict[str, dict]

    @property
    def export_bytes(self) -> bytes:
        return b"".join(
            _canonical(self.records[task.instance_id]) + b"\n"
            for task in self.tasks
            if self.prediction_status(task.instance_id) == "READY"
        )

    def prediction_status(self, instance_id: str) -> str:
        record = self.records.get(instance_id)
        if record is None:
            return "MISSING"
        patch = record["model_patch"]
        return "READY" if isinstance(patch, str) and patch.strip() else "INVALID_PATCH"

    def to_dict(self) -> dict:
        entries = []
        for task in self.tasks:
            record = self.records.get(task.instance_id)
            patch = record["model_patch"] if record else None
            entries.append(
                {
                    "instance_id": task.instance_id,
                    "prediction_status": self.prediction_status(task.instance_id),
                    "prediction_sha256": _hash(_canonical(record)) if record else None,
                    "model_patch_sha256": _hash(patch.encode("utf-8"))
                    if isinstance(patch, str)
                    else None,
                }
            )
        return {
            "schema_version": 1,
            "benchmark": "swebench-predictions",
            "status": "PREPARED",
            "scope": SCOPE,
            "run_id": self.run_id,
            "results_format": RESULTS_FORMAT,
            "manifest_sha256": self.manifest_sha256,
            "source_sha256": self.source_sha256,
            "predictions_sha256": self.predictions_sha256,
            "export_sha256": _hash(self.export_bytes),
            "model_name_or_path": next(iter(self.records.values()))["model_name_or_path"]
            if self.records
            else None,
            "tasks": entries,
        }


def prepare_predictions(manifest: Path, predictions: Path, *, run_id: str) -> PredictionSet:
    _identifier(run_id, "run_id")
    data, tasks, manifest_hash = load_manifest(manifest)
    raw = _read(predictions)
    try:
        lines = raw.decode("utf-8").split("\n")
    except UnicodeError as error:
        raise ValueError("Predictions must be UTF-8 JSONL") from error
    if lines[-1] == "":
        lines.pop()
    if len(lines) > swebench.MAX_SELECTED:
        raise ValueError("Too many SWE-bench predictions")
    records, models = {}, set()
    selected = {task.instance_id for task in tasks}
    for line in lines:
        if not line.strip() or len(line.encode("utf-8")) > MAX_PATCH_BYTES + 65_536:
            raise ValueError("Blank or oversized prediction row")
        record = swebench._loads(line)
        if not isinstance(record, dict) or set(record) != {
            "instance_id",
            "model_name_or_path",
            "model_patch",
        }:
            raise ValueError("Expected classic SWE-bench prediction fields")
        instance_id = _identifier(record["instance_id"], "instance_id")
        if instance_id not in selected or instance_id in records:
            raise ValueError("Unknown or duplicate prediction instance_id")
        model = swebench._text(
            record["model_name_or_path"], "model_name_or_path", 200, nonblank=True
        )
        if not MODEL.fullmatch(model) or any(part in ("", ".", "..") for part in model.split("/")):
            raise ValueError("Unsafe model_name_or_path")
        models.add(model)
        if len(models) > 1:
            raise ValueError("One model and one prediction per task are required")
        patch = record["model_patch"]
        if patch is not None:
            swebench._text(patch, "model_patch", 250_000)
            if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
                raise ValueError("Prediction patch exceeds its byte limit")
        records[instance_id] = record
    return PredictionSet(
        manifest_hash, data["source"]["sha256"], _hash(raw), run_id, tasks, records
    )


def write_predictions(path: Path, prepared: PredictionSet) -> None:
    """Publish complete deterministic JSONL without replacing existing files."""
    data = prepared.export_bytes
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _artifact(root: Path, path: Path, limit: int) -> bytes:
    try:
        contained = path.resolve().is_relative_to(root.resolve())
    except (OSError, RuntimeError) as error:
        raise ValueError("Harness artifact path cannot be resolved safely") from error
    if not contained:
        raise ValueError("Harness artifact escapes the selected results directory")
    return _read(path, limit)


def _outcome(raw: bytes, task: swebench.SWEbenchTask) -> str:
    data = _json(raw)
    if not isinstance(data, dict) or set(data) != {task.instance_id}:
        raise ValueError("Wrong per-instance harness report binding")
    result = data[task.instance_id]
    flags = {"patch_is_None", "patch_exists", "patch_successfully_applied", "resolved"}
    if (
        not isinstance(result, dict)
        or not flags.issubset(result)
        or not set(result).issubset(flags | {"tests_status", "none"})
        or any(type(result[name]) is not bool for name in flags)
        or ("none" in result and type(result["none"]) is not bool)
    ):
        raise ValueError("Unsupported classic harness report schema")
    if (
        result["patch_is_None"]
        or result.get("none", False)
        or not result["patch_exists"]
        or not result["patch_successfully_applied"]
    ):
        raise ValueError("Harness did not complete patch application and evaluation")
    groups = result.get("tests_status")
    if not isinstance(groups, dict) or set(groups) != {
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "FAIL_TO_FAIL",
        "PASS_TO_FAIL",
    }:
        raise ValueError("Complete classic test-status groups are required")
    if not task.fail_to_pass:
        raise ValueError("Empty failure expectations cannot establish task resolution")
    failures = False
    for name, expected in (
        ("FAIL_TO_PASS", task.fail_to_pass),
        ("PASS_TO_PASS", task.pass_to_pass),
        ("FAIL_TO_FAIL", ()),
        ("PASS_TO_FAIL", ()),
    ):
        group = groups[name]
        if not isinstance(group, dict) or set(group) != {"success", "failure"}:
            raise ValueError("Invalid harness test-status group")
        # Unlike task ingestion, harness reports must use actual arrays, not encoded strings.
        if not all(isinstance(group[key], list) for key in ("success", "failure")):
            raise ValueError("Harness test statuses must be arrays")
        passed = set(swebench._tests(group["success"], "success"))
        failed = set(swebench._tests(group["failure"], "failure"))
        if passed & failed or passed | failed != set(expected):
            raise ValueError("Harness tests differ from the selected manifest expectations")
        failures = failures or bool(failed)
    if result["resolved"] != (not failures):
        raise ValueError("Harness resolved flag contradicts its test statuses")
    return "RESOLVED" if result["resolved"] else "UNRESOLVED"


def import_results(
    prepared: PredictionSet,
    run_manifest: Path,
    results_dir: Path,
    *,
    results_format: str,
    confirm_harness_run: bool = False,
) -> dict:
    if results_format != RESULTS_FORMAT:
        raise ValueError("Unsupported SWE-bench results format")
    if type(confirm_harness_run) is not bool:
        raise ValueError("Harness confirmation must be boolean")
    receipt = _read(run_manifest)
    if _canonical(_json(receipt)) != _canonical(prepared.to_dict()):
        raise ValueError("Run manifest does not match the run ID, data or predictions")
    if not results_dir.is_dir():
        raise ValueError("Harness results directory is unavailable")
    entries = []
    for binding in prepared.to_dict()["tasks"]:
        instance_id = binding["instance_id"]
        item = {**binding, "status": "NOT_EVALUATED", "reason": "MISSING_PREDICTION"}
        entries.append(item)
        if binding["prediction_status"] == "MISSING":
            continue
        if binding["prediction_status"] == "INVALID_PATCH":
            item.update(status="ERROR", reason="INVALID_PREDICTION_PATCH")
            continue
        prediction = prepared.records[instance_id]
        directory = (
            results_dir
            / prepared.run_id
            / prediction["model_name_or_path"].replace("/", "__")
            / instance_id
        )
        item.update(status="ERROR", reason="INVALID_OR_INCOMPLETE_HARNESS_ARTIFACTS")
        try:
            if not directory.exists():
                item.update(status="NOT_EVALUATED", reason="NO_HARNESS_ARTIFACTS")
                continue
            patch = _artifact(results_dir, directory / "patch.diff", MAX_PATCH_BYTES)
            report = _artifact(results_dir, directory / "report.json", MAX_REPORT_BYTES)
            item["artifact_patch_sha256"], item["report_sha256"] = _hash(patch), _hash(report)
            if _hash(patch) != binding["model_patch_sha256"]:
                item["reason"] = "PREDICTION_PATCH_MISMATCH"
                continue
            task = next(task for task in prepared.tasks if task.instance_id == instance_id)
            item.update(status=_outcome(report, task), reason="BOUND_HARNESS_REPORT")
        except (OSError, ValueError):
            continue
    counts = {
        status: sum(item["status"] == status for item in entries)
        for status in ("RESOLVED", "UNRESOLVED", "ERROR", "NOT_EVALUATED")
    }
    evaluated = counts["RESOLVED"] + counts["UNRESOLVED"]
    complete = evaluated == len(entries)
    rates_available = complete and confirm_harness_run
    return {
        "schema_version": 1,
        "benchmark": "swebench-results",
        "scope": SCOPE,
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "evidence_kind": "user-attested-official-harness-artifacts"
        if confirm_harness_run
        else "unattested-harness-artifacts",
        "harness_run_confirmed_by_user": confirm_harness_run,
        "results_format": results_format,
        "run_id": prepared.run_id,
        "manifest_sha256": prepared.manifest_sha256,
        "source_sha256": prepared.source_sha256,
        "predictions_sha256": prepared.predictions_sha256,
        "export_sha256": _hash(prepared.export_bytes),
        "run_manifest_sha256": _hash(receipt),
        "results_directory": str(results_dir.resolve()),
        "model_name_or_path": prepared.to_dict()["model_name_or_path"],
        "summary": {
            **counts,
            "selected_tasks": len(entries),
            "predictions_present": len(prepared.records),
            "evaluated_tasks": evaluated,
            "coverage_pct": 100.0 * evaluated / len(entries),
            "prediction_coverage_pct": 100.0 * len(prepared.records) / len(entries),
            "metrics_available": rates_available,
            "resolution_rate_pct": 100.0 * counts["RESOLVED"] / len(entries)
            if rates_available
            else None,
            "pass_at_1": counts["RESOLVED"] / len(entries) if rates_available else None,
        },
        "results": entries,
    }


def markdown_report(data: dict) -> str:
    lines = [
        "# MSL-Arena SWE-bench — offline prediction/result handling",
        "",
        SCOPE,
        "",
        f"Status: **{data['status']}**; run: {markdown_cell(data['run_id'])}.",
        f"Manifest SHA-256: {data['manifest_sha256']}.",
        f"Predictions SHA-256: {data['predictions_sha256']}.",
        "",
    ]
    if data["benchmark"] == "swebench-results":
        summary = data["summary"]
        rate = summary["resolution_rate_pct"]
        label = (
            f"{rate:.2f}%"
            if rate is not None
            else "N/A (complete, user-confirmed evaluation required)"
        )
        lines.extend(
            [
                f"Evidence: {data['evidence_kind']}.",
                f"Coverage: {summary['evaluated_tasks']} / {summary['selected_tasks']} tasks.",
                f"Resolution rate / Pass@1: {label}.",
                "",
                "| Instance | Outcome | Detail |",
                "| --- | --- | --- |",
            ]
        )
        for item in data["results"]:
            lines.append(
                f"| {markdown_cell(item['instance_id'])} | {item['status']} | {item['reason']} |"
            )
    else:
        lines.extend(
            [
                "Preparation only; no task was evaluated.",
                "",
                "| Instance | Prediction |",
                "| --- | --- |",
            ]
        )
        for item in data["tasks"]:
            lines.append(f"| {markdown_cell(item['instance_id'])} | {item['prediction_status']} |")
    return "\n".join(lines)
