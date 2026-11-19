# Trusted reports for manual regression reporting

The manually dispatched `arena-regression.yml` workflow reads reviewed JSON files
only from this directory on the repository's default branch. Dispatch inputs are
relative filenames, for example `experiment/baseline.json`, not URLs or artifact IDs.
All path components must be regular directories/files; symlinks are forbidden.

Commit only reviewed, publishable reports and their optional M6a provenance JSON.
Do not include credentials, raw transcripts, gold patches or private task data.
Reports/provenance remain caller assertions, not authenticated execution evidence.
No benchmark data is fabricated or generated here, and this directory initially
contains no trusted comparison pair. Missing files cause workflow failure.

See [the Arena documentation](../../../docs/arena.md) for accepted report profiles,
comparison eligibility, manual dispatch and status interpretation.
