# mkl-verify-fix

Verify a proposed bug fix against an unchanged regression test and the relevant existing tests, reporting baseline and candidate outcomes separately. Use for fix verification, not a general claim that software is bug-free.

## Use in Grok Bot

This is a Markdown setup recipe for Grok Bot (SpaceXAI). It has not been evaluated in a live Bot.

1. Open an existing Bot or create one with this job.
2. Give it the workflow below with a concrete task and the required inputs or supporting files. Choose the access and approval limits.
3. Run the task once and inspect its output against the workflow checks.
4. Ask: "Save this validated workflow as a skill called mkl-verify-fix."
5. Check that the skill is enabled for this Bot in Settings → Plugins → Yours, then invoke it from the `/` menu.

An agent recipe combines its source instructions and dependent skills below. Copying this file does not create a Bot or routine.

Reference: [Grok Bot skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

## Workflow

# Verify a fix with comparable evidence

Identify the baseline revision, candidate revision, regression test, and expected behavior. If any is unavailable, narrow the conclusion instead of inventing missing evidence.

Use equivalent environments and identical test inputs for both versions. Keep the regression test and expected result outside the changes under evaluation or otherwise verify that they are unchanged. Inspect which source file the test actually imports; an installed package can hide the checkout being tested.

Check the baseline first. Distinguish an expected assertion failure from setup, import, collection, timeout, and execution errors. Then run the same test against the candidate and run existing tests appropriate to the affected behavior.

Report:

- Baseline and candidate identifiers and commands.
- The observed reason for the baseline failure.
- The candidate result and any relevant existing-test results.
- Environment differences, instability, and checks not performed.

Conclude "verified for this reproduction" only when the test fails for the reported behavioral reason on the baseline and passes on the candidate. A test that passes on both versions does not establish that it detects this regression. Avoid broad correctness or security claims from a small test suite.

If the candidate fails, report the evidence and return it to the implementer. Do not silently edit the verifier or loosen tolerances.
