"""Opt-in execution of the installed official SWE-bench v2.1.0 harness."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from evals.arena import swebench, swebench_eval
from evals.arena.runner import markdown_cell, safe_text

GIB = 1024**3
MIB = 1024**2
MIN_DISK_BYTES = 120 * GIB
MEMORY_PER_WORKER = 8 * GIB
FILE_LIMIT = 16 * MIB
CONSOLE_LIMIT = MIB
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCOPE = (
    "Execution status is separate from task resolution. Only the M5b importer may assess "
    "harness artifacts; process exit zero does not establish RESOLVED or Pass@1. "
    "This official harness profile is not the M4 adapter sandbox."
)

# This bootstrap limits host files and disables implicit .env credential loading.
# The official module retains all task execution and scoring responsibilities.
BOOTSTRAP = """import functools, resource, runpy, sys
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
import docker
docker.from_env = functools.partial(docker.from_env, version='1.41')
limit = int(sys.argv.pop(1))
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
sys.argv[0] = 'swebench.harness.run_evaluation'
runpy.run_module('swebench.harness.run_evaluation', run_name='__main__')
"""
PROBE = """import importlib.metadata, inspect, json, resource, sys
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
import docker
import swebench
from swebench.harness import run_evaluation
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
pairs = json.loads(sys.argv[1])
client = docker.from_env(timeout=5, version='1.41')
try:
    client.images.list()
    client.containers.list(all=True)
    print(json.dumps({
        'version': importlib.metadata.version('swebench'),
        'module_version': swebench.__version__,
        'python': list(sys.version_info[:2]),
        'parameters': list(inspect.signature(run_evaluation.main).parameters),
        'supported_tasks': all(repo in MAP_REPO_VERSION_TO_SPECS and version in MAP_REPO_VERSION_TO_SPECS[repo] for repo, version in pairs),
        'ping': client.ping(),
        'nofile_hard': resource.getrlimit(resource.RLIMIT_NOFILE)[1],
    }))
finally:
    client.close()
"""


class Unavailable(ValueError):
    """A mandatory execution prerequisite could not be confirmed."""


class CleanupFailure(OSError):
    """The host harness process group could not be terminated or reaped."""


class UnixAPI(http.client.HTTPConnection):
    def __init__(self, path: Path):
        super().__init__("localhost", timeout=5)
        self.path = path
        self.transport = None
        self.aborted = False

    def connect(self):
        if self.aborted:
            raise OSError("Rootless API deadline expired")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.transport = self.sock
        self.sock.settimeout(self.timeout)
        if self.aborted:
            self.abort()
            raise OSError("Rootless API deadline expired")
        self.sock.connect(str(self.path))

    def abort(self):
        self.aborted = True
        if self.transport is not None:
            try:
                self.transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.transport.close()


def _api(path: Path, method: str, route: str) -> tuple[int, bytes]:
    connection = UnixAPI(path)
    expired = threading.Event()

    def abort():
        expired.set()
        connection.abort()

    deadline = threading.Timer(5, abort)
    deadline.daemon = True
    deadline.start()
    response = None
    try:
        connection.request(method, route, headers={"Connection": "close"})
        response = connection.getresponse()
        body = response.read(65_537)
        if expired.is_set():
            raise Unavailable("Docker-compatible API deadline expired")
        if len(body) > 65_536:
            raise Unavailable("Docker-compatible API response exceeded its byte limit")
        return response.status, body
    except (OSError, http.client.HTTPException) as error:
        if expired.is_set():
            raise Unavailable("Docker-compatible API deadline expired") from error
        raise
    finally:
        deadline.cancel()
        if response is not None:
            response.close()
        connection.close()


def _api_json(path: Path, route: str) -> dict:
    status, body = _api(path, "GET", route)
    if status != 200:
        raise Unavailable("Local Docker-compatible API request failed")
    value = swebench_eval._json(body)
    if not isinstance(value, dict):
        raise Unavailable("Docker-compatible API returned an unsupported structure")
    return value


def _endpoint(engine: str) -> Path:
    if sys.platform != "linux" or not hasattr(os, "getuid") or os.getuid() == 0:
        raise Unavailable("Execution requires native Linux under a non-root host user")
    suffix = "docker.sock" if engine == "docker" else "podman/podman.sock"
    path = Path(f"/run/user/{os.getuid()}") / suffix
    if not path.is_socket() or path.stat().st_uid != os.getuid():
        raise Unavailable(
            "The selected user's rootless API socket is unavailable or not user-owned"
        )
    return path


def _environment(home: Path, endpoint: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "DOCKER_CONFIG": str(home),
        "DOCKER_HOST": f"unix://{endpoint}",
        "DOCKER_API_VERSION": "1.41",
        "HF_HUB_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(home),
    }


def _registry(run_id: str) -> Path:
    digest = swebench_eval._hash(run_id.encode("utf-8"))
    return Path.home() / ".local/state/msl-arena/swebench-runs" / f"{digest}.json"


def _log_bytes(directory: Path) -> int:
    """Count regular harness logs without following its image-build symlinks."""
    total = 0
    if not directory.exists():
        return total
    for parent, directories, files in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories if not (Path(parent) / name).is_symlink()]
        for name in files:
            path = Path(parent) / name
            if not path.is_symlink() and path.is_file():
                total += path.stat().st_size
    return total


@dataclass
class ProcessResult:
    status: str
    exit_code: int | None
    stdout: bytes = b""
    stderr: bytes = b""


def _stop(process) -> None:
    # The harness creates worker threads and may spawn subprocesses on the host.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise CleanupFailure("Could not terminate the harness process group") from error
    try:
        process.wait(timeout=2)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        pass
    # Kill surviving descendants even if their parent has already terminated.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise CleanupFailure("Could not kill the harness process group") from error
    try:
        process.wait(timeout=3)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        raise CleanupFailure("Harness process group could not be reaped") from error


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
    log_limit: int,
    console_limit: int = CONSOLE_LIMIT,
) -> ProcessResult:
    """M5-specific process bounds; M4's executor and its limits are unchanged."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
        bufsize=0,
    )
    buffers = [bytearray(), bytearray()]
    overflow, io_failed = threading.Event(), threading.Event()

    def drain(stream, buffer):
        try:
            while chunk := stream.read(4096):
                remaining = console_limit - len(buffer)
                buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    return
        except OSError:
            io_failed.set()
        finally:
            stream.close()

    threads = [
        threading.Thread(target=drain, args=(process.stdout, buffers[0]), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, buffers[1]), daemon=True),
    ]
    status = "COMPLETED"
    started = time.monotonic()
    try:
        for thread in threads:
            thread.start()
        while process.poll() is None or any(thread.is_alive() for thread in threads):
            if overflow.is_set() or _log_bytes(cwd / "logs") > log_limit:
                status = "LOG_LIMIT"
                break
            if io_failed.is_set():
                status = "FAILED"
                break
            if time.monotonic() - started >= timeout:
                status = "TIMEOUT"
                break
            overflow.wait(0.05)
    except KeyboardInterrupt:
        status = "INTERRUPTED"
    finally:
        _stop(process)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=1)
    if any(thread.is_alive() for thread in threads):
        raise CleanupFailure("Harness output pipes did not close")
    if status == "COMPLETED":
        if overflow.is_set() or _log_bytes(cwd / "logs") > log_limit:
            status = "LOG_LIMIT"
        elif io_failed.is_set() or process.returncode:
            status = "FAILED"
    return ProcessResult(status, process.returncode, bytes(buffers[0]), bytes(buffers[1]))


@dataclass
class RunPlan:
    prepared: swebench_eval.PredictionSet
    dataset_bytes: bytes
    predictions_bytes: bytes
    dataset_sha256: str
    run_manifest_bytes: bytes
    run_manifest_sha256: str
    work_dir: Path
    python: Path
    engine: str
    workers: int
    timeout: int
    test_timeout: int
    log_limit: int
    instance_ids: tuple[str, ...]

    @property
    def command(self) -> list[str]:
        return [
            str(self.python),
            "-I",
            "-B",
            "-c",
            BOOTSTRAP,
            str(FILE_LIMIT),
            "--dataset_name",
            str(self.work_dir / "inputs/dataset.json"),
            "--predictions_path",
            str(self.work_dir / "inputs/predictions.jsonl"),
            "--instance_ids",
            *self.instance_ids,
            "--max_workers",
            str(self.workers),
            "--timeout",
            str(self.test_timeout),
            "--open_file_limit",
            "1024",
            "--run_id",
            self.prepared.run_id,
            "--cache_level",
            "env",
            "--clean",
            "False",
            "--force_rebuild",
            "False",
        ]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(
            f"sweb.eval.{instance_id}.{self.prepared.run_id}" for instance_id in self.instance_ids
        )

    def report(self) -> dict:
        return {
            "schema_version": 1,
            "benchmark": "swebench-run",
            "scope": SCOPE,
            "execution_status": "PREVIEW",
            "evaluation_status": "NOT_IMPORTED",
            "run_id": self.prepared.run_id,
            "instance_ids": list(self.instance_ids),
            "command": self.command,
            "cwd": str(self.work_dir),
            "engine": self.engine,
            "environment_keys": sorted(
                _environment(self.work_dir / "home", Path("/rootless-socket"))
            ),
            "manifest_sha256": self.prepared.manifest_sha256,
            "dataset_sha256": self.dataset_sha256,
            "predictions_sha256": self.prepared.predictions_sha256,
            "validated_export_sha256": swebench_eval._hash(self.prepared.export_bytes),
            "executed_dataset_sha256": swebench_eval._hash(self.dataset_bytes),
            "executed_predictions_sha256": swebench_eval._hash(self.predictions_bytes),
            "run_manifest_sha256": self.run_manifest_sha256,
            "results_directory": str(self.work_dir / "logs/run_evaluation"),
            "limits": {
                "workers": self.workers,
                "timeout_seconds": self.timeout,
                "test_timeout_seconds": self.test_timeout,
                "console_bytes_per_stream": CONSOLE_LIMIT,
                "file_bytes": FILE_LIMIT,
                "harness_logs_bytes": self.log_limit,
                "minimum_disk_bytes": MIN_DISK_BYTES,
                "memory_bytes_per_worker": MEMORY_PER_WORKER,
            },
            "preflight": "NOT_RUN",
            "cleanup_errors": [],
        }


def plan_run(
    manifest: Path,
    predictions: Path,
    prediction_export: Path,
    dataset: Path,
    run_manifest: Path,
    *,
    run_id: str,
    work_dir: Path,
    python: Path | None = None,
    engine: str = "docker",
    limit: int = 1,
    workers: int = 1,
    timeout: int = 3600,
    test_timeout: int = 1800,
    log_limit_mib: int = 128,
) -> RunPlan:
    for value, minimum, maximum, label in (
        (limit, 1, 50, "task limit"),
        (workers, 1, 4, "workers"),
        (timeout, 1, 86_400, "overall timeout"),
        (test_timeout, 1, 3600, "test timeout"),
        (log_limit_mib, 16, 1024, "log limit"),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"Invalid SWE-bench runner {label}")
    if test_timeout > timeout or workers > limit or engine not in {"docker", "podman"}:
        raise ValueError("Inconsistent SWE-bench runner limits or engine")
    prepared = swebench_eval.prepare_predictions(manifest, predictions, run_id=run_id)
    if any(
        record["model_name_or_path"].casefold() == "gold" for record in prepared.records.values()
    ):
        raise ValueError("Gold prediction exports are not accepted for execution")
    receipt = swebench_eval._read(run_manifest)
    if swebench_eval._canonical(swebench_eval._json(receipt)) != swebench_eval._canonical(
        prepared.to_dict()
    ):
        raise ValueError("Saved M5b run manifest does not match the current inputs")
    if swebench_eval._read(prediction_export) != prepared.export_bytes:
        raise ValueError("Prediction export differs from the deterministic M5b export")
    manifest_data, _, _ = swebench_eval.load_manifest(manifest)
    local = swebench.prepare(dataset, limit=manifest_data["selection"]["limit"])
    if local.source["sha256"] != prepared.source_sha256 or local.tasks != prepared.tasks:
        raise ValueError("Local dataset does not match the M5a source and selected tasks")
    chosen = prepared.tasks[:limit]
    if workers > len(chosen):
        raise ValueError("Worker count exceeds the number of selected tasks")
    records = []
    for task in chosen:
        if prepared.prediction_status(task.instance_id) != "READY":
            raise ValueError("Every execution-selected task needs one ready prediction")
        private = task.evaluation_metadata
        if not isinstance(private.get("version"), str) or not private["version"].strip():
            raise ValueError("Execution requires a task version for the official harness")
        if (
            not isinstance(private.get("test_patch"), str)
            or not private["test_patch"].strip()
            or not task.fail_to_pass
        ):
            raise ValueError("Execution requires a nonempty test patch and failure expectations")
        if len(f"sweb.eval.{task.instance_id}.{run_id}") > 255:
            raise ValueError("Harness container name would exceed the supported length")
        records.append(
            {
                **task.agent_input(),
                "version": private["version"],
                "hints_text": private.get("hints_text") or "",
                "test_patch": private["test_patch"],
                "FAIL_TO_PASS": list(task.fail_to_pass),
                "PASS_TO_PASS": list(task.pass_to_pass),
            }
        )
        # M5a already validates non-null environment commits as full commit IDs.
        if private.get("environment_setup_commit") is not None:
            records[-1]["environment_setup_commit"] = private["environment_setup_commit"]
    work_dir = work_dir.absolute()
    if work_dir.exists() or work_dir.is_symlink():
        raise ValueError(
            "Harness work directory must be new; cached result directories are forbidden"
        )
    work_dir = work_dir.resolve()
    if not work_dir.parent.is_dir() or work_dir.is_relative_to(REPOSITORY_ROOT):
        raise ValueError("Harness work directory needs an existing parent outside this repository")
    registry = _registry(run_id)
    if registry.exists() or registry.is_symlink():
        raise ValueError("SWE-bench run_id was already reserved; use a fresh ID")
    # Resolving a venv's interpreter symlink would silently select system Python.
    interpreter = (python if python is not None else Path(sys.executable)).absolute()
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise ValueError("Harness Python interpreter is not executable")
    return RunPlan(
        prepared,
        swebench_eval._canonical(records) + b"\n",
        b"".join(
            swebench_eval._canonical(prepared.records[task.instance_id]) + b"\n" for task in chosen
        ),
        local.source["sha256"],
        receipt,
        swebench_eval._hash(receipt),
        work_dir,
        interpreter,
        engine,
        workers,
        timeout,
        test_timeout,
        log_limit_mib * MIB,
        tuple(task.instance_id for task in chosen),
    )


def _preflight(plan: RunPlan) -> Path:
    endpoint = _endpoint(plan.engine)
    info = _api_json(endpoint, "/info")
    if plan.engine == "docker":
        options = info.get("SecurityOptions")
        if (
            not isinstance(options, list)
            or not all(isinstance(option, str) for option in options)
            or "name=rootless" not in options
        ):
            raise Unavailable("Docker-compatible API did not confirm rootless Docker")
    else:
        libpod = _api_json(endpoint, "/libpod/info")
        host = libpod.get("host")
        security = host.get("security") if isinstance(host, dict) else None
        if not isinstance(security, dict) or security.get("rootless") is not True:
            raise Unavailable("Podman API did not confirm rootless mode")
    version = _api_json(endpoint, "/version")
    api_version = version.get("ApiVersion")
    try:
        compatible = (
            isinstance(api_version, str)
            and len(api_version.split(".")) == 2
            and tuple(int(part) for part in api_version.split(".")) >= (1, 41)
        )
    except ValueError:
        compatible = False
    if not compatible or info.get("OSType") != "linux":
        raise Unavailable(
            "Selected rootless API is not compatible with the required Linux Docker API 1.41"
        )
    cpus, memory = info.get("NCPU"), info.get("MemTotal")
    if (
        type(cpus) is not int
        or cpus < 2 * plan.workers
        or type(memory) is not int
        or memory < MEMORY_PER_WORKER * plan.workers
    ):
        raise Unavailable("Engine needs at least two CPUs and 8 GiB RAM capacity per worker")
    storage = info.get("DockerRootDir")
    if (
        not isinstance(storage, str)
        or not Path(storage).is_absolute()
        or not Path(storage).is_dir()
    ):
        raise Unavailable("Local engine storage path cannot be verified")
    for directory in (Path(storage), plan.work_dir.parent):
        if shutil.disk_usage(directory).free < MIN_DISK_BYTES:
            raise Unavailable(
                "At least 120 GiB free is required on engine storage and the work filesystem"
            )
    for name in plan.names:
        status, _ = _api(endpoint, "GET", f"/containers/{quote(name, safe='')}/json")
        if status != 404:
            raise Unavailable("A selected harness container already exists or cannot be checked")
    with tempfile.TemporaryDirectory(prefix="msl-swebench-probe-") as temporary:
        home = Path(temporary)
        pairs = [
            [task.repo, task.evaluation_metadata["version"]]
            for task in plan.prepared.tasks
            if task.instance_id in plan.instance_ids
        ]
        result = _run_process(
            [str(plan.python), "-I", "-B", "-c", PROBE, json.dumps(pairs)],
            cwd=home,
            environment=_environment(home, endpoint),
            timeout=20,
            log_limit=MIB,
            console_limit=65_536,
        )
        if result.status == "INTERRUPTED":
            raise KeyboardInterrupt
        if result.status != "COMPLETED" or result.exit_code:
            raise Unavailable(
                "Harness v2.1.0/dependencies or Docker SDK compatibility probe failed; nothing is installed automatically"
            )
        data = swebench_eval._json(result.stdout)
        expected = {
            "dataset_name",
            "split",
            "instance_ids",
            "predictions_path",
            "max_workers",
            "force_rebuild",
            "cache_level",
            "clean",
            "open_file_limit",
            "run_id",
            "timeout",
        }
        if (
            not isinstance(data, dict)
            or data.get("version") != "2.1.0"
            or data.get("module_version") != "2.1.0"
            or not isinstance(data.get("python"), list)
            or len(data["python"]) != 2
            or not all(type(value) is int for value in data["python"])
            or data["python"] < [3, 11]
            or not isinstance(data.get("parameters"), list)
            or not all(isinstance(value, str) for value in data["parameters"])
            or set(data["parameters"]) != expected
            or data.get("supported_tasks") is not True
            or data.get("ping") is not True
            or type(data.get("nofile_hard")) is not int
            or (data["nofile_hard"] != -1 and data["nofile_hard"] < 1024)
        ):
            raise Unavailable(
                "Installed harness version, task support or file-descriptor capacity is incompatible"
            )
    return endpoint


def _cleanup(plan: RunPlan, endpoint: Path) -> list[str]:
    errors = []
    for name in plan.names:
        try:
            status, _ = _api(
                endpoint, "DELETE", f"/containers/{quote(name, safe='')}?force=true&v=false"
            )
            if status not in (204, 404):
                errors.append(f"Could not remove harness container {name}")
        except (OSError, ValueError, http.client.HTTPException, KeyboardInterrupt):
            errors.append(f"Could not confirm cleanup of harness container {name}")
    return errors


def run(plan: RunPlan, *, execute: bool = False) -> dict:
    if type(execute) is not bool:
        raise ValueError("Execution must be explicitly enabled with a boolean")
    report = plan.report()
    if not execute:
        return report
    try:
        if (
            plan.work_dir.exists()
            or plan.work_dir.is_symlink()
            or _registry(plan.prepared.run_id).exists()
        ):
            raise Unavailable("Run ID or work directory was already used")
        endpoint = _preflight(plan)
    except KeyboardInterrupt:
        report.update(execution_status="INTERRUPTED", preflight="INTERRUPTED")
        return report
    except (OSError, ValueError, http.client.HTTPException) as error:
        report.update(
            execution_status="UNAVAILABLE",
            preflight="FAILED",
            diagnostic=safe_text(f"{plan.engine} preflight: {error}"),
        )
        return report
    report.update(preflight="PASSED", engine_endpoint=f"unix://{endpoint}")
    try:
        registry = _registry(plan.prepared.run_id)
        registry.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with registry.open("x", encoding="utf-8") as stream:
            os.chmod(registry, 0o600)
            json.dump(
                {
                    "run_id": plan.prepared.run_id,
                    "work_dir": str(plan.work_dir),
                    "manifest_sha256": plan.prepared.manifest_sha256,
                },
                stream,
            )
        plan.work_dir.mkdir(mode=0o700, exist_ok=False)
        inputs, home = plan.work_dir / "inputs", plan.work_dir / "home"
        inputs.mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        (inputs / "dataset.json").write_bytes(plan.dataset_bytes)
        (inputs / "predictions.jsonl").write_bytes(plan.predictions_bytes)
        (inputs / "run-manifest.json").write_bytes(plan.run_manifest_bytes)
    except OSError as error:
        report.update(
            execution_status="UNAVAILABLE",
            diagnostic=safe_text(f"Fresh run reservation failed: {error}"),
        )
        return report
    report["execution_status"] = "FAILED"
    host_cleanup_errors = []
    try:
        result = _run_process(
            plan.command,
            cwd=plan.work_dir,
            environment=_environment(home, endpoint),
            timeout=plan.timeout,
            log_limit=plan.log_limit,
        )
        report.update(execution_status=result.status, exit_code=result.exit_code)
        for label, raw in (("stdout", result.stdout), ("stderr", result.stderr)):
            (plan.work_dir / f"arena-{label}.log").write_bytes(raw)
            report[f"{label}_bytes"] = len(raw)
            report[f"{label}_sha256"] = swebench_eval._hash(raw)
    except KeyboardInterrupt:
        report["execution_status"] = "INTERRUPTED"
    except CleanupFailure as error:
        host_cleanup_errors.append(safe_text(str(error)))
    except (OSError, ValueError) as error:
        report["diagnostic"] = safe_text(str(error))
    finally:
        errors = host_cleanup_errors + _cleanup(plan, endpoint)
        report["cleanup_errors"] = errors
        if errors:
            report["prior_execution_status"] = report["execution_status"]
            report["execution_status"] = "CLEANUP_FAILED"
    return report


def markdown_report(report: dict) -> str:
    lines = [
        "# MSL-Arena SWE-bench — controlled harness execution",
        "",
        SCOPE,
        "",
        f"Execution: **{report['execution_status']}**; evaluation: **{report['evaluation_status']}**.",
        f"Run: {markdown_cell(report['run_id'])}; engine: {report['engine']}.",
        f"Selected tasks: {', '.join(markdown_cell(value) for value in report['instance_ids'])}.",
        "",
        "Command argv (JSON data, not a shell command):",
        "",
        "<pre><code>" + markdown_cell(json.dumps(report["command"])) + "</code></pre>",
        "",
        f"Working directory: {markdown_cell(report['cwd'])}.",
        f"Manifest SHA-256: {report['manifest_sha256']}.",
        f"Preflight: {report['preflight']}.",
        f"Limits: {report['limits']['timeout_seconds']}s overall; "
        f"{report['limits']['test_timeout_seconds']}s per task; "
        f"{report['limits']['workers']} worker(s); "
        f"{report['limits']['harness_logs_bytes']} bytes of harness logs; "
        f"{report['limits']['file_bytes']} bytes per host output file.",
    ]
    if "diagnostic" in report:
        lines.extend(["", markdown_cell(report["diagnostic"])])
    for error in report["cleanup_errors"]:
        lines.extend(["", "Cleanup error: " + markdown_cell(error)])
    return "\n".join(lines)
