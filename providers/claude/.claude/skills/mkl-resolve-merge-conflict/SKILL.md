---
name: "mkl-resolve-merge-conflict"
description: "Resolve git merge conflicts cleanly by analyzing only 3-way conflict hunks."
---

<skill name="mkl-resolve-merge-conflict">
  <description>Resolve git merge conflicts cleanly by analyzing only 3-way conflict hunks.</description>
  <context>
    Resolve git merge conflicts surgically by isolating only the 3-way conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) and surrounding context. Never dump entire multi-thousand-line files into the prompt, and never rewrite code outside the conflict boundaries.
  </context>
  <workflow>
    <step name="scan-unmerged-files">
      Identify conflicting paths without loading file contents:

      ```bash
      git diff --name-only --diff-filter=U
      ```
    </step>
    <step name="isolate-conflict-hunks">
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
    </step>
  </workflow>
  <workflow>
    <step name="preserve-intent">Integrate both sides when complementary (for example, non-overlapping imports or new methods added simultaneously).</step>
    <step name="choose-correct-semantic-precedence">If one branch refactors an internal call and the other adds a caller, update the caller to use the refactored signature.</step>
    <step name="clean-cleanup">Ensure ALL conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) are removed completely.</step>
    <step name="boundary-invariant">Touch strictly lines within the conflict zone. Do not reformat unrelated methods, reorder unaffected imports, or alter unrelated comments.</step>
  </workflow>
  <workflow>
    <step name="verify-resolution-before-staging">
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
    </step>
  </workflow>
  <example type="authored">
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
  </example>
</skill>
