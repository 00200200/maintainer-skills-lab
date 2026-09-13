# Bring a workflow you use

A useful contribution starts with a real task. You can suggest a workflow,
improve an example, report a client mismatch, or send a focused pull request.
No need to support every client by hand: the generator does that part.

**[Suggest a skill, agent, or hook](https://github.com/00200200/maintainer-skills-lab/issues/new?template=workflow.yml)** ·
**[Report a bug](https://github.com/00200200/maintainer-skills-lab/issues/new?template=bug_report.yml)**

Search existing issues and the [catalogue](providers/README.md) before starting.
For a small fix, a PR is welcome directly. For a larger workflow, an issue with
sample input and the desired result helps establish the scope.

## Contribute a task recipe

Start with an existing skill and a task you can explain with a small example.
You do not need a new agent or integration to contribute to the
[task gallery](docs/task-gallery.md).

Include a descriptive task title, a link to its canonical skill, the required
input, a prompt people can copy, and observable acceptance criteria. Explain
one meaningful failure case, such as a changed technical token or an unsupported
claim. Prefer a self-contained example; clearly mark any placeholders.

Label authored examples separately from recorded client runs. For a client run,
include the client/version, supplied input, observed output, and limitations.
Do not submit private material or present an expected result as a measured one.
Keep attribution for any reused material and check that its license permits reuse.

Submit one focused PR, with your authorship preserved in Git history. A gallery
edit does not need regenerated provider files unless the canonical skill also
changes. Check relative links and confirm the prompt fits the linked skill.

## Add a skill once

1. Fork the repository and create a branch for one coherent change.
2. Add `skills/mkl-your-workflow/SKILL.md`, using this source format:

   ```markdown
   ---
   name: "mkl-your-workflow"
   description: "Use when the user needs a specific, observable result."
   ---

   # Your workflow

   Describe the required inputs, steps, output, and checks.
   Include a small worked example and a case the workflow should decline or flag.
   ```

3. Make its scope distinct from existing workflows. Preserve facts, code, and
   user intent. State missing inputs instead of filling them with invented evidence.
4. Run `python3 tools/kit.py sync`. This generates the Codex, Claude Code, Cursor, OpenCode,
   and Grok Bot files and adds links to the provider catalogue.
5. Run the checks below, then include the source and generated files in one PR.

Keep `name` and `description` as single-line, double-quoted strings. Use the
`mkl-` namespace. Add supporting files beside `SKILL.md` when needed; Grok Bot
users must supply referenced resources manually with their task.

Worked examples should be inspectable and have meaningful acceptance criteria.
Label authored illustrations as such. A model run is separate evidence: record
the client/version, input, observed output, and limitations. [Evaluation guide](evals/README.md).

## Compose an agent

Add a TOML file under `agents/` following an existing profile. Use the four fields
`name`, `description`, `instructions`, and `skills`. List dependencies by their
existing `mkl-*` names. The exporter embeds the shared workflows into each agent
version; you do not need to copy their text into your source profile.

Models and execution permissions inherit from the host. An exported agent or
Grok Bot recipe does not grant access to accounts or publish content on its own.

## Add or improve a hook

The [hook catalogue](hooks/README.md) contains a Git pre-commit check for staged
exports. Reproduce a concrete failure before expanding a hook. Document its
trigger, inputs, output, execution cost, configuration, and removal. Keep checks
local and read-only when possible, and preserve existing user hooks. Test actual
Git behavior or the client protocol that changed; source parsing alone does not
establish a working client integration.

## Local checks

Use Python 3.11+. Library checks need no model API keys or third-party packages.

```sh
python3 tools/kit.py check
python3 tools/kit.py sync --check
python3 -m unittest discover -s tests -v
python3 examples/bugfix/run.py --json
python3 tools/kit.py build
```

For Python changes, also run the CI formatter and linter:

```sh
python3 -m pip install ruff==0.16.7
ruff check tools tests examples
ruff format --check tools tests examples
```

The optional [pre-commit hook](hooks/README.md) checks the staged library before
committing. It supplements the full checks above.

Edit canonical source files; do not hand-edit provider copies or built archives.
Test affected filesystem behavior when changing the installer. Workflow checks
should assess observable outcomes rather than exact prose or heading matches.

## Send the pull request

Describe the user's problem, the resulting behavior, and checks you actually ran.
Link the issue if there is one. Include relevant client versions and primary
format references for compatibility changes. Keep unrelated edits in another PR.

Don't submit secrets, private transcripts, or copied material without appropriate
permission and attribution. Routine checks do not require paid model APIs.

For presentation assets and aggregate GitHub statistics, see [assets/README.md](assets/README.md).
