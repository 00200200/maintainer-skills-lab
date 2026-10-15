---
name: "mkl-architect-editor"
description: "Two-model pipeline routing high-level design to an Architect model, and mechanical search/replace edits to an Editor model to cut costs by 70%+."
---

# Architect & Editor two-model pipeline

Decouple architectural reasoning from mechanical code editing. Use a frontier reasoning model (the **Architect**) to analyze invariants and formulate a concise change specification (< 400 tokens), then route the execution to a fast, cost-effective model (the **Editor**) to emit exact search-and-replace blocks.

## 1. Pipeline Overview & Roles

```text
[User Request / Bug Report]
            │
            ▼
┌────────────────────────────────────────┐
│  Architect Stage (Claude 3.7 / o3)     │
│  - Inspects AST scopes & invariants    │
│  - Designs architectural solution      │
│  - Emits ArchitectHandoff JSON         │ (< 400 tokens)
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Editor Stage (Haiku / GPT-4o-mini)    │
│  - Receives Target Files + Change Spec │
│  - Emits exact Search/Replace blocks   │ (Mechanical Edit)
└──────────────────┬─────────────────────┘
                   │
                   ▼
[tools/architect_editor.py apply & Syntax Verification]
```

- **Architect (Reasoning)**: Formulates the repair strategy, identifies affected files, and declares invariants that must remain unbroken. Prohibited from regenerating entire files.
- **Editor (Execution)**: Performs surgical search-and-replace replacements. If syntax or patch application fails, retries up to 2 times with compiler feedback before escalating.

## 2. Architect Handoff Contract

The Architect outputs a clean, structured `ArchitectHandoff` payload:

```json
{
  "task_id": "fix_null_key_exception",
  "target_files": ["src/cache.py"],
  "invariant_summary": "Session cache get() must return None on missing key without raising KeyError.",
  "changes": [
    {
      "file": "src/cache.py",
      "intent": "Guard dictionary retrieval with get() fallback",
      "search_block": "return self._entries[key]",
      "replace_block": "return self._entries.get(key, None)"
    }
  ]
}
```

## 3. Applying and Verifying the Handoff

Apply the handoff using `tools/architect_editor.py`:

```bash
# Verify proposed edits in dry-run mode
python3 tools/architect_editor.py apply --handoff handoff.json --dry-run

# Apply search/replace changes with automatic Python syntax validation
python3 tools/architect_editor.py apply --handoff handoff.json

# Estimate token savings compared to full-file regeneration
python3 tools/architect_editor.py estimate --file-tokens 4000
```

## 4. Cost Optimization Guarantees

By delegating mechanical search/replace generation to smaller models:
- **Token Cost Savings**: 70% to 85% reduction in API expenditure per editing turn.
- **Attention Fidelity**: Prevents frontier reasoning models from hallucinating unrelated edits across large files.
- **Fast Turnaround**: Editor turnaround latency is typically < 2 seconds.
