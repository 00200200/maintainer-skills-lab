# [Architecture / Graph] MSL-Graph: Distributed Codebase Knowledge Graph & Cross-Session Memory Engine (SQLite-vec & AST Entity Linking)

**Labels**: `architecture`, `optimization`, `help wanted`

## Context & Problem
In production software maintenance workflows, agentic coding models (such as Claude 3.7 Sonnet, OpenAI o3-mini, and DeepSeek-R1) spend **60% to 80% of their total token budget** purely exploring and rediscovering the repository's architecture across successive turns. When tasked with fixing a bug or reviewing a pull request, an agent typically greps for symbol names, reads full directory trees, and opens entire modules just to understand:
1. Which functions or classes call a specific API?
2. What interfaces or type signatures govern the inputs/outputs?
3. Which unit and integration test files exercise this code path?
4. What architectural layers (domain, service, database) surround the change?

Furthermore, when a conversation context window resets or compacts, all accumulated architectural awareness is lost, forcing the agent to repeat the entire costly discovery process from scratch.

To solve this fundamentally, MaintainerSkillsLab requires **MSL-Graph** (`tools/graph/`), a zero-dependency, local SQLite-backed knowledge graph and memory engine that builds an AST entity graph of the repository, links callers/callees and test coverage, and provides sub-5ms graph traversals that return compact, token-bounded architectural context (< 150 tokens) to coding agents.

```
       ┌────────────────────────────────────────────────────────┐
       │                   Repository Sources                  │
       │           (Python, TypeScript, Rust, Go)              │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │             AST Entity & Hierarchy Extractor           │
       │    (Symbols, Imports, Callers, Interfaces, Tests)     │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │              MSL-Graph Local Database                  │
       │   (SQLite relational schema + FTS5 + Vec Embeddings)   │
       └──────────────┬──────────────────────────┬──────────────┘
                      │                          │
                      ▼                          ▼
       ┌────────────────────────┐      ┌────────────────────────┐
       │  Token-Bounded Queries │      │  Cross-Session Memory  │
       │   `msl-graph query`    │      │  (Entity Recall & Log) │
       │    (< 150 tokens)      │      │     (< 50 tokens)      │
       └────────────────────────┘      └────────────────────────┘
```

## Prior Art & Industry Benchmarks
- **Sourcegraph SCIP / LSIF**: Standard Code Intelligence Protocol for precise code navigation and cross-repo dependency graphs.
- **Augment Code / Cursor Codebase Indexing**: Proprietary local graph indexers that resolve call-graph hops and type definitions before querying LLMs.
- **Aider RepoMap**: Tree-sitter / Pygments PageRank map of definitions, but lacks relational call hierarchies, test linking, and cross-session persistent memory.
- **SQLite-vec / SQLite FTS5**: Blazing-fast, embedded vector search and full-text search running entirely within standard Python environments without external services.

## Proposed Architecture & Components

### 1. AST Entity & Relation Extractor (`tools/graph/extractor.py`)
- Zero-dependency Python AST parser (with extensible grammars for TypeScript/JavaScript, Rust, and Go via standard regex/token scanners).
- Extracts entities:
  - `modules`: Path, docstring summary, exports.
  - `classes`: Base classes, implemented interfaces, methods, class docstrings.
  - `functions`: Signature, return type, parameters, decorators, called symbols.
  - `tests`: Test functions and the source symbols they instantiate or invoke.
  - `imports`: Directed edges between files (`A imports B`).

### 2. Embedded Graph Storage (`tools/graph/storage.py`)
- Backed by a single lightweight file (`.msl/graph.sqlite3`).
- Relational schema:
  - `nodes(id, kind, name, qualified_name, file_path, line_start, line_end, signature, docstring_summary)`
  - `edges(source_id, target_id, relation_type)` (`CALLS`, `IMPORTS`, `INHERITS`, `TESTS`, `DEFINES`)
  - `memory_logs(id, session_id, entity_name, note, created_at, decay_score)`
- Indexed with SQLite FTS5 for instant sub-millisecond lexical queries and optional 64-dim binary/quantized cosine vectors for semantic search.

### 3. Graph Traversal & Query CLI (`tools/graph/cli.py`)
- CLI command:
  ```bash
  # Query callers and callee graph of a function
  python3 tools/graph/cli.py query "callers of validate_token_budget"
  
  # Find tests covering a module
  python3 tools/graph/cli.py tests --file tools/patch_applier.py
  
  # Analyze blast radius / impact of modifying a symbol
  python3 tools/graph/cli.py impact --symbol SearchReplacePatch
  
  # Output token-bounded markdown context for LLM prompt injection
  python3 tools/graph/cli.py context --symbol apply_patch_string --max-tokens 200
  ```

### 4. Cross-Session Memory & Entity Recall
- Allows agents to record concise architectural facts learned during investigations:
  ```bash
  python3 tools/graph/cli.py remember --entity "TokenDiff" --note "Base token calculation skips new skills by design"
  python3 tools/graph/cli.py recall --query "TokenDiff"
  ```
- Incorporates a half-life decay score so obsolete notes from weeks ago naturally derank.

### 5. New Maintainer Skill (`skills/mkl-query-code-graph/SKILL.md`)
- Teaches coding agents to run targeted graph queries before opening files.
- Replaces 10,000-token directory scans with 150-token precise subgraph outputs.

## Implementation Tasks
- [ ] Implement AST entity extractor in `tools/graph/extractor.py` for Python standard library AST.
- [ ] Design relational SQLite schema with FTS5 in `tools/graph/storage.py`.
- [ ] Implement incremental graph updates (inspecting git commit delta or file mtimes so re-indexing takes < 100ms).
- [ ] Implement graph traversal algorithms (BFS/DFS k-hop neighborhood, PageRank centrality, impact blast radius) in `tools/graph/traversal.py`.
- [ ] Implement CLI with `query`, `impact`, `tests`, `context`, `remember`, and `recall` subcommands in `tools/graph/cli.py`.
- [ ] Author canonical maintainer skill `skills/mkl-query-code-graph/SKILL.md` (< 60 tokens description, < 800 tokens body).
- [ ] Add unit and benchmark tests in `tests/test_code_graph.py` verifying sub-5ms query latency and accurate edge extraction.
- [ ] Document architecture, schema, and performance benchmarks in `docs/architecture/graph.md`.

## Acceptance Criteria
- Extracts 100% of classes, functions, calls, and imports across MaintainerSkillsLab within 500ms.
- Incremental updates upon single-file edits complete in < 50ms.
- Subgraph context generator emits valid Markdown adhering strictly to `--max-tokens` constraint.
- Zero external runtime dependencies beyond Python 3.11+ standard library (`sqlite3`, `ast`, `re`, `pathlib`).
- 100% test pass rate in `tests/test_code_graph.py`.
