# A loss that is wrong despite perfect predictions

This example accompanies [Debug ML training](../../skills/mkl-debug-ml-training/SKILL.md)
and the [ML investigator](../../agents/mkl-ml-investigator.toml). It runs an actual
forward pass, gradient calculation, and SGD update on CPU in your chosen framework.

It demonstrates an authored bug in a **custom loss expression**, not a defect in
PyTorch, Lightning, or TensorFlow/Keras. No AI agent, pretrained model, downloaded
dataset, API key, or external experiment logger is involved.

## The failure

Two inputs `[[1], [3]]` pass through a scalar weight initialized to `1`, with no
bias. Their predictions are already correct. The labels are `[1, 3]`.

Subtracting labels of shape `[2]` from predictions of shape `[2, 1]` broadcasts
the residual to `[2, 2]`:

```text
[[ 0, -2],
 [ 2,  0]]
```

Its mean square is `2`. The gradient with respect to the weight is also `2`, so
SGD with learning rate `0.1` moves a correct weight from `1` to approximately
`0.8`. The baseline finishes training successfully, but fails the behavioral
assertion.

The candidate aligns these **scalar regression labels** to `[2, 1]` before
subtraction. The residual, loss, and gradient become zero, and the weight stays
at `1`. This reshape is specific to this target contract; it is not a general
fix for classification targets or every loss implementation.

## Run it

Use a disposable environment with **Python 3.11** from the repository root:

```sh
python3.11 -m venv .venv
```

Install the dependencies for the framework you want to exercise. These are
versions used in the recorded check below, not a claim about the latest release.

| Framework | Install in the environment |
| --- | --- |
| PyTorch | `.venv/bin/python -m pip install torch==2.8.0 numpy==2.0.2` |
| Lightning | `.venv/bin/python -m pip install torch==2.8.0 lightning==2.6.0 numpy==2.0.2` |
| TensorFlow / Keras | `.venv/bin/python -m pip install tensorflow==2.20.0 keras==3.15.1 numpy==2.0.2` |

Then run the corresponding command:

```sh
.venv/bin/python examples/ml-training/run.py --framework pytorch
.venv/bin/python examples/ml-training/run.py --framework lightning
.venv/bin/python examples/ml-training/run.py --framework tensorflow
```

Each command imports only its selected framework and writes a JSON report.
Framework diagnostics may also appear on stderr. Installing dependencies needs
network access; running the fixture uses local synthetic inputs.

The implementations use PyTorch autograd with SGD, a Lightning `Trainer` with
automatic optimization, and a Keras dense layer with TensorFlow `GradientTape`
and Keras SGD, respectively. The TensorFlow command explicitly selects the
TensorFlow backend for Keras. Lightning runs exactly one batch per variant,
with logging and checkpoints disabled and a temporary output directory.

Every variant starts with a new model and optimizer. Baseline and candidate run
in the same process for a given framework. The same analytical oracle checks
both outcomes, including residual shape, loss, gradient, and the weight after
the step, with absolute and relative tolerances of `1e-6`.

Exit codes:

- `0`: the known broadcasting failure was reproduced and the candidate passed.
- `1`: the observations did not establish both parts of that comparison.
- `2`: execution failed, including an unavailable or incompatible dependency.

A missing dependency does not count as reproducing the training bug.

## Recorded CPU check

Checked **2026-09-13**, in an isolated environment on **macOS 26.6.2 arm64**,
**Python 3.11.5**, with **NumPy 2.0.2**. Each framework command ran as a separate
process. All calculations used float32.

| Runtime | Baseline: loss / gradient / updated weight | Candidate: loss / gradient / updated weight | Result |
| --- | --- | --- | --- |
| PyTorch 2.8.0 | `2 / 2 / 0.800000011920929` | `0 / 0 / 1` | Verified for this fixture |
| Lightning 2.6.0 on PyTorch 2.8.0 | `2 / 2 / 0.800000011920929` | `0 / 0 / 1` | Verified for this fixture |
| TensorFlow 2.20.0 / Keras 3.15.1 | `2 / 2 / 0.800000011920929` | `0 / 0 / 1` | Verified for this fixture |

All three reported baseline residual shape `[2, 2]`, candidate shape `[2, 1]`,
baseline `assertion-failure`, candidate `pass`, and `verified: true`.

The regular repository suite tests the oracle's rejection of misleading success
claims, nonfinite values, and setup failures without installing ML libraries.
The three framework runs above are recorded local integration checks; they are
not part of the default CI matrix.

This checks one authored CPU fixture, not live-agent diagnosis, full training,
model quality, graph compilation, mixed precision, accelerators, distributed
training, checkpoint recovery, or cross-platform reproducibility. The skill's
broader diagnostic guidance has not been independently evaluated by an agent.
