# MSL-Arena — Mini, recorded-response redteam and offline variants

Arena provides `mini` for container infrastructure smoke checks and `redteam`
for heuristic verification of user-supplied recordings. `generate` creates
deterministic variant fixtures offline. No mode starts an agent or model;
Redteam and Generate do not require or invoke Docker/Podman.

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
