"""Manual Actions bridge for M6a offline reporting; never execute benchmarks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.arena import reporting, swebench_eval

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DIRECTORY = ("evals", "arena", "reports")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
NUMBER = re.compile(r"[1-9][0-9]{0,19}\Z")
STATUSES = {"NO_REGRESSION": 0, "REGRESSION": 1, "INCOMPARABLE": 2}
MAX_OUTPUT_BYTES = 1024 * 1024


def trusted_report(repository: Path, value: str, label: str) -> Path:
    """Resolve a strict relative JSON name without allowing any symlink component."""
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise ValueError(f"Missing or oversized {label} filename")
    parts = value.split("/")
    if len(parts) > 8 or any(
        not COMPONENT.fullmatch(part) or part in (".", "..") for part in parts
    ):
        raise ValueError(f"Invalid relative {label} filename")
    if not parts[-1].endswith(".json"):
        raise ValueError(f"The {label} file must use .json")
    current = repository.resolve(strict=True)
    components = [*TRUSTED_DIRECTORY, *parts]
    trusted = None
    for index, component in enumerate(components):
        current = current / component
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinks are forbidden in the {label} path")
        if index == len(components) - 1:
            if not stat.S_ISREG(mode):
                raise ValueError(f"The {label} input must be a regular file")
        elif not stat.S_ISDIR(mode):
            raise ValueError(f"The {label} parent must be a directory")
        if index == len(TRUSTED_DIRECTORY) - 1:
            trusted = current.resolve(strict=True)
    resolved = current.resolve(strict=True)
    if trusted is None or not resolved.is_relative_to(trusted):
        raise ValueError(f"The {label} path escapes the trusted report directory")
    return resolved


def output_directory(repository: Path, environment: dict[str, str]) -> Path:
    temporary = environment.get("RUNNER_TEMP", "")
    if not temporary or any(char in temporary for char in "\r\n\x00"):
        raise ValueError("A valid RUNNER_TEMP directory is required")
    parent = Path(temporary).resolve(strict=True)
    if not parent.is_dir() or parent.is_relative_to(repository.resolve()):
        raise ValueError("Runner temporary output must be outside the repository")
    identifiers = [environment.get(name, "") for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")]
    if not all(NUMBER.fullmatch(value) for value in identifiers):
        raise ValueError("Valid Actions run and attempt identifiers are required")
    directory = parent / f"arena-regression-{identifiers[0]}-{identifiers[1]}"
    if directory.is_relative_to(repository.resolve()):
        raise ValueError("Generated artifacts must be outside the repository")
    return directory


def _action_file(environment: dict[str, str], name: str, repository: Path) -> Path | None:
    value = environment.get(name)
    if value is None:
        return None
    parent = Path(environment["RUNNER_TEMP"]).resolve(strict=True)
    path = Path(value).resolve()
    if (
        not path.is_relative_to(parent)
        or path.is_relative_to(repository.resolve())
        or not path.parent.is_dir()
        or (path.exists() and not path.is_file())
    ):
        raise ValueError("Actions command files must be regular files in RUNNER_TEMP")
    return path


def _outputs(environment: dict[str, str], *, repository: Path, **values: str) -> None:
    path = _action_file(environment, "GITHUB_OUTPUT", repository)
    if path is not None:
        if any("\n" in value or "\r" in value for value in values.values()):
            raise ValueError("Invalid multiline Actions output")
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))


def _summary(environment: dict[str, str], markdown: str, *, repository: Path) -> None:
    path = _action_file(environment, "GITHUB_STEP_SUMMARY", repository)
    if path is not None:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown + "\n")


def result_status(data: dict) -> str:
    """Check the producer's comparison contract, without recomputing its scoring."""
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("benchmark") != "reporting"
        or data.get("evidence_kind") != "offline-report-aggregation"
        or not isinstance(data.get("status"), str)
        or data["status"] not in STATUSES
    ):
        raise ValueError("A completed M6a baseline/head comparison is required")
    status = data["status"]
    comparison, regressions = data.get("comparison"), data.get("regressions")
    if (
        not isinstance(comparison, dict)
        or comparison.get("status") != status
        or not isinstance(regressions, list)
    ):
        raise ValueError("Inconsistent M6a comparison outcome")
    metrics = comparison.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("Missing M6a comparison metrics")
    if status == "INCOMPARABLE":
        if metrics or regressions or not comparison.get("reasons"):
            raise ValueError("Invalid incomparable comparison")
    else:
        reports = data.get("reports")
        if not metrics or not isinstance(reports, list):
            raise ValueError("Comparable data must contain eligible reports and metrics")
        if comparison.get("reasons") != [] or any(
            not isinstance(item, dict) or not isinstance(item.get("report_id"), str)
            for item in reports
        ):
            raise ValueError("Invalid comparable report identities/reasons")
        by_id = {item["report_id"]: item for item in reports}
        if len(by_id) != len(reports) or not all(
            isinstance(comparison.get(side), str) for side in ("baseline", "head")
        ):
            raise ValueError("Duplicate or missing comparable report identities")
        selected = [by_id.get(comparison.get(side)) for side in ("baseline", "head")]
        if any(
            item is None
            or item.get("evaluation_status") != "EVALUATED"
            or item.get("reliability") != "USER_ATTESTED"
            or item.get("value") is None
            or not item.get("comparison_key")
            for item in selected
        ):
            raise ValueError("Comparable data lacks reliable complete evidence")
        if selected[0]["comparison_key"] != selected[1]["comparison_key"]:
            raise ValueError("Comparison scopes differ")
        if any(
            not isinstance(metric, dict) or type(metric.get("regression")) is not bool
            for metric in metrics
        ):
            raise ValueError("Invalid comparison regression flags")
        detected = [metric for metric in metrics if metric["regression"]]
        if detected != regressions or bool(detected) != (status == "REGRESSION"):
            raise ValueError("Regression status contradicts the comparison")
    return status


def collect(
    *, repository: Path = REPOSITORY_ROOT, environment: dict[str, str] | None = None
) -> int:
    """Successful collection returns zero even for regression; enforcement is separate."""
    environment = dict(os.environ) if environment is None else environment
    try:
        _outputs(
            environment, repository=repository, reporting_completed="false", result_status="ERROR"
        )
        directory = output_directory(repository, environment)
        # Never reuse artifacts from an earlier invocation of this run/attempt.
        directory.mkdir(mode=0o700, exist_ok=False)
        baseline = trusted_report(repository, environment.get("ARENA_BASELINE", ""), "baseline")
        head = trusted_report(repository, environment.get("ARENA_HEAD", ""), "head")
        provenance_name = environment.get("ARENA_PROVENANCE", "")
        provenance = (
            trusted_report(repository, provenance_name, "provenance")
            if provenance_name != ""
            else None
        )
        data = reporting.aggregate([], baseline=baseline, head=head, provenance=provenance)
        status = result_status(data)
        encoded = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        markdown = reporting.markdown_report(data) + "\n"
        markdown_bytes = markdown.encode("utf-8")
        if max(len(encoded), len(markdown_bytes)) > MAX_OUTPUT_BYTES:
            raise ValueError("Generated Actions reports exceed the output byte limit")
        (directory / "report.json").write_bytes(encoded)
        (directory / "report.md").write_bytes(markdown_bytes)
        receipt = {
            "schema_version": 1,
            "reporting_completed": True,
            "status": status,
            "report_sha256": hashlib.sha256(encoded).hexdigest(),
            "markdown_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
        }
        (directory / "result.json").write_bytes(
            (json.dumps(receipt, sort_keys=True) + "\n").encode()
        )
        _outputs(
            environment,
            repository=repository,
            reporting_completed="true",
            result_status=status,
            artifact_dir=str(directory),
        )
        _summary(environment, markdown, repository=repository)
        print(f"Arena offline comparison: {status}; artifacts prepared.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Arena offline comparison ERROR: {error}", file=sys.stderr)
        try:
            _summary(
                environment,
                "# MSL-Arena regression reporting\n\n**ERROR**: reporting or Actions summary delivery failed. No successful gate is inferred.",
                repository=repository,
            )
        except (OSError, ValueError, KeyError):
            pass
        return 1


def enforce(
    *, repository: Path = REPOSITORY_ROOT, environment: dict[str, str] | None = None
) -> int:
    """Fail closed on absent, partial, stale or inconsistent collection artifacts."""
    environment = dict(os.environ) if environment is None else environment
    try:
        if (
            environment.get("ARENA_REPORTING_COMPLETED") != "true"
            or environment.get("ARENA_REPORTING_OUTCOME") != "success"
        ):
            raise ValueError("The reporting step did not complete successfully")
        directory = output_directory(repository, environment)
        artifacts = {}
        for name in ("result.json", "report.json", "report.md"):
            path = directory / name
            if directory.is_symlink() or path.is_symlink():
                raise ValueError("Symlinked result artifacts are forbidden")
            artifacts[name] = swebench_eval._read(path, MAX_OUTPUT_BYTES)
        receipt = swebench_eval._json(artifacts["result.json"])
        if (
            not isinstance(receipt, dict)
            or set(receipt)
            != {
                "schema_version",
                "reporting_completed",
                "status",
                "report_sha256",
                "markdown_sha256",
            }
            or type(receipt["schema_version"]) is not int
            or receipt["schema_version"] != 1
            or receipt["reporting_completed"] is not True
        ):
            raise ValueError("Missing successful collection receipt")
        if any(
            hashlib.sha256(artifacts[name]).hexdigest() != receipt[key]
            for name, key in (("report.json", "report_sha256"), ("report.md", "markdown_sha256"))
        ):
            raise ValueError("Result artifacts changed after reporting")
        status = result_status(swebench_eval._json(artifacts["report.json"]))
        if receipt["status"] != status or environment.get("ARENA_RESULT_STATUS") != status:
            raise ValueError("Collection receipt contradicts the report")
        print(f"Arena regression gate: {status}")
        return STATUSES[status]
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(f"Arena regression gate ERROR: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("collect", "enforce"))
    args = parser.parse_args(argv)
    return collect() if args.operation == "collect" else enforce()


if __name__ == "__main__":
    raise SystemExit(main())
