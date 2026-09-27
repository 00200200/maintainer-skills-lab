# [Feature] Structured JSON Schemas with Minimal Error Retries for Triage Skills

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Motivation
Skills like `mkl-triage-issue` and `mkl-review-pr` often need to output structured verdicts (e.g. `severity`, `labels`, `component`, `is_reproducible`).

When LLMs produce malformed JSON or miss required keys, naive frameworks feed back the entire 2,000-word conversation history with a generic message: *"Your response was invalid JSON. Please regenerate everything."* This doubles the turn's token cost!

## Prior Art & Industry Standards
- **PydanticAI & Instructor**: Employs minimal validation feedback loops. When validation fails, only the specific schema validation error (`"missing field: 'repro_steps'"`) is passed to the correction turn, avoiding regenerating unproblematic fields.
- **OpenAI Structured Outputs & Anthropic JSON Schema**.

## Proposed Solution
Define explicit JSON schemas for triage and review skills:
1. Provide standard JSON schema definitions in `skills/mkl-triage-issue/schema.json` and `skills/mkl-review-pr/schema.json`.
2. Add a lightweight JSON schema validator helper in `tools/validate_output.py`.
3. In retry instructions, mandate that the agent only receives the specific validation diff, cutting retry tokens by 75%.

## Implementation Tasks
- [ ] Create JSON schemas for `mkl-triage-issue` and `mkl-review-pr`.
- [ ] Add `tools/validate_output.py` using standard library `json`.
- [ ] Update skill instructions with structured output schemas and minimal error recovery rules.
- [ ] Add unit tests in `tests/test_validation.py`.

## Acceptance Criteria
- Triage outputs adhere to standard JSON schemas.
- Error recovery guidance prevents full conversation replay.
