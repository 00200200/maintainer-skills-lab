# [RFC/Performance] Native Rust Engine for Ultra-Fast Token Hashing & Minification (msl-core)

**Labels**: `rfc`, `performance`, `help wanted`

## Context & Problem
As MaintainerSkillsLab scales from a collection of skills to an ecosystem supporting dozens of agent profiles, enterprise repositories with 10,000+ files, and continuous pre-commit / CI verification, pure Python operations are encountering latency bottlenecks:
1. **Token Counting Overhead**: Auditing token footprints across thousands of markdown, JSON, and source files using Python loops and regex estimators takes 3 to 10 seconds in CI pipelines.
2. **Markdown Minification & Synchronization**: Parsing Markdown ASTs, stripping redundant whitespace, normalizing lists, and compiling across multiple client targets (`.claude/`, `.cursor/`, `.codex/`) introduces perceptible lag during `kit.py sync`.
3. **Symbol Extraction & Graph Centrality**: Symbol scanning and PageRank calculation on large codebases can take 15+ seconds in pure Python.

Modern developer tooling (Ruff, uv, Ripgrep, Biome, Turborepo) has proven that rewriting hot-loop core primitives in Rust delivers 50x–100x speedups, instant developer feedback, and strong thread-safe concurrency.

## Prior Art & Industry Standards
- **Ruff (Astral)**: Replaced Flake8, Black, and isort with a unified Rust engine, executing 100x faster and eliminating developer lint friction.
- **uv (Astral)**: Ultra-fast Python package resolution and virtual environment management in Rust.
- **tiktoken-rs**: High-throughput BPE tokenizer implementation in Rust capable of processing gigabytes of text per second.
- **PyO3 & Maturin**: Industry standard for building and distributing native Rust extensions for Python with zero runtime overhead and pre-built multi-platform wheels.

## Proposed Solution
Introduce `msl-core`, a native Rust extension with Python bindings via PyO3, packaged in `crates/msl-core/`. MaintainerSkillsLab will import `msl_core` when present, while retaining 100% feature-complete pure Python fallbacks when the native extension is not installed.

### Architecture & Engine Components
1. **Zero-Dependency Fallback Principle**:
   - `MaintainerSkillsLab` must remain fully operational on vanilla Python 3.11+ without compilation tools.
   - Core Python modules (`kit.py`, `token_diff.py`, `budget_allocator.py`) use conditional imports:
     ```python
     try:
         import msl_core
         HAS_RUST_CORE = True
     except ImportError:
         HAS_RUST_CORE = False
     ```

2. **Native Rust Engine Modules (`crates/msl-core/`)**:
   - `msl_core::tokens`:
     - SIMD-accelerated character heuristic estimator (~4 chars/token).
     - Native BPE tokenization using `tiktoken-rs` for `cl100k_base` and `o200k_base`.
     - Parallel directory scanner processing 10,000 files in under 20ms using `rayon`.
   - `msl_core::minify`:
     - High-speed zero-allocation CommonMark minifier based on `pulldown-cmark`.
     - Strips redundant whitespace, HTML comment blocks, and extra line breaks while preserving code block integrity.
   - `msl_core::hasher`:
     - Fast incremental xxHash64 / BLAKE3 cache generator to skip unchanged files during `kit.py sync`.
   - `msl_core::symbols`:
     - Fast symbol identification using Tree-sitter for instant repository symbol mapping.

3. **Packaging & Build Setup**:
   - Build system: `maturin` and `setuptools-rust`.
   - Python type stubs (`msl_core.pyi`) for full type-safety in IDEs.
   - Automated GitHub Actions workflow using `maturin-action` to build wheels across Linux (x86_64, aarch64), macOS (x86_64, Apple Silicon), and Windows.

4. **Performance Target**:
   - Benchmark: Auditing and minifying 1,000 Markdown files:
     - Pure Python baseline: ~2,800 ms
     - `msl-core` Rust target: < 35 ms (> 80x speedup).

## Implementation Tasks
- [ ] Draft detailed RFC specification covering C-API/PyO3 boundaries and memory management.
- [ ] Initialize `crates/msl-core` with `Cargo.toml`, `pyo3`, and `tiktoken-rs` dependencies.
- [ ] Implement `msl_core::tokens::count_tokens(text: &str, encoding: &str) -> usize`.
- [ ] Implement `msl_core::minify::minify_markdown(text: &str) -> String`.
- [ ] Implement `msl_core::hasher::hash_file(path: &str) -> u64`.
- [ ] Generate Python type stub file `msl_core.pyi`.
- [ ] Wire optional Rust acceleration into `tools/kit.py` with seamless pure Python fallback.
- [ ] Setup `maturin` build configuration and GitHub Actions cross-compilation pipeline.
- [ ] Add benchmark suite comparing Python vs. Rust performance on sample repositories.

## Acceptance Criteria
- MaintainerSkillsLab runs seamlessly on vanilla Python without `msl_core` installed (zero breaking changes for existing users).
- When `msl-core` is compiled/installed, `kit.py tokens` and `kit.py sync` automatically leverage the Rust engine.
- Token counting and minification benchmarks demonstrate > 10x throughput improvement over pure Python baseline.
- All Python and Rust test suites pass cleanly across macOS, Linux, and Windows.
