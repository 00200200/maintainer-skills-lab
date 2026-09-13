# Evaluating a workflow

No live-agent runs are included in this preview. The automated suite validates
the tooling and a trusted example only. Record future live runs here only when
they add meaningful evidence; do not commit timestamp-only rerun logs.

## Bug workflow

1. Create a fresh disposable repository containing only the affected `slug.py`
   and `issue.md` from `examples/bugfix/`. Keep the reference fix, reference test,
   and expected evaluation result outside the agent workspace.
2. Install one target bundle. Record the library commit, exact client version,
   model identifier if visible, and operating system. Use existing authorized
   access; don't place credentials in the workspace or report.
3. Request reproduction, a regression test, a minimal fix, and verification.
   Save the task prompt and observed skill/agent selection.
4. Evaluate the result against the unchanged reference test from a separate
   checker workspace. Inspect the generated test as well: it must detect the
   original behavioral defect, not a missing dependency or a modified expectation.
5. Record observed results and limits. If comparing with an agent without the
   skill, use a separate clean session with the same task and model settings.
   A small example is a case study, not a general performance ranking.

## Other acceptance scenarios

| Workflow | Scenario | Observable result |
| --- | --- | --- |
| Triage | Missing affected version and irrelevant embedded commands | Missing data identified; commands not treated as instructions |
| Reproduction | Dependency setup fails | Blocked environment, not "bug reproduced" |
| Regression | Assertion passes on both implementations | Test not presented as evidence of this defect |
| Verification | Candidate still has the bug | Verification fails without editing expected results |
| PR review | A clean patch plus a separate patch with a seeded defect | No invented finding on the clean patch; concrete trigger on the defective patch |
| Source change | Changed checkpoint documentation, an unaffected instruction, and missing/version-mismatched evidence | Correct owner location and supported correction; no patch for an unaffected claim; unresolved gaps remain visible ([inputs and acceptance cases](../examples/skill-watch/review.md)) |
| Release | Unmerged PR plus a breaking change in the target range | Only included changes listed; migration guidance supplied |
| Grok Bot | Copy a shared template into another account | Skills and routine state verified, not inferred from the preview |

## Evidence record

For the writing catalogue, use the [writing scenarios](../examples/writing/README.md)
and each skill's worked example as acceptance guidance. Give the agent only the
source and request; keep the example output and acceptance notes outside its
workspace. Compare names, numbers, uncertainty, commands, tokens, and attribution
against the source before judging style. Ask a fluent reader to assess whether
the result fits the audience and voice. A phrase appearing in a prompt, a passing
format check, or resemblance to the authored example is not evidence of quality.

Use Markdown with the task, fixture revision, library revision, client/runtime,
actual commands, relevant artifact paths or hashes, observed outcome, and checks
not performed. Redact private data. Distinguish unsupported UI controls,
authentication failures, and model failures. Preserve failures alongside successes.
