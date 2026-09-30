# Bring a workflow you use

A useful contribution starts with a real task. You can suggest a workflow,
improve an example, report a client mismatch, or send a focused pull request.
No need to support every client by hand: the generator does that part.

**[Suggest a skill, agent, or hook](https://github.com/00200200/maintainer-skills-lab/issues/new?template=workflow.yml)** ·
**[Report a bug](https://github.com/00200200/maintainer-skills-lab/issues/new?template=bug_report.yml)** ·
**[Propose an optimization](https://github.com/00200200/maintainer-skills-lab/issues/new?template=optimization.yml)**

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

## Write token-efficient workflows

Keep frequently loaded skill descriptions focused; use 60 approximate tokens as
a working target, not a universal limit. Put required actions before background,
remove repeated instructions and conversational filler, and keep examples only
when they clarify a decision or show an important edge case. Preserve facts,
technical terms, safety constraints, and useful failure cases when shortening.

Compare the canonical source and affected generated files before and after a
change. Use the target model's tokenizer when you need an exact token count. For
a quick, rough comparison, count about one token per four characters:

```sh
python3 -c "from pathlib import Path; p = Path('skills/mkl-example/SKILL.md'); print((len(p.read_text(encoding='utf-8')) + 3) // 4)"
```

Replace the path with the file you want to measure. This estimate is roughly one
token per four characters; report it as an estimate, not a measured model-token
count. `kit.py tokens` is not currently a command. When proposing an
optimization, include the before/after counts, the files measured, and the
client/tokenizer or estimation method.

Browse [open help-wanted issues](https://github.com/00200200/maintainer-skills-lab/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22)
or [good first issues](https://github.com/00200200/maintainer-skills-lab/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
before starting a task.

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
