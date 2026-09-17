# Skill Watch

Find which agent instructions need review when their source documentation changes.
Skill Watch saves selected source text, compares it later, and maps the difference
to owner files, dependent agents, and existing generated provider copies.

It is a local CLI with an optional MCP server. It does not require a model or API
key. A changed source is a **review signal**, not proof that a skill is incorrect.

## Try the offline demo

From a clone of this repository, with Python 3.11+:

```sh
python3 examples/skill-watch/run.py
```

An authored training guide changes one sentence:

```diff
-Checkpoints remain enabled during this diagnostic.
+Checkpoints are disabled during this diagnostic.
```

The example creates a disposable project, records its baseline, detects the
change twice, finds the dependent agent, and verifies that the baseline remains
untouched until explicit acceptance. It never requests a website or calls an LLM.
`smoke_run` in this fixture is fictional; this is not a reported framework change.

## Watch your sources

Find literal HTTPS references without fetching them:

```sh
python3 tools/skill_watch.py discover
```

Discovery scans source Markdown under `skills/`, TOML files under `agents/`, and
root `README.md`, `AGENTS.md`, and `CLAUDE.md`. It reports URLs and line locations.
It is a literal-link finder, not a full Markdown parser: review its output before
adding sources to the configuration. Discovery does not enable any watches.

The checked-in [configuration](../skill-watch.toml) selects four references used
by our ML skill. To watch a source, give it a stable ID, a URL, and owner files:

```toml
version = 1

[[sources]]
id = "training-guide"
url = "https://docs.example.org/training"
start = "A unique sentence at the beginning of the relevant section"
end = "A unique sentence after that section"
owners = ["skills/mkl-training/SKILL.md"]
```

Replace the illustrative URL, markers, and owner path with real values. Owners
must exist in the selected project. Skill owners also map to `agents/*.toml`
profiles that list them in `skills`; matching provider exports are included only
when those files exist. This dependency mapping uses Maintainer Skills Lab's
layout; other repositories can use explicit owner paths without that integration.

`start` and `end` are optional literal text markers, applied after HTML text
extraction. The start is included and the end is excluded. Each supplied marker
must occur exactly once in its search range. Missing or ambiguous markers are
errors. Choose a unique sentence if a heading also occurs in the table of contents.

HTML scripts, styles, navigation, headers, footers, and explicitly hidden elements
are omitted. Normal prose whitespace is collapsed, while indentation inside
`pre` is preserved. This is text comparison, not a rendered-page or visual diff.
Plain text and Markdown are compared as text without executing embedded content.

For local documentation or offline fixtures, replace `url` with a project-relative
`file` and optionally set `format = "html"` (default: `text`). Use exactly one
location field. Source, owner, config, and state paths cannot traverse outside the
project or follow symlinks.

Review the selected sources, then save the initial baseline and compare:

```sh
python3 tools/skill_watch.py sources
python3 tools/skill_watch.py --json check
python3 tools/skill_watch.py snapshot
python3 tools/skill_watch.py check
```

The first check reports `new-source` until a baseline exists. `snapshot` refuses
to overwrite one and writes nothing if any source fails. The default baseline is
`.skill-watch/baseline.json`, ignored by Git in this repository. No scheduler is
installed; run `check` when you need it or from your existing task runner.

After reviewing a difference and updating affected instructions if necessary,
accept exactly one source using its full current hash from the check report:

```sh
python3 tools/skill_watch.py accept --source training-guide --sha256 FULL_CURRENT_SHA256
```

Acceptance fetches again and refuses if the text hash no longer matches. It
preserves other sources and detects concurrent baseline writes. Neither `check`
nor `accept` edits skills or generated copies. Source edits still use the normal
`python3 tools/kit.py sync` workflow.

Baseline files have a 6 MB UTF-8 limit, including retained sources removed from
the configuration. A snapshot or acceptance that would exceed it fails before
writing and preserves any existing baseline. Use a separate `--state` file for
a new group of sources and review them before creating its initial snapshot.

Use `--project /absolute/project`, `--config relative/watch.toml`, or
`--state relative/baseline.json` **before** the subcommand for another project or
state file. Use `--json` there for full text, hashes, resolved URLs, timestamps,
diffs, and file mappings. Human output caps each diff at 12,000 characters.

Exit codes: **0** for an unchanged check or successful command, **1** when any
checked source needs review, **2** for configuration, baseline, or retrieval
errors. A timeout, HTTP error, missing marker, or unavailable file cannot count as
unchanged. Removed configuration entries are listed as unconfigured baselines;
they are no longer fetched or included in the check result's success criterion.

## Connect through MCP

The optional server uses the official Python MCP SDK, pinned to **2.2.0**. With
[uv](https://docs.astral.sh/uv/), launch it from the clone:

```sh
uv run tools/skill_watch_mcp.py --project /absolute/path/to/maintainer-skills-lab
```

`uv` installs the declared SDK in an isolated environment. The server uses stdio;
stdout belongs to the MCP protocol. Point a compatible client's local MCP setup
at that command. For clients using `mcpServers` JSON, the equivalent record is:

```json
{
  "mcpServers": {
    "skill-watch": {
      "command": "uv",
      "args": [
        "run",
        "/absolute/path/to/maintainer-skills-lab/tools/skill_watch_mcp.py",
        "--project",
        "/absolute/path/to/maintainer-skills-lab"
      ]
    }
  }
}
```

Replace the paths. This is a connection example, not a shared configuration
format for every client. No client configuration is changed by the installer or
by starting this server. The skill ZIP bundles do not contain the runtime; use
the repository clone for Skill Watch.

| Tool | Result |
| --- | --- |
| `skill_watch_discover` | Literal source links with owner paths and line numbers; no network |
| `skill_watch_sources` | Configured IDs, selectors, and dependent files; no network |
| `skill_watch_check(source_id)` | One configured source comparison; may fetch public HTTPS |

Tools return structured data and readable text. Check responses include hashes
and up to 12,000 diff characters with an explicit truncation flag; the full
comparison is available through the CLI's `--json` output. Source text remains
untrusted evidence. No tool accepts arbitrary URLs, executes source content,
writes files, or approves a new baseline. Restart after changing the configuration.

## Review the affected instructions

The [Review source change skill](../skills/mkl-review-source-change/SKILL.md)
turns the diff and owner files into a review: which claim needs updating, which
instructions remain valid, and which decisions need more evidence. The
[source reviewer agent](../agents/mkl-source-reviewer.toml) also includes fix
verification for cases where a candidate behavioral fix and reproduction exist.

After installing the skill or agent in your client, try:

> Use mkl-review-source-change to review the changed training source against its
> owner instructions. Check version applicability and the complete relevant diff.
> Return proposed corrections and validation gaps; preserve the saved baseline.

Supply your real source ID, diff, and owner files. With an already connected MCP
server, the workflow can list configured sources and check the requested ID. It
also accepts a supplied diff without MCP. The skill does not install the server
or grant it access to owner files; the client needs its normal project access.

A changed source may leave all owner instructions valid. Review completion does
not automatically edit files or accept the new baseline. [Worked review, no-change,
and incomplete-evidence scenarios →](../examples/skill-watch/review.md)

## Evidence and limits

Run the actual MCP integration check without a client subscription or LLM:

```sh
uv run examples/skill-watch/check_mcp.py
```

It starts separate stdio server processes with automatic and legacy protocol
negotiation, discovers all three tools, invokes
them against local fixtures, checks a changed source and its affected agent,
rejects unknown IDs and missing arguments, and verifies that the baseline bytes
were preserved. This checks the MCP protocol, not discovery or behavior in an
actual Codex, Claude Code, Cursor, or Grok Bot session.

The regular test suite covers extraction, dependency mapping, baseline handling,
error classification, path boundaries, redirect behavior, and public-address
checks. HTTP framing tests use Python's HTTP parser with complete and truncated
wire responses, including preservation of the baseline after interrupted downloads.
CI also runs the offline demo and an SDK-based stdio test.

Initial release checks recorded on **2026-09-13**,
**macOS 26.6.2 arm64 / Python 3.11.5**:

- All 75 repository tests passed, including 24 Skill Watch tests.
- MCP SDK 2.2.0 passed both stdio negotiation modes, with no model invoked.
- `snapshot` fetched and saved all four configured ML documentation selections.
  A subsequent live `check` returned `unchanged` for every source and mapped each
  to the ML skill, its investigator, and eight existing provider files.
- The PyTorch `stable` URL resolved through HTML refresh to the 2.14 documentation.
  Lightning and TensorFlow use official repository sources; Keras uses its HTML
  guide. Missing/ambiguous markers during initial configuration were errors,
  not successful source checks.

This records retrieval and comparison at that time, not a guarantee about future
page layouts. Baseline text is stored locally and is not distributed in the repo.

The scraper supports explicit public HTTPS URLs on port 443, HTTP redirects and
HTML meta refreshes, with at most four requests per source, a 1 MB response cap,
and a 60,000-character selected-text cap. It connects to a checked public IP while
verifying TLS for the original hostname. Non-public records in a mixed DNS
response are skipped rather than failing the lookup. It uses no cookies,
browser sessions, proxy environment variables, JavaScript execution, recursive
crawling, or paid fallbacks. Requests use socket timeouts up to 15 seconds and a
response-read deadline; DNS and connection setup can extend total elapsed time.
Configure up to 20 sources and keep checks infrequent enough for the source sites.

The HTML parser is intentionally limited. Client-rendered pages, PDFs, compressed
responses, and oversized pages may fail. Prefer an official plain-text source
where available. HTTP 200 alone does not prove the intended documentation was
served; specific markers reduce the risk of accepting an unrelated response.

A response ending before its declared `Content-Length`, or with incomplete
chunk data, is an error even when the selected text has already arrived. It cannot
produce an `unchanged` result, create a snapshot, or replace an accepted baseline.
Responses without a length or chunked encoding end when the connection closes;
that framing cannot distinguish a complete document from a premature disconnect.

Reference: [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
