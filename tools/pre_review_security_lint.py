#!/usr/bin/env python3
"""tools/pre_review_security_lint.py - Pre-Review AST Security & Secret Linter.

Audits git diffs or source files for secret leaks and dangerous AST anti-patterns
in milliseconds, emitting ultra-compact summaries for LLM review skills.

Standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

# =============================================================================
# Secret Signatures & Entropy Heuristics
# =============================================================================

KNOWN_SECRET_PATTERNS = [
    (
        "SEC_SECRET_GH",
        "HIGH",
        "GitHub Token",
        re.compile(r"(?:ghp_[A-Za-z0-9_]{36,}|github_pat_[A-Za-z0-9_]{82})"),
    ),
    ("SEC_SECRET_OAI", "HIGH", "OpenAI API Key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("SEC_SECRET_ANT", "HIGH", "Anthropic API Key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{32,}")),
    ("SEC_SECRET_AWS", "HIGH", "AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "SEC_SECRET_PEM",
        "HIGH",
        "Private Key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ),
    (
        "SEC_SECRET_SLACK",
        "HIGH",
        "Slack Token / Webhook",
        re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,32}"),
    ),
]

# Exclude obvious non-secret dummy tokens used in fixtures and test suites
SAFE_TOKEN_PATTERNS = [
    re.compile(r"^[xX0\-_]+$"),
    re.compile(r"example|placeholder|dummy|test_token|fake|your[-_]?key", re.IGNORECASE),
]


def shannon_entropy(data: str) -> float:
    """Calculates Shannon entropy in bits per character."""
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def is_high_entropy_secret(token_candidate: str) -> bool:
    """Detects likely unclassified API tokens / credentials by Shannon entropy."""
    if len(token_candidate) < 24:
        return False
    # Must not contain whitespace
    if any(c.isspace() for c in token_candidate):
        return False
    # Check against safe placeholders
    for safe in SAFE_TOKEN_PATTERNS:
        if safe.search(token_candidate):
            return False
    # Must have character set diversity (letters and numbers)
    has_lower = any(c.islower() for c in token_candidate)
    has_upper = any(c.isupper() for c in token_candidate)
    has_digit = any(c.isdigit() for c in token_candidate)
    if not ((has_lower and has_digit) or (has_upper and has_digit)):
        return False

    entropy = shannon_entropy(token_candidate)
    return entropy >= 4.5


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class SecurityFinding:
    file_path: str
    line: int
    rule: str
    severity: str  # HIGH, MEDIUM, LOW
    message: str
    snippet: str = ""


# =============================================================================
# AST Security Visitor
# =============================================================================


class ASTSecurityVisitor(ast.NodeVisitor):
    """Inspects Python AST for security-sensitive API misuses."""

    def __init__(self, file_path: str, target_lines: set[int] | None = None) -> None:
        self.file_path = file_path
        self.target_lines = target_lines
        self.findings: list[SecurityFinding] = []

    def _should_report(self, lineno: int) -> bool:
        if self.target_lines is None:
            return True
        return lineno in self.target_lines

    def visit_Call(self, node: ast.Call) -> None:
        self._check_subprocess_shell(node)
        self._check_os_execution(node)
        self._check_insecure_deserialization(node)
        self._check_dynamic_code(node)
        self._check_sql_injection(node)
        self._check_insecure_tempfile(node)
        self.generic_visit(node)

    def _check_subprocess_shell(self, node: ast.Call) -> None:
        """Detects subprocess.* calls with shell=True."""
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"run", "Popen", "call", "check_call", "check_output"}:
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    if self._should_report(node.lineno):
                        self.findings.append(
                            SecurityFinding(
                                file_path=self.file_path,
                                line=node.lineno,
                                rule="SEC001",
                                severity="HIGH",
                                message=f"Dangerous command injection: `subprocess.{func_name}` with `shell=True`.",
                            )
                        )

    def _check_os_execution(self, node: ast.Call) -> None:
        """Detects os.system or os.popen calls."""
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "os" and node.func.attr in {"system", "popen"}:
                if self._should_report(node.lineno):
                    self.findings.append(
                        SecurityFinding(
                            file_path=self.file_path,
                            line=node.lineno,
                            rule="SEC002",
                            severity="HIGH",
                            message=f"Command injection risk: `os.{node.func.attr}` executes shell directly.",
                        )
                    )

    def _check_insecure_deserialization(self, node: ast.Call) -> None:
        """Detects unsafe pickle or yaml.load calls."""
        func_str = ""
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            func_str = f"{node.func.value.id}.{node.func.attr}"

        if func_str in {
            "pickle.loads",
            "pickle.load",
            "_pickle.loads",
            "_pickle.load",
            "marshal.loads",
            "marshal.load",
        }:
            if self._should_report(node.lineno):
                self.findings.append(
                    SecurityFinding(
                        file_path=self.file_path,
                        line=node.lineno,
                        rule="SEC003",
                        severity="HIGH",
                        message=f"Insecure deserialization: `{func_str}` allows arbitrary remote code execution.",
                    )
                )

        if func_str == "yaml.load":
            # Check if Loader is explicitly SafeLoader
            has_safe_loader = False
            for kw in node.keywords:
                if kw.arg == "Loader":
                    if isinstance(kw.value, ast.Attribute) and kw.value.attr in {
                        "SafeLoader",
                        "CSafeLoader",
                    }:
                        has_safe_loader = True
            if not has_safe_loader and self._should_report(node.lineno):
                self.findings.append(
                    SecurityFinding(
                        file_path=self.file_path,
                        line=node.lineno,
                        rule="SEC003",
                        severity="HIGH",
                        message="Insecure YAML deserialization: `yaml.load` without `SafeLoader`.",
                    )
                )

    def _check_dynamic_code(self, node: ast.Call) -> None:
        """Detects eval/exec on variable expressions."""
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

        if func_name in {"eval", "exec"}:
            if node.args and not isinstance(node.args[0], ast.Constant):
                if self._should_report(node.lineno):
                    self.findings.append(
                        SecurityFinding(
                            file_path=self.file_path,
                            line=node.lineno,
                            rule="SEC004",
                            severity="HIGH",
                            message=f"Arbitrary dynamic code execution: `{func_name}()` evaluated on dynamic expression.",
                        )
                    )

    def _check_sql_injection(self, node: ast.Call) -> None:
        """Detects formatted strings passed into database .execute() calls."""
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany"}:
            if node.args:
                first_arg = node.args[0]
                is_formatted = False
                if isinstance(first_arg, ast.JoinedStr):  # f-string
                    is_formatted = True
                elif isinstance(first_arg, ast.BinOp) and isinstance(
                    first_arg.op, ast.Mod
                ):  # % format
                    is_formatted = True
                elif isinstance(first_arg, ast.Call) and isinstance(first_arg.func, ast.Attribute):
                    if first_arg.func.attr == "format":  # .format()
                        is_formatted = True

                if is_formatted and self._should_report(node.lineno):
                    self.findings.append(
                        SecurityFinding(
                            file_path=self.file_path,
                            line=node.lineno,
                            rule="SEC005",
                            severity="MEDIUM",
                            message=f"SQL injection risk: string-interpolated query passed to `.{node.func.attr}()`.",
                        )
                    )

    def _check_insecure_tempfile(self, node: ast.Call) -> None:
        """Detects mktemp usage."""
        func_str = ""
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            func_str = f"{node.func.value.id}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            func_str = node.func.id

        if func_str in {"tempfile.mktemp", "mktemp"}:
            if self._should_report(node.lineno):
                self.findings.append(
                    SecurityFinding(
                        file_path=self.file_path,
                        line=node.lineno,
                        rule="SEC006",
                        severity="MEDIUM",
                        message="Insecure temporary file: `mktemp()` is vulnerable to symlink race conditions.",
                    )
                )

    def visit_Assign(self, node: ast.Assign) -> None:
        """Detects insecure randomness used for security credentials."""
        var_names = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_names.append(target.id.lower())

        security_words = {"token", "secret", "salt", "passwd", "password", "api_key", "nonce"}
        is_security_var = any(any(sw in vn for sw in security_words) for vn in var_names)

        if is_security_var and isinstance(node.value, ast.Call):
            call_str = ""
            if isinstance(node.value.func, ast.Attribute) and isinstance(
                node.value.func.value, ast.Name
            ):
                call_str = f"{node.value.func.value.id}.{node.value.func.attr}"
            if call_str in {"random.random", "random.choice", "random.randint", "random.randrange"}:
                if self._should_report(node.lineno):
                    self.findings.append(
                        SecurityFinding(
                            file_path=self.file_path,
                            line=node.lineno,
                            rule="SEC007",
                            severity="MEDIUM",
                            message=f"Weak PRNG for credentials: `{call_str}` used for sensitive variable. Use `secrets` instead.",
                        )
                    )

        self.generic_visit(node)


# =============================================================================
# Secret Scanner (Text / Regex / Entropy)
# =============================================================================


def scan_text_for_secrets(
    file_path: str,
    lines: list[tuple[int, str]],
) -> list[SecurityFinding]:
    """Scans specific line numbers and content for hardcoded secrets."""
    findings: list[SecurityFinding] = []

    for lineno, line_text in lines:
        stripped = line_text.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 1. Check known signature regexes
        matched_known = False
        for rule_id, sev, desc, pat in KNOWN_SECRET_PATTERNS:
            match = pat.search(line_text)
            if match:
                matched_known = True
                matched_val = match.group(0)
                # Ensure it's not a dummy test token
                if not any(safe.search(matched_val) for safe in SAFE_TOKEN_PATTERNS):
                    findings.append(
                        SecurityFinding(
                            file_path=file_path,
                            line=lineno,
                            rule=rule_id,
                            severity=sev,
                            message=f"Hardcoded credential detected: {desc}.",
                            snippet=f"{matched_val[:6]}...{matched_val[-4:]}",
                        )
                    )

        # 2. Check for high-entropy string literals if not already matched
        if not matched_known:
            quoted_strings = re.findall(r'["\']([A-Za-z0-9_\-\.]{24,})["\']', line_text)
            for candidate in quoted_strings:
                if is_high_entropy_secret(candidate):
                    findings.append(
                        SecurityFinding(
                            file_path=file_path,
                            line=lineno,
                            rule="SEC_HIGH_ENTROPY",
                            severity="HIGH",
                            message=f"High-entropy candidate secret ({shannon_entropy(candidate):.2f} bits/char).",
                            snippet=f"{candidate[:6]}...{candidate[-4:]}",
                        )
                    )

    return findings


# =============================================================================
# Diff Parser
# =============================================================================


def parse_unified_diff(diff_text: str) -> dict[str, list[tuple[int, str]]]:
    """Parses git unified diff into {file_path: [(added_lineno, line_content)]}."""
    files_added_lines: dict[str, list[tuple[int, str]]] = {}
    current_file = ""
    current_line = 0

    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_file = raw_line[6:].strip()
            if current_file not in files_added_lines:
                files_added_lines[current_file] = []
            continue

        hunk_match = hunk_header_re.match(raw_line)
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if not current_file:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added_content = raw_line[1:]
            files_added_lines[current_file].append((current_line, added_content))
            current_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            # Old deleted line; doesn't increment new line number
            pass
        else:
            # Context line
            current_line += 1

    return files_added_lines


# =============================================================================
# Core Scanner Orchestrator
# =============================================================================


def scan_file_content(
    file_path: str,
    content: str,
    target_lines: set[int] | None = None,
) -> list[SecurityFinding]:
    """Runs secret scanning and AST security checks on a file."""
    findings: list[SecurityFinding] = []

    # Prepare lines to inspect
    all_lines = [(idx + 1, line) for idx, line in enumerate(content.splitlines())]
    if target_lines is not None:
        lines_to_scan = [item for item in all_lines if item[0] in target_lines]
    else:
        lines_to_scan = all_lines

    # 1. Text & Secret scan
    findings.extend(scan_text_for_secrets(file_path, lines_to_scan))

    # 2. AST scan (for Python files)
    if file_path.endswith(".py"):
        try:
            tree = ast.parse(content, filename=file_path)
            visitor = ASTSecurityVisitor(file_path, target_lines=target_lines)
            visitor.visit(tree)
            findings.extend(visitor.findings)
        except SyntaxError:
            # Skip invalid syntax in partial diffs or draft files
            pass

    return findings


def scan_diff(diff_text: str, repo_root: Path | None = None) -> list[SecurityFinding]:
    """Scans git diff additions across all modified files."""
    file_diffs = parse_unified_diff(diff_text)
    findings: list[SecurityFinding] = []
    root = repo_root or Path.cwd()

    for rel_path, added_lines in file_diffs.items():
        if not added_lines:
            continue

        # Fast secret check directly on diff addition lines
        findings.extend(scan_text_for_secrets(rel_path, added_lines))

        # AST analysis: read full file if available on disk to preserve context
        if rel_path.endswith(".py"):
            target_line_set = {line_num for line_num, _ in added_lines}
            full_path = root / rel_path
            if full_path.exists():
                try:
                    full_content = full_path.read_text(encoding="utf-8")
                    try:
                        tree = ast.parse(full_content, filename=rel_path)
                        visitor = ASTSecurityVisitor(rel_path, target_lines=target_line_set)
                        visitor.visit(tree)
                        findings.extend(visitor.findings)
                    except SyntaxError:
                        pass
                except Exception:
                    pass
            else:
                try:
                    tree = ast.parse("\n".join(text for _, text in added_lines), filename=rel_path)
                    visitor = ASTSecurityVisitor(rel_path, target_lines=None)
                    visitor.visit(tree)
                    findings.extend(visitor.findings)
                except SyntaxError:
                    pass

    return findings


# =============================================================================
# Formatters
# =============================================================================


def format_compact_xml(findings: list[SecurityFinding]) -> str:
    """Formats findings into ultra-compact XML context block for LLM prompts."""
    if not findings:
        return '<security_preflight status="CLEAN" findings="0"/>'

    lines = [f'<security_preflight status="FLAGGED" findings="{len(findings)}">']
    for f in findings:
        snippet_attr = f' snippet="{f.snippet}"' if f.snippet else ""
        lines.append(
            f'  <finding file="{f.file_path}" line="{f.line}" rule="{f.rule}" severity="{f.severity}"{snippet_attr}>\n'
            f"    {f.message}\n"
            f"  </finding>"
        )
    lines.append("</security_preflight>")
    return "\n".join(lines)


def format_terminal(findings: list[SecurityFinding]) -> str:
    """Formats human-friendly terminal report."""
    if not findings:
        return "✓ Security Preflight: CLEAN (0 vulnerabilities or secrets detected)."

    lines = [f"⚠️ Security Preflight: FLAGGED ({len(findings)} findings)\n"]
    for f in findings:
        sev_badge = f"[{f.severity}]"
        lines.append(f"  • {f.file_path}:{f.line} {sev_badge} ({f.rule})")
        lines.append(f"    {f.message}")
        if f.snippet:
            lines.append(f"    Snippet: {f.snippet}")
    return "\n".join(lines)


# =============================================================================
# CLI Interface
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-review AST security and secret linter for pull requests and coding agents."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--staged", action="store_true", help="Audit git staged changes (git diff --cached)."
    )
    group.add_argument(
        "--diff", metavar="FILE_OR_DASH", help="Audit git diff from file or '-' for stdin."
    )
    group.add_argument(
        "--commit", metavar="REF", help="Audit git diff introduced by a specific commit ref."
    )
    group.add_argument("--file", "-f", metavar="PATH", help="Audit a single file directly.")

    parser.add_argument("paths", nargs="*", help="Optional files or paths to audit.")
    parser.add_argument(
        "--compact", action="store_true", help="Output ultra-compact XML for LLM context injection."
    )
    parser.add_argument("--json", action="store_true", help="Output findings as JSON.")
    parser.add_argument(
        "--fail-on-high",
        action="store_true",
        help="Exit with code 1 if any HIGH severity finding exists.",
    )

    args = parser.parse_args(argv)

    findings: list[SecurityFinding] = []

    if args.staged:
        proc = subprocess.run(
            ["git", "diff", "--cached"], check=False, capture_output=True, text=True
        )
        findings = scan_diff(proc.stdout)
    elif args.commit:
        proc = subprocess.run(
            ["git", "show", args.commit], check=False, capture_output=True, text=True
        )
        findings = scan_diff(proc.stdout)
    elif args.diff:
        if args.diff == "-":
            diff_text = sys.stdin.read()
        else:
            diff_text = Path(args.diff).read_text(encoding="utf-8")
        findings = scan_diff(diff_text)
    elif args.file:
        p = Path(args.file)
        if not p.exists():
            sys.stderr.write(f"Error: File '{args.file}' not found.\n")
            return 1
        content = p.read_text(encoding="utf-8")
        findings = scan_file_content(str(p), content)
    elif args.paths:
        for p_str in args.paths:
            p = Path(p_str)
            if p.is_file():
                content = p.read_text(encoding="utf-8")
                findings.extend(scan_file_content(str(p), content))
    else:
        # Default: audit unstaged git diff if in a git repository
        proc = subprocess.run(["git", "diff"], check=False, capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            findings = scan_diff(proc.stdout)
        else:
            # Fall back to staged diff
            proc_staged = subprocess.run(
                ["git", "diff", "--cached"], check=False, capture_output=True, text=True
            )
            findings = scan_diff(proc_staged.stdout)

    # Deduplicate findings
    seen = set()
    unique_findings: list[SecurityFinding] = []
    for f in findings:
        key = (f.file_path, f.line, f.rule)
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    # Output formatting
    if args.json:
        print(json.dumps([asdict(f) for f in unique_findings], indent=2))
    elif args.compact:
        print(format_compact_xml(unique_findings))
    else:
        print(format_terminal(unique_findings))

    if args.fail_on_high and any(f.severity == "HIGH" for f in unique_findings):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
