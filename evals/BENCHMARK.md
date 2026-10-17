# 📊 MaintainerSkillsLab Token & Cost Benchmark Report

Empirical benchmark evaluating token footprint, inference costs, and prompt cache hit rates
comparing unassisted baseline prompts against MaintainerSkillsLab skill-guided workflows.

| Scenario | Model | Baseline Tokens | MKL Tokens | Token Savings | Baseline Cost | MKL Cost | Cost Savings | Cache Hit Ratio |
|:---|:---|---:|---:|:---:|---:|---:|:---:|:---:|
| `bugfix` | `claude-3-7-sonnet` | 265 | 116 | **-56.2%** | $0.0021 | $0.0007 | **-69.0%** | 36.1% |
| `pr_review` | `claude-3-7-sonnet` | 1,601 | 102 | **-93.6%** | $0.0060 | $0.0006 | **-89.4%** | 44.1% |
| `cve_audit` | `claude-3-7-sonnet` | 609 | 111 | **-81.8%** | $0.0025 | $0.0008 | **-68.6%** | 45.5% |

### 📈 Aggregate Benchmark Summary

- **Total Baseline Tokens**: 2,475
- **Total MKL Assisted Tokens**: 329
- **Aggregate Token Reduction**: **86.7%**
- **Total Baseline Cost**: $0.0106
- **Total MKL Assisted Cost**: $0.0021
- **Aggregate Cost Reduction**: **80.3%**

> ⚡ **Verdict**: MaintainerSkillsLab reduces prompt bloat by filtering context at the AST level,
> localizing faults before repair turns, and utilizing prompt caching across turns.
