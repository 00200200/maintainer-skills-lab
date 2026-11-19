"""Validate and prepare local legacy SWE-bench exports; never execute tasks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from evals.arena.redteam import _reject_constant, _unique_fields
from evals.arena.runner import markdown_cell

MAX_SELECTED = 50
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_RECORDS = 10_000
MAX_TESTS = 10_000
MAX_TEST_CHARS = 2048
MAX_METADATA_NODES = 4096
REQUIRED = {
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
}
OPTIONAL_TEXT = {"hints_text", "created_at", "version", "environment_setup_commit", "difficulty"}
OPTIONAL = OPTIONAL_TEXT | {"patch", "test_patch", "metadata"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
COMMIT = re.compile(r"[0-9a-fA-F]{40}\Z")
SCOPE = (
    "Offline validation and preparation of a user-supplied legacy SWE-bench export only. "
    "No agent, project tests or external SWE-bench harness were run. "
    "Dataset identity is not authenticated; no task resolution or Pass@1 is measured."
)


def _loads(text: str):
    try:
        return json.loads(text, object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError(
            "Invalid SWE-bench JSON (including duplicate keys or non-finite values)"
        ) from error


def _text(value, name: str, limit: int, *, nonblank: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or "\x00" in value
        or (nonblank and not value.strip())
    ):
        raise ValueError(f"Invalid or oversized SWE-bench {name}")
    try:
        value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"Invalid Unicode in SWE-bench {name}") from error
    return value


def _tests(value, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        _text(value, name, MAX_RECORD_BYTES)
        value = _loads(value)
    if not isinstance(value, list) or len(value) > MAX_TESTS:
        raise ValueError(f"SWE-bench {name} must be a bounded array of test identifiers")
    seen = set()
    for item in value:
        _text(item, name, MAX_TEST_CHARS, nonblank=True)
        if item != item.strip() or any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ValueError(f"Invalid control characters or surrounding whitespace in {name}")
        if item in seen:
            raise ValueError(f"Duplicate test identifier in {name}")
        seen.add(item)
    return tuple(value)


def _metadata(value) -> None:
    remaining = MAX_METADATA_NODES

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if depth > 8 or remaining < 0:
            raise ValueError("SWE-bench metadata exceeds depth or node limits")
        if isinstance(item, str):
            _text(item, "metadata text", 16_384)
        elif item is None or type(item) in (bool, int):
            return
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Non-finite SWE-bench metadata")
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items():
                _text(key, "metadata key", 128, nonblank=True)
                visit(child, depth + 1)
        else:
            raise ValueError("SWE-bench metadata must contain only JSON values")

    if not isinstance(value, dict):
        raise ValueError("SWE-bench metadata must be an object")
    visit(value, 0)


@dataclass(frozen=True)
class SWEbenchTask:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    fail_to_pass: tuple[str, ...] = field(repr=False)
    pass_to_pass: tuple[str, ...] = field(repr=False)
    evaluation_metadata: dict = field(repr=False)

    def agent_input(self) -> dict[str, str]:
        """An explicit allowlist; never serialize the entire task into an agent prompt."""
        return {
            "instance_id": self.instance_id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "problem_statement": self.problem_statement,
        }

    def evaluation_input(self) -> dict:
        """Private evaluator data for a later isolated patch-evaluation stage."""
        return {
            "instance_id": self.instance_id,
            "FAIL_TO_PASS": list(self.fail_to_pass),
            "PASS_TO_PASS": list(self.pass_to_pass),
            **self.evaluation_metadata,
        }


def validate_records(records) -> tuple[SWEbenchTask, ...]:
    """Validate every record, including records outside the selected subset."""
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValueError(f"SWE-bench input must contain 1–{MAX_RECORDS} task objects")
    tasks, seen = [], set()
    for row, record in enumerate(records, 1):
        if (
            not isinstance(record, dict)
            or not REQUIRED.issubset(record)
            or not set(record).issubset(REQUIRED | OPTIONAL)
        ):
            raise ValueError(f"SWE-bench row {row} has missing or unsupported fields")
        instance_id = _text(record["instance_id"], "instance_id", 200, nonblank=True)
        repo = _text(record["repo"], "repo", 201, nonblank=True)
        commit = _text(record["base_commit"], "base_commit", 40, nonblank=True)
        problem = _text(record["problem_statement"], "problem_statement", 100_000, nonblank=True)
        if (
            not IDENTIFIER.fullmatch(instance_id)
            or not REPOSITORY.fullmatch(repo)
            or not COMMIT.fullmatch(commit)
        ):
            raise ValueError(f"SWE-bench row {row} has an invalid identifier, repository or commit")
        if instance_id in seen:
            raise ValueError(f"SWE-bench row {row} has a duplicate instance_id")
        seen.add(instance_id)
        failing = _tests(record["FAIL_TO_PASS"], "FAIL_TO_PASS")
        passing = _tests(record["PASS_TO_PASS"], "PASS_TO_PASS")
        if set(failing).intersection(passing):
            raise ValueError(f"SWE-bench row {row} has conflicting test expectations")
        private = {}
        for name in sorted(OPTIONAL.intersection(record)):
            value = record[name]
            if name == "metadata":
                _metadata(value)
            elif name in {"patch", "test_patch"}:
                _text(value, name, 250_000)
            elif value is not None:
                _text(value, name, 100_000 if name == "hints_text" else 2048)
                if name == "environment_setup_commit" and not COMMIT.fullmatch(value):
                    raise ValueError("Invalid SWE-bench environment_setup_commit")
            private[name] = value
        try:
            serialized = json.dumps(record, ensure_ascii=False, allow_nan=False)
            if len(serialized.encode("utf-8")) > MAX_RECORD_BYTES:
                raise ValueError("SWE-bench record exceeds its size limit")
            # Detach nested metadata from the caller's mutable source objects.
            private = _loads(json.dumps(private, ensure_ascii=False, allow_nan=False))
        except (UnicodeError, RecursionError) as error:
            raise ValueError("Invalid or excessively nested SWE-bench record") from error
        tasks.append(SWEbenchTask(instance_id, repo, commit, problem, failing, passing, private))
    return tuple(tasks)


@dataclass
class SWEbenchReport:
    source: dict
    tasks: tuple[SWEbenchTask, ...]
    total_tasks: int
    limit: int
    status: str = "PREPARED"

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "benchmark": "swebench",
            "status": self.status,
            "evidence_kind": "offline-swebench-preparation",
            "live_agent_run": False,
            "evaluation_performed": False,
            "evaluation_status": "NOT_EVALUATED",
            "scope": SCOPE,
            "source": dict(self.source),
            "selection": {"strategy": "instance_id_ascending", "limit": self.limit},
            "summary": {
                "input_tasks": self.total_tasks,
                "selected_tasks": len(self.tasks),
                "omitted_tasks": self.total_tasks - len(self.tasks),
                "evaluated_tasks": 0,
            },
            "agent_tasks": [task.agent_input() for task in self.tasks],
            "evaluation_tasks": [task.evaluation_input() for task in self.tasks],
        }


def prepare(path: Path, *, limit: int = MAX_SELECTED) -> SWEbenchReport:
    """Load a bounded local JSON/JSONL export and select by ascending exact ID."""
    if type(limit) is not int or not 1 <= limit <= MAX_SELECTED:
        raise ValueError(f"SWE-bench limit must be between 1 and {MAX_SELECTED}")
    suffix = path.suffix.lower()
    if suffix not in {".json", ".jsonl"} or not path.is_file():
        raise ValueError("SWE-bench input must be a regular .json or .jsonl file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("SWE-bench input exceeds the file size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as error:
        raise ValueError("SWE-bench input is not valid UTF-8") from error
    if suffix == ".json":
        records = _loads(text)
    else:
        lines = text.split("\n")
        if lines[-1] == "":
            lines.pop()
        if not 1 <= len(lines) <= MAX_RECORDS:
            raise ValueError("SWE-bench JSONL exceeds the record count limit or is empty")
        records = []
        for row, line in enumerate(lines, 1):
            if not line.strip() or len(line.encode("utf-8")) > MAX_RECORD_BYTES:
                raise ValueError(f"SWE-bench JSONL row {row} is blank or oversized")
            records.append(_loads(line))
    tasks = validate_records(records)
    selected = tuple(sorted(tasks, key=lambda task: task.instance_id)[:limit])
    return SWEbenchReport(
        source={
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "format": f"legacy-{suffix[1:]}",
            "provenance": "User-supplied local export; Lite/Verified identity is not authenticated",
        },
        tasks=selected,
        total_tasks=len(tasks),
        limit=limit,
    )


def markdown_report(report: SWEbenchReport) -> str:
    lines = [
        "# MSL-Arena SWE-bench — offline preparation",
        "",
        SCOPE,
        "",
        f"Status: **{report.status}**; evaluation: **NOT_EVALUATED**.",
        "",
        f"Validated: {report.total_tasks}; selected: {len(report.tasks)}; limit: {report.limit}.",
        "Selection: ascending instance_id, without sampling or padding.",
        f"Source format: {report.source['format']}; SHA-256: {report.source['sha256']}.",
        "",
        "The JSON manifest contains private evaluation data. Only agent_tasks may be sent to an agent.",
        "No gold/test patches, test identifiers or optional metadata are rendered below.",
        "",
        "| Instance | Repository | Base commit |",
        "| --- | --- | --- |",
    ]
    for task in report.tasks:
        lines.append(
            f"| {markdown_cell(task.instance_id)} | {markdown_cell(task.repo)} | "
            f"{markdown_cell(task.base_commit)} |"
        )
    return "\n".join(lines)
