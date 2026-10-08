# [Feature] MCP Resource Provider for Dynamic Skill & Doc Delivery (tools/mcp_resource_server.py)

**Labels**: `enhancement`, `optimization`, `help wanted`

## Problem & Context
When configuring AI coding agents in environments that support the Model Context Protocol (MCP)—such as Claude Desktop, Cursor, Continue, and Windsurf—maintainers commonly dump entire skill workflows, reference manuals, and project documentation directly into the system prompt or static instructions.

With 17+ specialized skills and comprehensive maintainer guidelines, this upfront injection bloats the base prompt by 15,000 to 25,000+ tokens on every single turn. An agent tasked with a straightforward task like `mkl-generate-commit` or formatting a changelog is burdened with thousands of irrelevant tokens describing PyTorch NaN debugging, CVE audit matrices, and complex git bisect state machines. This wasteful bloat inflates latency, drains user token allowances, and dilutes model focus.

## Prior Art & Industry Standards
- **Anthropic Model Context Protocol (MCP)**: The official MCP specification separates server capabilities into:
  - **Tools** (`tools/call`): Executable functions that perform side-effects or computations.
  - **Prompts** (`prompts/get`): Slash-command templates for user-initiated workflows.
  - **Resources** (`resources/list`, `resources/read`): Static or dynamic content sources that agents and hosts can discover lazily and inspect on demand using standardized URIs (`protocol://path`).
- **Claude Desktop & Zed MCP Resource Integrations**: Host environments index available resources as lightweight metadata (< 200 tokens) and only load the full resource body when explicitly referenced by the agent or user.

## Proposed Solution
Build `tools/mcp_resource_server.py`, a zero-dependency, standard-library MCP server implementing dynamic resource delivery for all MaintainerSkillsLab skills and documentation:

```text
Host Environment (Claude Desktop / Cursor / Zed)
                     │
    1. resources/list│ (Returns ~150 tokens: URIs & titles)
                     ▼
┌────────────────────────────────────────────────────────┐
│  tools/mcp_resource_server.py                          │
│  - URI: mkl://skills/mkl-review-pr                     │
│  - URI: mkl://skills/mkl-triage-issue                  │
│  - URI: mkl://docs/architecture                        │
└────────────────────┬───────────────────────────────────┘
                     │
    2. resources/read│ (Fetches on demand when needed)
                     ▼
  Agent loads ONLY relevant skill content into context
```

### Architecture Details
1. **Lightweight JSON-RPC 2.0 stdio Implementation**:
   - Implemented in pure Python 3.11+ using standard library `sys.stdin`, `sys.stdout`, and `json` (no heavy third-party framework dependencies required).
   - Handles standard MCP lifecycle methods: `initialize`, `notifications/initialized`, and `ping`.
2. **Resource Protocol Specification**:
   - `resources/list`: Returns an array of available skills and documentation files with their canonical URI, name, MIME type (`text/markdown`), and a 1-sentence description. Total footprint: < 200 tokens.
   - `resources/read`: Resolves URIs such as `mkl://skills/{skill_name}` and `mkl://docs/{doc_name}`, streaming the exact markdown content on demand.
3. **MCP Prompts Protocol Integration**:
   - Implements `prompts/list` and `prompts/get`, enabling users in MCP-aware editors to invoke skills directly via slash prompts (e.g. `/mkl-review-pr`).
4. **Client Config Generation in `tools/kit.py`**:
   - Add export target `--target mcp` to generate plug-and-play configuration blocks for `claude_desktop_config.json`, `.cursor/mcp.json`, and Continue configuration files.

## Implementation Tasks
- [ ] Implement `tools/mcp_resource_server.py` supporting MCP JSON-RPC 2.0 protocol over stdio.
- [ ] Implement `resources/list` handler indexing all skills from `skills/` and guides from `docs/`.
- [ ] Implement `resources/read` handler with URI routing and path-traversal security guards.
- [ ] Implement `prompts/list` and `prompts/get` mapping skills to slash-command templates.
- [ ] Add `--target mcp` to `tools/kit.py` to emit client configuration snippets.
- [ ] Add integration tests in `tests/test_mcp_resource_server.py` exercising JSON-RPC handshakes, resource listing, and URI reading.
- [ ] Add setup guide in `docs/mcp_setup.md` detailing integration with Claude Desktop, Cursor, and Zed.

## Acceptance Criteria
- Server complies with MCP 2024-11-05+ specification over stdio.
- Initial context footprint for skill discovery in MCP clients is reduced from >15,000 tokens to under 200 tokens.
- Path traversal attacks (e.g., `mkl://skills/../../etc/passwd`) are strictly blocked and return standard JSON-RPC error codes.
- Pure Python 3.11+ without third-party package dependencies.
- All unit tests pass (`python3 -m unittest discover -s tests -v`).
