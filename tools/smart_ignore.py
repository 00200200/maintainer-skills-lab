#!/usr/bin/env python3
"""Exclude lockfiles, minified blobs, and large artifacts from agent context."""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IGNORE_FILE = ROOT / ".mklignore"

# Built-in defaults mirror .mklignore so the guard works even without the file.
DEFAULT_PATTERNS: tuple[str, ...] = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.pyc",
    "*.wasm",
    "dist/**",
    "build/**",
    "*.bin",
    "*.pt",
    "*.onnx",
    "*.parquet",
    "*.sqlite",
)

LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
    }
)

LOCKFILE_INSPECT = {
    "package-lock.json": "npm list <package>",
    "yarn.lock": "yarn list <package>",
    "pnpm-lock.yaml": "pnpm list <package>",
    "Cargo.lock": "cargo tree -i <crate>",
    "poetry.lock": "poetry show <package>",
    "uv.lock": "uv tree",
    "Pipfile.lock": "pipenv graph",
}


def load_patterns(ignore_file: Path | None = None) -> tuple[str, ...]:
    """Load ignore globs from `.mklignore`, falling back to built-in defaults."""
    path = DEFAULT_IGNORE_FILE if ignore_file is None else Path(ignore_file)
    if not path.is_file():
        return DEFAULT_PATTERNS
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return tuple(patterns) if patterns else DEFAULT_PATTERNS


def _normalize(path: Path | str) -> PurePosixPath:
    text = Path(path).as_posix().replace("\\", "/")
    return PurePosixPath(text)


def _matches(path: PurePosixPath, pattern: str) -> bool:
    """Match a path against a gitignore-style glob (basename or full relative path)."""
    posix = path.as_posix().lstrip("./")
    name = path.name
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return posix == prefix or posix.startswith(prefix + "/")
    if "/" in pattern:
        return fnmatch.fnmatchcase(posix, pattern) or fnmatch.fnmatchcase(name, pattern)
    return fnmatch.fnmatchcase(name, pattern) or any(
        fnmatch.fnmatchcase(part, pattern) for part in path.parts
    )


def is_ignorable_for_context(
    path: Path | str,
    *,
    patterns: tuple[str, ...] | None = None,
) -> bool:
    """Return True when *path* should be omitted from agent context packs."""
    normalized = _normalize(path)
    if not normalized.parts or normalized.as_posix() in {".", ""}:
        return False
    active = DEFAULT_PATTERNS if patterns is None else patterns
    return any(_matches(normalized, pattern) for pattern in active)


def omission_message(path: Path | str) -> str:
    """One-line diagnostic when a lockfile or other ignorable path is skipped."""
    normalized = _normalize(path)
    name = normalized.name
    kind = "lockfile" if name in LOCKFILE_NAMES else "generated or binary artifact"
    line_count: int | None = None
    candidate = Path(path)
    if candidate.is_file():
        try:
            with candidate.open("rb") as handle:
                line_count = sum(1 for _ in handle)
        except OSError:
            line_count = None
    if line_count is None:
        size = f"{kind}"
    else:
        size = f"{line_count:,} lines ({kind})"
    if name in LOCKFILE_INSPECT:
        hint = f"Use '{LOCKFILE_INSPECT[name]}' to inspect dependencies."
    else:
        hint = "Inspect the source or package metadata instead."
    return f"[File '{name}' is {size}. Omitted to preserve token budget. {hint}]"


def filter_paths(
    paths: list[Path | str] | tuple[Path | str, ...],
    *,
    patterns: tuple[str, ...] | None = None,
) -> list[Path | str]:
    """Return paths that are safe to include in context."""
    active = load_patterns() if patterns is None else patterns
    return [path for path in paths if not is_ignorable_for_context(path, patterns=active)]
