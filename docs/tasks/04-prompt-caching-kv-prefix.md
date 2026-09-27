# [Architecture] Prompt Caching & KV-Cache Prefix Alignment in Multi-Client Exporter

**Labels**: `architecture`, `optimization`, `help wanted`

## Context & Motivation
Modern LLM inference engines (Anthropic Claude 3.5/3.7, OpenAI GPT-4o, Google Gemini 2.0) offer **Prompt Caching** (KV-Cache reuse). When an identical prompt prefix is sent across multiple conversational turns or across requests, the provider reuses the precomputed key-value pairs.

This delivers:
- **Up to 90% cost savings** on cached input tokens.
- **Up to 80% lower time-to-first-token (TTFT)**.

However, prompt caching relies on **exact byte-for-byte prefix matching**. If generated agent files or skill bundles have non-deterministic ordering, dynamic metadata (timestamps, versions), or interleave dynamic user text before static skills, the entire cache is invalidated on every turn!

## Prior Art & Industry Standards
- **Claude Code Architecture**: Orders static system instructions first, followed by static tool definitions, static project rules (`CLAUDE.md`), and only then places dynamic turn history and user messages.
- **Aider Cache Warming**: Places repository maps and system instructions in a deterministic, cache-stable prefix block to maximize cache hits.
- **Anthropic Prompt Caching Guide**: Recommends keeping static prompt sections >= 1024 tokens and maintaining absolute order across interactions.

## Proposed Solution
Re-architect `tools/kit.py` agent generation and client exports to ensure **KV-cache friendliness**:
1. **Deterministic Ordering**: Ensure skills embedded in agent profiles (`.claude/agents/*.md`, `.codex/agents/*.toml`, `.cursor/agents/*.md`) are always sorted deterministically (by canonical skill name), never by variable filesystem iteration.
2. **Static Prefix Separation**: Separate static core instructions from variable session parameters or dynamic client configs.
3. **Cache Breakpoint Markers**: Where client formats support it (e.g. Claude Code / Anthropic API format), add explicit cache control markers (`"cache_control": {"type": "ephemeral"}`) at the boundary between static skills and dynamic prompt zones.
4. **Cache-Friendly Linting**: Add a check in `tools/kit.py check` to verify that exported files contain zero variable timestamps or non-deterministic structures.

## Implementation Tasks
- [ ] Audit `export_agents()` in `tools/kit.py` to guarantee strict lexical sorting of skills and tools.
- [ ] Ensure no dynamic timestamps or volatile metadata are written into generated export files.
- [ ] Add support for Claude Code / Anthropic prompt caching headers in exported agent configs.
- [ ] Add a `check_cache_friendliness()` method in `tools/kit.py check`.
- [ ] Add unit tests verifying byte-for-byte reproducibility of exported agents across different machines and filesystem orderings.

## Acceptance Criteria
- Running `python3 tools/kit.py sync` produces byte-for-byte deterministic output regardless of OS or filesystem order.
- Generated Claude Code and Cursor agent profiles are structured with static skill definitions strictly ahead of variable instructions.
- All unit tests pass.
