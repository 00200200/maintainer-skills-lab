# mkl-localize-fault

Isolate suspect files and line ranges before code repair using AST skeletons and stack traces (< 300 tokens). Use before editing code to prevent full-file context dumps.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-localize-fault."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Localize faults before code repair

Isolate bugs to specific files, symbols, and line ranges before attempting code repair. Never dump entire modules or multi-thousand line files into context. Enforce a two-stage protocol: localize first (< 300 tokens), then extract only the relevant scoped slice.

## 1. Stage 1: Hierarchical Localization

Pinpoint the candidate failure site using stack trace analysis or AST structural inspection:

```bash
# Analyze failing exception traceback
python3 tools/localize_fault.py locate --traceback path/to/traceback.txt

# Inspect signatures and class outlines without reading implementation bodies
python3 tools/localize_fault.py skeleton --file path/to/suspect.py

# Find exact line bounds for a specific symbol
python3 tools/localize_fault.py symbol --file path/to/suspect.py --symbol MyClass.method_name
```

Emit a compact, structured localization finding (< 300 tokens) using standard YAML:

```yaml
fault_localization:
  file: "src/maintainer_skills/triage.py"
  symbol: "TriageClassifier.classify_issue"
  line_range: [142, 168]
  confidence: "high"
  rationale: "Unchecked KeyError when issue labels list is empty."
```

## 2. Stage 2: Scoped Context Extraction

Extract only the localized line range with bounded padding (+/- 15 lines) using `tools/localize_fault.py extract`:

```bash
python3 tools/localize_fault.py extract --file src/maintainer_skills/triage.py --lines 142-168 --padding 15
```

The tool produces a bounded view omitting surrounding irrelevant lines:

```python
# ... [126 lines omitted for brevity (lines 1-126)] ...
127 |     def validate_payload(self, payload: dict) -> bool:
128 |         return "title" in payload
...
142 |     def classify_issue(self, issue: dict) -> str:
143 |         labels = issue["labels"]
# ... [340 lines omitted for brevity (lines 184-524)] ...
```

## 3. Targeted Repair and Verification

Pass ONLY the extracted hunk to the code repair prompt or tool:

1. **Verify Boundaries**: Ensure the proposed patch edits exclusively lines within the localized range.
2. **Prevent File Bloat**: Do not re-emit or reformat omitted code sections.
3. **Run Focused Tests**: Verify the candidate fix against the reproduction test case before running the broader suite.
