# mkl-fix-type-errors

Resolve static type checker errors (mypy, pyright) using localized symbol-level diagnostics without whole-file rewrites. Use when type checks fail on candidate patches.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-fix-type-errors."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Fix static type checker errors

Resolve type checker errors (`mypy`, `pyright`) by diagnosing the failing symbol and applying minimal, surgical repairs. Never feed whole source files into context or rewrite entire modules to fix isolated type mismatches.

## 1. Extract Localized Diagnostics

Run the compact diagnostic extractor to isolate only the failing symbol, line numbers, and error codes:

```bash
# Mypy text output
mypy --show-error-codes path/to/file.py | python3 tools/extract_type_diagnostics.py

# Pyright JSON output
pyright --outputjson path/to/file.py | python3 tools/extract_type_diagnostics.py --format pyright
```

Inspect the returned `<type_error>` block:
- Note the exact error code (for example `union-attr`, `arg-type`, `return-value`).
- Focus only on the enclosing symbol (`<symbol>`) and localized line context (`<context>`).
- If multiple cascading errors stem from one symbol, fix the root symbol first.

## 2. Select Minimal Repair Strategy

Choose the least invasive repair that satisfies the type checker without altering runtime behavior:

1. **Type Narrowing (`[union-attr]` / `Optional`)**:
   Add an early return or guard clause before member access:
   ```python
   if val is None:
       return default_value
   ```
2. **Signature Widening (`[arg-type]`)**:
   If a function accepts multiple collection types, widen the parameter annotation from concrete `list[T]` to abstract `Sequence[T]` or `Iterable[T]`, or `dict[K, V]` to `Mapping[K, V]`.
3. **Return Type Adjustment (`[return-value]`)**:
   If a function can return `None` on failure or fallback branches, widen the return annotation to `T | None`. If `None` should not be returned, ensure all code paths return a valid instance.
4. **Variable Annotation (`[var-annotated]` / `[assignment]`)**:
   Provide an explicit type annotation on initialization (`items: list[str] = []`) or use `typing.cast(TargetType, expr)` where dynamic behavior cannot be expressed in standard type syntax.

## 3. Apply Surgical Patch

Modify only the affected signature, variable annotation, or guard line. Do not reformat unrelated functions, invent new abstractions, or replace working standard library calls.

## 4. Verify Resolution

Re-run the type checker strictly on the modified file:

```bash
mypy --show-error-codes path/to/file.py
```

Confirm that the target error is eliminated, error count dropped to zero, and existing regression tests continue to pass without behavioral drift.
