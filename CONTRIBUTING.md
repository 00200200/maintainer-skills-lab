# Contributing

Useful contributions include a reproducible client incompatibility, a focused
workflow improvement, or a fixture that demonstrates a real failure.

## Local checks

Python 3.11+ is sufficient; no model API keys are needed.

```sh
python3 tools/kit.py check
python3 -m unittest discover -s tests -v
python3 examples/bugfix/run.py --json
python3 tools/kit.py build
```

Edit shared instructions in `skills/` and agent definitions in `agents/`.
Do not hand-edit built archives. Keep skill frontmatter in the supported source
subset: single-line, double-quoted `name` and `description` values. Use the
`mkl-` namespace to avoid overriding a client's built-in workflows.

For a new skill, describe one distinct job, its expected inputs and outputs,
an inspectable example, and meaningful acceptance criteria. Don't add generic
personas or duplicate an existing workflow merely under another client name.

When modifying the installer, test the filesystem behavior affected by the
change. When modifying a workflow, validate its observable outcome; exact prose
or heading matches are not behavioral evidence. See [evals](evals/README.md).

PR descriptions should explain the problem, resulting behavior, actual checks,
and limitations. Cite sources for format changes and include relevant client
versions. Don't submit secrets, private transcripts, or copied content without
appropriate attribution and permission.
