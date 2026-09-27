# [Optimization] HTTP Caching (ETags & `If-None-Match`) in `watch_fetch.py` to Eliminate Zero-Change Token Transfers

**Labels**: `enhancement`, `optimization`, `good first issue`

## Context & Motivation
`Skill Watch` (`tools/skill_watch.py` & `tools/watch_fetch.py`) monitors upstream documentation URLs (such as PyTorch, Lightning, TensorFlow GitHub files) to detect upstream API changes.

Currently, every execution of `skill_watch.py check` or calling the MCP tool makes an unconditional HTTP GET request over the network. If the upstream doc has not changed (which is true 99% of the time during routine developer checks):
1. The full HTML/text payload is re-downloaded over HTTPS.
2. The entire text is parsed, stripped, and hashed.
3. The server and local agent spend unnecessary network bandwidth and compute.

## Prior Art & Industry Standards
- **RFC 7232 (Conditional Requests)**: Standard HTTP `ETag` / `If-None-Match` and `Last-Modified` / `If-Modified-Since` validation.
- **GitHub API Polling**: Recommends using `ETag` to preserve rate limits and avoid payload transfer when resources haven't changed (HTTP 304 Not Modified).

## Proposed Solution
Enhance `tools/watch_fetch.py` and `tools/skill_watch.py` to support **HTTP conditional requests**:
1. When a source is fetched, save its `ETag` and/or `Last-Modified` HTTP response headers alongside the baseline in `.skill-watch/baseline.json`.
2. On subsequent checks, pass `If-None-Match: <etag>` and `If-Modified-Since: <timestamp>`.
3. If the server responds with **`HTTP 304 Not Modified`**:
   - Immediately conclude that the source has not changed without downloading the response body.
   - Return `{ "status": "unchanged", "cached": True }` instantly.
   - Keep network transfer to < 500 bytes and execution latency under 100ms.

## Implementation Tasks
- [ ] Add `etag` and `last_modified` fields to baseline source records in `tools/skill_watch.py`.
- [ ] Update `fetch()` in `tools/watch_fetch.py` to accept optional `etag: str | None` and `last_modified: str | None` parameters and include appropriate HTTP headers.
- [ ] Handle `HTTP 304 Not Modified` response code cleanly in `watch_fetch.py`.
- [ ] Ensure backward compatibility with existing `baseline.json` files that lack caching headers.
- [ ] Add unit tests in `tests/test_skill_watch.py` mocking 304 Not Modified responses and verifying that no payload is processed.

## Acceptance Criteria
- Fetching an unchanged documentation source with an ETag performs a lightweight conditional GET and returns 304 Not Modified.
- Zero extra tokens or response payloads are processed when sources are unchanged.
- All existing tests in `tests/test_skill_watch.py` continue to pass.
