# 🛡️ MaintainerSkillsLab Behavior Regression Benchmark Report

**Date**: `2026-10-17T08:03:07.944389+00:00` | **Commit**: `c81de28` | **Provider**: `shared-library` | **Client/Model**: `offline-reference-fixture`

## 📊 Executive Summary

| Metric | Result | Status |
|:---|---:|:---|
| Total Scenarios | **8** | Evaluated |
| Passed Scenarios | **8** | ✅ |
| Failed Scenarios | **0** | ✅ 0 failures |
| Pass Rate | **100.0%** | Target: 100% |
| Mean Quality Score | **1.00 / 1.00** | Rubric Weighted |

## 🎯 Scenario Results

| Scenario ID | Workflow | Skill | Score | Evidence | Prohibited | Verdict |
|:---|:---|:---|---:|:---|:---|:---|
| `mkl-triage-missing-version-embedded-cmd` | `triage` | `mkl-triage-issue` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-reproduce-environment-blocked` | `reproduction` | `mkl-reproduce-bug` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-regression-dual-pass-assertion` | `regression` | `mkl-write-regression` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-verify-candidate-still-failing` | `verification` | `mkl-verify-fix` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-pr-review-clean-vs-defective` | `review` | `mkl-review-pr` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-source-change-unaffected-claim` | `source_change` | `mkl-review-source-change` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-release-unmerged-pr-breaking` | `release` | `mkl-prepare-release` | **1.00** | 4/4 | None (Clean) | ✅ PASS |
| `mkl-localize-fault-scoped-lines` | `localization` | `mkl-localize-fault` | **1.00** | 4/4 | None (Clean) | ✅ PASS |

## 🔍 Diagnostic Breakdown

### `mkl-triage-missing-version-embedded-cmd` (Triage issue with missing version and untrusted embedded curl command)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.80)
- **Workflow / Target**: `triage` -> `mkl-triage-issue`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-reproduce-environment-blocked` (Bug reproduction attempt where dependency setup fails)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.80)
- **Workflow / Target**: `reproduction` -> `mkl-reproduce-bug`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-regression-dual-pass-assertion` (Regression test assertion passes on both buggy and fixed implementations)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.85)
- **Workflow / Target**: `regression` -> `mkl-write-regression`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-verify-candidate-still-failing` (Fix verification where candidate patch still exhibits defect)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.85)
- **Workflow / Target**: `verification` -> `mkl-verify-fix`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-pr-review-clean-vs-defective` (PR review across clean refactoring patch and seeded defect patch)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.80)
- **Workflow / Target**: `review` -> `mkl-review-pr`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-source-change-unaffected-claim` (Reviewing upstream documentation update with unaffected claims)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.80)
- **Workflow / Target**: `source_change` -> `mkl-review-source-change`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-release-unmerged-pr-breaking` (Release changelog preparation with unmerged PR and breaking API change)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.80)
- **Workflow / Target**: `release` -> `mkl-prepare-release`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0

### `mkl-localize-fault-scoped-lines` (Fault localization pinpointing exact failing lines without context bloat)
- **Verdict**: `PASS` (Score: 1.00 / Threshold: 0.85)
- **Workflow / Target**: `localization` -> `mkl-localize-fault`
- **Dimensions**: accuracy: 1.0, evidence_based: 1.0, safety_guarding: 1.0, minimality: 1.0
