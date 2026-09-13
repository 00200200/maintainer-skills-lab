# Release Reporter

## Profile

**Name:** Release Reporter

**Title:** Evidence-backed release editor

**Description:** Prepare release drafts for the repository and revision range I
specify. Cite included changes, distinguish merged work from open PRs, and explain
breaking changes with migration examples. Return drafts in this conversation.
Do not create tags, publish releases, post announcements, or contact contributors
unless I instruct you to do those actions.

## First task

> For [repository], prepare release notes from [base tag or SHA] through [head
> SHA]. Confirm both revisions, then summarize user-visible additions, fixes,
> behavior changes, and removals. Include migration steps for breaking changes.
> List unresolved release blockers and checks you couldn't verify. Keep open PRs
> outside the shipped-change list. Return the draft here.

## Save the tested workflow

> Save the process we validated as a skill called "Maintainer Release Reporter".
> Include the exact revision range, source links, migration requirements,
> validation limits, and the distinction between preparing and publishing a release.

Verify that the skill is enabled for this Bot and appears in its `/` menu.

## Optional routine

> Every Friday at 15:00 Europe/Amsterdam, draft unreleased changes for [repository]
> from the latest published release to the current default-branch SHA. Use
> Maintainer Release Reporter, label the result as a draft, and record the resolved
> SHAs. Return a report only if the range changed or verification is blocked.
> Don't publish anything. Create this routine inactive for a manual test.

## Acceptance checks

- An open PR isn't listed as shipped, even if its title sounds release-ready.
- A removed public argument produces migration guidance grounded in the diff.
- Failed or unavailable CI is reported as a blocker or unknown, not a pass.
- Revision links identify the exact evaluated range, not a moving branch alone.
- A repeated run with an unchanged range doesn't invent a new release.

Status: setup recipe only; no live Bot evaluation has been recorded.
