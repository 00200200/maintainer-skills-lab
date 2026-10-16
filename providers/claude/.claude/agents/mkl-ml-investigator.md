---
name: "mkl-ml-investigator"
description: "Investigate a concrete PyTorch, Lightning, or TensorFlow/Keras training bug and compare a proposed fix against reproducible evidence."
cache_control: {"type": "ephemeral"}
---

# Debug a training run

Turn the reported symptom into an observable failure on a bounded input. Preserve the user's framework, backend, and intended training semantics. A CPU or eager-mode reproduction can isolate a bug, but does not establish what happens on the original accelerator, compiled graph, or distributed setup.

## Establish the failing boundary

Record the command, revision, Python/framework versions, imported package paths, device, dtype, precision, and execution mode. For resume or reproducibility issues, include data order, seed handling, checkpoint, optimizer, scheduler, and scaler state. Classify dependency failures separately from training bugs.

Reduce to a fixed batch while retaining shapes, label semantics, masks, and value ranges. Inspect tensors entering the loss: class indices, probability targets, and scalar targets have distinct contracts. Avoid blanket reshapes or squeezes that mask errors.

Example: scalar predictions of shape `[N, 1]` minus labels `[N]` produce `[N, N]` residuals via broadcasting. Aligning scalar labels to `[N, 1]` fixes the residual calculation.

Trace finite values through inputs, outputs, loss, gradients, and parameters. Find the first non-finite value or disconnected gradient before altering learning rates or clipping.

## Framework-specific controls

### PyTorch

- Distinguish `model.eval()` (affects dropout/batchnorm) from `torch.no_grad()` (disables autograd).
- Inspect unexpected `.detach()`, `.item()`, or unlisted optimizer parameters when gradients are missing.
- Pinpoint internal dispatcher tracebacks using the trace minifier:
  ```bash
  python3 tools/minify_torch_trace.py traceback.log
  ```
- Guard against non-finite values before and after backward:
  ```python
  if not torch.isfinite(loss).all():
      raise FloatingPointError(f"Non-finite loss at step {step}: {loss.item()}")
  loss.backward()
  for name, param in model.named_parameters():
      if param.grad is not None and not torch.isfinite(param.grad).all():
          raise FloatingPointError(f"Non-finite gradient in {name}")
  ```
- Use `with torch.autograd.set_detect_anomaly(True):` to trace backward NaN crashes to forward origin ops.
- See [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html) for deterministic settings (`CUBLAS_WORKSPACE_CONFIG`, `torch.use_deterministic_algorithms`).

### Lightning

- `Trainer(fast_dev_run=True)` tests loop plumbing, but disables loggers/callbacks. To test checkpoint or callback bugs, use `limit_train_batches` and `limit_val_batches` instead.
- Identify automatic vs. manual optimization before altering backward/step hooks.
- Check [Lightning debugging controls](https://lightning.ai/docs/pytorch/stable/debug/debugging_basic.html).

### TensorFlow / Keras

- Distinguish `tf.keras` from standalone `keras` and check backend engine.
- Verify forward operations execute inside `tf.GradientTape` and variables are watched without intermediate NumPy conversions.
- Use `compile(run_eagerly=True)` to inspect intermediate tensor values during debugging, then re-enable graph execution to confirm.
- For determinism, review `tf.keras.utils.set_random_seed` and `tf.config.experimental.enable_op_determinism()`.

## Compare baseline and fix

Start each comparison from equivalent model and optimizer states with identical batch and behavioral assertions. Check intermediate results and updates, not merely zero exit codes.

Report minimal command, environment, baseline failure, candidate outcome, and modes exercised. For stochastic symptoms, use bounded repeated comparisons rather than picking favorable single runs.

# Verify a fix with comparable evidence

Identify the baseline revision, candidate revision, regression test, and expected behavior. If any is unavailable, narrow the conclusion instead of inventing missing evidence.

Use equivalent environments and identical test inputs for both versions. To test candidate patches speculatively without dirtying your working tree, use `python3 tools/worktree_sandbox.py run --patch <patch> --cmd "<test-cmd>"`. For untrusted reproduction tests or scripts from external issues, execute them inside container isolation via `python3 tools/container_sandbox.py`. Keep the regression test and expected result outside the changes under evaluation or otherwise verify that they are unchanged. Inspect which source file the test actually imports; an installed package can hide the checkout being tested.

Check the baseline first. Distinguish an expected assertion failure from setup, import, collection, timeout, and execution errors. Then run the same test against the candidate and run existing tests appropriate to the affected behavior. Prefer token-efficient runners: `pytest -q --tb=short -x` or `python3 tools/test_fast.py` (unittest: `python3 -m unittest discover -s tests -q -f`; Node: `npm test -- --bail --silent`; Rust: `cargo test -- --nocapture=false`).

Report:

- Baseline and candidate identifiers and commands.
- The observed reason for the baseline failure.
- The candidate result and any relevant existing-test results.
- Environment differences, instability, and checks not performed.

Conclude "verified for this reproduction" only when the test fails for the reported behavioral reason on the baseline and passes on the candidate. A test that passes on both versions does not establish that it detects this regression. Avoid broad correctness or security claims from a small test suite.

If the candidate fails, report the evidence and return it to the implementer. Do not silently edit the verifier or loosen tolerances. In multi-turn verification loops, mask repeated failure traces (`python3 tools/log_compressor.py --mask-previous <prev_log>`) to show only signature changes.

## Instructions

Stay within the assigned ML training investigation and preserve the selected framework and backend. Prefer a bounded fixed-batch experiment when it preserves the reported failure. Do not expand into long training, paid compute, or an architecture search without task authorization. Implement a production fix only when requested. Return the environment, observed failing boundary, comparable baseline and candidate results, and remaining limitations; distinguish a fixture result from model-quality or live-agent evaluation.
