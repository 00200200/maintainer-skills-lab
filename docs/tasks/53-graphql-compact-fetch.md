# [Optimization] GraphQL Compact PR & Issue Ingestion Tool (tools/gh_compact_fetch.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Context & Problem
Maintainer triage and review skills (`mkl-triage-issue`, `mkl-review-pr`, `mkl-write-maintainer-reply`) require ingesting remote GitHub issue and pull request discussion threads into agent context.

Currently, when agents fetch discussions using `gh issue view`, `gh pr view`, or standard REST endpoints (`/repos/{owner}/{repo}/issues/{id}/comments`), the raw payload introduces massive token bloat:
1. **Automated Bot Comments**: Multi-thousand token comments posted by automated bots: Codecov coverage diff tables, Dependabot release matrices, Stale bot warnings, and CI status reporters.
2. **Metadata Over-fetching**: Redundant REST payload metadata: avatar URLs, node IDs, reaction dictionaries (`+1`, `heart`, `hooray`), user URLs, and nested commit SHA links.
3. **Quoted Reply Chains & Signatures**: Email-based replies quoting the entire previous discussion thread (`> On Mon, Jan 1...`), mobile footers ("Sent from my iPhone"), and lengthy personal email signatures.

An issue with 4 short developer comments (around 150 words of actual human conversation) frequently blows up into 3,000 to 5,000 ingested context tokens! This wastes model attention, increases latency, and significantly inflates API costs.

We need a dedicated, token-optimized ingestion utility `tools/gh_compact_fetch.py` utilizing GitHub's GraphQL API. By querying only necessary semantic fields, filtering out bot spam, stripping quoted replies, and minifying formatting, it reduces ingestion token consumption by **75% to 85%**.

## Prior Art & Industry Standards
- **GitHub GraphQL API v4**: Allows precise client-specified field selection, eliminating REST over-fetching in a single round-trip query.
- **Mailgun Talon / Email Reply Parser**: Industry standard heuristics for detecting and stripping email signature blocks and quoted reply headers.
- **Aider & Repomix Context Filters**: Stripping non-essential conversational and structural noise before packing context into LLM prompts.

## Proposed Solution
Create `tools/gh_compact_fetch.py`:
- Zero external Python dependencies: executes via `gh api graphql` CLI or standard library `urllib.request` with `GITHUB_TOKEN`.
- Executes an optimized GraphQL query selecting only essential fields (`title`, `state`, `author.login`, `body`, and `comments`).
- Filters out bot comments, automated tables, and reactions.
- Strips quoted email reply blocks and signature noise.
- Formats conversations into ultra-dense Markdown or compact JSON.

```bash
# Ingest an issue thread compactly
python3 tools/gh_compact_fetch.py --issue owner/repo#123

# Ingest a pull request, filtering out bot comments
python3 tools/gh_compact_fetch.py --pr owner/repo#456 --exclude-bots

# Output compact JSON for programmatic skill pipelines
python3 tools/gh_compact_fetch.py --issue owner/repo#123 --json

# Report token savings compared to standard REST payload
python3 tools/gh_compact_fetch.py --issue owner/repo#123 --stats
```

### Ingestion & Pruning Pipeline

```
[ GitHub Issue / PR Thread (REST: ~4,200 tokens) ]
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│               tools/gh_compact_fetch.py                │
├────────────────────────────────────────────────────────┤
│ 1. Minimal Single-Query GraphQL Fetch:                 │
│    Queries only { title, author, body, comments }      │
│ 2. Automated Bot Filtering:                            │
│    Detects & excludes dependabot, codecov, stale bots  │
│ 3. Reply Chain & Signature Trimming:                   │
│    Strips `> Quoted text`, "Sent from my iPhone", etc. │
│ 4. Whitespace & Table Normalization                    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
[ Compact Thread Markdown (Compressed: ~650 tokens) ]
   -> 84% Token Reduction with Zero Loss of Context!
```

### Compact Markdown Output Format
```markdown
# [Issue #123] Crash in parse_url when port is empty
**Author**: @alice | **State**: OPEN | **Labels**: bug, parser

### Description
When passing an empty port, `parse_url("http://example.com:")` raises ValueError instead of falling back to default port.

### Discussion (2 comments, 2 bot comments omitted)
**@bob** (Maintainer):
Reproduced on Python 3.12. Root cause is in `src/url.py:45`.

**@alice** (Author):
I can submit a patch if the expected behavior is returning None.
```

### Key Capabilities
1. **GraphQL Single-Query Ingestion**:
   - Fetches thread details and paginated comments in one network request, reducing roundtrips.
2. **Intelligent Bot Classifier**:
   - Matches known bot suffixes (`[bot]`), author types (`Bot`), and known usernames (`codecov`, `dependabot`, `github-actions`, `vercel`).
   - Collapses bot comments into a 1-line summary: `(1 bot comment from @codecov omitted)`.
3. **Quoted Reply & Signature Stripper**:
   - Strips email quote blocks beginning with `>`.
   - Cleans signatures ("Sent from my iPhone", "Best regards", PGP signatures).
4. **Integration with Maintainer Skills**:
   - Update `skills/mkl-triage-issue/SKILL.md` and `skills/mkl-write-maintainer-reply/SKILL.md` to recommend `python3 tools/gh_compact_fetch.py` for thread ingestion.

## Implementation Tasks
- [ ] Implement `tools/gh_compact_fetch.py` using `gh api graphql` or `urllib.request`.
- [ ] Write GraphQL queries for issues and pull requests fetching only essential fields.
- [ ] Implement bot detection heuristics with configurable `--include-bots` / `--exclude-bots`.
- [ ] Implement email signature and quoted reply pruning regex patterns.
- [ ] Implement `--stats` token comparison reporting (raw vs compact token counts).
- [ ] Add unit tests in `tests/test_gh_compact_fetch.py` using mock GraphQL JSON responses.
- [ ] Update `skills/mkl-triage-issue/SKILL.md` and `skills/mkl-review-pr/SKILL.md` to document compact thread ingestion.

## Acceptance Criteria
- Pure standard library Python 3.11+ (interfacing cleanly with `gh` CLI or `GITHUB_TOKEN`).
- Reduces token footprint of bot-heavy and email-threaded discussions by at least 75%.
- Correctly identifies and filters common bot users (`codecov[bot]`, `dependabot[bot]`).
- Preserves all human author comments, code blocks, and essential technical context.
- Unit tests pass cleanly with `python3 -m unittest discover -s tests -v`.
