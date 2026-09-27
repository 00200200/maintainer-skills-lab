# [Feature] DSPy-Style Automated Skill Few-Shot Optimizer (`tools/optimize_skill.py`)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Currently, skills in `skills/*/SKILL.md` contain manually written worked examples. These examples are often either too long (wasting tokens in every prompt) or insufficiently diverse (failing to teach the model how to handle tricky edge cases).

In modern AI engineering, manual prompt tinkering is increasingly replaced by automated prompt optimization against objective evaluation metrics.

## Prior Art & Industry Standards
- **DSPy (Stanford NLP)**: Uses MIPROv2 and Teleprompter algorithms to compile prompts and few-shot examples automatically, finding the minimal set of demonstration tokens that maximizes accuracy on a validation dataset.
- **Anthropic Prompt Improver**: Iteratively tests and optimizes prompt wording.

## Proposed Solution
Create a prompt compilation tool `tools/optimize_skill.py`:
```bash
python3 tools/optimize_skill.py --skill mkl-humanize --dataset examples/writing/ --metric token_efficiency
```

### Mechanism
1. **Benchmark Evaluation**: Runs the skill against baseline scenarios in `examples/` using an offline evaluator or LLM API.
2. **Token Pruning**: Iteratively shortens instructions and worked examples line-by-line.
3. **Validation Check**: If task pass-rate remains 100% while token count drops by 20%, the optimizer outputs the compressed prompt candidate as a suggested PR diff.

## Implementation Tasks
- [ ] Create `tools/optimize_skill.py`.
- [ ] Implement iterative token reduction and validation runner.
- [ ] Support `--skill`, `--dataset`, and `--target-reduction` flags.
- [ ] Add unit tests in `tests/test_optimizer.py`.

## Acceptance Criteria
- Running `optimize_skill.py` identifies redundant phrasing in sample skills and suggests token-compact edits without reducing test pass rates.
