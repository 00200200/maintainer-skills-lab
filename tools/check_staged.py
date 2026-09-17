#!/usr/bin/env python3
"""Check the staged skill library and its generated exports without changing Git state."""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

import kit

PATHS = ("skills", "agents", "grok-bot", "providers", "tools/kit.py")
OBJECT_ID = re.compile(rb"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class StagedError(Exception):
    """The staged library cannot be validated."""


def git(root: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True, timeout=30
    )
    return result.stdout


def staged_files(root: Path) -> dict[str, bytes]:
    entries = []
    listing = git(root, "ls-files", "--stage", "-z", "--", *PATHS)
    for record in listing.split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, oid, stage = header.split()
        name = os.fsdecode(raw_name)
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or path.as_posix() != name:
            raise StagedError(f"Unsupported staged path: {name!r}")
        if stage != b"0":
            raise StagedError(f"Resolve the staged merge conflict: {name!r}")
        if mode not in {b"100644", b"100755"}:
            raise StagedError(f"Only regular library files are supported: {name!r}")
        if not OBJECT_ID.fullmatch(oid):
            raise StagedError("Invalid staged object ID")
        entries.append((name, oid))
    # Read raw blobs, without checkout, smudge filters, textconv, or source execution.
    responses = io.BytesIO(
        git(root, "cat-file", "--batch", data=b"".join(oid + b"\n" for _, oid in entries))
    )
    files = {}
    for name, oid in entries:
        actual, kind, raw_size = responses.readline().split()
        size = int(raw_size)
        if actual != oid or kind != b"blob" or size < 0:
            raise StagedError(f"Could not read staged blob: {name!r}")
        content = responses.read(size)
        if len(content) != size or responses.read(1) != b"\n":
            raise StagedError("Incomplete staged blob response")
        files[name] = content
    return files


def check(root: Path) -> dict:
    root = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel")).rstrip("\n"))
    if not git(root, "diff", "--cached", "--name-only", "-z", "--", *PATHS):
        return {"checked": False, "reason": "No library changes staged"}
    files = staged_files(root)
    if kit.canonical_bytes(files.get("tools/kit.py", b"")) != kit.canonical_bytes(
        Path(kit.__file__).read_bytes()
    ):
        raise StagedError(
            "The staged tools/kit.py differs from the running exporter. "
            "Use the intended exporter revision in both the working tree and index."
        )
    with tempfile.TemporaryDirectory(prefix="mkl-staged-") as temporary:
        snapshot = Path(temporary)
        for name, content in files.items():
            path = snapshot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        try:
            result = kit.sync_providers(snapshot, check=True)
        except (kit.KitError, ValueError) as exc:
            # Hide the disposable snapshot path in actionable error messages.
            raise StagedError(str(exc).replace(str(snapshot), "<staged>")) from exc
    if not result["up_to_date"]:
        affected = sorted(set(result["written"]) | set(result["removed"]))
        if result["manifest_changed"]:
            affected.append(".manifest.json")
        raise StagedError(
            "Staged provider exports do not match the staged source: "
            + ", ".join(repr(name) for name in affected[:6])
            + (f" (+{len(affected) - 6} more)" if len(affected) > 6 else "")
            + ". Run python3 tools/kit.py sync, review the diff, and stage the matching "
            "source and providers/ files together. No files were changed by this check."
        )
    return {"checked": True, "reason": "Staged source and provider exports match"}


def main() -> int:
    try:
        result = check(Path.cwd())
        print(f"Maintainer Skills Lab: {result['reason']}.")
        return 0
    except (StagedError, OSError, ValueError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, StagedError) else type(exc).__name__
        print(f"Maintainer Skills Lab: staged check failed. {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
