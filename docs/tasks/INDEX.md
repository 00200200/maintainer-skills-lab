# Contributor Tasks & Usage Optimization Roadmap (39 SOTA Issues)

This roadmap contains **39 production-grade tasks and issues** designed for open-source contributors to make **Maintainer Skills Lab** state-of-the-art in:
- **Token Efficiency & Budgeting** (Repomix, Aider, Cursor)
- **Prompt Caching & KV-Cache Alignment** (Anthropic Claude Code, OpenAI, Gemini)
- **Context Pruning & Observation Masking** (SWE-bench, OpenHands)
- **Automated Prompt Optimization** (DSPy, MIPROv2, Promptfoo)
- **Multi-IDE & Agent Ecosystem Exports** (Antigravity, Windsurf, Cline, Continue, Zed, Copilot)
- **Maintainer Workflows & Sandboxing** (3-Way Merge, Conventional Commits, Git Bisect, CVE Audits)

---

## Complete Task Directory (39 Issues)

### 📈 Phase 1: Token Profiling & Budget Quality Gates
| # | Task / Issue | Category | Difficulty | Labels |
|---|---|---|---|---|
| **01** | [Token Profiler CLI command (`kit.py tokens`)](01-token-profiler-cli.md) | Token Profiling | Medium | `enhancement`, `optimization`, `help wanted` |
| **02** | [Token Budget Linter & Pre-commit Check](02-token-budget-linter-ci.md) | Quality Gates | Medium | `enhancement`, `optimization`, `help wanted` |
| **03** | [Automated Markdown Minification & Whitespace Trimming](03-markdown-minification-sync.md) | Compression | Easy | `enhancement`, `optimization`, `good first issue` |
| **04** | [Prompt Caching & KV-Cache Prefix Alignment](04-prompt-caching-kv-prefix.md) | Prompt Caching | Hard | `architecture`, `optimization`, `help wanted` |
| **05** | [Two-Tier Progressive Disclosure (Lazy Loading) for Skills](05-lazy-loading-progressive-disclosure.md) | Context Management | Hard | `enhancement`, `optimization`, `help wanted` |

### 🛠️ Phase 2: MCP, Network & Context Extraction Tools
| # | Task / Issue | Category | Difficulty | Labels |
|---|---|---|---|---|
| **06** | [Smart Diff Chunking and AST Hunk Pruning in MCP](06-mcp-diff-chunking-pruning.md) | MCP & Tooling | Medium | `enhancement`, `optimization`, `help wanted` |
| **07** | [HTTP Caching (ETags & `If-None-Match`) in `watch_fetch.py`](07-http-caching-watch-fetch.md) | Network & HTTP | Easy | `enhancement`, `optimization`, `good first issue` |
| **08** | [Scoped AST Code Extractor Tool (`tools/scope_extract.py`)](08-scoped-ast-code-extractor.md) | AST / Code Review | Medium | `enhancement`, `optimization`, `help wanted` |
| **15** | [Tail-and-Filter Command Output Compressor (`tools/log_compressor.py`)](15-log-output-compressor.md) | Log Pruning | Medium | `enhancement`, `optimization`, `help wanted` |
| **16** | [Auto-Exclude Lockfiles & Minified Blobs in Context (`tools/smart_ignore.py`)](16-smart-ignore-lockfiles.md) | Context Guard | Easy | `enhancement`, `optimization`, `good first issue` |
| **17** | [XML Semantic Tagging for Claude and Gemini Provider Bundles](17-xml-semantic-tagging-claude.md) | Prompt Engineering | Medium | `enhancement`, `optimization`, `help wanted` |
| **18** | [Observation Masking for Repeated Test Failures in Bug Repro](18-observation-masking-bug-repro.md) | Context Optimization | Medium | `enhancement`, `optimization`, `help wanted` |

### 🌐 Phase 3: SOTA IDE & Ecosystem Exporter Targets
| # | Task / Issue | Category | Difficulty | Labels |
|---|---|---|---|---|
| **09** | [Google Antigravity & Gemini CLI Exporter Target](09-antigravity-gemini-exporter.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |
| **10** | [Windsurf (Codeium Cascade) Rule & Workflow Exporter Target](10-windsurf-cascade-exporter.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |
| **19** | [File-Glob Pattern Matching for Conditional Skill Activation](19-file-glob-conditional-skills.md) | Rule Routing | Medium | `enhancement`, `optimization`, `help wanted` |
| **20** | [PageRank AST-Based Symbol Map for Skill Workflows (`tools/repomap.py`)](20-pagerank-ast-repomap.md) | Global Context | Hard | `enhancement`, `optimization`, `help wanted` |
| **21** | [Role-Specific Subagent Isolation (Modular Agent Profiles)](21-modular-subagent-profiles.md) | Agent Architecture | Hard | `architecture`, `optimization`, `help wanted` |
| **29** | [Cline & Roo Code Custom Modes Exporter (`.roomodes`)](29-cline-roomodes-exporter.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |
| **30** | [Continue.dev Slash Command & Prompt Generator (`.continue/prompts`)](30-continue-dev-exporter.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |
| **31** | [GitHub Copilot Workspace & Instructions Exporter (`.github/copilot-instructions.md`)](31-copilot-instructions-exporter.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |
| **32** | [Zed Editor Slash Commands & Assistant Support (`.zed/`)](32-zed-editor-slash-commands.md) | Client Ecosystem | Easy | `enhancement`, `good first issue` |

### ⚡ Phase 4: SOTA Maintainer Skills & Git Workflows
| # | Task / Issue | Category | Difficulty | Labels |
|---|---|---|---|---|
| **11** | [New Skill: `mkl-prune-context` (Session Compactor)](11-skill-mkl-prune-context.md) | Session Pruning | Medium | `enhancement`, `new skill`, `help wanted` |
| **12** | [Output Token Budget Constraints across Writing Skills](12-output-token-budget-writing-skills.md) | Prompt Engineering | Easy | `documentation`, `optimization`, `good first issue` |
| **22** | [Three-Way Minimal Git Conflict Solver Skill (`mkl-resolve-merge-conflict`)](22-skill-mkl-resolve-merge-conflict.md) | Git Automation | Medium | `enhancement`, `new skill`, `help wanted` |
| **23** | [Token-Budgeted Conventional Commit Message Generator (`mkl-generate-commit`)](23-skill-mkl-generate-commit.md) | Git Automation | Easy | `enhancement`, `new skill`, `good first issue` |
| **24** | [Token-Optimized Security & CVE Dependency Auditor (`mkl-audit-cve`)](24-skill-mkl-audit-cve.md) | Security | Medium | `enhancement`, `new skill`, `help wanted` |
| **25** | [Automated PR Description & Changelog Generator with Strict Bounds](25-skill-mkl-generate-changelog.md) | Release Automation | Easy | `enhancement`, `new skill`, `good first issue` |
| **33** | [`mkl-bisect-regression` — Token-Efficient Git Bisect Automator](33-skill-mkl-bisect-regression.md) | Debugging | Medium | `enhancement`, `new skill`, `help wanted` |
| **34** | [`mkl-profile-performance` — Python CPU & Memory Profiler Interpreter](34-skill-mkl-profile-performance.md) | Performance | Medium | `enhancement`, `new skill`, `help wanted` |
| **35** | [PyTorch / CUDA Shape & NaN Diagnosis Minifier in `mkl-debug-ml-training`](35-pytorch-nan-traceback-minifier.md) | ML Debugging | Medium | `enhancement`, `optimization`, `help wanted` |
| **36** | [Fast Local Test Runner Hook with `pytest -q --tb=short` Defaults](36-fast-pytest-defaults.md) | Testing | Easy | `enhancement`, `optimization`, `good first issue` |

### 🔬 Phase 5: Automated Prompt Optimization, Evals & Security
| # | Task / Issue | Category | Difficulty | Labels |
|---|---|---|---|---|
| **13** | [Automated Token Usage & Cost Benchmark Runner (`evals/harness.py`)](13-evals-token-benchmark-harness.md) | Evals & Benchmarks | Hard | `enhancement`, `optimization`, `help wanted` |
| **14** | [Contributor Guide for Token Optimization & Issue Templates](14-contributor-guide-optimization-template.md) | DX & Templates | Easy | `documentation`, `good first issue` |
| **26** | [DSPy-Style Automated Skill Few-Shot Optimizer (`tools/optimize_skill.py`)](26-dspy-skill-optimizer.md) | Prompt Optimization | Hard | `enhancement`, `optimization`, `help wanted` |
| **27** | [Prompt Drift & Token Regression Detector in GitHub Actions](27-ci-token-regression-detector.md) | CI / Regression | Medium | `enhancement`, `optimization`, `help wanted` |
| **28** | [Structured JSON Schemas with Minimal Error Retries for Triage Skills](28-structured-json-pydantic-schemas.md) | Structured Output | Medium | `enhancement`, `optimization`, `help wanted` |
| **37** | [Agent Safety & Command Sandbox Classifier Tool (`tools/sandbox_check.py`)](37-agent-safety-sandbox-classifier.md) | Safety & Sandboxing | Medium | `enhancement`, `security`, `help wanted` |
| **38** | [Offline Deterministic Mock Server for Skill Watch Testing](38-offline-deterministic-mock-server.md) | Test Infrastructure | Easy | `enhancement`, `testing`, `good first issue` |
| **39** | [Interactive Terminal Dashboard & Skill Manager (`tools/dashboard.py`)](39-interactive-token-dashboard-tui.md) | Terminal UI | Easy | `enhancement`, `dx`, `good first issue` |

---

## How to Publish Issues to GitHub

Publish these issues directly using the built-in publishing utility:

```bash
# Preview all 39 issues (Dry Run)
python3 tools/publish_issues.py --dry-run

# Publish a single issue (e.g. Issue 20 - PageRank AST RepoMap)
python3 tools/publish_issues.py --issue 20 --publish

# Publish all 39 issues to GitHub
python3 tools/publish_issues.py --publish
```
