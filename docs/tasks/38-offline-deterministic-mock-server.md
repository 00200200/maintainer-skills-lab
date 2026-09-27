# [Feature] Offline Deterministic Mock Server for Skill Watch Testing

**Labels**: `enhancement`, `testing`, `good first issue`

## Context & Motivation
`Skill Watch` (`tools/skill_watch.py`) tests currently mock network behavior via custom socket or mock objects. As we add features (HTTP 304 caching, diff pruning, TLS handshake timeouts), unit tests need realistic, recorded HTTP upstream fixtures (PyTorch docs, Lightning docs) that run 100% offline with zero network variance.

## Prior Art & Industry Standards
- **VCR.py / Betamax**: Records and replays HTTP interactions for deterministic, zero-network testing.
- Standard mock servers in client SDK test suites.

## Proposed Solution
Build `tools/mock_http.py` (or recorded JSON fixtures in `tests/fixtures/http/`):
- Provides a lightweight, local HTTP server thread in tests that responds with exact recorded HTTP headers (`ETag`, `Content-Length`) and bodies.
- Allows testing DNS pinning, timeouts, 304 Not Modified, and chunked transfer encoding completely offline.

## Implementation Tasks
- [ ] Implement `MockServer` context manager in `tests/test_skill_watch.py` using standard library `http.server`.
- [ ] Add fixtures for PyTorch randomness docs and Lightning smoke test docs.
- [ ] Verify test suite runs 100% offline without network access.

## Acceptance Criteria
- Full test suite runs in isolation with network disabled (`curl` or socket blocked).
- Test execution time remains fast (< 10ms per test).
