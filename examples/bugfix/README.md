# Bug report → unchanged regression test → verified fix

Run from the source repository with Python 3.11+:

```sh
python3 examples/bugfix/run.py
python3 examples/bugfix/run.py --json
```

Expected summary:

```text
Baseline:  assertion-failure
Candidate: pass
Verified for this fixture: True
This checks the bundled example, not agent performance.
```

Read [the report](issue.md), [the independent test](test_slug.py), and the
[before](before/slug.py) / [after](after/slug.py) implementations.

The runner copies each implementation and the **same test** into separate
temporary directories and launches a fresh interpreter. It checks the imported
source path, records test and implementation hashes, and distinguishes assertion
failures from import errors, missing tests, skips, timeouts, and process failures.

This is a small, trusted example with a deliberately narrow ASCII slug contract.
It is not a general Unicode slug library, a security sandbox, a runner for
untrusted repositories, or evidence of a model's performance. The probe is not
designed to resist malicious Python code tampering with the test process.

## Try the workflow in an agent

Install the library into a disposable project, copy only `before/slug.py` and
`issue.md` there, and ask:

> Use mkl-reproduce-bug and mkl-write-regression to investigate issue.md.
> Establish the failure before changing the implementation. Then propose the
> smallest fix and use mkl-verify-fix to check it. Do not publish anything.

Keep `after/` and the reference test outside the agent's working directory when
evaluating it. The evaluation guide in `evals/README.md` explains how to record
a live run without confusing it with the deterministic fixture check.
