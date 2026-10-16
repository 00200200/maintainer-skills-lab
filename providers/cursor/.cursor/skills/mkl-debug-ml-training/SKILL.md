---
name: "mkl-debug-ml-training"
description: "Investigate training failures, NaNs, missing gradients, misleading losses, and non-reproducible runs in PyTorch, Lightning, or TensorFlow/Keras. Use for concrete training bugs, not open-ended architecture or hyperparameter search."
globs: ["*.py", "*.ipynb", "models/**", "*.pt", "*.pth", "*.ckpt"]
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
