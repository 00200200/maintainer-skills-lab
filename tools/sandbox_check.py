#!/usr/bin/env python3
"""Agent Safety & Command Sandbox Classifier Tool.

Classifies proposed shell commands for autonomous agent execution into:
- READ_ONLY (Auto-Safe): git status, git diff, pytest, cat, ls, grep, ruff check
- LOCAL_MUTATION (Safe with warning): git add, git commit, ruff format, touch, mkdir
- BLOCKED / HIGH_RISK (Requires confirmation): rm -rf /, git push --force, curl | sh, DROP TABLE
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from typing import Any

# Safety Categories
READ_ONLY = "READ_ONLY"
LOCAL_MUTATION = "LOCAL_MUTATION"
BLOCKED = "BLOCKED"

# Category Priority (most restrictive wins for compound commands)
CATEGORY_PRIORITY = {
    READ_ONLY: 1,
    LOCAL_MUTATION: 2,
    BLOCKED: 3,
}

# Dangerous regex patterns checked across full command lines / pipelines
DESTRUCTIVE_GLOBAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(?:/|/\*|~|\$HOME|\.\./\.\.|\*)\b"),
        "Destructive recursive deletion of root, home, parent directories, or wildcard root",
    ),
    (
        re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+(?:/|/\*|~|\$HOME|\.\./\.\.|\*)\b"),
        "Destructive recursive deletion of root, home, parent directories, or wildcard root",
    ),
    (
        re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(?:/|/\*|~|\$HOME|\.\./\.\.|\*)\b"),
        "Destructive recursive deletion of root, home, parent directories, or wildcard root",
    ),
    (
        re.compile(r"\b(?:curl|wget|fetch)\b[^|;&\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|python\d?|perl|ruby)\b"),
        "Remote script piping directly to shell execution (curl | sh)",
    ),
    (
        re.compile(r"\bgit\s+push\b.*(?:--force|-f)\b.*(?:main|master|prod|production)\b"),
        "Destructive force push to protected main/master/prod branch",
    ),
    (
        re.compile(r"\bgit\s+push\b.*(?:--force|-f)\b"),
        "Destructive force push to remote repository",
    ),
    (
        re.compile(r"\bgit\s+push\b.*--delete\b"),
        "Remote branch deletion via git push --delete",
    ),
    (
        re.compile(r"\bgit\s+reset\s+--hard\b"),
        "Destructive git reset --hard discarding uncommitted changes",
    ),
    (
        re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f[a-zA-Z]*\b"),
        "Destructive git clean permanently deleting untracked files",
    ),
    (
        re.compile(r"\b(?:DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE)\b", re.IGNORECASE),
        "Destructive SQL database modification (DROP/TRUNCATE)",
    ),
    (
        re.compile(r"\bDELETE\s+FROM\s+\w+\s*(?:;|\"|\'|$)", re.IGNORECASE),
        "Unbounded SQL DELETE statement without WHERE clause",
    ),
    (
        re.compile(r"(?:\b|/)(?:etc/(?:passwd|shadow|sudoers)|boot|proc|sys|root)\b"),
        "Targeting protected system configuration or root paths",
    ),
    (
        re.compile(r"\bsudo\b"),
        "Privileged superuser execution (sudo)",
    ),
    (
        re.compile(r"\bchmod\s+(-[a-zA-Z]*R[a-zA-Z]*\s+)?(?:777|a\+[rw]*x)\s+(?:/|/\*|~|\$HOME)\b"),
        "Insecure broad permission escalation on system or home path",
    ),
    (
        re.compile(r"\bdd\s+if=.*of=/dev/(?:sda|sdb|nvme|disk|rdisk)"),
        "Direct block device overwrite via dd",
    ),
    (
        re.compile(r"\bmkfs(?:\.\w+)?\b"),
        "Filesystem format command (mkfs)",
    ),
    (
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
        "Fork bomb pattern detected",
    ),
    (
        re.compile(r"\b(?:nc|ncat)\s+-[a-zA-Z]*e[a-zA-Z]*\b"),
        "Network reverse shell execution via netcat",
    ),
    (
        re.compile(r"/dev/tcp/\d+\.\d+\.\d+\.\d+/\d+"),
        "Raw TCP network socket redirection",
    ),
    (
        re.compile(r"\b(?:shutdown|reboot|poweroff|init\s+0|halt)\b"),
        "Host system shutdown/reboot command",
    ),
]

# Common CLI tools classified by default nature
READ_ONLY_COMMANDS = frozenset({
    "cat",
    "head",
    "tail",
    "more",
    "less",
    "ls",
    "dir",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ag",
    "find",
    "wc",
    "stat",
    "file",
    "which",
    "where",
    "whereis",
    "type",
    "pwd",
    "echo",
    "printf",
    "env",
    "printenv",
    "diff",
    "cmp",
    "md5",
    "md5sum",
    "shasum",
    "sha256sum",
    "sha1sum",
    "cksum",
    "true",
    "false",
    "test",
    "[",
    "sleep",
    "date",
    "uname",
    "whoami",
    "id",
    "cut",
    "sort",
    "uniq",
    "tr",
    "awk",
    "sed",
    "column",
    "tree",
    "basename",
    "dirname",
    "realpath",
    "readlink",
})

# Git subcommands that are read-only
GIT_READ_ONLY_SUBCOMMANDS = frozenset({
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "tag",
    "describe",
    "rev-parse",
    "remote",
    "ls-files",
    "ls-tree",
    "cat-file",
    "config",
    "check-ref-format",
    "check-ignore",
    "blame",
    "shortlog",
    "help",
    "version",
})

# Git subcommands that are local workspace mutations
GIT_LOCAL_MUTATION_SUBCOMMANDS = frozenset({
    "add",
    "commit",
    "checkout",
    "switch",
    "restore",
    "stash",
    "merge",
    "rebase",
    "cherry-pick",
    "fetch",
    "pull",
    "push",
    "clone",
    "init",
    "clean",
    "reset",
    "branch",
    "mv",
    "rm",
})

# Read-only linters and static analyzers (unless formatting flags passed)
LINTER_READ_ONLY = frozenset({
    "ruff",
    "flake8",
    "mypy",
    "pylint",
    "pyright",
    "bandit",
    "shellcheck",
})


def _strip_quotes(token: str) -> str:
    """Strip bounding matching single or double quotes."""
    if len(token) >= 2 and ((token[0] == token[-1] == "'") or (token[0] == token[-1] == '"')):
        return token[1:-1]
    return token


def _tokenize_script(script: str) -> list[list[str]]:
    """Tokenize a script into individual command statements separated by operators (|, &&, ||, ;).

    Respects single and double quotes so operators inside quotes are not split.
    """
    try:
        lexer = shlex.shlex(script, punctuation_chars=True)
        lexer.whitespace_split = True
        raw_tokens = list(lexer)
    except ValueError:
        raw_tokens = script.split()

    commands: list[list[str]] = []
    current: list[str] = []

    for t in raw_tokens:
        if t in (";", "&&", "||", "|", "\n", "\r\n"):
            if current:
                commands.append(current)
                current = []
        else:
            current.append(t)

    if current:
        commands.append(current)

    return commands


def _analyze_git(tokens: list[str]) -> tuple[str, str]:
    """Classify a git command invocation."""
    cleaned = [_strip_quotes(t) for t in tokens]
    if len(cleaned) == 1:
        return READ_ONLY, "Git help / status inspection"

    subcmd = cleaned[1]
    idx = 1
    while idx < len(cleaned) and cleaned[idx].startswith("-"):
        idx += 1
    if idx < len(cleaned):
        subcmd = cleaned[idx]

    # High-risk git checks
    if subcmd == "push":
        if any(flag in cleaned for flag in ("--force", "-f", "--force-with-lease")):
            return BLOCKED, "Destructive force push to remote repository"
        if "--delete" in cleaned or "-d" in cleaned:
            return BLOCKED, "Remote branch deletion via git push --delete"
        return LOCAL_MUTATION, "Push changes to remote repository"

    if subcmd == "reset" and "--hard" in cleaned:
        return BLOCKED, "Destructive git reset --hard discarding uncommitted changes"

    if subcmd == "clean" and any(arg.startswith("-") and "f" in arg for arg in cleaned[idx:]):
        return BLOCKED, "Destructive git clean permanently deleting untracked files"

    if subcmd in GIT_READ_ONLY_SUBCOMMANDS:
        # Check config write vs read
        if subcmd == "config":
            if any(t in cleaned for t in ("--unset", "--unset-all", "--add", "--replace-all")):
                return LOCAL_MUTATION, "Git configuration mutation"
            non_flag_args = [t for t in cleaned[idx + 1 :] if not t.startswith("-")]
            if len(non_flag_args) >= 2:
                return LOCAL_MUTATION, "Git configuration write"
            return READ_ONLY, "Git configuration query"
        # Check git branch delete vs list
        if subcmd == "branch":
            if any(t in cleaned for t in ("-d", "-D", "--delete")):
                return LOCAL_MUTATION, "Git branch deletion"
            if len([t for t in cleaned[idx + 1 :] if not t.startswith("-")]) > 0:
                return LOCAL_MUTATION, "Git branch creation or modification"
            return READ_ONLY, "Git branch list"
        return READ_ONLY, f"Read-only git {subcmd}"

    if subcmd in GIT_LOCAL_MUTATION_SUBCOMMANDS:
        return LOCAL_MUTATION, f"Local git mutation: git {subcmd}"

    return LOCAL_MUTATION, f"Git command: {subcmd}"


def _analyze_tokens(tokens: list[str]) -> tuple[str, str]:
    """Classify a single command represented by tokens."""
    if not tokens:
        return READ_ONLY, "Empty command"

    cleaned_tokens = [_strip_quotes(t) for t in tokens]
    joined_cmd = " ".join(tokens)

    # 1. Global regex safety scan across the segment
    for pattern, reason in DESTRUCTIVE_GLOBAL_PATTERNS:
        if pattern.search(joined_cmd):
            return BLOCKED, reason

    # Filter leading environment variables
    while cleaned_tokens and "=" in cleaned_tokens[0] and not cleaned_tokens[0].startswith("-"):
        cleaned_tokens.pop(0)

    if not cleaned_tokens:
        return LOCAL_MUTATION, "Environment variable assignment"

    base_cmd = cleaned_tokens[0].rsplit("/", 1)[-1]

    # Check for redirection to system files
    if ">" in cleaned_tokens or ">>" in cleaned_tokens:
        for idx, t in enumerate(cleaned_tokens):
            if t in (">", ">>") and idx + 1 < len(cleaned_tokens):
                target = cleaned_tokens[idx + 1]
                if target.startswith(("/etc", "/root", "/boot", "/sys", "/dev", "/usr")):
                    return BLOCKED, f"Redirection into protected system path: {target}"

    # Check git specifically
    if base_cmd == "git":
        return _analyze_git(cleaned_tokens)

    # Check rm specifically
    if base_cmd == "rm":
        for arg in cleaned_tokens[1:]:
            if arg in ("/", "/*", "~", "$HOME", "..", "../..", "*"):
                return BLOCKED, f"Destructive file deletion target: {arg}"
            if arg.startswith(("/etc", "/var", "/usr", "/boot", "/dev", "/sys", "/root")):
                return BLOCKED, f"Deletion targeting protected system path: {arg}"
        if any(arg.startswith("-") and "r" in arg for arg in cleaned_tokens):
            return LOCAL_MUTATION, "Recursive directory deletion within local workspace"
        return LOCAL_MUTATION, "Local file removal"

    # Check linters and analyzers
    if base_cmd == "ruff":
        if len(cleaned_tokens) > 1 and cleaned_tokens[1] == "format":
            return LOCAL_MUTATION, "Code formatting with ruff format"
        if len(cleaned_tokens) > 1 and cleaned_tokens[1] == "check":
            if "--fix" in cleaned_tokens or "--fix-only" in cleaned_tokens:
                return LOCAL_MUTATION, "Linter automated fixes with ruff check --fix"
            return READ_ONLY, "Linter check with ruff"
        return READ_ONLY, "Ruff analysis"

    if base_cmd in LINTER_READ_ONLY:
        return READ_ONLY, f"Read-only lint check: {base_cmd}"

    if base_cmd in ("black", "isort", "prettier"):
        if any(flag in cleaned_tokens for flag in ("--check", "--diff", "-c")):
            return READ_ONLY, f"Read-only format check with {base_cmd}"
        return LOCAL_MUTATION, f"Code formatting with {base_cmd}"

    if base_cmd in ("pytest", "py.test"):
        if "--fix" in cleaned_tokens or "--update" in cleaned_tokens:
            return LOCAL_MUTATION, "Test suite run with mutation flags"
        return READ_ONLY, "Test execution with pytest"

    # Python execution
    if base_cmd in ("python", "python3", "py"):
        joined = " ".join(cleaned_tokens)
        if "tools/kit.py check" in joined or "tools/kit.py list" in joined or "sync --check" in joined:
            return READ_ONLY, "Read-only kit inspection"
        if "tools/sandbox_check.py" in joined:
            return READ_ONLY, "Sandbox security check"
        if "-m" in cleaned_tokens:
            m_idx = cleaned_tokens.index("-m")
            if m_idx + 1 < len(cleaned_tokens):
                mod = cleaned_tokens[m_idx + 1]
                if mod == "unittest":
                    return READ_ONLY, "Unit test execution with unittest"
                if mod in ("pytest", "pyright", "mypy", "ruff", "flake8"):
                    return READ_ONLY, f"Tool run: {mod}"
        if "-c" in cleaned_tokens:
            c_idx = cleaned_tokens.index("-c")
            if c_idx + 1 < len(cleaned_tokens):
                code = cleaned_tokens[c_idx + 1]
                if re.search(r"\b(?:shutil\.rmtree|os\.remove|os\.unlink|subprocess\.run)\b", code):
                    return LOCAL_MUTATION, "Inline python script executing mutations"
                return READ_ONLY, "Inline python code execution"
        return LOCAL_MUTATION, "Python script execution"

    # Read-only commands
    if base_cmd in READ_ONLY_COMMANDS:
        if any(">" in t for t in cleaned_tokens):
            return LOCAL_MUTATION, f"File output redirection from {base_cmd}"
        return READ_ONLY, f"Read-only command: {base_cmd}"

    # Package managers & build tools
    if base_cmd in ("pip", "uv", "poetry", "npm", "yarn", "pnpm", "cargo", "go"):
        joined = " ".join(cleaned_tokens)
        if any(sub in joined for sub in ("install", "add", "remove", "update", "upgrade", "build")):
            return LOCAL_MUTATION, f"Package management or build: {base_cmd}"
        if any(sub in joined for sub in ("list", "show", "search", "tree", "check", "audit", "test")):
            return READ_ONLY, f"Package inspection: {base_cmd}"
        return LOCAL_MUTATION, f"Package manager command: {base_cmd}"

    # Local workspace file manipulation
    if base_cmd in ("mkdir", "touch", "cp", "mv", "ln", "chmod", "chown"):
        return LOCAL_MUTATION, f"Local filesystem mutation: {base_cmd}"

    return LOCAL_MUTATION, f"General command: {base_cmd}"


def classify_command(command: str) -> dict[str, Any]:
    """Classify a full command (which may be a compound script or pipeline).

    Returns a dict with:
      - command: the original command string
      - verdict: READ_ONLY | LOCAL_MUTATION | BLOCKED
      - category: READ_ONLY | LOCAL_MUTATION | HIGH_RISK
      - reason: human-readable rationale
      - details: list of segment-level assessments
    """
    cleaned = command.strip()
    if not cleaned:
        return {
            "command": command,
            "verdict": READ_ONLY,
            "category": READ_ONLY,
            "reason": "Empty command",
            "details": [],
        }

    # 1. Global check first across the whole raw script
    for pattern, reason in DESTRUCTIVE_GLOBAL_PATTERNS:
        if pattern.search(cleaned):
            return {
                "command": command,
                "verdict": BLOCKED,
                "category": "HIGH_RISK",
                "reason": reason,
                "details": [{"segment": cleaned, "verdict": BLOCKED, "reason": reason}],
            }

    # 2. Tokenize into distinct commands
    cmd_token_lists = _tokenize_script(cleaned)
    max_priority = 0
    worst_verdict = READ_ONLY
    worst_reason = "All operations are read-only"
    details: list[dict[str, str]] = []

    for tokens in cmd_token_lists:
        seg_str = " ".join(tokens)
        verdict, reason = _analyze_tokens(tokens)
        details.append({"segment": seg_str, "verdict": verdict, "reason": reason})

        prio = CATEGORY_PRIORITY.get(verdict, 2)
        if prio > max_priority:
            max_priority = prio
            worst_verdict = verdict
            worst_reason = reason

    category = "HIGH_RISK" if worst_verdict == BLOCKED else worst_verdict

    return {
        "command": command,
        "verdict": worst_verdict,
        "category": category,
        "reason": worst_reason,
        "details": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Classify shell commands for autonomous agent safety."
    )
    parser.add_argument(
        "command",
        nargs="*",
        help="Command to inspect (can be passed as a single quoted string or arguments)",
    )
    parser.add_argument(
        "-c",
        "--command-string",
        dest="cmd_str",
        help="Command string to inspect",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Format output as JSON (default behavior)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if command is BLOCKED",
    )

    args = parser.parse_args(argv)

    cmd: str
    if args.cmd_str:
        cmd = args.cmd_str
    elif args.command:
        cmd = " ".join(args.command)
    else:
        # Read from stdin if piped
        if not sys.stdin.isatty():
            cmd = sys.stdin.read().strip()
        else:
            parser.print_help()
            return 2

    assessment = classify_command(cmd)
    print(json.dumps(assessment, indent=2))

    if args.strict and assessment["verdict"] == BLOCKED:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
