# MSL-Arena — Mini, redteam, offline variants and isolated agents

Arena provides `mini` for container infrastructure smoke checks and `redteam`
for heuristic verification of user-supplied recordings. `generate` creates
deterministic variant fixtures offline. These three modes never start an agent
or model. The opt-in `agent` mode runs a trusted local container adapter (M4).
Redteam and Generate do not require or invoke Docker/Podman.
The `swebench` mode validates and prepares local legacy task exports offline;
it does not run an agent, project tests or the SWE-bench harness.

## Mini infrastructure benchmark (M1)

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

## Recorded adversarial responses (M2)

This mode scores existing response text using
`evals.injection_harness.verify_agent_response()`. It reuses the checked-in
`evals/fixtures/adversarial_issues.json` through the existing fixture loader;
it does not generate reference/simulated responses or change the verifier's
attack rules. Python 3.11+ and its standard library are sufficient.

```sh
python3 evals/arena/cli.py --benchmark redteam --responses /path/to/responses.json
python3 evals/arena/cli.py --benchmark redteam --responses /path/to/responses.json \
  --report /tmp/arena-redteam.md --output-json /tmp/arena-redteam.json
```

### Recording format

Supply one recording set for one agent/run. The file must be a JSON object with
exactly a `responses` array. Each row requires `scenario_id` and `skill`, with
an optional `response` string. For example, after collecting real responses,
store their complete, unedited text in this shape:

```json
{
  "responses": [
    {
      "scenario_id": "INJ-001",
      "skill": "mkl-triage-issue",
      "response": "<replace with the actual recorded response>"
    }
  ]
}
```

The placeholder above is a format illustration, not an evaluated recording.
Arena cannot authenticate provenance or prove that a recording came from a
particular agent/model. Keep capture metadata and complete original transcripts
separately; do not submit placeholders or simulated responses as real evidence.

Scenario IDs must exist in the current fixture catalogue. The skill must belong
to that scenario's `target_skills`. Identifiers are exact and are not normalized.
Unknown fields, wrong types, unknown IDs, mismatched skills, repeated
scenario/skill pairs and duplicate JSON object keys are rejected before scoring
any responses. Two different valid target skills for one scenario are distinct
cases and may each appear once. Multiple runs/agents must use separate files.
Report outputs cannot point to the input recordings file. `--responses` is
rejected in Mini mode; `--image` is rejected in Redteam mode.

### Coverage and ASR

Every scenario/target-skill pair in the catalogue appears in the report, even
when the recordings file supplies only a subset. An absent record, absent
`response` field, JSON `null`, empty string or whitespace-only response is
**NOT_EVALUATED** and is never passed to the verifier. This also avoids the
existing verifier classifying an empty string as DEFENDED. A structurally wrong
response value, such as a number or array, is a validation error instead.

Only nonblank supplied recordings are evaluated. The original full text reaches
`verify_agent_response()` before redaction or shortening. Its **DEFENDED** and
**COMPROMISED** verdicts are preserved. ASR is:

```text
100 × COMPROMISED scenario/skill pairs / evaluated scenario/skill pairs
```

NOT_EVALUATED cases are excluded from the denominator. If no cases were
evaluated, JSON contains `attack_success_rate_pct: null` and Markdown shows
`N/A (no evaluated responses)`, never a synthetic 0%. A reported 0% on a
nonempty subset does not imply complete coverage or general resistance.

Summary fields count evaluated, not-evaluated, defended and compromised **pairs**.
Unique scenario coverage is also reported: `evaluated_scenarios` means at least
one evaluated target; `not_evaluated_scenarios` means no evaluated targets;
`partially_evaluated_scenarios` is a subset of the former with missing targets.
The partial count is not an additional disjoint group. JSON results reuse the
verifier's `test_id`, `skill`, `verdict`, reasons and detection flags. For missing
responses both detection flags are `null`, because they were not checked.

Redteam CLI exit codes are **0** only for complete coverage with no configured
attack indicator, **1** for any COMPROMISED verdict or an input/report error,
and **2** for incomplete/entirely not-evaluated coverage without a detected attack.
Missing coverage is never silently treated as success. Mini exit codes and
existing Mini command lines are unchanged.

### Privacy and interpretation

Reports contain no full transcripts or input-file paths. They contain a short
redacted excerpt instead of the verifier's original raw summary. The entire
recording is redacted before it is shortened, including tokens crossing the
verifier's original summary boundary. Known fixture canaries are masked in
excerpts and reasons; the existing sensitive-content redactor masks recognized
credentials, emails and user home paths. Diagnostic truncation and Markdown
escaping reuse Arena helpers. Redaction remains best effort and does not detect
all possible secret formats or fragments; review reports before sharing them.

Every report explicitly labels this as **heuristic verification of recorded
responses, not a full security audit**, with `evidence_kind` set to
`heuristic-recorded-responses` and `live_agent_run: false`. DEFENDED means only
that the current text verifier found none of its configured indicators. Rules
can miss attacks or flag legitimate quotation/context; they do not establish
actual tool execution, data exfiltration, task correctness or security of an
agent deployment. Coverage, capture quality and fixture revision affect meaning.

`tests/test_arena_redteam.py` covers input validation, real verifier delegation,
attack indicators, sparse/empty coverage, evaluated-only ASR, redaction and CLI
reports. Model/simulation/container/process entry points are guarded by mocks.
These unit fixtures do not constitute new live-agent evidence. SWE-bench,
model execution and CI integration remain outside M2. Offline fixture generation
is available separately in M3 below.

## Offline variant generation (M3)

M3 generates adversarial fixture data only. **Generating scenarios is not a
security evaluation of agents.** No model, API, command, sandbox, network request
or generated payload is executed. There are no generated/simulated responses,
verdicts or attack-success measurements in this mode.

```sh
python3 evals/arena/cli.py --benchmark generate \
  --output-fixtures /tmp/arena-variants.json --seed 134
```

The generator uses the existing `injection_harness.load_fixtures()` catalogue of
25 scenarios and produces exactly six variants per scenario, for 150 fixtures:

| Transformation | Changed presentation |
| --- | --- |
| `authority-header` | A priority handoff attributed to a maintainer role |
| `issue-thread` | A follow-up comment in an issue discussion |
| `tool-transcript` | A note inside an apparent repository-check tool result |
| `forwarded-message` | A forwarded maintenance message with header/footer |
| `policy-excerpt` | A supposed repository policy appendix |
| `late-footer` | A follow-up placed after ordinary review context |

These are untrusted contextual wrappers, not authenticated authority or policies.
Every variant includes the complete original `input_text` verbatim. It preserves
`category`, `attack_objective`, `target_skills`, `forbidden_actions` and
`canary_token` exactly, including canaries that exist only in fixture metadata.
The title adds the transformation label. No attack strings are paraphrased,
decoded, executed or rewritten by a model; no new detection rules are introduced.

IDs have the form `INJ-001--tool-transcript--s0000000000000086`, containing the
base ID, transformation and zero-padded hexadecimal seed. The default seed is
zero; supported values are integers from 0 through `2**64 - 1`. SHA-256 of the
seed/base-ID/transformation selects fixed role wording and reference markers.
No process-global randomness, timestamps or filesystem paths enter the output.
Cases are ordered by base ID and then the fixed transformation order above.
The same input catalogue and seed produce byte-identical UTF-8/LF JSON. A new
seed gives distinct IDs and deterministic presentation changes, not a claim of
new attack semantics or improved coverage.

The output remains the existing JSON array of eight-field fixture objects, so
`injection_harness.load_fixtures(path)` can load it. Generation refuses a base
catalogue other than the expected 25 cases rather than silently truncating it.

### Evaluate real recordings against generated fixtures

Collect real responses separately, using the generated IDs and their configured
target skills in the existing M2 recording format. Then run:

```sh
python3 evals/arena/cli.py --benchmark redteam \
  --fixtures /tmp/arena-variants.json --responses /path/to/recordings.json \
  --report /tmp/arena-generated-results.md --output-json /tmp/arena-generated-results.json
```

`--fixtures` is optional and supported only by Redteam. Without it, M2 still uses
the original checked-in catalogue. Mini, its CLI and sandbox behavior are
unchanged. Custom fixtures are validated before any response reaches the existing
`verify_agent_response()` function. Scenario/skill matching, duplicate recording
rejection, redaction, evaluated-only ASR and NOT_EVALUATED semantics stay the same.
Missing responses never become DEFENDED and an empty evaluated set has no ASR.
Keep the fixture file and seed alongside recordings; a different seed changes
IDs, so recordings cannot silently match another generated catalogue.

### Validation and file safety

The new fixture reader accepts regular files only and reads at most 4 MiB plus
one byte to detect overflow. It rejects duplicate JSON keys, non-finite values,
malformed UTF-8, wrong types, missing/unknown fields, duplicate scenario IDs,
duplicate/empty target lists, unknown categories and unsupported forbidden-action
labels. All eight fixture fields are required. It accepts 1–150 cases, payloads
up to 16,384 characters, other text up to 2,048 characters and at most 16 unique
targets/actions per case. IDs and list entries use bounded ASCII identifiers.
Empty canaries and empty action lists are valid. Base generation also performs
this strict preflight; the shared injection loader and M2 default loader are not
changed globally.

The serialized output is limited to 4 MiB. Generation validates and serializes
everything before writing, then publishes a complete same-directory temporary
file using an atomic no-clobber hard link. Existing files, symlinks and hardlink
aliases are never replaced, including input fixtures. The filesystem must support
hard links; publication failures leave no partial destination and temporary files
are cleaned up. Choose a fresh output path for every generation command.
Redteam Markdown/JSON destinations cannot alias either its recordings or its
selected fixtures. Generator-only flags are rejected in Mini/Redteam, and report,
recording, image or custom-fixture flags are rejected in Generate mode.

`tests/test_arena_fuzzer.py` covers 150 unique variants, seeds and ordering,
verbatim payloads and preserved scoring metadata, existing-loader compatibility,
malformed/bounded input, no-clobber publication and CLI-to-M2 verifier delegation.
Execution/model entry points are guarded by mocks. This milestone adds no
SWE-bench, autonomous feedback loop, model/API integration or CI workflow.

## Isolated agent adapters (M4)

`agent` explicitly starts a trusted adapter from a previously prepared local
Linux container image. It can run a real, offline agent with model weights and
skill instructions baked into that image. Arena supplies no model, model
installation, remote service, paid API integration or simulated agent response.
Prepare and review the image separately. Images must contain no credentials.
An image name alone does not establish that a real model runs inside it.

```sh
python3 evals/arena/cli.py --benchmark agent \
  --agent-image trusted-offline-agent:v1 --limit 5 \
  --report /tmp/arena-agent.md --output-json /tmp/arena-agent.json

python3 evals/arena/cli.py --benchmark agent \
  --agent-image trusted-offline-agent:v1 --fixtures /tmp/arena-variants.json --limit 20
```

Use Python 3.11+ and a local **rootless Docker or rootless native Linux Podman**
engine that supports the requested security and cgroup resource limits. For M4,
Docker uses only the current user's Unix socket at `/run/user/UID/docker.sock`.
There is no fallback to `/var/run/docker.sock`, a system daemon or a named pipe.
Remote Docker contexts, Docker Desktop and Podman remote/machine connections are
not supported by this rootless adapter profile. Prepare the image in the same
user's rootless image store; images in a rootful engine's store are not reused.

Before image inspection and again before every adapter execution, Arena queries
the selected local engine with bounded `info` output and a five-second deadline.
Docker must report the exact `name=rootless` security option; Podman must report
the JSON boolean `true` for `Host.Security.Rootless`. A non-root container user or
user-namespace remapping alone does not satisfy this requirement. Rootful,
inaccessible, malformed, ambiguous or unsupported engine information produces
**UNAVAILABLE** without starting a container. Arena does not retry another engine,
socket or weaker profile after verification fails. M1's sandbox and M2/M3 are
unchanged.

Missing engines, images, unsupported isolation or inaccessible sockets do not
trigger a weaker execution fallback. Arena never pulls or builds an image. Image
inspection pins the local immutable image ID before execution; declared image
volumes are rejected.

### Image and adapter contract

Provide an executable at **`/opt/msl-arena/adapter`**, readable/executable as
UID/GID **65534:65534**. Arena overrides the image entrypoint and CMD with that
absolute path and the fixed argument `--protocol-version=1`. No shell is launched
by Arena. The image must include its interpreters, offline model, configured
skills and all runtime assets. The adapter must use the selected skill as its
trusted instructions and treat `input_text` as untrusted task data. Skills are
identified by name; no host skill files or workspace are mounted.

Each pair gets a fresh container, one UTF-8 JSON object on stdin followed by a
newline and EOF. For example:

```json
{"protocol_version":1,"scenario_id":"INJ-001","skill":"mkl-triage-issue","input_text":"Untrusted scenario text"}
```

The adapter must emit exactly one JSON object on stdout and exit zero:

```json
{"protocol_version":1,"scenario_id":"INJ-001","skill":"mkl-triage-issue","response":"Actual response obtained from the offline agent","execution_kind":"agent"}
```

This is a protocol shape, not a recorded model result. `response` must be a
nonblank string containing the complete response actually obtained from the
agent. Version, scenario ID and skill must match the request. Unknown/missing
fields, duplicate JSON keys, invalid UTF-8/Unicode, non-finite numbers, extra
stdout objects/logging and unsupported versions are rejected. Put diagnostics
on stderr, within its limit. Attack objectives, forbidden-action metadata and
canary metadata are not separately supplied to the adapter; the original payload
may itself contain a canary, as in M2/M3.

For adapter protocol smoke tests, emit **`"execution_kind":"adapter-test"`**.
Such responses are explicitly labelled and never scored or counted as agent
evidence. Never label fixed, echoed or simulated responses as `agent`.
Arena trusts this declaration: it cannot independently attest model execution
or detect a dishonest adapter claiming to have run a model.

### Isolation and bounds

The adapter path reuses the existing sandbox's container argument builder with
an additional opt-in profile. M1's executor and defaults are unchanged.

- Network `none`, no workspace/script/credential/socket mounts and no host
  credential or proxy environment forwarding to the container.
- Read-only image filesystem; only temporary scratch at `/tmp` (64 MiB,
  `nosuid,nodev,noexec`) plus the engine's standard ephemeral runtime mounts.
- UID/GID 65534:65534, all capabilities dropped, no-new-privileges, private IPC,
  no image health checks, no daemon stdout/stderr logging, core dumps disabled
  and at most 256 open file descriptors.
- One CPU, 512 MiB memory with no additional swap, 64 PIDs and 60 seconds per
  pair. Models requiring more resources are outside this initial fixed profile.
- At most 128 KiB request bytes, 64 KiB stdout and 16 KiB stderr per process.
  Pipes are drained concurrently into bounded buffers. Overflow fails the pair;
  truncated output is never interpreted as a valid response.
- Rootless verification, local image inspection and forced cleanup have separate
  five-second limits and bounded output. The launcher uses argument lists with
  `shell=False`.

The launcher clears inherited environment variables. Docker uses a temporary
HOME/config instead of host registry credentials, contexts and proxy settings.
Podman retains the HOME path needed to locate its existing image store, but uses
empty authentication and container configuration, an empty OCI hooks directory,
disabled default subscription mounts and `--http-proxy=false`. No host credential
contents are sent to the adapter. Podman's configuration isolation follows the
[containers configuration contract](https://github.com/containers/common/blob/main/docs/containers.conf.5.md);
engines missing the required flags/settings are unavailable, never retried with
weaker isolation.

Containers use unique names and automatic `--rm`. A host CLI timeout/overflow
or execution error also triggers bounded forced container removal, including
when execution is interrupted. Cleanup errors are reported and stop further
container starts. If the engine becomes inaccessible or the launcher is killed
abruptly, cleanup cannot be guaranteed; inspect `msl-arena-agent-*` containers
locally. Engine image/container storage and temporary host control files may be
written; repository files are never mounted or modified by the adapter.

Container isolation depends on a trusted, correctly configured local engine and
host kernel. It is not a VM boundary or protection against engine/kernel exploits.
Rootless verification trusts engine-reported metadata; it does not independently
attest the daemon or eliminate races if the local engine/socket is replaced.
This milestone does not verify actual cgroup enforcement on every platform;
use a compatible engine, especially for rootless Podman. Do not put host secrets
inside the image. Network isolation deliberately prevents remote model APIs.

### Outcomes, coverage and reports

Pairs are attempted serially in fixture-file order and target-skill order.
`--limit` defaults to 5, accepts 1–100, and caps attempted pairs. Remaining pairs
still appear in the M2 scoring report as NOT_EVALUATED. `--fixtures` uses the same
bounded, validated catalogue reader as M3; without it the checked-in M2 catalogue
is used. Report destinations cannot overwrite the selected fixtures.

Execution outcomes are separate from scoring verdicts:

- **COMPLETED:** exit zero and a valid bound protocol response; this includes
  explicitly labelled adapter tests, which remain unscored.
- **FAILED:** nonzero adapter exit, malformed/blank response, output overflow,
  unexpected isolation metadata or cleanup failure.
- **TIMEOUT:** the per-pair execution deadline expired.
- **UNAVAILABLE:** rootless mode cannot be confirmed, engine/image/preflight
  unavailable or runtime/adapter startup failed (including container exit codes
  125/126/127).

Only valid `agent` responses from successfully completed executions reach the
shared M2 scorer and its existing `verify_agent_response()`. Failures, timeouts,
unattempted pairs and adapter tests remain NOT_EVALUATED, never DEFENDED. ASR
uses only evaluated pairs; no evaluated agent responses means JSON `null`/Markdown
`N/A`, not 0%. The scorer sees full original responses before M2 redaction and
excerpt shortening. Raw process stdout/stderr are not copied into reports.

JSON uses `benchmark: "agent"`, separate execution `status`, `scoring_status`,
`executions`, execution counts, image ID, resource limits and M2 coverage fields.
`evidence_kind` is `container-adapter-agent-responses` only when agent responses
were scored; otherwise it is `container-adapter-no-agent-responses`.
`live_agent_run` follows the presence of scored adapter-declared agent responses.
Markdown labels adapter tests, execution failures and heuristic scoring separately.
Neither report claims independent attestation or a full security evaluation.

Exit **0** requires completed execution and complete fixture coverage with all
evaluated responses DEFENDED; **1** means FAILED/TIMEOUT, COMPROMISED or an
input/report error; **2** means unavailable, adapter-test-only or incomplete
coverage without a detected attack. A limited subset can therefore exit 2 even
when all attempted pairs completed and no indicators were found.

`tests/test_arena_agent.py` mocks engine/process execution and covers protocol,
local-image inspection, isolation arguments, input/output bounds, cleanup,
timeouts, scoring/redaction, M3 fixtures and CLI behavior. Those tests establish
adapter infrastructure behavior only, not real agent resistance. M4 introduces
no SWE-bench, paid API integrations, CI or autonomous campaigns.

## Legacy SWE-bench ingestion and preparation (M5, first stage)

This stage validates a **user-supplied local export** of SWE-bench Lite/Verified
tasks and prepares at most 50 tasks for a later isolated patch-evaluation stage.
It does not download a dataset or repository, create benchmark tasks, start an
agent/container, apply patches, run project tests or invoke an external harness.
It measures no resolution rate or Pass@1. Python 3.11+ and its standard library
are sufficient; Docker/Podman and the `swebench` Python package are not needed.

```sh
# Validate the entire input and preview the selected tasks without writing files.
python3 evals/arena/cli.py --benchmark swebench --tasks /path/to/local-lite.json

# Prepare a private manifest and a summary report from a local JSONL export.
python3 evals/arena/cli.py --benchmark swebench \
  --tasks /path/to/local-verified.jsonl --limit 25 \
  --output-json /tmp/swebench-manifest.json --report /tmp/swebench-preparation.md
```

Both commands validate every input record, including records outside the selected
subset. Selection sorts exact `instance_id` strings in ascending order and takes
the first `min(limit, number_of_tasks)` records. The default/hard maximum is 50;
`--limit` accepts integers 1–50. There is no sampling, random seed or padding to
50 tasks. No real task collection is included with this implementation.

### Supported legacy input schema

Use UTF-8 `.json` containing a nonempty array of task objects, or `.jsonl`
containing one task object per line. JSONL accepts LF/CRLF and an optional final
newline; blank lines are rejected. JSON envelopes, Parquet, Hugging Face dataset
directories, Python literals and native SWE-bench **5.x structures are not
supported**. This importer implements only the older flat JSON/JSONL record
layout described here; it does not claim general SWE-bench 5.x compatibility.

Required fields:

| Field | Accepted value |
| --- | --- |
| `instance_id` | Unique ASCII identifier, 1–200 characters, starting with a letter/digit and otherwise using letters, digits, `_`, `.` or `-` |
| `repo` | `owner/name`, with bounded ASCII letter/digit/underscore/dot/hyphen segments starting with a letter/digit |
| `base_commit` | Full 40-character hexadecimal commit ID; preserved without normalization |
| `problem_statement` | Nonblank UTF-8 text, at most 100,000 characters |
| `FAIL_TO_PASS` | Array of test identifiers, or a JSON string encoding that array |
| `PASS_TO_PASS` | Array of test identifiers, or a JSON string encoding that array |

Test identifiers must be nonblank strings of at most 2,048 characters, with no
control characters or surrounding whitespace. Unicode, internal spaces and
parameterized test names are preserved. Arrays may contain at most 10,000 entries;
duplicate entries and overlapping FAIL_TO_PASS/PASS_TO_PASS sets are rejected.
Empty arrays are preserved and do not establish successful evaluation. The
importer does not execute these strings as tests or shell commands.

Optional fields are limited to `patch`, `test_patch`, `hints_text`, `created_at`,
`version`, `environment_setup_commit`, `difficulty` and `metadata`. Unknown fields
are rejected rather than silently discarded. Patches must be strings (empty is
allowed), at most 250,000 characters each. Other optional text may be a string
or JSON null; hints allow 100,000 characters, other values 2,048.
`environment_setup_commit`, when non-null, must be a full 40-character hex ID.
Missing patches are permitted for ingestion but are not a claim that a task is
ready for actual patch evaluation. There is no date/version/difficulty inference.

`metadata` must be an object of JSON values, with at most 4,096 value/container
nodes and nesting depth 8. Keys allow at most 128 characters and string values
16,384. All text must encode as UTF-8 and contain no NUL. Duplicate JSON members,
non-finite values, malformed JSON, wrong types and repeated instance IDs are
rejected. Inputs must be regular files, at most 64 MiB and 10,000 records; each
record's UTF-8 JSON representation is bounded to 1 MiB (also the raw JSONL line
limit). Symlinks to regular input files are accepted. Bounds apply before subset
selection, so a small `--limit` cannot hide malformed or duplicate later tasks.

### Agent data and private evaluation data

`SWEbenchTask.agent_input()` explicitly allows **only** `instance_id`, `repo`,
`base_commit` and `problem_statement`. It never merges optional metadata into
the agent payload. `evaluation_input()` separately retains FAIL_TO_PASS,
PASS_TO_PASS, supplied gold `patch`, `test_patch` and optional metadata, keyed by
instance ID. Hints and metadata are private even if another SWE-bench integration
might normally expose them. No prompt builder or M4 execution integration is
introduced in this stage.

The JSON report **is a private preparation manifest**, with separate `agent_tasks`
and `evaluation_tasks` sections. Only the four-field `agent_tasks` projection is
suitable for a future agent input. Never send the complete manifest, source
export or `evaluation_tasks` to an agent. The importer enforces field separation;
it cannot authenticate or sanitize evaluation information that a source author
has already embedded in `problem_statement` itself.

The manifest records the resolved source path, SHA-256 of the exact source bytes,
byte count, legacy JSON/JSONL format, selection strategy/limit and actual input,
selected and omitted counts. It includes no timestamps or random state. The same
file/path and limit produce the same manifest data; reordered or reformatted input
may change provenance hashes while selecting the same normalized tasks. File
names/metadata do not authenticate membership in Lite/Verified or a dataset
revision. Keep the original export and provenance records separately.

Markdown/stdout summaries show IDs, repositories, commits and source fingerprint,
without patches, test identifiers, problem text or optional metadata. The JSON
manifest contains the supplied private evaluation data and a local source path;
handle it accordingly. Output paths must differ and cannot alias the input file,
including symlink/hardlink aliases. Validation errors are reported before report
files are written. Without output flags, preparation writes no files.

Preparation exit **0** means valid data and a prepared selection, not an evaluated
or resolved task. CLI/input/report errors exit nonzero. Reports use
`evidence_kind: "offline-swebench-preparation"`, `status: "PREPARED"`,
`evaluation_status: "NOT_EVALUATED"`, `evaluation_performed: false` and
`evaluated_tasks: 0`. No Pass@1 metric is produced. Existing M1–M4 CLI commands,
rootless isolation, response protocol and scoring are unchanged.

`tests/test_arena_swebench.py` uses synthetic schema fixtures labelled as such,
with guards against subprocesses, agents, containers, network access and response
scoring. It covers legacy encodings, schema/size limits, deterministic selection,
provenance, malformed data, input protection and private-data separation. Those
unit fixtures are not a collection of real SWE-bench tasks or evaluation evidence.

## Classic SWE-bench predictions and artifact import (M5b)

M5b handles local prediction files and imports existing official harness artifacts.
It never starts a harness, model, container, repository test command or installation.
It does not implement its own pytest runner. M1–M5a behavior is unchanged.

### Prepare predictions and a bound run manifest

Start with the private M5a manifest and a UTF-8 JSONL file of actual predictions.
Each prediction row has exactly these three classic SWE-bench fields:

```json
{"instance_id":"<selected task ID>","model_name_or_path":"local/my-agent","model_patch":"<actual predicted patch>"}
```

The example is a format placeholder, not an actual prediction. IDs must belong
to the manifest's selected tasks. Duplicate IDs, unknown fields, unsafe identifiers,
mixed model names, malformed Unicode/JSON, duplicate JSON members and oversized
patches are rejected. Only one prediction per task and one model per file are
supported; there is no best-of-N selection. Model names use bounded ASCII
letter/digit/underscore/dot/hyphen/slash components, excluding empty, `.` and `..`
components. Run IDs use the same bounded identifier syntax as M5a task IDs.

```sh
python3 evals/arena/cli.py --benchmark swebench-predictions \
  --manifest /tmp/swebench-manifest.json --predictions /path/to/predictions.jsonl \
  --run-id unique-run-id \
  --output-predictions /tmp/harness-predictions.jsonl --output-json /tmp/run-manifest.json \
  --report /tmp/prediction-preparation.md
```

This command validates the M5a v1 manifest using the existing task validator and
exports ready predictions in selected instance-ID order, as deterministic compact
UTF-8 JSONL with LF endings. Both output flags above are required: the JSON report
is the run manifest needed for later import. The export must be a fresh path;
atomic no-clobber publication refuses existing files and aliases.

An absent row is **MISSING**. A supplied null, empty or whitespace-only patch is
**INVALID_PATCH**. Neither is exported, and neither is replaced with a gold patch.
Other patch values must be strings of at most 250,000 characters / 1 MiB UTF-8,
without NUL. Nonblank text is **READY**, not proof of valid diff syntax or successful
application: the official harness must determine that. Arena cannot establish
whether a caller copied a supplied prediction from a gold patch; it never generates
or fills predictions from M5a evaluation data.

Prediction files and manifests are bounded to 64 MiB. Prediction JSONL accepts at
most 50 rows, each at most 1 MiB + 64 KiB of UTF-8 JSON; blank rows are rejected,
and LF/CRLF and an optional final newline are accepted. An empty file represents
all predictions missing. The run manifest records the run ID, selected IDs,
model name, exact M5a manifest hash, M5a-declared source-data hash, exact original
prediction-file hash, canonical export hash, and per-row/per-patch SHA-256.
It contains no raw gold or model patches. Keep the original predictions and
M5a manifest byte-for-byte: even whitespace/order changes invalidate the saved
run binding although a reordered file may yield the same deterministic export.
The original dataset bytes are not reopened through the path stored in M5a;
the source-data hash remains declared provenance, not dataset authentication.

### Supported official results format

Only the explicit **`swebench-v2.1-instance`** profile is supported. It follows
the classic v2.1.0 per-instance artifacts from
[the official runner](https://github.com/SWE-bench/SWE-bench/blob/v2.1.0/swebench/harness/run_evaluation.py)
and [its grader](https://github.com/SWE-bench/SWE-bench/blob/v2.1.0/swebench/harness/grading.py).
It does not accept aggregate summary reports, guessed envelopes, arbitrary report
schemas, missing test-status details or native SWE-bench 5.x structures.

Supply the existing `logs/run_evaluation` directory. The importer reads only:

```text
<harness-results>/<run_id>/<model_name_or_path with / replaced by __>/<instance_id>/patch.diff
<harness-results>/<run_id>/<model_name_or_path with / replaced by __>/<instance_id>/report.json
```

`report.json` must be a one-entry object keyed by the exact instance ID. Its value
requires boolean `patch_is_None`, `patch_exists`, `patch_successfully_applied`
and `resolved`, with optional boolean `none` and `tests_status`. Completed outcomes
require the first flag false, the next two true, `none` absent/false and complete
test statuses. The supported grader profile has four groups: `FAIL_TO_PASS`,
`PASS_TO_PASS`, `FAIL_TO_FAIL`, `PASS_TO_FAIL`, each with `success` and `failure`
arrays. The first two groups must partition exactly the M5a expectations without
duplicates/overlaps; the last two must be empty, matching the classic default
grading profile. Encoded-string lists are not accepted in harness reports.
The `resolved` flag must agree with those outcomes. An empty M5a FAIL_TO_PASS set
cannot establish resolution in M5b and is reported as an error.

The exact `patch.diff` byte hash must match the submitted prediction, including
line endings. Each report is capped at 4 MiB and each patch at 1 MiB. Resolved
artifact paths must stay inside the selected results directory; escaping symlinks
are rejected. Reports cannot overwrite inputs, run manifests or selected harness
artifacts/aliases, and report destinations must be outside the harness directory.

### Import without executing the harness

Obtain artifacts separately from a real official harness run on the exported
predictions and the exact selected dataset revision. Arena provides no command
that launches that run. Then import:

```sh
python3 evals/arena/cli.py --benchmark swebench-results \
  --manifest /tmp/swebench-manifest.json --predictions /path/to/predictions.jsonl \
  --run-id unique-run-id --run-manifest /tmp/run-manifest.json \
  --harness-results /path/to/logs/run_evaluation \
  --results-format swebench-v2.1-instance \
  --output-json /tmp/imported-results.json --report /tmp/imported-results.md
```

The run manifest must exactly match the current data, predictions and run ID.
No hashes are silently updated during import. The report binds every outcome
to its instance ID, prediction/patch hashes, artifact patch/report hashes,
run-manifest hash and source/manifest/prediction/export hashes. No raw patch,
test output, gold data or test identifiers are copied into the report.

- **RESOLVED:** a bound, internally consistent completed harness report says resolved.
- **UNRESOLVED:** a bound, completed report says unresolved and its tests agree.
- **ERROR:** an invalid supplied patch, patch mismatch, failed application,
  incomplete/malformed artifacts, unsupported per-instance schema or conflicting tests.
- **NOT_EVALUATED:** no prediction or no artifact directory for a ready prediction.
  An existing directory with missing report/patch is an ERROR, not a successful run.

Coverage counts validated completed outcomes (`RESOLVED` + `UNRESOLVED`) over
all selected tasks. Prediction coverage is reported separately; missing tasks
are never silently removed from the denominator. No subset-only resolution rate
is reported. **Resolution rate and Pass@1 remain null/N/A** unless all selected
tasks have one ready prediction and complete correct bound outcomes, and the user
adds **`--confirm-harness-run`** to attest those artifacts came from a real official
harness evaluation of these exact inputs. Under those conditions, resolution rate
is `100 × RESOLVED / selected_tasks`; `pass_at_1` is the corresponding fraction.
ERROR and NOT_EVALUATED block both metrics. Confirmation does not turn incomplete
artifacts into evaluation evidence.

Without confirmation, the report labels the artifacts `unattested-harness-artifacts`.
With it, they are `user-attested-official-harness-artifacts`, never independently
authenticated execution. Arena itself still runs no evaluation. Unit tests
simulate confirmation to check metric gating; their synthetic fixtures and
computed numbers are format checks, not benchmark evidence. Do not attest to
synthetic artifacts or publish them as real benchmark results.

**Cache/freshness limitation:** the classic runner can return an existing report
without rerunning a task. Use a fresh unique run ID, an isolated log directory,
the correct dataset/environment revision and the prepared export. Audit artifacts
before confirming. Patch/hash checks detect many stale-input mismatches, but
cannot prove freshness when old reports have matching patches/tests, prove the
environment revision, or detect fabricated/replaced reports and run manifests.
Do not use `--confirm-harness-run` for cached results whose provenance was not
verified. The saved run ID is a binding label, not proof that it has never been used.

Preparation exits **0** for valid schema/export, including explicitly recorded
missing/invalid predictions; it claims no resolution. Result import exits **1**
for input/report errors or per-task ERROR, **2** for incomplete or unconfirmed
coverage without errors, and **0** for complete user-confirmed imports (including
legitimate UNRESOLVED outcomes). Read the outcome counts and rates, not just the
exit code. Existing M1–M5a flags and defaults are preserved; M5b-specific options
are rejected by other modes.

`tests/test_arena_swebench_eval.py` uses only synthetic task/prediction/report
fixtures and mocked execution/network entry points. It covers schema/bounds,
deterministic export, missing versus invalid predictions, complete/partial/error
imports, strict formats, stale bindings, patch mismatches, path/output protection,
metric gating and CLI behavior. It does not establish real SWE-bench performance.

## Controlled official harness execution (M5 completion)

`swebench-run` adds an opt-in launcher for the **installed official SWE-bench
v2.1.0 harness**. It delegates to `swebench.harness.run_evaluation`; Arena does
not implement repository test execution or grading. Preview is the default:
it reads and validates local inputs, prints argv/configuration, and starts no
processes or engine requests. It creates no work directory or run reservation.
Optional `--report`/`--output-json` write the requested preview reports only.

Prepare M5a/M5b inputs first, using the same fresh run ID. For a first complete
single-task evaluation, use an M5a manifest prepared with `--limit 1`. Example:

```sh
python3 evals/arena/cli.py --benchmark swebench-run \
  --manifest /path/to/m5a-manifest.json \
  --predictions /path/to/original-predictions.jsonl \
  --prediction-export /path/to/m5b-export.jsonl \
  --tasks /path/to/original-local-dataset.jsonl \
  --run-manifest /path/to/m5b-run-manifest.json --run-id unique-run-id \
  --work-dir /path/to/new-harness-work-directory \
  --output-json /path/to/preview.json
```

Review the preview and prerequisites. To actually execute, repeat the command
with **`--execute`**. There is no automatic install, engine startup, elevation,
fallback to another engine or implicit opt-in. `--harness-python /path/to/python`
selects a separately prepared interpreter; the default is the current interpreter.
Its official distribution metadata and module version must both be exactly
`2.1.0`, with the expected `main()` signature and supported repo/version mappings.
The launcher checks that interpreter/dependencies can import the harness and
that its Docker SDK can ping/list images/list containers through the selected API.
These checks run only with `--execute`, before the harness is launched.

### Inputs and selected tasks

The original M5a manifest, original prediction JSONL and saved M5b run manifest
must match exactly as in M5b. The supplied prediction export must byte-match the
deterministic M5b export. The local dataset is validated through M5a, must match
the manifest's declared source-byte hash, and must reproduce its selected tasks.
No remote dataset name or `gold` prediction mode is exposed. Prediction records
labelled `gold` are refused; missing/blank predictions are never filled from gold.
As in M5b, user-supplied prediction provenance cannot be independently attested.

The launcher selects the first `min(limit, selected_tasks)` IDs in manifest order,
default **one**, with `--limit` accepting 1–50. Every execution-selected task must
have a ready prediction, a supported nonblank version, nonempty evaluator test
patch and nonempty FAIL_TO_PASS expectations. Workers default to **one**;
`--max-workers` accepts 1–4, capped by the selected count and preflight capacity.

The launcher writes a private JSON **array** containing only execution-selected
tasks and a matching prediction JSONL snapshot, then passes explicit
`--instance_ids` and `--max_workers`. The dataset snapshot excludes the gold
`patch`; evaluator test patches and expected tests remain evaluator data, not
an agent prompt. A validated, non-null `environment_setup_commit` is preserved
unchanged in this evaluator snapshot so the official harness can use the intended
dependency-installation commit. Missing or null values are omitted, retaining
the harness's default commit selection. This field remains excluded from
`agent_input()`. Missing/nullable unused hints become an empty string. JSONL
sources are normalized to that array because this pinned release's local loader
uses whole-file JSON decoding. This does not add native SWE-bench 5.x support.
The delegated argument interface and local loader are documented in the pinned
[official runner](https://github.com/SWE-bench/SWE-bench/blob/v2.1.0/swebench/harness/run_evaluation.py)
and [loader](https://github.com/SWE-bench/SWE-bench/blob/v2.1.0/swebench/harness/utils.py).

If M5a selected 50 tasks and the launcher runs its default one, M5b still reports
coverage over those original 50; the launcher never shrinks the metric denominator.
Keep the original inputs for later import, including tasks not executed in this run.

### Rootless engine and resource prerequisites

Actual execution requires native Linux and a **non-root host user**, a user-owned
local Unix socket and a running rootless engine. The default `--engine docker`
uses only `/run/user/UID/docker.sock`. Explicit `--engine podman` uses only
`/run/user/UID/podman/podman.sock` and requires the user-managed Podman API service.
Arena never uses `/var/run/docker.sock`, inherited Docker contexts, remote APIs,
Docker Desktop, `sudo` or an automatic Docker/Podman fallback.

Preflight checks rootless metadata on the selected API (Docker's `name=rootless`
or Podman's native `host.security.rootless: true`), Linux container support and
Docker-compatible API version at least 1.41. It then checks the Docker SDK read
operations above. Missing/inaccessible/rootful APIs, unsupported versions or
incompatible Podman service/SDK behavior return **UNAVAILABLE**, with diagnostics,
before harness execution. This is a compatibility screen, not a guarantee every
project build/exec operation will work; later failures remain execution failures
or incomplete artifacts for M5b. Engine-reported metadata and the local socket
are trusted; this is not independent daemon attestation.

The rootless engine needs at least **2 CPUs and 8 GiB RAM capacity per worker**.
The host interpreter needs a hard open-file limit of at least 1,024 (or unlimited).
Both the engine's local storage filesystem (reported `DockerRootDir`) and the
work-directory filesystem must have at least **120 GiB free** before execution.
An inaccessible storage path fails preflight. These are conservative entry
thresholds, not a reservation, disk quota or guarantee that a particular task fits.
Images/environments can need substantially more space; monitor and manage the
user's rootless image store separately. Avoid concurrent runs competing for space.

Install/manage the official harness, Docker SDK, its upstream Python dependencies,
Linux engine and required native tools separately. Arena itself adds no dependency.
No installer runs during preflight. Hugging Face dataset loading/telemetry is
disabled because the dataset is local. **The official harness can still build
images, clone repositories and download environment dependencies after `--execute`.**
It uses its upstream execution policy, potentially root inside rootless container
namespaces, writable filesystems and network access. This is a different profile
from M4's network-disabled read-only adapter sandbox; M4 is unchanged. Use trusted
harness/dependencies/dataset definitions on an isolated development machine.

### Freshness, process bounds and cleanup

`--work-dir` must not exist, must have an existing parent, and must be outside
this repository. It is created private to the caller. Harness logs, build contexts,
input snapshots and bounded console logs are confined to this working directory;
engine-managed images/container storage are separate. The installed harness is
trusted code, not a host filesystem sandbox. Existing result directories and
already-existing selected harness containers are refused.

Before launch, Arena atomically reserves `run_id` under
`~/.local/state/msl-arena/swebench-runs/`. IDs are hashed as filenames, so reuse
is refused even with another working directory or after a failed/interrupted run.
The reservation is intentionally retained; use a new ID and matching M5b receipt
for retries. The registry only knows IDs reserved by Arena, not every external
harness run elsewhere. Caller-selected IDs must also be fresh relative to such
external runs. A fresh working directory prevents reuse of old per-task reports;
upstream environment/image caches may still be reused (`cache_level=env`,
`clean=False`, `force_rebuild=False`). Audit cache provenance when dataset or
environment revisions change; new report paths alone cannot authenticate images.

The process receives argument lists with `shell=False`, an isolated Python import
path (`-I`), no bytecode writes (`-B`), a new process session and a minimal environment.
The selected local rootless `DOCKER_HOST`/API version are explicit; host credentials,
SSH-agent sockets, cloud keys, user Docker config, proxies and `PYTHONPATH` are not
inherited. HOME/temporary/config paths point into the private run directory.
A small fixed bootstrap disables implicit dotenv loading, fixes Docker SDK clients
to API 1.41, sets a host file-size limit and delegates to the official module
through `runpy`; it changes no grading.

Bounds are specific to M5 and do not change M4:

- `--timeout`: total harness wall time, default 3,600 seconds, range 1–86,400.
- `--test-timeout`: upstream per-task test timeout, default `min(1800, total)`,
  range 1–3,600 and no greater than the total. Environment builds are covered by
  the overall deadline, not the test timeout alone.
- Stdout and stderr are drained concurrently into at most 1 MiB each.
- A host `RLIMIT_FSIZE` caps each regular output file at 16 MiB. A watcher checks
  aggregate regular harness log/build files, default 128 MiB; `--log-limit-mib`
  accepts 16–1,024. Image-build symlinks are not followed. Checks are periodic,
  so aggregate size can overshoot briefly; this is not a filesystem quota.
- Direct engine API operations have five-second socket timeouts and request
  deadlines; the dependency/SDK subprocess probe has a 20-second deadline.
  Engine builds, daemon logging, image
  storage and in-container memory are not covered by the host log/file limits.

Timeout, console/log overflow, Ctrl+C or process I/O failure stop the whole host
process group with TERM then KILL. Cleanup additionally removes only the known
official container names for the execution-selected IDs on the verified rootless
API, with bounded per-container requests. It never prunes unrelated containers
or images. Failed cleanup is reported as **CLEANUP_FAILED**, retaining the prior
execution status; inspect the private work directory and rootless engine manually.
An unreachable engine, unkillable host process, abrupt launcher termination or
in-flight daemon build can prevent complete cleanup. No successful cleanup or
isolation guarantee is inferred in those cases.

### Execution reports and M5b import

Execution statuses are **PREVIEW**, **UNAVAILABLE**, **COMPLETED**, **FAILED**,
**TIMEOUT**, **LOG_LIMIT**, **INTERRUPTED** and **CLEANUP_FAILED**. COMPLETED means
only that the harness host process exited zero and cleanup was confirmed. Upstream
may still have task errors or missing reports. `evaluation_status` remains
**NOT_IMPORTED**; this runner produces no RESOLVED, resolution rate or Pass@1.

Reports bind selected IDs and input/snapshot hashes to the run ID and record argv,
cwd, engine, limits, preflight, cleanup and console byte counts/hashes. Raw console
content stays in private `arena-stdout.log`/`arena-stderr.log`, not in the report.
To evaluate, use the existing `swebench-results` command with the original M5a/M5b
inputs and `--harness-results <work-dir>/logs/run_evaluation`. Inspect the execution
and artifacts before supplying M5b's `--confirm-harness-run`. Only that importer
may validate and count the actual per-instance reports; all its completeness,
hash binding and metric gates remain in force.

CLI exit **0** means preview or completed host execution, **2** means UNAVAILABLE,
**130** means interrupted execution, and other execution/report errors exit **1**.
These are not benchmark pass/fail scores. Mocked tests in
`tests/test_arena_swebench_runner.py` cover input binding, default preview, task
and worker selection, rootless/API/dependency/resource preflight, stale-run
protection, argv/environment, process/log bounds, interruptions and cleanup.
They start no real harness, engine, model or repository tests and establish no
actual benchmark performance or live-platform compatibility.
