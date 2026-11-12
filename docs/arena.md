# MSL-Arena Mini — M1

Arena Mini runs five fixed infrastructure smoke checks inside the existing
Docker/Podman sandbox. It does **not** run a model, agent, paid API or simulated
agent conversation. PASS means a small deterministic container assertion passed,
not that an agent resisted prompt injection. No resistance score, agent ranking
or attack success rate is calculated.

## Requirements and usage

Use Python 3.11+ and a local, functioning Docker or Podman engine. No Python
packages are required. Runtime detection reuses `tools.container_sandbox` and
prefers Podman when both executables are on PATH. The engine must be accessible
to the current user and support the sandbox's memory/CPU and read-only mounts.
Remote engine contexts are not supported; configure a local engine first.

An appropriate Linux Python image must already exist locally. Mini defaults to
`python:3.11-alpine`; image acquisition is a separate user-managed prerequisite.
The benchmark never pulls or builds an image, installs packages, performs DNS
lookups or contacts a network endpoint from its scenarios. Both the local image
preflight and `--pull=never` prevent accidental registry downloads.

From the repository root:

```sh
python3 evals/arena/cli.py --benchmark mini
python3 evals/arena/cli.py --benchmark mini \
  --report /tmp/arena-mini.md --output-json /tmp/arena-mini.json
```

`--image` selects an already-present, trusted image with Python 3.11+ and its full
standard library and enabled assertions (no Python optimization mode). Each
fixture rejects an older interpreter or disabled assertions explicitly. For
repeatable environments, use the same locally available
image digest on each machine. Mutable image tags do not pin image content. The
report records the requested image and the local image ID returned by the engine.
The Markdown report always prints to stdout; file outputs are opt-in. Markdown
and JSON destinations must differ. Report write errors produce a nonzero exit.

## Fixed scenarios

| ID | Check | Meaning of PASS |
| --- | --- | --- |
| mini-01 | Python/JSON round trip | Small fixed data round-trips through Python's JSON module |
| mini-02 | Read-only root and script | Root reports read-only and opening the mounted fixture for writing is denied; no write is performed |
| mini-03 | Temporary scratch | A small file can be written/read under the container's `/tmp` and removed |
| mini-04 | Network interfaces | The network namespace exposes no non-loopback interfaces; no connection is attempted |
| mini-05 | Framing and redaction fixtures | Existing input wrapping produces one XML data element and the existing redactor removes a synthetic token |

Mini reuses `injection_harness.wrap_untrusted_input()` and
`behavior_harness.redact_sensitive_content()`. It does not call their simulated
response engines, agent scorers, Git discovery or full evaluation/report runners.
The final fixture checks deterministic helper output, not agent behavior.

Each scenario is a fresh invocation of `container_sandbox.execute_sandbox()`:

- Network disabled with `--network none`; no repository/workspace mount.
- Only the temporary fixture script is mounted, read-only.
- Read-only container root, 64 MiB `/tmp` tmpfs.
- Requested memory limit 128 MiB and CPU quota 0.5 CPUs.
- Ten-second host execution timeout; five-second image preflight/cleanup calls.
- `--rm` on normal completion; a uniquely named container for timeout cleanup.
- Scenarios are serial, fixed and benign: no forks, stress tests, malicious
  commands, sleeping indefinitely, fuzzing or live adversarial agent tasks.

The shared sandbox's optional `pull_never` and `container_name` parameters are
used by Arena; default behavior for existing sandbox callers is unchanged.

## Outcomes and exit codes

- **PASS:** sandbox completed with exit 0, requested security configuration and
  the exact fixture output marker. Stderr diagnostics remain visible.
- **FAIL:** a scenario assertion/output failed, the sandbox reported unexpected
  settings/status, or the runner encountered an unexpected invocation error.
- **TIMEOUT:** the sandbox reported execution timeout. Cleanup is attempted with
  the same runtime and that invocation's unique container name.
- **UNAVAILABLE:** no runtime, inaccessible engine, missing local image, preflight
  timeout, or runtime/image startup failure. No runtime means five UNAVAILABLE
  results, zero PASS results, and a nonzero exit. No host-Python execution fallback
  or synthetic passing responses are provided.
- **SKIPPED:** represented separately in the report schema for explicitly unrun
  checks. M1 uses UNAVAILABLE for missing prerequisites and does not skip checks
  after a successful preflight.

Exit **0** requires all five PASS; **1** means FAIL/TIMEOUT or a CLI/report error;
**2** means an unavailable/skipped benchmark (unless a FAIL/TIMEOUT also occurred).
Summary counts include every status, including unrun checks. JSON includes
`evidence_kind: "infrastructure-smoke"` and `agent_evaluation: false`.

## Limits and verification

Fixture inputs and expected markers are deterministic. Durations, generated
container names in runtime diagnostics, engine versions and images may vary.
Limits in the report describe requested configuration, not an independent audit
of kernel or cgroup enforcement. The read-only and interface checks do not prove
the sandbox is escape-proof or inspect every isolation mechanism.

The shared host timeout stops the runtime CLI, which alone cannot guarantee that
its container stopped. Arena additionally attempts bounded, named cleanup after
timeouts/errors and interruptions. A cleanup failure is visible in the report
and the container may remain; inspect and remove it using the local engine. Engine
failure or forcefully killing Arena can prevent cleanup. Host fixture files are
temporary; no repository files or host credentials are mounted into containers.

Diagnostics reuse the existing redaction and output truncation helpers. Redaction
is best effort, not a promise to detect every possible secret format. Only fixed
trusted fixtures are supported in M1; do not use this as an arbitrary code runner.
Docker/Podman permissions and the chosen image remain part of the trust boundary.

`tests/test_arena.py` uses mocks for runtime detection, process calls and sandbox
execution, covering statuses, cleanup, isolation arguments and report semantics.
Those unit checks do not establish a working local container engine or live-agent
resistance. No SWE-bench adapter, autonomous fuzzing, CI integration, external
service or large attack catalogue is included in this milestone.
