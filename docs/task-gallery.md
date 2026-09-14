# Pick a task. Copy the prompt.

Start with something you already need to do. Each recipe names the skill, the
input it needs, and what to look for in the result.

[Install a skill](install.md) once, then paste a prompt into your client.
Replace bracketed placeholders with your own material. These are authored
starting points, not recorded model results or guarantees of output quality.
For Grok Bot, follow the [manual recipes](../grok-bot/README.md) and supply the
linked skill instructions with your task.

| Task | Bring | Look for |
| --- | --- | --- |
| [Make a draft natural](#make-a-draft-natural) | A paragraph | Clear prose with the same facts |
| [Keep your writing voice](#keep-your-writing-voice) | A draft and style samples | Your style without borrowed claims |
| [Translate technical copy](#translate-technical-copy) | Polish or English text | Natural translation, exact technical tokens |
| [Improve a README](#improve-a-readme) | An accessible repository | A quickstart grounded in available commands |
| [Reproduce a bug](#reproduce-a-bug) | A report and code | A rerunnable failure or a named blocker |
| [Review a pull request](#review-a-pull-request) | Base and head revisions | Findings with triggers and evidence |
| [Review an ML refactor](#review-an-ml-refactor) | Base/head revisions and the project checkout | Reproducibility evidence scoped to the changed experiment |
| [Debug a training loss](#debug-a-training-loss) | One batch and the loss expression | A shape diagnosis before a proposed fix |
| [Review changed documentation](#review-changed-documentation) | A source diff and dependent instructions | Supported corrections and unresolved claims |

## Make a draft natural

Skill: [mkl-humanize](../skills/mkl-humanize/SKILL.md).
Try this supplied paragraph first, or replace it with your draft.

```text
Use mkl-humanize to edit this project update for developers. Keep its language,
facts, command flags, and limitations. Return the edited paragraph.

Draft:
We are thrilled to announce that our innovative installer now empowers users
to preview changes with --dry-run. In our Linux fixture, it inspected 20 files
and wrote none. Windows has not been tested yet.
```

**Check the result:** `--dry-run`, 20 files, zero writes, the Linux fixture scope,
and untested Windows status survive. No claim about speed or universal safety
is added. [More writing examples](../examples/writing/README.md).

## Keep your writing voice

Skill: [mkl-match-voice](../skills/mkl-match-voice/SKILL.md).
Supply samples you want the edit to sound like, separately from the new draft.

```text
Use mkl-match-voice to edit my draft for the same audience as my samples.
Use the samples as style evidence only. Do not transfer their facts,
achievements, or anecdotes into the draft. Return one version and briefly
explain the style choices you used.

Style samples:
[Paste two or three short examples of your writing.]

Draft:
[Paste the text to edit.]
```

**Check the result:** the draft's meaning remains; style is tied to observable
choices in the samples. A thin sample should lead to a qualified explanation,
not a claim that the agent has learned your complete voice.

## Translate technical copy

Skill: [mkl-localize-pl-en](../skills/mkl-localize-pl-en/SKILL.md).
This example can be pasted as written.

```text
Use mkl-localize-pl-en to translate this UI message into English for developers.
Keep the command, placeholder, and unit exactly as written. Preserve uncertainty.

Uruchom `kit --dry-run`, aby podejrzeć zmiany. Ta wersja może nie działać
w Windows. Limit wynosi {max_mb} MB.
```

**Check the result:** `kit --dry-run`, `{max_mb}`, and `MB` are unchanged. The
translation retains “may not work” rather than asserting Windows support or
a definite failure. The command is example text, not an instruction to run it.

## Improve a README

Skill: [mkl-write-readme](../skills/mkl-write-readme/SKILL.md).
Open the repository in your coding client before using this prompt.

```text
Use mkl-write-readme to improve this repository's README. Read repository
guidance, package metadata, entry points, and examples first. Lead with one
concrete user task, then prerequisites, a short quickstart, and expected output.
Preserve the license and useful existing links. Edit README.md only.
Report which commands you actually verified and any remaining setup gaps.
```

**Check the result:** installation names and commands exist in the project;
expected output is distinguished from executed checks. No invented benchmark,
endorsement, or adoption figure appears.

## Reproduce a bug

Skill: [mkl-reproduce-bug](../skills/mkl-reproduce-bug/SKILL.md).
Supply an accessible checkout and the smallest report you have.

```text
Use mkl-reproduce-bug to investigate the report below. Inspect the code and
dependencies before running commands. Keep experiments separate from my work
and leave production code unchanged. Return the smallest reproduction, exact
command, environment, expected and observed behavior, and exit status.
If setup prevents reproduction, name that blocker separately.

Report:
[Paste the symptom, input, expected behavior, and relevant error output.]
```

**Check the result:** another maintainer can rerun the same failure. A missing
dependency is not counted as reproducing the reported bug. For a local fixture
that needs no model, see the [runnable bugfix example](../examples/bugfix/README.md).

## Review a pull request

Skill: [mkl-review-pr](../skills/mkl-review-pr/SKILL.md).
Supply revisions that exist in the accessible repository.

```text
Use mkl-review-pr to review the change between these revisions:
Base: [base commit]
Head: [head commit]

Read the diff, surrounding code, and relevant tests. Prioritize correctness
regressions. For each finding give its location, concrete trigger, consequence,
and evidence. State the review scope and checks actually performed. If there
are no actionable findings, say so. Return the review here without posting,
approving, merging, or editing the patch.
```

**Check the result:** findings explain a reachable failure rather than stylistic
preferences; untested assumptions remain explicit. An empty finding list is
acceptable and does not establish that every behavior was tested.

## Review an ML refactor

Skill: [mkl-review-pr](../skills/mkl-review-pr/SKILL.md).
Use this when a pull request changes data preparation, randomness, training, or
evaluation code and the repository checkout is available to the client.

```text
Use mkl-review-pr to review this ML change for correctness and reproducibility.
Read the complete diff and the repository guidance first.

Base: [base commit]
Head: [head commit]
Project checkout: [path]

If the project provides a reproducibility checker such as Repro Lens, run its
static check on the checkout and inspect any RNG, device, data-order, or
configuration findings. If before/after reports exist, compare them. Run a
bounded replay only when the repository documents the command and inputs.
Return findings with locations, triggers, consequences, exact commands and
environment, and keep a clean static scan or matching run scoped to its evidence.
Do not edit, approve, merge, or post comments.
```

**Check the result:** a finding is tied to changed behavior and a reachable
consequence. Static review findings are separated from replay results, and a
matching fixture run is not presented as proof of scientific validity or
cross-platform equivalence. [Repro Lens framework checks](https://github.com/00200200/repro-lens#framework-checks)
show the kind of evidence this recipe can consume.

## Debug a training loss

Skill: [mkl-debug-ml-training](../skills/mkl-debug-ml-training/SKILL.md).
Try this bounded numerical example before supplying your own training code.

```text
Use mkl-debug-ml-training to diagnose this scalar regression loss expression:
predictions = [[1], [3]] with shape [2, 1]
labels = [1, 3] with shape [2]
loss = mean((predictions - labels) ** 2)

Under NumPy-style broadcasting, the loss is 2, but I expected 0 for these
per-example predictions. Explain the residual shape and the intended target
contract before suggesting a change. Distinguish this expression from any
framework's built-in loss behavior. Do not start a full training run.
```

**Check the result:** the broadcast residual has shape `[2, 2]`; aligning these
scalar labels to `[2, 1]` gives zero loss. This does not justify reshaping every
classification target. [CPU examples for PyTorch, Lightning, and TensorFlow/Keras](../examples/ml-training/README.md)
also check gradients and an optimizer update.

## Review changed documentation

Skill: [mkl-review-source-change](../skills/mkl-review-source-change/SKILL.md).
Use a supplied diff or a [Skill Watch](skill-watch.md) result.

```text
Use mkl-review-source-change to review this source change against the dependent
instructions below. Confirm the version and scope match. For each affected
claim, explain whether it needs a correction, remains valid, or lacks evidence.
Return proposed edits and remaining checks. Do not change files or accept a
new baseline during this review.

Source identity and version:
[URL or file, version, and baseline/current hashes if available]

Before/after diff:
[Paste the relevant complete diff.]

Dependent instructions:
[Provide accessible canonical file paths or paste their relevant contents.]
```

**Check the result:** an upstream edit is tied to a specific dependent claim.
Version mismatches remain unresolved; an editorial change need not result in
a patch. [Worked review cases](../examples/skill-watch/review.md).

## Share a recipe that helped

Found a task you want to use again?
**[☆ Star on GitHub](https://github.com/00200200/maintainer-skills-lab)** to keep
the library in your saved repositories.

You can contribute an example without creating a new skill. Add a focused recipe
to this page in a PR, or [open an issue](https://github.com/00200200/maintainer-skills-lab/issues/new)
with the task, a small input, and what a useful result should preserve or prove.
See [the contribution guide](../CONTRIBUTING.md#contribute-a-task-recipe).

If you ran it in a client, include the client/version, observed result, and
limitations. Otherwise label it as an authored example. Remove private material
and use original or appropriately licensed samples. Contribution history keeps
authorship with the change; publication follows review.
