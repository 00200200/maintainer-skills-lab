# [Feature] Pre-Review AST Security & Secret Linter (tools/pre_review_security_lint.py)

**Labels**: `enhancement`, `security`, `help wanted`

## Context & Problem
In `mkl-review-pr` and `mkl-review-source-change`, autonomous LLM reviewers are tasked with auditing pull requests for security vulnerabilities, unsafe API usage, and credential leaks.

In practice, large language models are non-deterministic, slow, and expensive when searching for needles in haystacks across large multi-file diffs. Relying purely on LLM attention to catch:
1. **Accidental secret leaks**: High-entropy API keys (OpenAI, Anthropic, AWS, GitHub tokens), private keys, or webhook URLs.
2. **Dangerous Python AST patterns**: Insecure deserialization (`pickle.loads`, `yaml.load`), remote code execution (`eval`, `exec`), command injection (`subprocess.Popen(shell=True)`), or string-formatted SQL queries.

This current approach suffers from two severe problems:
- **Excessive Token Consumption**: Prompts must include lengthy lists of security rules and anti-patterns, consuming hundreds of valuable context tokens on every invocation.
- **High False Negative Rate**: Under large diffs, attention fatigue causes LLMs to easily miss subtle hardcoded tokens or disguised shell calls.

Instead of forcing the LLM to search the entire haystack, local static analysis can scan the diff in milliseconds, flagging candidate secrets and AST anti-patterns. By passing a pre-flagged, compact `<security_preflight>` summary (30–80 tokens) directly to the LLM reviewer, the model can focus solely on contextual evaluation and triage without token bloat.

## Prior Art & Industry Standards
- **Semgrep & Bandit**: AST-based static application security testing (SAST) for Python that detects dangerous function calls and insecure defaults without runtime overhead.
- **TruffleHog & Gitleaks**: Shannon entropy and regex-based credential scanners that inspect git commit diffs for exposed secrets and tokens.
- **GitHub Advanced Security (Secret Scanning & CodeQL)**: Automated pre-flight security gates that annotate pull requests before human or AI maintainer review.

## Proposed Solution
Create a lightweight, zero-dependency Python utility `tools/pre_review_security_lint.py`:
- Pure standard library Python 3.11+ (`ast`, `re`, `math.log2`, `subprocess`, `argparse`).
- Evaluates only modified and added lines in git diffs (`+` lines) to avoid noisy legacy codebase warnings.
- Emits either human-readable terminal alerts, machine-readable JSON, or ultra-compact LLM context blocks.

```bash
# Run security preflight on staged changes
python3 tools/pre_review_security_lint.py --staged

# Run on a specific git diff or commit
git diff main...feature | python3 tools/pre_review_security_lint.py --diff -

# Output compact XML for injection into LLM review context
python3 tools/pre_review_security_lint.py --staged --compact

# Output structured JSON for CI gates
python3 tools/pre_review_security_lint.py --file src/api/routes.py --json
```

### Core Architecture & Detection Engines

```
[ Git Diff / Source Files ]
            │
            ▼
┌───────────────────────────────────────────────┐
│        tools/pre_review_security_lint.py      │
├───────────────────────┬───────────────────────┤
│ 1. Secret & Entropy   │ 2. AST Vulnerability  │
│    Scanner            │    Visitor            │
│  - Known Token Regex  │  - Dangerous calls    │
│  - Shannon Entropy    │  - shell=True checks  │
│  - PEM / Private Keys │  - Insecure loaders   │
└───────────────────────┴───────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────┐
│        Output Formatter & Token Compactor     │
├───────────────────────────────────────────────┤
│ --compact: <security_findings count="1">      │
│   src/auth.py:42 [HIGH] SEC001 shell=True     │
│ </security_findings> (~45 tokens)             │
└───────────────────────────────────────────────┘
```

#### 1. High-Entropy Secret & Key Detector
- **Deterministic Regex Matchers**:
  - GitHub Personal Access Tokens (`ghp_[A-Za-z0-9_]{36,}`, `github_pat_[A-Za-z0-9_]{82}`)
  - OpenAI API Keys (`sk-[A-Za-z0-9]{32,}`)
  - Anthropic API Keys (`sk-ant-[A-Za-z0-9\-_]{32,}`)
  - AWS Access Keys (`AKIA[0-9A-Z]{16}`)
  - Private Key Headers (`-----BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE) KEY-----`)
  - Generic Bearer / Basic auth tokens embedded in string literals.
- **Shannon Entropy Calculation**:
  - Calculates entropy $H = -\sum p(x) \log_2 p(x)$ on quoted strings $\ge 20$ characters.
  - Flags strings with $H > 4.5$ and character set diversity as potential unclassified secrets.

#### 2. AST Vulnerability Visitor (`ast.NodeVisitor`)
- **Command Injection**: `subprocess.run(..., shell=True)`, `subprocess.Popen(..., shell=True)`, `os.system(...)`, `os.popen(...)`.
- **Insecure Deserialization**: `pickle.load*`, `_pickle.load*`, `marshal.load*`, `yaml.load(..., Loader=...)` without `SafeLoader`.
- **Dynamic Code Execution**: `eval(...)`, `exec(...)`, `compile(...)` when passed variable expressions.
- **SQL Injection**: String formatting (`f"SELECT ... {var}"`, `"... %s" % var`, `"...".format(...)`) passed into `.execute(...)` calls.
- **Insecure Cryptography / Randomness**: `random.random()`, `random.choice()` used in security-sensitive symbol contexts (e.g., token, secret, salt, password generation) instead of `secrets`.
- **Temporary File Insecurity**: `mktemp()` instead of `NamedTemporaryFile()`.

#### 3. Compact LLM Output Format
When invoked with `--compact`, outputs token-optimized context suitable for insertion into `mkl-review-pr`:
```xml
<security_preflight status="FLAGGED" findings="1">
  <finding file="src/worker.py" line="58" rule="SEC002" severity="HIGH">
    subprocess.Popen with shell=True detected in run_command()
  </finding>
</security_preflight>
```
If no findings are detected, emits:
```xml
<security_preflight status="CLEAN" findings="0"/>
```
*(Consumes only 8 tokens when clean!)*

## Implementation Tasks
- [ ] Implement `tools/pre_review_security_lint.py` with pure standard library modules (`ast`, `re`, `math`, `subprocess`, `argparse`).
- [ ] Implement `DiffHunkParser` to extract modified line numbers and additions from git diff text.
- [ ] Implement `SecretScanner` with regex patterns for major cloud/AI API providers and Shannon entropy scoring.
- [ ] Implement `ASTSecurityVisitor` with rules for `shell=True`, insecure deserialization (`pickle`, `yaml`), `eval`/`exec`, and SQL formatting.
- [ ] Support CLI flags: `--diff <path_or_stdin>`, `--staged`, `--commit <ref>`, `--file <path>`, `--json`, `--compact`, `--fail-on-high`.
- [ ] Add unit tests in `tests/test_pre_review_security_lint.py` verifying true positives (flagged patterns) and false positive resilience (safe usages).
- [ ] Update `skills/mkl-review-pr/SKILL.md` and `skills/mkl-review-source-change/SKILL.md` instructions to run `pre_review_security_lint.py` during preflight inspection.

## Acceptance Criteria
- Pure standard library Python 3.11+ with zero external dependencies.
- Analyzes typical 500-line git diffs in under 50 milliseconds.
- Clean diffs emit `<security_preflight status="CLEAN" findings="0"/>` consuming $\le 10$ context tokens.
- Flaggable violations (hardcoded secrets, `shell=True`, `pickle.loads`) are reliably identified with exact file and line numbers.
- Zero false positives on idiomatic safe usages (e.g. `subprocess.run(["git", "status"], shell=False)`).
- Comprehensive unit test suite in `tests/test_pre_review_security_lint.py` passing with `python3 -m unittest discover -s tests -v`.
