#!/usr/bin/env python3
"""Automated SemVer / Conventional Commit Bump Evaluator for Maintainer Skills Lab.

Evaluates git commits since the latest git tag using Conventional Commits rules,
calculates the next Semantic Version (SemVer 2.0.0), and surgically updates version
declarations in pyproject.toml and src/**/__init__.py preserving formatting and comments.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SEMVER_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)

CONVENTIONAL_HEADER = re.compile(
    r"^(?P<type>[a-zA-Z0-9_-]+)(?:\([^)]+\))?(?P<breaking>!)?:\s*(?P<desc>.*)$"
)

BREAKING_BODY_PATTERN = re.compile(r"^[ \t]*BREAKING[- ]CHANGE:\s*", re.MULTILINE)

PYPROJECT_VERSION_PATTERN = re.compile(
    r"^(?P<prefix>\s*version\s*=\s*)([\"'])(?P<ver>[^\"']+)\2",
    re.MULTILINE,
)

INIT_VERSION_PATTERN = re.compile(
    r"^(?P<prefix>\s*__version__\s*=\s*)([\"'])(?P<ver>[^\"']+)\2",
    re.MULTILINE,
)


def resolve_latest_tag(repo_root: Path | None = None) -> tuple[str, str | None]:
    """Resolve the latest git tag via git describe, or fallback to ('0.1.0', None)."""
    cwd = str(repo_root) if repo_root else None
    proc = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return "0.1.0", None

    tag = proc.stdout.strip()
    match = SEMVER_PATTERN.match(tag)
    if match:
        version = tag.lstrip("vV")
        return version, tag
    return "0.1.0", tag


def get_commits_since_tag(tag: str | None, repo_root: Path | None = None) -> list[str]:
    """Fetch commit messages since the given tag (or all commits if no tag) up to HEAD."""
    cwd = str(repo_root) if repo_root else None
    if tag:
        cmd = ["git", "log", f"{tag}..HEAD", "--format=%B%x00"]
    else:
        cmd = ["git", "log", "HEAD", "--format=%B%x00"]

    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return []

    return [msg.strip() for msg in proc.stdout.split("\0") if msg.strip()]


def classify_commit(message: str) -> str:
    """Classify commit as 'breaking', 'feat', 'fix', or 'chore'."""
    first_line = message.splitlines()[0].strip() if message else ""
    header_match = CONVENTIONAL_HEADER.match(first_line)

    if header_match and header_match.group("breaking") == "!":
        return "breaking"

    if BREAKING_BODY_PATTERN.search(message):
        return "breaking"

    if header_match:
        commit_type = header_match.group("type").lower()
        if commit_type == "feat":
            return "feat"
        if commit_type == "fix":
            return "fix"
        return "chore"

    return "chore"


def summarize_commits(commits: list[str]) -> dict[str, int]:
    """Produce summary dictionary for conventional commit categories."""
    categories = [classify_commit(msg) for msg in commits]
    return {
        "breaking": sum(1 for c in categories if c == "breaking"),
        "feat": sum(1 for c in categories if c == "feat"),
        "fix": sum(1 for c in categories if c == "fix"),
        "chore": sum(1 for c in categories if c == "chore"),
        "total_commits": len(commits),
    }


def calculate_bump_type(summary: dict[str, int], override_level: str | None = None) -> str | None:
    """Determine bump type ('major', 'minor', 'patch') or None."""
    if override_level:
        return override_level.lower()
    if summary["breaking"] > 0:
        return "major"
    if summary["feat"] > 0:
        return "minor"
    if summary["total_commits"] > 0:
        return "patch"
    return None


def bump_semver(version: str, bump_type: str | None) -> str:
    """Calculate next SemVer 2.0 version given current version and bump type."""
    match = SEMVER_PATTERN.match(version.strip())
    if not match:
        raise ValueError(f"Invalid SemVer string: {version}")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))

    if not bump_type or bump_type == "none":
        return version
    if bump_type == "major":
        return f"{major + 1}.0.0"
    if bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    if bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown bump type: {bump_type}")


def format_next_tag(next_version: str, previous_tag: str | None) -> str:
    """Format the next git tag string, matching prefix convention."""
    if previous_tag and not previous_tag.startswith(("v", "V")):
        return next_version
    return f"v{next_version}"


def is_working_tree_dirty(repo_root: Path | None = None) -> bool:
    """Check if the git working tree has uncommitted modifications."""
    cwd = str(repo_root) if repo_root else None
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(proc.stdout.strip())


def update_version_files(repo_root: Path, next_version: str, apply: bool = False) -> list[str]:
    """Target and surgically update version declarations in pyproject.toml and src/**/__init__.py.

    Returns the list of relative file paths containing version declarations.
    """
    updated_files: list[str] = []

    # 1. pyproject.toml
    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.is_file():
        content = pyproject_path.read_text(encoding="utf-8")
        new_content, count = PYPROJECT_VERSION_PATTERN.subn(
            rf'\g<prefix>"{next_version}"',
            content,
            count=1,
        )
        if count > 0:
            if apply:
                pyproject_path.write_text(new_content, encoding="utf-8")
            updated_files.append("pyproject.toml")

    # 2. src/**/__init__.py
    src_dir = repo_root / "src"
    if src_dir.is_dir():
        for init_path in sorted(src_dir.rglob("__init__.py")):
            if not init_path.is_file():
                continue
            content = init_path.read_text(encoding="utf-8")
            new_content, count = INIT_VERSION_PATTERN.subn(
                rf'\g<prefix>"{next_version}"',
                content,
                count=1,
            )
            if count > 0:
                if apply:
                    init_path.write_text(new_content, encoding="utf-8")
                updated_files.append(str(init_path.relative_to(repo_root)))

    return updated_files


def evaluate_version_bump(
    repo_root: Path,
    *,
    apply: bool = False,
    override_level: str | None = None,
    allow_dirty: bool = False,
) -> dict:
    """Evaluate repository commit history, calculate SemVer, and optionally apply changes."""
    if apply and not allow_dirty and is_working_tree_dirty(repo_root):
        raise RuntimeError(
            "Working directory has uncommitted changes. "
            "Commit or stash changes before applying version bump, or pass --allow-dirty."
        )

    previous_version, previous_tag = resolve_latest_tag(repo_root)
    commits = get_commits_since_tag(previous_tag, repo_root)
    summary = summarize_commits(commits)
    bump_type = calculate_bump_type(summary, override_level=override_level)

    if bump_type:
        next_version = bump_semver(previous_version, bump_type)
        next_tag = format_next_tag(next_version, previous_tag)
    else:
        next_version = previous_version
        next_tag = previous_tag or format_next_tag(previous_version, None)

    files_updated = update_version_files(repo_root, next_version, apply=apply)

    return {
        "previous_version": previous_version,
        "previous_tag": previous_tag,
        "next_version": next_version,
        "next_tag": next_tag,
        "bump_type": bump_type or "patch",
        "summary": summary,
        "files_updated": files_updated,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated SemVer / Conventional Commit Bump Evaluator"
    )
    parser.add_argument(
        "--repo",
        "--path",
        dest="repo_path",
        default=".",
        help="Path to git repository root (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview version bump without modifying files",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply calculated version bump to repository files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON schema",
    )
    parser.add_argument(
        "--level",
        choices=["major", "minor", "patch"],
        help="Force a specific SemVer bump level",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow version bumping on a dirty git working tree",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.repo_path).resolve()

    apply = args.apply and not args.dry_run

    try:
        result = evaluate_version_bump(
            repo_root,
            apply=apply,
            override_level=args.level,
            allow_dirty=args.allow_dirty,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    mode_label = "[APPLIED]" if apply else "[DRY RUN]"
    print(f"{mode_label} SemVer Evaluation:")
    print(
        f"  Previous version: {result['previous_version']} ({result['previous_tag'] or 'no tag'})"
    )
    print(f"  Bump type:        {result['bump_type']}")
    print(f"  Next version:     {result['next_version']} ({result['next_tag']})")
    print("\nCommit Summary:")
    print(f"  Breaking:       {result['summary']['breaking']}")
    print(f"  Features:       {result['summary']['feat']}")
    print(f"  Fixes:          {result['summary']['fix']}")
    print(f"  Chores:         {result['summary']['chore']}")
    print(f"  Total commits:  {result['summary']['total_commits']}")

    if result["files_updated"]:
        action_verb = "Updated files:" if apply else "Files to update:"
        print(f"\n{action_verb}")
        for path in result["files_updated"]:
            print(f"  - {path}")
    else:
        print("\nNo version files found to update (pyproject.toml, src/**/__init__.py).")

    next_tag = result["next_tag"]
    print(f'\nRecommended release tag command:\n  git tag -a {next_tag} -m "Release {next_tag}"')

    if not apply:
        print("\nTo apply these changes, run with --apply:")
        print("  python3 tools/bump_version.py --apply")

    return 0


if __name__ == "__main__":
    sys.exit(main())
