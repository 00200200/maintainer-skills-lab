#!/usr/bin/env python3
"""Build and install this repository's skill library using Python 3.11+."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "codex": (".agents/skills", ".codex/agents", ".toml"),
    "claude": (".claude/skills", ".claude/agents", ".md"),
    "cursor": (".cursor/skills", ".cursor/agents", ".md"),
    "opencode": (".opencode/skills", ".opencode/agents", ".md"),
}
EXPORT_TARGETS = (*TARGETS, "grok-bot")
NAME = re.compile(r"mkl-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class KitError(Exception):
    """Expected input, source, or installation conflict."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def skill_metadata(path: Path) -> tuple[dict[str, str], str]:
    """Our source files intentionally use only JSON-quoted YAML scalars.

    This is a valid, small subset of YAML, not a general Agent Skills validator.
    Reject other frontmatter instead of silently interpreting it differently.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise KitError(f"{path}: missing frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise KitError(f"{path}: unclosed frontmatter") from exc
    metadata = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or key not in {"name", "description"} or key in metadata:
            raise KitError(f"{path}: unsupported or duplicate metadata field")
        try:
            parsed = json.loads(value.strip())
        except json.JSONDecodeError as exc:
            raise KitError(f"{path}: use a double-quoted string for {key}") from exc
        if not isinstance(parsed, str) or not parsed.strip() or "\n" in parsed:
            raise KitError(f"{path}: {key} must be a nonempty, single-line string")
        metadata[key] = parsed
    if set(metadata) != {"name", "description"}:
        raise KitError(f"{path}: name and description are required")
    if not NAME.fullmatch(metadata["name"]) or len(metadata["name"]) > 64:
        raise KitError(f"{path}: invalid namespaced skill name")
    if path.parent.name != metadata["name"] or len(metadata["description"]) > 1024:
        raise KitError(f"{path}: directory/name mismatch or oversized description")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise KitError(f"{path}: empty skill body")
    return metadata, body


def source_files(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink():
        raise KitError(f"Source directory must not be a symlink: {directory}")
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise KitError(f"Source symlinks are unsupported: {path}")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            files[relative] = path.read_bytes()
    return files


def load_library(root: Path = ROOT) -> tuple[dict, dict]:
    skills = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        metadata, body = skill_metadata(path)
        skills[metadata["name"]] = {**metadata, "body": body, "files": source_files(path.parent)}
    if not skills:
        raise KitError("No skills found")
    agents = {}
    for path in sorted((root / "agents").glob("*.toml")):
        if path.is_symlink():
            raise KitError(f"Source symlinks are unsupported: {path}")
        agent = tomllib.loads(path.read_text(encoding="utf-8"))
        if set(agent) != {"name", "description", "instructions", "skills"}:
            raise KitError(f"{path}: expected name, description, instructions, skills")
        if any(
            not isinstance(agent[key], str) or not agent[key].strip()
            for key in ("name", "description", "instructions")
        ):
            raise KitError(f"{path}: invalid agent text")
        if not NAME.fullmatch(agent["name"]) or path.stem != agent["name"]:
            raise KitError(f"{path}: invalid agent name")
        if not isinstance(agent["skills"], list) or not agent["skills"]:
            raise KitError(f"{path}: skills must be a nonempty list")
        if any(not isinstance(item, str) or item not in skills for item in agent["skills"]):
            raise KitError(f"{path}: unknown skill dependency")
        if len(set(agent["skills"])) != len(agent["skills"]):
            raise KitError(f"{path}: repeated skill dependency")
        agents[agent["name"]] = agent
    if not agents:
        raise KitError("No agent profiles found")
    return skills, agents


def agent_body(agent: dict, skills: dict) -> str:
    # Embed dependencies so an exported agent does not need another skill
    # to be implicitly loaded by the client.
    return (
        agent["instructions"]
        + "\n\n"
        + "\n\n".join(skills[skill]["body"] for skill in agent["skills"])
    )


def export_files(target: str, root: Path = ROOT) -> dict[str, bytes]:
    skills, agents = load_library(root)
    if target == "grok-bot":
        files = source_files(root / "grok-bot")
        if not files:
            raise KitError("Missing Grok Bot setup recipes")
        exports = {f"grok-bot/{name}": data for name, data in files.items()}
        for kind, items in (("skills", skills), ("agents", agents)):
            for name, item in items.items():
                body = item["body"] if kind == "skills" else agent_body(item, skills)
                content = (
                    f"# {name}\n\n{item['description']}\n\n"
                    "## Use in Grok Bot\n\n"
                    "This is a Markdown setup recipe for Grok Bot (SpaceXAI). "
                    "It has not been evaluated in a live Bot.\n\n"
                    "1. Open an existing Bot or create one with this job.\n"
                    "2. Give it the workflow below with a concrete task and the required "
                    "inputs or supporting files. Choose the access and approval limits.\n"
                    "3. Run the task once and inspect its output against the workflow checks.\n"
                    f'4. Ask: "Save this validated workflow as a skill called {name}."\n'
                    "5. Check that the skill is enabled for this Bot in "
                    "Settings → Plugins → Yours, then invoke it from the `/` menu.\n\n"
                    "An agent recipe combines its source instructions and dependent skills "
                    "below. Copying this file does not create a Bot or routine.\n\n"
                    "Reference: [Grok Bot skills and routines]"
                    "(https://docs.x.ai/grok-bot/skills-routines-and-automations).\n\n"
                    "## Workflow\n\n" + body + "\n"
                )
                exports[f"{kind}/{name}.md"] = content.encode("utf-8")
        return exports
    skill_dir, agent_dir, extension = TARGETS[target]
    files = {}
    for name, skill in skills.items():
        for relative, data in skill["files"].items():
            files[f"{skill_dir}/{name}/{relative}"] = data
    for name, agent in agents.items():
        body = agent_body(agent, skills)
        if target == "codex":
            content = (
                "\n".join(
                    f"{key} = {json.dumps(value, ensure_ascii=False)}"
                    for key, value in {
                        "name": name,
                        "description": agent["description"],
                        "developer_instructions": body,
                    }.items()
                )
                + "\n"
            )
        elif target == "opencode":
            content = (
                "---\n"
                f"description: {json.dumps(agent['description'], ensure_ascii=False)}\n"
                'mode: "subagent"\n'
                "---\n\n" + body + "\n"
            )
        else:
            content = (
                "---\n"
                f"name: {json.dumps(name)}\n"
                f"description: {json.dumps(agent['description'], ensure_ascii=False)}\n"
                "---\n\n" + body + "\n"
            )
        files[f"{agent_dir}/{name}{extension}"] = content.encode("utf-8")
    return files


def provider_instructions(target: str) -> str:
    if target == "grok-bot":
        return (
            "Follow [the setup guide](grok-bot/README.md) to configure a Bot and "
            "save its skills. Every library skill and agent has a Markdown recipe "
            "under `skills/` or `agents/`. These require manual setup in Grok Bot "
            "(SpaceXAI); they are not automatic Bot imports.\n"
        )
    skill_dir, agent_dir, extension = TARGETS[target]
    return (
        f"Copy the selected `mkl-*` skill folders into `{skill_dir}/` and agent "
        f"files into `{agent_dir}/` in your project, keeping the paths shown here. "
        f"Agent files use `{extension}`. Check existing files before copying.\n\n"
        "For conflict detection, updates, and removal, use the installer from "
        "the source clone:\n\n"
        "```sh\n"
        f"python3 tools/kit.py install --target {target} --project /existing/project\n"
        "```\n\n"
        "The installer reads the canonical source and installs the full library by default. "
        "Add `--skill mkl-humanize` to install or update only that skill; repeat `--skill` "
        "to select more. Other skills and native agents are preserved. Use the same "
        "selection with `uninstall` to remove only unchanged files owned for those skills.\n\n"
        + (
            "OpenCode 1.18.30 discovery and agent loading were checked on macOS arm64. "
            "Model task outcomes remain unevaluated. See `examples/opencode/README.md` "
            "in the source clone for the repeatable check and its limits.\n"
            if target == "opencode"
            else "Live-client discovery and task outcomes have not yet been evaluated.\n"
        )
        + (
            "\nOpenCode derives agent names from filenames; agents use `mode: subagent`. "
            "Try `@mkl-writing-editor` with a draft after installing the full library. "
            "For a skill-only install, ask OpenCode to load `mkl-humanize` using its skill tool. "
            "Model and permissions remain controlled by your OpenCode configuration. "
            "No config file or plugin is installed. Avoid duplicate skill names in "
            "`.agents/skills/` and `.claude/skills/`, which OpenCode can also discover.\n\n"
            "References: [skills](https://opencode.ai/docs/skills), "
            "[agents](https://opencode.ai/docs/agents).\n"
            if target == "opencode"
            else ""
        )
    )


def provider_files(root: Path = ROOT) -> dict[str, bytes]:
    """The checked-in, browsable catalogue uses the same exports as ZIPs/install."""
    files = {}
    for target in EXPORT_TARGETS:
        files.update(
            {f"{target}/{name}": data for name, data in export_files(target, root).items()}
        )
        files[f"{target}/README.md"] = (
            f"# {target}\n\n"
            "[All providers and source links](../README.md)\n\n"
            + provider_instructions(target)
            + "\nGenerated by `python3 tools/kit.py sync`. Edit the source, then regenerate.\n"
        ).encode("utf-8")
    skills, agents = load_library(root)
    lines = [
        "# Choose your provider",
        "",
        "One source workflow produces each provider version below. These files are",
        "generated by `python3 tools/kit.py sync`; CI checks that they match the source.",
        "",
        " | ".join(f"[{target}]({target}/README.md)" for target in EXPORT_TARGETS),
        "",
        "Codex, Claude Code, Cursor, and OpenCode get native files. Grok Bot (SpaceXAI) gets",
        "a Markdown setup recipe for every skill and agent. Format checks do not",
        "establish live-client behavior.",
    ]
    for kind, items in (("skills", skills), ("agents", agents)):
        lines += [
            "",
            f"## {kind.title()}",
            "",
            "| Source | Codex | Claude Code | Cursor | OpenCode | Grok Bot |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for name in items:
            source = f"skills/{name}/SKILL.md" if kind == "skills" else f"agents/{name}.toml"
            links = [f"[{name}](../{source})"]
            for target in EXPORT_TARGETS:
                if target == "grok-bot":
                    relative = f"{kind}/{name}.md"
                else:
                    skill_dir, agent_dir, extension = TARGETS[target]
                    relative = (
                        f"{skill_dir}/{name}/SKILL.md"
                        if kind == "skills"
                        else f"{agent_dir}/{name}{extension}"
                    )
                links.append(f"[{target}]({target}/{relative})")
            lines.append("| " + " | ".join(links) + " |")
    files["README.md"] = ("\n".join(lines) + "\n").encode("utf-8")
    return files


def provider_path(relative: str) -> bool:
    if not isinstance(relative, str):
        return False
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        return False
    if path.as_posix() != relative:
        return False
    if relative == "README.md":
        return True
    target, separator, rest = relative.partition("/")
    if not separator or target not in (*EXPORT_TARGETS, "groq"):
        return False
    if rest == "README.md":
        return True
    if target in TARGETS:
        return managed_path(rest, target)
    # Accept retired Groq paths only so sync can remove unchanged, manifest-owned files.
    if target == "groq" or path.parts[1] in {"skills", "agents"}:
        return (
            len(path.parts) == 3
            and path.parts[1] in {"skills", "agents"}
            and path.suffix == (".json" if target == "groq" else ".md")
            and NAME.fullmatch(path.stem) is not None
        )
    return rest.startswith("grok-bot/") and len(path.parts) >= 3


def sync_providers(root: Path = ROOT, check: bool = False) -> dict:
    root = root.resolve()
    destination = checked_path(root, "providers")
    if destination.exists() and not destination.is_dir():
        raise KitError("providers must be a directory")
    desired = provider_files(root)
    manifest = checked_path(root, "providers/.manifest.json")
    old = {}
    if manifest.exists():
        state = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise KitError("Invalid provider manifest")
        old = state.get("files")
        if not isinstance(old, dict) or any(
            not provider_path(name) or not isinstance(sha, str) or not SHA256.fullmatch(sha)
            for name, sha in old.items()
        ):
            raise KitError("Invalid provider manifest paths or hashes")
    writes, removals = {}, []
    for relative in sorted(set(desired) | set(old)):
        if not provider_path(relative):
            raise KitError(f"Invalid provider path: {relative}")
        path = checked_path(root, f"providers/{relative}")
        current = current_digest(path)
        wanted = digest(desired[relative]) if relative in desired else None
        if current is not None and current != wanted and current != old.get(relative):
            raise KitError(
                f"Edited or unmanaged provider file: {relative}; preserve edits in the source "
                "or restore the generated file before syncing"
            )
        if relative in desired and current != wanted:
            writes[relative] = desired[relative]
        elif relative not in desired and current is not None:
            removals.append(relative)
    state_bytes = (
        json.dumps(
            {"schema_version": 1, "files": {name: digest(data) for name, data in desired.items()}},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()
    manifest_changed = not manifest.exists() or manifest.read_bytes() != state_bytes
    if not check:
        for relative, data in writes.items():
            atomic_write(checked_path(root, f"providers/{relative}"), data)
        for relative in removals:
            checked_path(root, f"providers/{relative}").unlink()
        if manifest_changed:
            atomic_write(manifest, state_bytes)
    return {
        "up_to_date": not check or not (writes or removals or manifest_changed),
        "check": check,
        "written": sorted(writes),
        "removed": removals,
        "manifest_changed": manifest_changed,
    }


def managed_path(relative: str, target: str) -> bool:
    if not isinstance(relative, str):
        return False
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        return False
    if path.as_posix() != relative:
        return False
    skill_dir, agent_dir, extension = TARGETS[target]
    try:
        parts = path.relative_to(skill_dir).parts
        if len(parts) >= 2 and NAME.fullmatch(parts[0]):
            return True
    except ValueError:
        pass
    return (
        path.parent.as_posix() == agent_dir
        and path.suffix == extension
        and NAME.fullmatch(path.stem) is not None
    )


def checked_path(project: Path, relative: str) -> Path:
    path = project / relative
    for candidate in [path, *path.parents]:
        if candidate == project:
            break
        if candidate.is_symlink():
            raise KitError(f"Refusing symlink in installation path: {candidate}")
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise KitError(f"Parent is not a directory: {candidate}")
    return path


def installed_state(project: Path, target: str) -> tuple[Path, dict[str, str]]:
    path = checked_path(project, f".maintainer-skills-lab/{target}.json")
    if not path.exists():
        return path, {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != 1
        or state.get("target") != target
        or not isinstance(state.get("files"), dict)
    ):
        raise KitError(f"Invalid install manifest: {path}")
    for relative, checksum in state["files"].items():
        if (
            not managed_path(relative, target)
            or not isinstance(checksum, str)
            or not SHA256.fullmatch(checksum)
        ):
            raise KitError(f"Invalid owned file in install manifest: {relative}")
    return path, state["files"]


def current_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise KitError(f"Expected a file: {path}")
    return digest(path.read_bytes())


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def skill_prefixes(target: str, skill_names: list[str] | None) -> tuple[str, ...] | None:
    if skill_names is None:
        return None
    if not skill_names or any(
        not isinstance(name, str) or not NAME.fullmatch(name) for name in skill_names
    ):
        raise KitError("Select at least one valid mkl-* skill name")
    return tuple(f"{TARGETS[target][0]}/{name}/" for name in sorted(set(skill_names)))


def manifest_bytes(target: str, owned: dict[str, str]) -> bytes:
    state = {"schema_version": 1, "target": target, "files": owned}
    return (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()


def install(
    target: str,
    project: Path,
    root: Path = ROOT,
    dry_run: bool = False,
    *,
    skill_names: list[str] | None = None,
) -> dict:
    project = project.resolve()
    if not project.is_dir():
        raise KitError(f"Project directory does not exist: {project}")
    prefixes = skill_prefixes(target, skill_names)
    desired = export_files(target, root)
    if prefixes is not None:
        for prefix in prefixes:
            if prefix + "SKILL.md" not in desired:
                raise KitError(f"Unknown source skill: {prefix.split('/')[-2]}")
        desired = {name: data for name, data in desired.items() if name.startswith(prefixes)}
    manifest_path, old = installed_state(project, target)
    # Keep other workflows' ownership hashes, even when their local files were edited.
    owned = {
        name: sha
        for name, sha in old.items()
        if prefixes is not None and not name.startswith(prefixes)
    }
    old = {name: sha for name, sha in old.items() if name not in owned}
    writes, removals, retained = {}, [], []
    # Preflight every selected path before creating directories or changing files.
    for relative in sorted(set(desired) | set(old)):
        if not managed_path(relative, target):
            raise KitError(f"Invalid installation path: {relative}")
        path = checked_path(project, relative)
        current = current_digest(path)
        if relative not in desired:
            if current is not None and current != old[relative]:
                raise KitError(f"Locally modified, refusing removal: {relative}")
            if current is not None:
                removals.append(relative)
            continue
        wanted = digest(desired[relative])
        if current is None:
            writes[relative] = desired[relative]
            owned[relative] = wanted
        elif current == wanted:
            if relative in old:
                owned[relative] = wanted
            else:
                # An identical pre-existing file remains owned by the user.
                retained.append(relative)
        elif relative in old and current == old[relative]:
            writes[relative] = desired[relative]
            owned[relative] = wanted
        else:
            raise KitError(f"Existing or locally modified file conflicts: {relative}")
    state_bytes = manifest_bytes(target, owned)
    manifest_changed = (bool(owned) or manifest_path.exists()) and (
        not manifest_path.exists() or manifest_path.read_bytes() != state_bytes
    )
    if not dry_run:
        for relative, data in writes.items():
            atomic_write(checked_path(project, relative), data)
        for relative in removals:
            checked_path(project, relative).unlink()
        if manifest_changed:
            atomic_write(manifest_path, state_bytes)
    return {
        "target": target,
        "selected_skills": sorted(set(skill_names)) if skill_names is not None else None,
        "project": str(project),
        "dry_run": dry_run,
        "written": sorted(writes),
        "removed": removals,
        "identical_unmanaged": retained,
        "manifest_changed": manifest_changed,
    }


def uninstall(
    target: str,
    project: Path,
    dry_run: bool = False,
    *,
    skill_names: list[str] | None = None,
) -> dict:
    project = project.resolve()
    if not project.is_dir():
        raise KitError(f"Project directory does not exist: {project}")
    prefixes = skill_prefixes(target, skill_names)
    manifest_path, old = installed_state(project, target)
    kept = {}
    removals = []
    for relative, checksum in old.items():
        if prefixes is not None and not relative.startswith(prefixes):
            kept[relative] = checksum
            continue
        path = checked_path(project, relative)
        current = current_digest(path)
        if current is not None and current != checksum:
            raise KitError(f"Locally modified, refusing removal: {relative}")
        if current is not None:
            removals.append(relative)
    manifest_changed = manifest_path.exists() and (prefixes is None or kept != old)
    if not dry_run:
        for relative in removals:
            checked_path(project, relative).unlink()
        if manifest_changed:
            if kept:
                atomic_write(manifest_path, manifest_bytes(target, kept))
            else:
                manifest_path.unlink()
        # Remove only now-empty directories below our known installation roots.
        for relative in removals:
            directory = (project / relative).parent
            while directory != project:
                try:
                    directory.rmdir()
                except OSError:
                    break
                directory = directory.parent
        try:
            manifest_path.parent.rmdir()
        except OSError:
            pass
    return {
        "target": target,
        "selected_skills": sorted(set(skill_names)) if skill_names is not None else None,
        "dry_run": dry_run,
        "removed": sorted(removals),
        "manifest_changed": manifest_changed,
    }


def build(target: str, output: Path, root: Path = ROOT) -> Path:
    files = export_files(target, root)
    prefix = f"maintainer-skills-lab-{target}"
    instructions = (
        "# Installation\n\nExtract this archive into a temporary directory.\n\n"
        + provider_instructions(target)
        + "\nSource: https://github.com/00200200/maintainer-skills-lab\n"
    )
    files["INSTALL.md"] = instructions.encode()
    files["LICENSE"] = (root / "LICENSE").read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{prefix}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(f"{prefix}/{name}", (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            handle.writestr(entry, data)
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List source skills and native agents")
    commands.add_parser("check", help="Validate this library and generate exports in memory")
    sync_parser = commands.add_parser("sync", help="Regenerate the browsable provider catalogue")
    sync_parser.add_argument("--check", action="store_true", help="Fail on drift without writing")
    build_parser = commands.add_parser("build", help="Build deterministic installation archives")
    build_parser.add_argument("--target", choices=[*EXPORT_TARGETS, "all"], default="all")
    build_parser.add_argument("--output", type=Path, default=ROOT / "dist")
    for action in ("install", "uninstall"):
        action_parser = commands.add_parser(action, help=f"{action.title()} in one project")
        action_parser.add_argument("--target", choices=TARGETS, required=True)
        action_parser.add_argument("--project", type=Path, required=True)
        action_parser.add_argument("--dry-run", action="store_true")
        action_parser.add_argument(
            "--skill",
            dest="skill_names",
            action="append",
            metavar="NAME",
            help="Limit changes to this skill; repeat to select more. Other workflows are preserved.",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            skills, agents = load_library()
            print(
                json.dumps(
                    {
                        "skills": [
                            {"name": s["name"], "description": s["description"]}
                            for s in skills.values()
                        ],
                        "agents": list(agents.values()),
                    },
                    indent=2,
                )
            )
        elif args.command == "check":
            skills, agents = load_library()
            counts = {target: len(export_files(target)) for target in EXPORT_TARGETS}
            print(
                json.dumps(
                    {
                        "skills": len(skills),
                        "agents": len(agents),
                        "export_files": counts,
                        "validation": "source-and-export checks only; no live-agent runs",
                    },
                    indent=2,
                )
            )
        elif args.command == "sync":
            result = sync_providers(check=args.check)
            print(json.dumps(result, indent=2))
            if args.check and not result["up_to_date"]:
                return 1
        elif args.command == "build":
            targets = EXPORT_TARGETS if args.target == "all" else [args.target]
            print(
                json.dumps(
                    {"archives": [str(build(target, args.output)) for target in targets]}, indent=2
                )
            )
        elif args.command == "install":
            print(
                json.dumps(
                    install(
                        args.target,
                        args.project,
                        dry_run=args.dry_run,
                        skill_names=args.skill_names,
                    ),
                    indent=2,
                )
            )
        else:
            print(
                json.dumps(
                    uninstall(
                        args.target, args.project, args.dry_run, skill_names=args.skill_names
                    ),
                    indent=2,
                )
            )
    except (KitError, OSError, ValueError) as exc:
        print(f"kit: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
