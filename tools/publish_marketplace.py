#!/usr/bin/env python3
"""Validate and build local, reproducible Claude and Cursor release bundles."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

if __package__:
    from . import kit
else:
    import kit


class PublishError(Exception):
    """Invalid release input or an unsafe artifact destination."""


NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)
MARKETPLACE = ".claude-plugin/marketplace.json"


def validate_version(value: str) -> str:
    match = VERSION.fullmatch(value) if isinstance(value, str) and len(value) <= 100 else None
    if not match or any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in (match[4] or "").split(".")
    ):
        raise PublishError(f"Invalid version: {value!r}; expected SemVer, e.g. 1.2.3")
    return value


def _read(root: Path, relative: str) -> bytes:
    path = kit.checked_path(root, relative)
    if not path.is_file():
        raise PublishError(f"Missing required file: {relative}")
    return path.read_bytes()


def _json_object(data: bytes, label: str) -> dict:
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate field {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError) as exc:
        raise PublishError(f"Invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublishError(f"{label}: expected an object")
    return value


def _text(value, label: str):
    if not isinstance(value, str) or not value.strip():
        raise PublishError(f"{label}: expected a nonempty string")


def _name(value, label: str):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise PublishError(f"{label}: invalid name")


def _required_fields(item: dict, fields: tuple[str, ...], label: str):
    missing = [field for field in fields if field not in item]
    if missing:
        raise PublishError(f"{label}: missing required fields: {', '.join(missing)}")


def _optional_fields(item: dict, label: str):
    for field in ("description", "license", "repository", "homepage", "category"):
        if field in item:
            _text(item[field], f"{label} {field}")
    if "keywords" in item:
        keywords = item["keywords"]
        if not isinstance(keywords, list):
            raise PublishError(f"{label} keywords must be a list")
        for keyword in keywords:
            _text(keyword, f"{label} keyword")


def _source(value) -> str:
    if not isinstance(value, str) or not value.startswith("./"):
        raise PublishError("Plugin source must be a local ./directory path")
    relative = value[2:]
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or "\x00" in relative
        or relative.startswith("/")
        or any(part in ("", ".", "..") for part in relative.split("/"))
    ):
        raise PublishError(f"Unsafe plugin source: {value!r}")
    return relative


def _metadata(root: Path, version: str | None) -> dict[str, bytes]:
    data = _read(root, MARKETPLACE)
    marketplace = _json_object(data, MARKETPLACE)
    _required_fields(marketplace, ("name", "owner", "plugins"), "Marketplace")
    _name(marketplace.get("name"), "Marketplace name")
    _optional_fields(marketplace, "Marketplace")
    owner = marketplace.get("owner")
    if not isinstance(owner, dict):
        raise PublishError("Marketplace owner must be an object")
    _required_fields(owner, ("name",), "Marketplace owner")
    _text(owner.get("name"), "Marketplace owner.name")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise PublishError("Marketplace plugins must be a nonempty list")

    versions = []

    def record_version(item, label):
        if "version" in item:
            versions.append((label, validate_version(item["version"])))

    record_version(marketplace, MARKETPLACE)
    metadata = marketplace.get("metadata", {})
    if not isinstance(metadata, dict):
        raise PublishError("Marketplace metadata must be an object")
    record_version(metadata, "Marketplace metadata")
    files = {
        f".claude-plugin/{name}": content
        for name, content in kit.source_files(kit.checked_path(root, ".claude-plugin")).items()
    }
    names = set()
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise PublishError("Every plugin must be an object")
        _required_fields(plugin, ("name", "source", "description"), "Plugin")
        name = plugin.get("name")
        _name(name, "Plugin name")
        if name in names:
            raise PublishError(f"Duplicate plugin name: {name}")
        names.add(name)
        _text(plugin.get("description"), f"{name} description")
        _optional_fields(plugin, name)
        strict = plugin.get("strict", True)
        if not isinstance(strict, bool):
            raise PublishError(f"{name}: strict must be a boolean")
        record_version(plugin, name)
        relative = _source(plugin.get("source"))
        directory = kit.checked_path(root, relative)
        if not directory.is_dir():
            raise PublishError(f"Missing plugin source directory: {relative}")
        contents = kit.source_files(directory)
        if not contents:
            raise PublishError(f"Empty plugin source directory: {relative}")
        manifest_name = ".claude-plugin/plugin.json"
        if manifest_name in contents:
            manifest = _json_object(contents[manifest_name], f"{relative}/{manifest_name}")
            if manifest.get("name") != name:
                raise PublishError(f"{relative}/{manifest_name}: plugin name mismatch")
            _optional_fields(manifest, f"{relative}/{manifest_name}")
            record_version(manifest, f"{relative}/{manifest_name}")
        elif strict:
            raise PublishError(f"{name}: strict plugin is missing {manifest_name}")
        files.update({f"{relative}/{path}": content for path, content in contents.items()})

    root_manifest = files.get(".claude-plugin/plugin.json")
    if root_manifest is not None:
        manifest = _json_object(root_manifest, ".claude-plugin/plugin.json")
        if manifest.get("name") != marketplace["name"]:
            raise PublishError("Root plugin name does not match marketplace name")
        _optional_fields(manifest, ".claude-plugin/plugin.json")
        record_version(manifest, ".claude-plugin/plugin.json")
    if version is not None:
        versions.append(("--version", validate_version(version)))
    if len({value for _, value in versions}) > 1:
        raise PublishError(
            "Inconsistent versions: " + ", ".join(f"{label}={value}" for label, value in versions)
        )
    return files


def _exports(root: Path, target: str) -> dict[str, bytes]:
    expected = kit.export_files(target, root=root)
    directory = kit.checked_path(root, f"providers/{target}/.{target}")
    actual = {f".{target}/{name}": data for name, data in kit.source_files(directory).items()}
    if actual != expected:
        changed = sorted(
            name for name in set(actual) | set(expected) if actual.get(name) != expected.get(name)
        )
        raise PublishError(
            f"Stale or missing {target} exports: {', '.join(changed)}; run tools/kit.py sync"
        )
    return {f"providers/{target}/{name}": data for name, data in actual.items()}


def _prepare(root: Path, version: str | None = None) -> tuple[dict, dict]:
    if version is not None:
        validate_version(version)
    root = root.resolve()
    claude = _metadata(root, version)
    # Keep kit's hard budgets and advisory warnings; 800 is not a new hard limit.
    report = kit.check_library(root=root)
    claude.update(_exports(root, "claude"))
    cursor = _exports(root, "cursor")
    for directory in ("skills", "agents"):
        contents = kit.source_files(kit.checked_path(root, directory))
        claude.update({f"{directory}/{name}": data for name, data in contents.items()})
    for relative in ("README.md", "LICENSE"):
        data = _read(root, relative)
        claude[relative] = cursor[relative] = data
    rules = kit.checked_path(root, ".cursorrules")
    if rules.exists():
        cursor[".cursorrules"] = _read(root, ".cursorrules")
    return report, {"claude": claude, "cursor": cursor}


def validate(root: Path = kit.ROOT) -> dict:
    report, _ = _prepare(root)
    return report


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    # Stored entries also avoid dependence on the host's zlib version.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
                raise PublishError(f"Unsafe archive path: {name!r}")
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    return buffer.getvalue()


def _write_artifacts(output: Path, artifacts: dict[str, bytes]):
    output = output.absolute()
    kit.checked_path(Path(output.anchor), output.relative_to(output.anchor).as_posix())
    existed = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".marketplace-", dir=output) as temporary:
            staging = Path(temporary)
            backups = {}
            for index, (name, data) in enumerate(artifacts.items()):
                destination = kit.checked_path(output, name)
                if destination.exists():
                    if not destination.is_file():
                        raise PublishError(f"Artifact destination is not a file: {destination}")
                    backup = staging / f"backup-{index}"
                    backup.write_bytes(destination.read_bytes())
                    backups[name] = backup
                (staging / name).write_bytes(data)
            written = []
            try:
                for name in artifacts:
                    os.replace(staging / name, output / name)
                    written.append(name)
            except BaseException:
                for name in reversed(written):
                    if name in backups:
                        os.replace(backups[name], output / name)
                    else:
                        (output / name).unlink()
                raise
    except BaseException:
        if not existed:
            output.rmdir()
        raise


def build(version: str, output_dir: Path | None = None, root: Path = kit.ROOT) -> dict:
    report, bundles = _prepare(root, version)
    artifacts = {
        f"maintainer-skills-lab-{target}-v{version}.zip": _zip(files)
        for target, files in bundles.items()
    }
    artifacts["checksums.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(artifacts.items())
    ).encode("ascii")
    output = output_dir if output_dir is not None else root / "dist"
    _write_artifacts(output, artifacts)
    return {
        "version": version,
        "artifacts": [str(output / name) for name in artifacts],
        "warnings": report["warnings"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="Validate marketplace sources and provider exports")
    command = commands.add_parser("build", help="Build local ZIP bundles and SHA-256 checksums")
    command.add_argument("--version", required=True)
    command.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate() if args.command == "validate" else build(args.version, args.output_dir)
    except (PublishError, kit.KitError, OSError, ValueError) as exc:
        print(f"Marketplace error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
