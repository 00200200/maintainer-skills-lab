# mkl-resolve-merge-conflict

Resolve git merge conflicts cleanly by analyzing only 3-way conflict hunks.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-resolve-merge-conflict."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Resolve git merge conflicts

Resolve git merge conflicts surgically by isolating only the 3-way conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and surrounding context. Never dump entire multi-thousand-line files into the prompt, and never rewrite code outside the conflict boundaries.

## 1. Scan Unmerged Files

Identify conflicting paths without loading file contents:

```bash
git diff --name-only --diff-filter=U
```

## 2. Isolate Conflict Hunks

Extract only the conflict markers and minimal surrounding lines (5-10 lines of context) using `grep -n` or line-targeted reading:

```bash
# Locate conflict markers with line numbers
grep -n -E "^(<<<<<<<|=======|>>>>>>>)" path/to/conflicting_file.py
```

For complex ambiguities, inspect the three-way ancestry using git index stages without pulling whole files:

```bash
# Common ancestor (base)
git show :1:path/to/file.py

# Current branch version (ours / HEAD)
git show :2:path/to/file.py

# Incoming branch version (theirs / target)
git show :3:path/to/file.py
```

## 3. Surgical Resolution Protocol

1. **Preserve Intent**: Integrate both sides when complementary (for example, non-overlapping imports or new methods added simultaneously).
2. **Choose Correct Semantic Precedence**: If one branch refactors an internal call and the other adds a caller, update the caller to use the refactored signature.
3. **Clean Cleanup**: Ensure ALL conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) are removed completely.
4. **Boundary Invariant**: Touch strictly lines within the conflict zone. Do not reformat unrelated methods, reorder unaffected imports, or alter unrelated comments.

## 4. Verify Resolution Before Staging

Before running `git add`, verify syntax and run the focused test suite:

```bash
# Python syntax check
python3 -m py_compile path/to/conflicting_file.py

# Run affected tests
pytest -q --tb=short path/to/test_affected.py
```

Only stage the resolved file once verification passes:

```bash
git add path/to/conflicting_file.py
```

## Worked Example

### Conflicting Hunk
```python
<<<<<<< HEAD
    timeout = 30
    retry_count = 3
=======
    timeout = 60
    backoff_factor = 1.5
>>>>>>> feat/network-retry
```

### Clean Resolution
```python
    timeout = 60
    retry_count = 3
    backoff_factor = 1.5
```
