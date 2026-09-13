---
name: "mkl-release-editor"
description: "Prepare accurate release notes, migration guidance, and outstanding blockers from a specific revision range."
---

Keep shipped changes, unreleased changes, and plans separate. Produce a reviewable release draft. Do not claim to publish or announce a release unless the assigned task actually authorizes and completes those actions.

# Prepare a release

Read the project's release policy, previous release, and requested target revision. Resolve the revision range before summarizing. Keep unmerged work and future plans separate from changes actually included in that range.

Group changes by their effect on users: additions, fixes, behavior changes, deprecations, and removals. Link claims to commits, PRs, or affected public interfaces. Omit internal churn that has no useful consequence for the reader.

For breaking changes, show the previous and new behavior and a concrete migration example. Inspect package metadata, supported runtimes, installation instructions, and required release checks. Treat CI badges and old test output as insufficient evidence for the current revision.

Return draft release notes, a migration section when needed, the evaluated revision range, completed checks, and remaining release blockers. Follow the repository's versioning policy; don't invent a version if the user's requested release is still ambiguous.

Creating tags, publishing packages or releases, and sending announcements are separate external actions. Perform them when already authorized by the user; otherwise finish the reviewable draft and identify the exact remaining action.
