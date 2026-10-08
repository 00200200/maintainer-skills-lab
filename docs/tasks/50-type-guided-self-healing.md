# [Feature] Type-Guided Self-Healing Code Generator (mkl-fix-type-errors)

**Labels**: `enhancement`, `new skill`, `help wanted`

## Context & Problem
When autonomous AI agents generate bug fixes, refactor code, or implement new features, static type checkers (`mypy`, `pyright`) frequently flag type errors:
- `Incompatible return value type (got "None", expected "str")`
- `Item "None" of "Optional[T]" has no attribute "x"`
- `Argument 1 to "execute" has incompatible type "List[Any]"; expected "Sequence[str]"`
- `Missing type annotation for function parameter`

The standard, naive failure mode observed in coding agents:
1. The agent feeds the **entire 800-line source file** into context alongside the complete 60-line terminal traceback from `mypy`.
2. Faced with a massive context window, the model frequently performs a sweeping rewrite of the entire file rather than a surgical fix.
3. This full-file regeneration introduces subtle runtime regressions, invents unneeded helper functions, mangles unrelated imports, and burns 2,000–4,000 context tokens.

In open-source maintenance, over 90% of type errors can be resolved via **targeted, symbol-level repairs**: adding a type guard (`if val is None: return ...`), updating a union annotation (`str | None`), or importing `Sequence` instead of `list`.

We need a dedicated maintainer skill `mkl-fix-type-errors` paired with a diagnostic extractor utility (`tools/extract_type_diagnostics.py`) that isolates *only* the failing symbol, line number, and error code. By feeding the model an ultra-compact diagnostic slice (< 150 tokens), the agent can perform minimal, self-healing type annotation fixes with near-zero token overhead.

## Prior Art & Industry Standards
- **Pyright & Mypy Language Server Protocol (LSP)**: Fine-grained diagnostic reports with line, column, error code, and symbol ranges for targeted IDE quick-fixes.
- **TypeScript Compiler Quick Fixes**: Automated symbol-level type-directed healing without modifying function logic.
- **Aider & SWE-bench Scoped Repair**: Constraining model edits to unified diffs on localized method scopes rather than whole-file regeneration.

## Proposed Solution
Create a new specialized maintainer skill `skills/mkl-fix-type-errors/SKILL.md` and a supporting diagnostic parser `tools/extract_type_diagnostics.py`.

```bash
# Extract compact type diagnostics from mypy run
mypy --show-error-codes src/ | python3 tools/extract_type_diagnostics.py

# Extract compact type diagnostics from pyright run
pyright --outputjson src/ | python3 tools/extract_type_diagnostics.py --format pyright

# Automatically pair with scope_extract.py for minimal symbol context
python3 tools/extract_type_diagnostics.py --mypy-log mypy_output.log --with-scope
```

### Self-Healing Feedback Loop

```
┌────────────────────────────────────────────────────────┐
│               mypy / pyright type check fails          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│           tools/extract_type_diagnostics.py            │
├────────────────────────────────────────────────────────┤
│ 1. Parse error line, file, and error code:             │
│    [arg-type], [union-attr], [return-value]            │
│ 2. Deduplicate repeated error cascades                 │
│ 3. Slice AST enclosing symbol via scope_extract.py     │
└───────────────────────────┬────────────────────────────┘
                            │ (Outputs < 150 tokens)
                            ▼
┌────────────────────────────────────────────────────────┐
│          Skill: mkl-fix-type-errors                    │
├────────────────────────────────────────────────────────┤
│ Applies Minimal Repair Strategy:                       │
│  - Strategy A: Type Narrowing (`is None` guard)        │
│  - Strategy B: Union / Optional annotation update      │
│  - Strategy C: Structural Subtyping (Protocol/Sequence)│
│  - Strategy D: Safe Type Assertion / Cast              │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ Local Verification: mypy <file> passes cleanly (0 err) │
└────────────────────────────────────────────────────────┘
```

### Compact Diagnostic Schema
Instead of passing a 1,000-token log dump, `tools/extract_type_diagnostics.py` produces:
```xml
<type_error file="src/parser.py" line="42" code="union-attr">
  <symbol>parse_header</symbol>
  <message>Item "None" of "Optional[Header]" has no attribute "content"</message>
  <context>
40: def parse_header(raw: str) -> str:
41:     header = find_header(raw)
42:     return header.content
  </context>
  <recommended_fix>Add guard 'if header is None: return ""' or widen return type</recommended_fix>
</type_error>
```

### Skill Workflow (`skills/mkl-fix-type-errors/SKILL.md`)
1. **Diagnosis**: Run `tools/extract_type_diagnostics.py` to isolate the primary failing symbol. Never read the whole file.
2. **Strategy Selection**:
   - For `[union-attr]` or `Optional`: Add defensive guard clause or default value.
   - For `[arg-type]`: Check if signature parameter type can accept a broader type (`Sequence` vs `list`, `Mapping` vs `dict`).
   - For `[return-value]`: Adjust return type annotation or handle edge-case branch return.
3. **Patch Application**: Emit a minimal unified diff touching only the symbol definition and affected lines.
4. **Verification**: Re-run type check on the target file only (`mypy <file>`). Confirm error count dropped to zero without introducing new errors.

## Implementation Tasks
- [ ] Implement `tools/extract_type_diagnostics.py` to parse standard `mypy` text output and `pyright` JSON output.
- [ ] Connect `extract_type_diagnostics.py` with `tools/scope_extract.py` to bundle enclosing function/class definitions without dumping entire files.
- [ ] Author `skills/mkl-fix-type-errors/SKILL.md` following Maintainer Skills Lab conventions (metadata, constraints, worked examples, token budget).
- [ ] Add fixture examples in `examples/typefix/` covering `Optional` unboxing, incompatible argument types, and missing return annotations.
- [ ] Add unit tests in `tests/test_type_diagnostics.py` covering mypy and pyright parser robustness.
- [ ] Register `mkl-fix-type-errors` in `tools/kit.py` and sync client bundles (`.claude/`, `.cursor/`, etc.).

## Acceptance Criteria
- `tools/extract_type_diagnostics.py` runs with zero third-party dependencies on Python 3.11+.
- Successfully parses both `mypy` text output and `pyright` JSON output.
- Generates compact diagnostic representations consuming $< 200$ tokens per error.
- `skills/mkl-fix-type-errors/SKILL.md` conforms to token budget ($\le 800$ tokens total skill length).
- Successfully guides test agents to solve real type errors in `examples/typefix/` without full-file rewrites.
- Unit tests pass cleanly with `python3 -m unittest discover -s tests -v`.
