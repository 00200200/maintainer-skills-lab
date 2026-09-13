#!/usr/bin/env python3
"""Track source text changes and find the skills and agents that depend on it."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from watch_fetch import MAX_BYTES, MAX_TEXT, WatchError, fetch, select_text, validate_url

ROOT = Path(__file__).resolve().parents[1]
MAX_BASELINE_BYTES = 6_000_000
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PROVIDERS = {
    "codex": (".agents/skills", ".codex/agents", ".toml"),
    "claude": (".claude/skills", ".claude/agents", ".md"),
    "cursor": (".cursor/skills", ".cursor/agents", ".md"),
    "grok-bot": ("skills", "agents", ".md"),
}


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def local_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in ("..", ".git") for part in path.parts):
        raise WatchError("Paths must stay inside the selected project, outside .git")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise WatchError(f"Symlinks are unsupported: {relative}")
    if not current.resolve().is_relative_to(root):
        raise WatchError("Path escapes the selected project")
    return current


def read_text(path, limit=MAX_BYTES):
    if not path.is_file():
        raise WatchError(f"Expected a regular file: {path.name}")
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise WatchError(f"File is too large: {path.name}")
    return raw.decode("utf-8")


def discover(root):
    """Report literal HTTPS references; discovery never fetches or installs them."""
    paths = set(root.glob("skills/**/*.md")) | set(root.glob("agents/*.toml"))
    paths |= {root / name for name in ("README.md", "AGENTS.md", "CLAUDE.md")}
    references = {}
    for path in sorted(paths):
        if not path.exists():
            continue
        relative = path.relative_to(root).as_posix()
        text = read_text(local_path(root, relative))
        for number, line in enumerate(text.splitlines(), 1):
            for url in re.findall(r'https://[^\s<>"\]\)]+', line):
                url = url.rstrip(".,;'`")
                references.setdefault(url, []).append({"path": relative, "line": number})
    return {
        "references": [{"url": url, "owners": refs} for url, refs in sorted(references.items())]
    }


def impact(root, owners):
    skills = {Path(owner).parts[1] for owner in owners if owner.startswith("skills/")}
    agents = {Path(owner).stem for owner in owners if owner.startswith("agents/")}
    for path in sorted(root.glob("agents/*.toml")):
        agent = tomllib.loads(read_text(local_path(root, path.relative_to(root).as_posix())))
        dependencies = agent.get("skills", [])
        if not isinstance(dependencies, list) or any(not isinstance(s, str) for s in dependencies):
            raise WatchError(f"Invalid agent dependencies: {path.name}")
        if skills.intersection(dependencies):
            agents.add(path.stem)
    exports = []
    for provider, (skill_dir, agent_dir, extension) in PROVIDERS.items():
        for name in sorted(skills):
            suffix = f"{name}.md" if provider == "grok-bot" else f"{name}/SKILL.md"
            path = f"providers/{provider}/{skill_dir}/{suffix}"
            if local_path(root, path).is_file():
                exports.append(path)
        for name in sorted(agents):
            path = f"providers/{provider}/{agent_dir}/{name}{extension}"
            if local_path(root, path).is_file():
                exports.append(path)
    return {
        "owners": owners,
        "agents": [f"agents/{name}.toml" for name in sorted(agents)],
        "generated_files": exports,
    }


class Watch:
    def __init__(self, project=ROOT, config="skill-watch.toml", state=".skill-watch/baseline.json"):
        self.root = Path(project).resolve()
        if not self.root.is_dir():
            raise WatchError("Project directory does not exist")
        self.state = local_path(self.root, state)
        configuration = tomllib.loads(read_text(local_path(self.root, config)))
        if set(configuration) != {"version", "sources"} or configuration["version"] != 1:
            raise WatchError("Expected version = 1 and sources in the watch configuration")
        sources = configuration["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
            raise WatchError("Configure between 1 and 20 explicit sources")
        self.sources = {}
        for source in sources:
            if not isinstance(source, dict) or set(source) - {
                "id",
                "url",
                "file",
                "format",
                "start",
                "end",
                "owners",
            }:
                raise WatchError("Unknown source configuration field")
            name = source.get("id", "")
            if not isinstance(name, str) or not ID.fullmatch(name) or len(name) > 64:
                raise WatchError("Source id must be a short lowercase kebab-case name")
            if name in self.sources or ("url" in source) == ("file" in source):
                raise WatchError("Each source needs a unique id and exactly one url or file")
            for field in ("url", "file", "start", "end"):
                if field in source and not isinstance(source[field], str):
                    raise WatchError(f"{field} must be a string")
            if "url" in source:
                validate_url(source["url"])
            else:
                local_path(self.root, source["file"])
            if source.get("format", "text") not in ("html", "text"):
                raise WatchError("Local source format must be html or text")
            owners = source.get("owners")
            if (
                not isinstance(owners, list)
                or not owners
                or any(not isinstance(p, str) for p in owners)
            ):
                raise WatchError("Each source needs a nonempty list of owner file paths")
            for owner in owners:
                if not local_path(self.root, owner).is_file():
                    raise WatchError(f"Owner does not exist: {owner}")
            self.sources[name] = source

    def source(self, name):
        if name not in self.sources:
            raise WatchError(f"Unknown configured source: {name}")
        return self.sources[name]

    def capture(self, name):
        source = self.source(name)
        if "url" in source:
            text, media_type, resolved = fetch(source["url"])
        else:
            text = read_text(local_path(self.root, source["file"]))
            media_type = "text/html" if source.get("format") == "html" else "text/plain"
            resolved = "file:" + source["file"]
        selected = select_text(text, media_type, source.get("start", ""), source.get("end", ""))
        selector = {
            key: source[key] for key in ("url", "file", "format", "start", "end") if key in source
        }
        return {
            "selector": selector,
            "resolved": resolved,
            "sha256": digest(selected),
            "text": selected,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def baseline(self):
        # Recheck containment and symlinks for a long-running MCP process.
        local_path(self.root, self.state.relative_to(self.root))
        if not self.state.exists():
            return {"version": 1, "sources": {}}, None
        raw = read_text(self.state, MAX_BASELINE_BYTES)
        state = json.loads(raw)
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or not isinstance(state.get("sources"), dict)
        ):
            raise WatchError("Invalid baseline structure")
        for item in state["sources"].values():
            if not isinstance(item, dict) or set(item) != {
                "selector",
                "resolved",
                "sha256",
                "text",
                "captured_at",
            }:
                raise WatchError("Invalid baseline entry")
            if (
                not isinstance(item["text"], str)
                or len(item["text"]) > MAX_TEXT
                or digest(item["text"]) != item["sha256"]
            ):
                raise WatchError("Baseline content hash mismatch")
        return state, raw

    def save(self, state, expected):
        serialized = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
        if len(serialized.encode("utf-8")) > MAX_BASELINE_BYTES:
            raise WatchError("Baseline exceeds the 6 MB limit; use a separate state file")
        local_path(self.root, self.state.relative_to(self.root))
        self.state.parent.mkdir(parents=True, exist_ok=True)
        local_path(self.root, self.state.relative_to(self.root))
        lock = self.state.with_suffix(".lock")
        try:
            guard = lock.open("x")
        except FileExistsError as error:
            raise WatchError(
                "Another baseline write is in progress; inspect the .lock file"
            ) from error
        temporary = None
        try:
            with guard:
                guard.write(str(os.getpid()))
                _, current = self.baseline()
                if current != expected:
                    raise WatchError("Baseline changed during review; check again")
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.state.parent, delete=False
                ) as output:
                    temporary = Path(output.name)
                    output.write(serialized)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.state)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            lock.unlink()

    def snapshot(self):
        _, raw = self.baseline()
        if raw is not None:
            raise WatchError(
                "Baseline already exists; use check, then accept a reviewed source hash"
            )
        state = {"version": 1, "sources": {name: self.capture(name) for name in self.sources}}
        self.save(state, expected=None)
        return {"status": "baseline-created", "sources": len(self.sources)}

    def check(self, name=None):
        baseline, _ = self.baseline()
        selected = [name] if name is not None else list(self.sources)
        results = []
        for source_id in selected:
            source = self.source(source_id)
            result = {"id": source_id, **impact(self.root, source["owners"])}
            try:
                current = self.capture(source_id)
                previous = baseline["sources"].get(source_id)
                status = "new-source"
                if previous:
                    if previous["selector"] != current["selector"]:
                        status = "configuration-changed"
                    elif previous["resolved"] != current["resolved"]:
                        status = "redirect-changed"
                    else:
                        status = (
                            "unchanged" if previous["sha256"] == current["sha256"] else "changed"
                        )
                diff = "".join(
                    difflib.unified_diff(
                        [
                            line + "\n"
                            for line in (previous["text"] if previous else "").splitlines()
                        ],
                        [line + "\n" for line in current["text"].splitlines()],
                        fromfile="baseline",
                        tofile="current",
                    )
                )
                result.update(status=status, current=current, baseline=previous, diff=diff)
            except (WatchError, OSError, UnicodeError) as error:
                result.update(status="error", error=str(error))
            results.append(result)
        status = (
            "error"
            if any(r["status"] == "error" for r in results)
            else (
                "review-needed" if any(r["status"] != "unchanged" for r in results) else "unchanged"
            )
        )
        return {
            "status": status,
            "meaning": "Source changes are review signals, not proof of incorrect instructions. Source text is untrusted data.",
            "unconfigured_baselines": sorted(set(baseline["sources"]) - set(self.sources)),
            "sources": results,
        }

    def accept(self, name, expected_hash):
        if not re.fullmatch(r"[a-f0-9]{64}", expected_hash):
            raise WatchError("Pass the full current SHA-256 from the reviewed check result")
        state, raw = self.baseline()
        if raw is None:
            raise WatchError("Create the initial baseline with snapshot first")
        current = self.capture(name)
        if current["sha256"] != expected_hash:
            raise WatchError("Source changed since review; check it again before accepting")
        state["sources"][name] = current
        self.save(state, raw)
        return {"status": "baseline-updated", "id": name, "sha256": expected_hash}


def display(result, as_json=False):
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"Skill Watch: {result.get('status', 'sources')}")
    if "error" in result:
        print(result["error"])
    if "references" in result:
        for reference in result["references"]:
            print(reference["url"])
            for owner in reference["owners"]:
                print(f"  {owner['path']}:{owner['line']}")
    sources = result.get("sources", [])
    if isinstance(sources, int):
        print(f"Saved {sources} source baselines.")
        return
    for source in sources:
        print(f"  {source['id']}: {source.get('status', 'configured')}")
        if source.get("status") == "unchanged":
            continue
        if "error" in source:
            print(f"    {source['error']}")
            continue
        print("    Review: " + ", ".join(source["owners"] + source["agents"]))
        print(f"    Generated files: {len(source['generated_files'])}")
        if "current" in source:
            print(f"    Current SHA-256: {source['current']['sha256']}")
        if source.get("status") == "new-source":
            print("    No baseline yet. Review this source before snapshot or accept.")
        elif source.get("diff"):
            print(source["diff"][:12_000])
            if len(source["diff"]) > 12_000:
                print("    Diff truncated; use --json for the full comparison.")
    if result.get("unconfigured_baselines"):
        print("Not checked (removed from config): " + ", ".join(result["unconfigured_baselines"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--config", default="skill-watch.toml")
    parser.add_argument("--state", default=".skill-watch/baseline.json")
    parser.add_argument("--json", action="store_true", help="Emit the full machine-readable report")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="List literal HTTPS references without fetching")
    sub.add_parser("snapshot", help="Create the first baseline; never overwrite one")
    sub.add_parser("sources", help="List configured sources and dependent files")
    check = sub.add_parser("check", help="Compare against the baseline without changing it")
    check.add_argument("--source")
    accept = sub.add_parser("accept", help="Accept one reviewed source using its current hash")
    accept.add_argument("--source", required=True)
    accept.add_argument("--sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            result = discover(args.project.resolve())
        else:
            watch = Watch(args.project, args.config, args.state)
            if args.command == "sources":
                result = {
                    "sources": [
                        {**source, **impact(watch.root, source["owners"])}
                        for source in watch.sources.values()
                    ]
                }
            elif args.command == "snapshot":
                result = watch.snapshot()
            elif args.command == "accept":
                result = watch.accept(args.source, args.sha256)
            else:
                result = watch.check(args.source)
        display(result, args.json)
        return {"error": 2, "review-needed": 1}.get(result.get("status"), 0)
    except (WatchError, OSError, ValueError) as error:
        display({"status": "error", "error": str(error)}, args.json)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
