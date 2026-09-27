# [Optimization] PyTorch / CUDA Shape & Gradient NaN Diagnosis Minifier in `mkl-debug-ml-training`

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
In `mkl-debug-ml-training`, agents diagnose PyTorch, Lightning, and TensorFlow errors (e.g. NaNs in loss, CUDA out of memory, tensor dimension mismatches).

CUDA and PyTorch autograd tracebacks can span multiple pages (100+ frames through internal C++ dispatcher bindings like `torch/_tensor.py`, `torch/autograd/__init__.py`), wasting thousands of tokens without providing useful context.

## Prior Art & Industry Standards
- **PyTorch `torch.autograd.set_detect_anomaly(True)`**: Emits detailed backward tracebacks.
- **Better Exceptions / Rich Traceback**: Filters standard library and internal framework frames to show only user-level model code.

## Proposed Solution
Enhance `skills/mkl-debug-ml-training/SKILL.md` with a **PyTorch Traceback Minification** recipe and tool:
1. **Frame Filtering**:
   - Filter out internal PyTorch dispatcher frames (`torch/nn/modules/*`, `torch/autograd/*`).
   - Extract only the user model layer (`MyTransformer.forward`) and tensor shapes at point of failure (`torch.Size([32, 128]) vs torch.Size([32, 256])`).
2. **NaN Checkpoint Recipe**:
   - Provide a 3-line check hook (`torch.isnan(loss).any()`) to immediately halt training and inspect the exact layer producing non-finite gradients.

## Implementation Tasks
- [ ] Update `skills/mkl-debug-ml-training/SKILL.md` with traceback filtering instructions.
- [ ] Add a small helper script `tools/minify_torch_trace.py`.
- [ ] Run `python3 tools/kit.py sync` across all clients.
- [ ] Add unit tests in `tests/test_ml_example.py`.

## Acceptance Criteria
- 150-line PyTorch autograd traceback compressed to < 15 lines of actionable user-code stack frames (< 200 tokens).
- Unit tests pass.
