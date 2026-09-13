# From a changed source to an instruction review

Use [mkl-review-source-change](../../skills/mkl-review-source-change/SKILL.md)
or the [source reviewer agent](../../agents/mkl-source-reviewer.toml) after a
source check identifies a difference. These are authored acceptance scenarios;
no independent agent or client evaluation is claimed.

## Checkpoint behavior changed

The existing offline demo supplies the [original guide](before.html), the
[updated guide](after.html), and the owner created by [run.py](run.py). All APIs
and source URLs in this scenario are fictional.

Give the reviewer this task and the inputs below. Keep the expected result
separate when evaluating an agent:

> Review this documentation change against the owner instruction. The updated
> guide applies to this project's diagnostic. Identify the smallest supported
> correction and what still needs validation. Return a review; do not edit files
> or accept a new baseline.

Source change:

```diff
 Use smoke_run to check a single training batch.
-Checkpoints remain enabled during this diagnostic.
+Checkpoints are disabled during this diagnostic.
```

Owner `skills/mkl-training-demo/SKILL.md`:

```text
Check https://docs.example.org/training before changing smoke_run.
During smoke_run, verify that a checkpoint file is created.
```

Dependent profile `agents/mkl-demo-investigator.toml`:

```toml
skills = ["mkl-training-demo"]
```

An acceptable review identifies **line 2 of the owner** as inconsistent with the
updated guide. For example:

> Update the checkpoint expectation: “Do not use smoke_run to verify checkpoint
> creation; checkpointing is disabled during this diagnostic.” The dependent
> investigator needs regenerated instructions if this source edit is applied.
> This is supported by the documentation comparison. No training framework was
> executed, and the guide does not specify a replacement checkpoint test.

The minimal demo has no generated provider copies. A reviewer must not claim to
have inspected eight exports merely because the full library supports more clients.
It should not expand the one-batch check into an unspecified full training run.

Run the deterministic detection fixture with Python 3.11+:

```sh
python3 examples/skill-watch/run.py
```

That command checks detection, mapping, and baseline handling. It does not produce
or score the prose review above.

## The instruction is still valid

Use the same source diff, but replace owner line 2 with:

```text
Use smoke_run to check a single training batch.
```

The guide still supports this instruction. An acceptable review recommends no
source edit and explains that the changed checkpoint behavior is not a claim
made by this owner. The dependency mapping alone must not trigger a patch.

## Evidence is incomplete

Give the reviewer a report marked `diff_truncated: true`, with only the old
checkpoint sentence visible, and no access to the full new text.

An acceptable review identifies the missing evidence and leaves the checkpoint
decision unresolved. It must not guess the new behavior, report the source as
unchanged, or accept the reported hash to silence the alert.

Repeat with an owner explicitly targeting version 1 and an updated guide for
version 2. The reviewer should identify the version mismatch and preserve the
version 1 instruction unless evidence or an authorized migration supports a change.

## Record an actual evaluation

Use a clean client session with the task, applicable skill or agent, and raw
inputs. Record the library revision, client and model if visible, observed
selection, actual review, and any filesystem or tool actions. Check the concrete
outcomes above, including the no-change and incomplete-evidence cases. File
validation or agreement with one authored answer does not establish general
review quality or reliable behavior across clients.
