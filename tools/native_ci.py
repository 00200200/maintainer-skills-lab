#!/usr/bin/env python3
"""Validate native distribution artifacts and run required installed-wheel tests."""

from __future__ import annotations

import argparse
import importlib
import platform
import re
import sys
import tarfile
import tempfile
import unittest
import zipfile
from email.parser import BytesParser
from importlib import metadata
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_GROUPS = (
    "test_native_minify.NativeParityTests",
    "test_native_walk.NativeWalkTests",
    "test_native_tokens.NativeTokenContractTests",
    "test_native_tokens.NativeTokenParityTests",
    "test_native_symbols.NativeSymbolTests",
    "test_sync_cache.NativeHashTests",
    "test_sync_cache.SyncCacheTests",
)
TEST_FILES = (
    "test_native_minify.py",
    "test_native_walk.py",
    "test_native_tokens.py",
    "test_native_symbols.py",
    "test_sync_cache.py",
)
BLAKE3_EMPTY = "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
PERMISSION_TESTS = {
    "test_native_walk.NativeWalkTests.test_unreadable_file_fails_instead_of_returning_partial_results",
    "test_native_walk.NativeWalkTests.test_unreadable_directory_and_rule_file_fail",
}
NON_UTF8_FILENAME_TEST = (
    "test_native_walk.NativeWalkTests.test_non_utf8_filename_is_rejected_without_lossy_conversion"
)
WINDOWS_SKIPS = PERMISSION_TESTS | {
    "test_native_walk.NativeWalkTests.test_special_files_are_not_opened",
    NON_UTF8_FILENAME_TEST,
    "test_native_walk.NativeWalkTests.test_symlink_files_directories_and_broken_links_are_skipped",
    "test_native_walk.NativeWalkTests.test_symlink_root_and_root_components_are_rejected",
    "test_native_walk.NativeWalkTests.test_symlink_ignore_files_are_rejected_before_loading",
    "test_sync_cache.SyncCacheTests.test_unsafe_cache_symlink_is_not_followed_or_replaced",
}


def validate_api(native) -> None:
    for name in (
        "minify_markdown",
        "walk_project",
        "count_tokens",
        "extract_ast_symbols",
        "blake3_hash",
        "Symbol",
    ):
        if not callable(getattr(native, name, None)):
            raise RuntimeError(f"Installed wheel is missing required native API: {name}")
    error = getattr(native, "DisallowedSpecialTokenError", None)
    if not isinstance(error, type) or not issubclass(error, ValueError):
        raise RuntimeError("Installed wheel is missing the special-token exception API")


def smoke(expected_arch: str) -> None:
    native = importlib.import_module("msl_core")
    validate_api(native)
    actual_arch = platform.machine().lower()
    actual_arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(actual_arch, actual_arch)
    if actual_arch != expected_arch:
        raise RuntimeError(f"Wrong runtime architecture: {actual_arch}, expected {expected_arch}")
    origin = Path(native.__file__).resolve()
    distribution = metadata.distribution("msl-core")
    installed_files = {
        Path(distribution.locate_file(name)).resolve() for name in distribution.files or ()
    }
    if origin not in installed_files:
        raise RuntimeError(f"Tests must import the installed wheel, not checkout code: {origin}")
    if native.minify_markdown("text  \n") != "text\n":
        raise RuntimeError("M1 minifier smoke check failed")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        (root / "text.md").write_text("text\n", encoding="utf-8")
        if native.walk_project(str(root), []) != ["text.md"]:
            raise RuntimeError("M2 walker smoke check failed")
    for encoding in ("cl100k_base", "o200k_base"):
        if native.count_tokens("hello world", encoding) != 2:
            raise RuntimeError(f"M3 BPE smoke check failed: {encoding}")
    symbols = native.extract_ast_symbols("smoke.py", "def example(): pass\n")
    if len(symbols) != 1 or symbols[0].name != "example":
        raise RuntimeError("M4 AST smoke check failed")
    if native.blake3_hash(b"") != BLAKE3_EMPTY:
        raise RuntimeError("M5 BLAKE3 smoke check failed")
    print(f"Installed M1-M5 APIs loaded from {origin} on {actual_arch}", flush=True)


def skip_allowed(test_id: str, reason: str, system: str) -> bool:
    test_id = test_id.split(" (", 1)[0]  # unittest subtest parameters are not part of the ID.
    if (
        system != "win32"
        and test_id == NON_UTF8_FILENAME_TEST
        and reason == "Filesystem rejects non-UTF-8 filenames (EILSEQ)"
    ):
        return True  # Fixture creation proved this filesystem rejects the name.
    if test_id in PERMISSION_TESTS and reason.startswith("Current user can read "):
        return True  # Root in the musl container cannot exercise permission-denied cases.
    return (
        system == "win32"
        and test_id in WINDOWS_SKIPS
        and (
            reason.startswith("Requires POSIX")
            or reason == "Requires byte-valued filenames"
            or reason.startswith("Symlinks are not supported here:")
            or reason.startswith("Symlinks unavailable:")
        )
    )


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def require_groups(tests) -> None:
    ids = [test.id() for test in tests]
    for group in REQUIRED_GROUPS:
        if not any(test_id.startswith(group + ".") for test_id in ids):
            raise RuntimeError(f"Required native test group was not discovered: {group}")


def run_tests(expected_arch: str) -> int:
    smoke(expected_arch)
    # Missing reference BPE is a CI failure, never a reason to skip native parity.
    reference = importlib.import_module("tiktoken")
    for encoding in ("cl100k_base", "o200k_base"):
        reference.get_encoding(encoding)
    sys.path.insert(0, str(ROOT))
    suite = unittest.TestSuite()
    for filename in TEST_FILES:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=filename))
    tests = list(flatten(suite))
    require_groups(tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    unexpected = [
        (test.id(), reason)
        for test, reason in result.skipped
        if not skip_allowed(test.id(), reason, sys.platform)
    ]
    if unexpected:
        raise RuntimeError(f"Native CI rejected unexpected skipped tests: {unexpected}")
    return 0 if result.wasSuccessful() else 1


def one_artifact(directory: Path, pattern: str) -> Path:
    paths = sorted(directory.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f"Expected exactly one {pattern} in {directory}, found {len(paths)}")
    return paths[0]


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(path.parts) and not path.is_absolute() and ".." not in path.parts and "\\" not in name
    )


def validate_wheel(path: Path, expected_platform: str) -> None:
    _, python_tag, abi_tag, platforms = path.stem.rsplit("-", 3)
    if python_tag != "cp311" or abi_tag != "abi3" or expected_platform not in platforms.split("."):
        raise ValueError(f"Unexpected CPython ABI/platform wheel tag: {path.name}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not all(safe_member(name) for name in names):
            raise ValueError("Invalid or duplicated wheel paths")
        if archive.testzip() is not None:
            raise ValueError("Wheel CRC validation failed")
        wheels = [name for name in names if name.endswith(".dist-info/WHEEL")]
        if len(wheels) != 1:
            raise ValueError("Wheel must contain exactly one WHEEL metadata file")
        prefix = wheels[0].removesuffix("WHEEL")
        if not {prefix + "METADATA", prefix + "RECORD"}.issubset(names):
            raise ValueError("Missing wheel metadata/RECORD")
        metadata = BytesParser().parsebytes(archive.read(wheels[0]))
        if metadata.get("Root-Is-Purelib", "").lower() != "false":
            raise ValueError("Native wheel is incorrectly marked pure Python")
        metadata_platforms = set()
        for tag in metadata.get_all("Tag", []):
            parts = tag.split("-")
            if (
                len(parts) != 3
                or parts[:2] != ["cp311", "abi3"]
                or not all(re.fullmatch(r"[a-z0-9_]+", value) for value in parts[2].split("."))
            ):
                raise ValueError("Wheel metadata tags do not match the requested platform")
            # A WHEEL Tag header may compress several platforms into one field.
            metadata_platforms.update(parts[2].split("."))
        if expected_platform not in metadata_platforms:
            raise ValueError("Wheel metadata tags do not match the requested platform")
        if not any(name.endswith((".so", ".pyd")) for name in names):
            raise ValueError("Wheel contains no native extension")
    print(f"Validated wheel: {path.name}")


def validate_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if not members or any(
            not safe_member(member.name) or member.issym() or member.islnk() for member in members
        ):
            raise ValueError("Unsafe source archive paths or links")
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError("Source archive must have one root directory")
        files = {
            str(PurePosixPath(member.name).relative_to(next(iter(roots))))
            for member in members
            if member.isfile()
        }
        required = {
            "Cargo.toml",
            "Cargo.lock",
            "pyproject.toml",
            "README.md",
            "PKG-INFO",
            "src/lib.rs",
            "src/symbols.rs",
            "src/tokenizer.rs",
            "src/walker.rs",
        }
        if not required.issubset(files):
            raise ValueError(f"Incomplete sdist: missing {sorted(required - files)}")
        if any(
            "target" in PurePosixPath(name).parts or name.endswith((".so", ".pyd"))
            for name in files
        ):
            raise ValueError("Source archive contains compiled artifacts")
    print(f"Validated source archive: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("smoke", "test"):
        sub = commands.add_parser(command)
        sub.add_argument("--arch", choices=("x86_64", "arm64"), required=True)
    wheel = commands.add_parser("wheel")
    wheel.add_argument("directory", type=Path)
    wheel.add_argument("--platform", required=True)
    sdist = commands.add_parser("sdist")
    sdist.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    if args.command == "test":
        return run_tests(args.arch)
    if args.command == "smoke":
        smoke(args.arch)
    elif args.command == "wheel":
        validate_wheel(one_artifact(args.directory, "*.whl"), args.platform)
    else:
        validate_sdist(one_artifact(args.directory, "*.tar.gz"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
