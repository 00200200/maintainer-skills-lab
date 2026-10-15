# [Architecture / Protocol] MSL-Gateway: Multi-Provider MCP Gateway & Dynamic KV-Cache Streaming Daemon

**Labels**: `architecture`, `dx`, `help wanted`

## Context & Problem
MaintainerSkillsLab currently supports 11 different AI coding environments (Claude Code, Cursor, Windsurf, OpenCode, Codex, Copilot, Zed, Cline, etc.) by statically syncing files into provider-specific directories (`providers/`). While effective for file-based configuration, modern agentic coding ecosystems are rapidly converging on the **Model Context Protocol (MCP)** and real-time streaming tool standards.

Developers using Cursor, Claude Desktop, Windsurf, or terminal agents face key limitations with purely static file exports:
1. **Redundant Prompt Bloat**: Statically injecting 20+ skill manifests into system instructions consumes 10,000+ tokens on every interaction turn, whether or not those skills are relevant to the user's task.
2. **Cache Busting**: Unaligned preambles and dynamic timestamp injection invalidate provider-side KV prompt caches (such as Anthropic 5-minute Prompt Caching and OpenAI automatic prefix caching), leading to 4x higher API costs and latency.
3. **No Dynamic Telemetry or Auditing**: Maintainers lack visibility into which skills are invoked, their execution latency, and token consumption across client sessions.

MaintainerSkillsLab requires **MSL-Gateway** (`tools/gateway/`), a persistent, low-latency MCP server and protocol gateway bridging MaintainerSkillsLab into any MCP-compatible client via `stdio` and `SSE/HTTP`.

```
       ┌────────────────────────────────────────────────────────┐
       │             Client Agent (Cursor / Claude / Windsurf)  │
       └───────────────────────────┬────────────────────────────┘
                                   │  MCP JSON-RPC (stdio / SSE)
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │             MSL-Gateway Daemon (tools/gateway/)        │
       │    (Static KV-Cache Normalizer + Schema Minifier)       │
       └──────┬────────────────────┬─────────────────────┬──────┘
              │                    │                     │
              ▼                    ▼                     ▼
       ┌─────────────┐      ┌─────────────┐       ┌─────────────┐
       │ MCP Skills  │      │ MCP Tools   │       │ Token Audit │
       │ (On-Demand) │      │ (Executors) │       │ (Live Stats)│
       └─────────────┘      └─────────────┘       └─────────────┘
```

## Prior Art & Industry Benchmarks
- **Model Context Protocol (MCP) Specification**: Anthropic's open standard for exposing tools, resources, and prompts to LLM clients.
- **Anthropic Prompt Caching Guidelines**: Best practices requiring strict prefix determinism (minimum 1,024-token identical blocks) to achieve 90% cache read discounts.
- **SGLang / RadixAttention**: KV-cache sharing across concurrent agent threads using common radix tree prefix matching.

## Proposed Architecture & Components

### 1. Zero-Dependency MCP Server (`tools/gateway/server.py`)
- Standard-compliant MCP JSON-RPC 2.0 server supporting both `stdio` transport and `SSE` (Server-Sent Events) HTTP transport.
- Exposes:
  - `prompts/list` & `prompts/get`: Dynamic, on-demand invocation of maintainer skills (`mkl-triage-issue`, `mkl-review-pr`, `mkl-bump-version`).
  - `tools/list` & `tools/call`: Direct execution of lab utilities (`tools/patch_applier.py`, `tools/log_compressor.py`, `tools/strip_comments.py`).
  - `resources/list` & `resources/read`: Real-time inspection of repository guides, architecture notes, and token budgets.

### 2. Deterministic KV-Cache Normalizer (`tools/gateway/cache.py`)
- Enforces byte-level prefix invariance for all served prompts and tool schemas.
- Replaces dynamic volatile values (timestamps, session random UUIDs) with static anchors or trailing parameters so that the initial 2,048 tokens remain 100% cacheable across repeated turns.

### 3. Tool Schema Minifier (`tools/gateway/minifier.py`)
- Translates verbose JSON Schemas (which often take 400+ tokens per tool) into ultra-compact TypeScript-style signatures or minified JSON, saving 40-50% in schema overhead.

### 4. Live Token Accounting & Telemetry (`tools/gateway/telemetry.py`)
- Tracks per-session prompt tokens, completion tokens, cache hit rates, and execution runtimes.
- Exposes metrics endpoint (`/metrics`) and JSON summary command (`msl-gateway stats`).

### 5. CLI Management (`tools/gateway/cli.py`)
- Commands:
  ```bash
  # Start stdio MCP server (for Claude Desktop / Cursor config)
  python3 tools/gateway/cli.py stdio
  
  # Start HTTP/SSE gateway daemon for multi-client sharing
  python3 tools/gateway/cli.py serve --port 8765
  
  # Inspect live connection status and token savings
  python3 tools/gateway/cli.py status
  
  # Generate ready-to-use client configurations
  python3 tools/gateway/cli.py config --client [claude|cursor|windsurf]
  ```

## Implementation Tasks
- [ ] Implement MCP JSON-RPC 2.0 core protocol handler in `tools/gateway/server.py`.
- [ ] Implement tool, prompt, and resource dispatchers linking to existing MSL skills and tools.
- [ ] Implement prefix cache normalizer in `tools/gateway/cache.py`.
- [ ] Implement schema minifier in `tools/gateway/minifier.py`.
- [ ] Implement telemetry logger and stats aggregator in `tools/gateway/telemetry.py`.
- [ ] Add CLI interface in `tools/gateway/cli.py` with `stdio`, `serve`, `config`, and `status`.
- [ ] Author integration test suite in `tests/test_mcp_gateway.py` validating MCP handshake, tool calling, and cache hit determinism.
- [ ] Document setup instructions for Cursor, Claude Desktop, and VS Code in `docs/gateway.md`.

## Acceptance Criteria
- Fully conforms to MCP 1.0 JSON-RPC specification; successfully completes handshake with Claude Desktop and Cursor.
- Cache prefix normalizer ensures 100% byte-identical preamble across consecutive turns.
- Sub-15ms response latency on local tool and prompt resolution.
- Pure Python 3.11+ standard library implementation (no heavy third-party async frameworks required).
- 100% test pass rate in `tests/test_mcp_gateway.py`.
