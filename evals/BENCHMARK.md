# 📊 MaintainerSkillsLab Token & Cost Benchmark Report

Empirical benchmark evaluating token footprint, inference costs, and prompt cache hit rates
comparing unassisted baseline prompts against MaintainerSkillsLab skill-guided workflows.

| Scenario | Model | Baseline Tokens | MKL Tokens | Token Savings | Baseline Cost | MKL Cost | Cost Savings | Cache Hit Ratio |
|:---|:---|---:|---:|:---:|---:|---:|:---:|:---:|
| `bugfix` | `claude-3-7-sonnet` | 265 | 116 | **-56.2%** | $0.0021 | $0.0007 | **-69.0%** | 36.1% |
| `pr_review` | `claude-3-7-sonnet` | 1,601 | 102 | **-93.6%** | $0.0060 | $0.0006 | **-89.4%** | 44.1% |
| `cve_audit` | `claude-3-7-sonnet` | 609 | 111 | **-81.8%** | $0.0025 | $0.0008 | **-68.6%** | 45.5% |
| `multi_skill` | `claude-3-7-sonnet` | 162 | 137 | **-15.4%** | $0.0009 | $0.0007 | **-24.2%** | 28.6% |

### 📈 Aggregate Benchmark Summary

- **Total Baseline Tokens**: 2,637
- **Total MKL Assisted Tokens**: 466
- **Aggregate Token Reduction**: **82.3%**
- **Total Baseline Cost**: $0.0116
- **Total MKL Assisted Cost**: $0.0028
- **Aggregate Cost Reduction**: **75.8%**

### ⚡ KV-Cache Prefix Normalization Simulation

- **Simulated Workflow**: `mkl-triage-issue -> mkl-localize-fault -> mkl-write-regression -> mkl-review-pr` (4 turns)
- **Canonical Static Preamble**: 660 tokens (Tier 1 shared prefix)
- **Unnormalized Cross-Skill Cache Hit**: **0.0%** (0 tokens reused across skill switches)
- **Normalized Cross-Skill Cache Hit**: **32.8%** (1,980 tokens reused)
- **Estimated Time-To-First-Token (TTFT) Speedup**: **1.5x faster**
- **GPU KV-Cache Memory Reduction**: **32.8%** (shared radix tree root)

> ⚡ **Verdict**: MaintainerSkillsLab reduces prompt bloat by filtering context at the AST level,
> localizing faults before repair turns, and utilizing prompt caching across turns.
