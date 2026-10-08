# [Optimization] Deterministic Prefix Normalization for Cross-Skill KV-Cache Sharing

**Labels**: `optimization`, `architecture`, `help wanted`

## Problem & Context
Modern high-throughput LLM inference systems (such as SGLang with RadixAttention, vLLM with PagedAttention and chunked prefill, and hosted provider caching like Anthropic Prompt Caching and OpenAI Prefix Caching) achieve low latency and up to 90% cost savings by reusing precomputed Key-Value (KV) cache pages. However, KV-cache matching requires **exact, byte-for-byte token prefix equality**.

Currently in `MaintainerSkillsLab`, each skill and agent profile defines its own frontmatter, unique introductory sentences, and varying preamble structures. When an agent switches skills (for instance, transitioning from `mkl-review-pr` to `mkl-triage-issue` or invoking `mkl-bisect-regression`), the initial prompt tokens differ immediately at token position 0.

As a result:
1. Every skill switch completely misses the KV cache, forcing inference engines to recompute 1,000 to 4,000 prompt tokens from scratch.
2. Multi-skill workflows incur severe time-to-first-token (TTFT) latency spikes.
3. GPU memory is wasted storing redundant, fragmented cache trees for disparate skills that share identical core instructions.

## Prior Art & Industry Standards
- **SGLang & RadixAttention**: Uses a radix tree to manage KV cache across concurrent and branching requests. If multiple agent prompts share an identical common prefix (even across different tasks), SGLang reuses the shared root branch in memory, dropping prefill latency to near zero.
- **vLLM Chunked Prefill & Prefix Caching**: Automatically matches and reuses KV cache blocks for identical prefix tokens across separate requests in a serving batch.
- **Anthropic Prompt Caching Guidelines**: Recommends placing static, reusable system instructions in an invariant, deterministic prefix block (>= 1,024 tokens) to guarantee cache hits across user interactions.

## Proposed Solution
Architect a deterministic prefix normalization system across `MaintainerSkillsLab` so that all skills, subagent prompts, and exported client configurations share a standardized, byte-identical prefix:

```text
Prompt Structure Across Different Skills:

┌─────────────────────────────────────────────────────────────┐
│ Tier 1: Canonical Static Preamble (Identical Byte-for-Byte) │  ◄── 100% KV Cache Hit
│ - Core Maintainer Philosophy & Code Style Rules             │      Shared across all
│ - Standard Output Formatting Contracts                      │      skills & agents
│ (Tokens 0 - 512+)                                           │
├─────────────────────────────────────────────────────────────┤
│ Tier 2: Skill-Specific Rules & Workflows                    │  ◄── Cached per skill
│ - Specific skill steps, schemas, and examples               │
│ (Tokens 513 - 1,500)                                        │
├─────────────────────────────────────────────────────────────┤
│ Tier 3: Dynamic Conversation History & User Context         │  ◄── Computed per turn
│ - Current issue description, file diffs, user instructions  │
└─────────────────────────────────────────────────────────────┘
```

### Architecture Specifications
1. **Canonical Static Preamble (`assets/canonical_preamble.md`)**:
   - Establish a shared, immutable maintainer preamble covering universal instructions (role definitions, commit standards, minimal diff guidelines, markdown formatting).
   - Designed to cross the minimum threshold for provider caching (e.g., Anthropic's 1,024 token minimum or vLLM's 16/32-token block alignment).
2. **Deterministic Layout & Whitespace Normalization**:
   - Ensure LF line endings, canonical indentation, and deterministic key sorting across all exporters in `tools/kit.py`.
   - Strip dynamic values, variable timestamps, random hashes, and client-specific order variations prior to the Tier 1 boundary.
3. **Prefix Alignment Linter in `tools/kit.py check`**:
   - Add `--cache-prefix` validation to ensure every skill and generated agent configuration begins with the exact canonical preamble byte sequence.
   - Fail CI if non-deterministic tokens or variable metadata appear before the prefix boundary.
4. **Cache Metrics in Benchmark Harness**:
   - Extend `evals/harness.py` to simulate prefix hit ratios and report estimated TTFT improvements across multi-skill sequences.

## Implementation Tasks
- [ ] Define and benchmark the static preamble in `assets/canonical_preamble.md`.
- [ ] Update `tools/kit.py` exporter to inject the canonical preamble deterministically across all client export targets (`claude`, `cursor`, `codex`, `opencode`).
- [ ] Implement `check_prefix_normalization()` in `tools/kit.py check` with automated error reporting.
- [ ] Add unit tests in `tests/test_kit.py` verifying that all exported skills match the canonical prefix byte-for-byte.
- [ ] Add cache hit simulation benchmarks in `evals/harness.py`.
- [ ] Document prefix normalization best practices in `docs/architecture.md`.

## Acceptance Criteria
- All exported skills share an identical byte-for-byte prefix of at least 512 tokens across all supported target formats.
- `python3 tools/kit.py check --cache-prefix` succeeds with zero errors.
- Unit tests verify deterministic serialization regardless of OS, platform line endings (CRLF vs LF), or filesystem traversal order.
- Documented prefix caching guarantees compatible with SGLang, vLLM, Anthropic, and OpenAI inference endpoints.
